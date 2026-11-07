"""Timestamp-aware Grafana frame parsing and coverage for rightsizing."""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from app.telemetry_contract import _finite_sample_value, moment

CONTAINER_KEY = tuple[str, str, str, str]  # cluster, namespace, pod, container
OWNER_KEY = tuple[str, str, str]  # cluster, namespace, pod
WORKLOAD_KEY = tuple[str, str, str, str]  # cluster, namespace, kind, name

MAX_FRAME_BYTES = 4_000_000
MAX_FRAMES_PER_QUERY = 2_000
MAX_SAMPLES_PER_SERIES = 11_000


class GrafanaSeriesError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _timestamp_iso(raw) -> str | None:
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, str):
        return moment(raw).isoformat() if moment(raw) else None
    if isinstance(raw, (int, float)) and math.isfinite(float(raw)):
        stamp = float(raw)
        if stamp > 1e12:
            stamp /= 1000.0
        try:
            return datetime.fromtimestamp(stamp, timezone.utc).isoformat()
        except (OSError, OverflowError, ValueError):
            return None
    return None


def _finite_float(raw) -> float | None:
    if isinstance(raw, bool) or raw is None:
        return None
    if isinstance(raw, str):
        try:
            raw = float(raw.strip())
        except ValueError:
            return None
    if not isinstance(raw, (int, float)) or not math.isfinite(float(raw)):
        return None
    return float(raw)


def validate_query_payload(payload) -> None:
    if not isinstance(payload, dict):
        raise GrafanaSeriesError('GRAFANA_RESPONSE_INVALID')
    results = payload.get('results')
    if not isinstance(results, dict):
        raise GrafanaSeriesError('GRAFANA_RESPONSE_INVALID')
    for block in results.values():
        if not isinstance(block, dict):
            continue
        if block.get('error'):
            raise GrafanaSeriesError('GRAFANA_QUERY_FAILED')
        status = block.get('status')
        if status not in (None, 200, '200'):
            raise GrafanaSeriesError('GRAFANA_QUERY_FAILED')
    frame_count = sum(len((block or {}).get('frames') or []) for block in results.values())
    if frame_count > MAX_FRAMES_PER_QUERY:
        raise GrafanaSeriesError('GRAFANA_RESPONSE_TOO_LARGE')


def _cluster_from_labels(labels: dict, cluster_label: str, default_cluster: str) -> str:
    value = labels.get(cluster_label)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return default_cluster


def series_from_frames(payload, *, cluster: str, cluster_label: str) -> dict[CONTAINER_KEY, list[dict]]:
    """Map (cluster, namespace, pod, container) -> [{at, value}]."""
    validate_query_payload(payload)
    series: dict[CONTAINER_KEY, list[dict]] = {}
    for block in ((payload or {}).get('results') or {}).values():
        for frame in (block or {}).get('frames') or []:
            schema = (frame.get('schema') or {}).get('fields') or []
            values = (frame.get('data') or {}).get('values') or []
            if len(values) < 2:
                continue
            labels = (schema[1] if len(schema) > 1 else {}).get('labels') or {}
            ns, pod, container = labels.get('namespace', ''), labels.get('pod', ''), labels.get('container', '')
            if not container or container == 'POD':
                continue
            cl = _cluster_from_labels(labels, cluster_label, cluster)
            key = (cl, ns, pod, container)
            times, samples = values[0], values[1]
            if len(times) != len(samples):
                if len(times) == 1 and len(samples) > 1:
                    step_ms = 300_000
                    base = float(times[0])
                    times = [base + index * step_ms for index in range(len(samples))]
                else:
                    continue
            if len(samples) > MAX_SAMPLES_PER_SERIES:
                raise GrafanaSeriesError('GRAFANA_RESPONSE_TOO_LARGE')
            for stamp, raw in zip(times, samples):
                at = _timestamp_iso(stamp)
                value = _finite_float(raw)
                if at is None or value is None or value < 0:
                    continue
                series.setdefault(key, []).append({'at': at, 'value': value})
    return series


def instant_label_rows(payload, *, cluster: str, cluster_label: str) -> list[dict]:
    validate_query_payload(payload)
    rows = []
    for block in ((payload or {}).get('results') or {}).values():
        for frame in (block or {}).get('frames') or []:
            schema = (frame.get('schema') or {}).get('fields') or []
            values = (frame.get('data') or {}).get('values') or []
            if not values:
                continue
            labels = (schema[-1] if schema else {}).get('labels') or {}
            cl = _cluster_from_labels(labels, cluster_label, cluster)
            val = _finite_float(values[-1][-1] if values[-1] else None)
            rows.append({**labels, 'cluster': cl, 'value': val})
    return rows


def requests_from_frames(payload, resource: str, *, cluster: str, cluster_label: str) -> dict[CONTAINER_KEY, float]:
    validate_query_payload(payload)
    out: dict[CONTAINER_KEY, float] = {}
    for block in ((payload or {}).get('results') or {}).values():
        for frame in (block or {}).get('frames') or []:
            schema = (frame.get('schema') or {}).get('fields') or []
            values = (frame.get('data') or {}).get('values') or []
            if not values:
                continue
            labels = (schema[-1] if schema else {}).get('labels') or {}
            if labels.get('resource') != resource:
                continue
            ns, pod, container = labels.get('namespace', ''), labels.get('pod', ''), labels.get('container', '')
            if not container or container == 'POD':
                continue
            val = _finite_float(values[-1][-1] if values[-1] else None)
            if val is None:
                continue
            cl = _cluster_from_labels(labels, cluster_label, cluster)
            out[(cl, ns, pod, container)] = val
    return out


def coverage_ratio(
    points: list[dict],
    *,
    window_start: datetime,
    window_end: datetime,
    window_days: int,
    now: datetime | None = None,
    interval_minutes: int = 5,
    min_coverage_ratio: float = 0.90,
    max_gap_minutes: int = 60,
    max_staleness_seconds: int = 86400,
) -> tuple[float | None, str | None]:
    """Return (coverage_ratio, gap_code). gap_code set when insufficient."""
    now = now or datetime.now(timezone.utc)
    if window_end - window_start != timedelta(days=window_days):
        return None, 'INVALID_OBSERVATION_WINDOW'
    if not 0 <= (now - window_end).total_seconds() < max_staleness_seconds:
        return None, 'STALE_OR_FUTURE_WINDOW'
    expected = window_days * 1440 // interval_minutes
    parsed: dict[datetime, float] = {}
    for point in points:
        if not isinstance(point, dict):
            return None, 'INVALID_SAMPLE'
        at, value = moment(point.get('at')), point.get('value')
        if not at or not window_start < at <= window_end:
            return None, 'INVALID_SAMPLE'
        if (at - window_start).total_seconds() % (interval_minutes * 60):
            return None, 'UNALIGNED_SAMPLE'
        if at in parsed or not _finite_sample_value(value) or value < 0:
            return None, 'DUPLICATE_OR_INVALID_SAMPLE'
        parsed[at] = float(value)
    if len(parsed) < math.ceil(expected * min_coverage_ratio):
        ratio = len(parsed) / expected if expected else 0.0
        return ratio, 'INSUFFICIENT_SAMPLE_COVERAGE'
    times = [window_start, *sorted(parsed), window_end]
    gap = max((b - a).total_seconds() / 60 for a, b in zip(times, times[1:]))
    if gap > max_gap_minutes:
        ratio = len(parsed) / expected if expected else 0.0
        return ratio, 'UNEXPLAINED_TELEMETRY_GAP'
    return len(parsed) / expected, None


def values_for_percentile(points: list[dict]) -> list[float]:
    return [float(p['value']) for p in points if isinstance(p, dict) and _finite_sample_value(p.get('value'))]
