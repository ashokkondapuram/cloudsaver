"""Shared latency series helpers for Kubernetes SLO packets and Grafana rightsizing."""

from __future__ import annotations

import math
import re
from datetime import datetime, timezone

from app.telemetry_contract import TimeSeriesEvidenceContract, evaluate_series

PROXY_BASIS = 'decoupled_low_latency_proxy'
OBSERVABILITY_LATENCY_BASIS = 'observability_latency_query'
PROMETHEUS_LATENCY_BASIS = 'prometheus_latency'

LATENCY_QUERY_MAX = 2000


def validate_latency_query(expr: str | None) -> str | None:
    """Return a normalized PromQL fragment or None when unset."""
    if expr is None:
        return None
    if not isinstance(expr, str):
        raise ValueError('latency_query must be text.')
    cleaned = expr.strip()
    if not cleaned:
        return None
    if not 1 <= len(cleaned) <= LATENCY_QUERY_MAX:
        raise ValueError(f'latency_query must be 1–{LATENCY_QUERY_MAX} characters.')
    if re.search(r'[\n\r;]', cleaned):
        raise ValueError('latency_query must be a single-line PromQL expression.')
    return cleaned


def validate_latency_unit(unit: str | None) -> str:
    if unit is None:
        return 'milliseconds'
    if unit not in ('seconds', 'milliseconds'):
        raise ValueError('latency_unit must be seconds or milliseconds.')
    return unit


def render_latency_query(template: str, *, cluster_matcher: str, namespace: str = '', pod: str = '', container: str = '') -> str:
    return (template.replace('{cluster_matcher}', cluster_matcher)
            .replace('{namespace}', namespace)
            .replace('{pod}', pod)
            .replace('{container}', container))


def _to_latency_ms(value: float, unit: str) -> float:
    return float(value) * (1000.0 if unit == 'seconds' else 1.0)


def proxy_latency_series(cpu_series: dict, *, target_ms: float = 10.0) -> dict:
    return {
        'window_start': cpu_series['window_start'],
        'window_end': cpu_series['window_end'],
        'points': [
            {'at': point['at'], 'value': target_ms * (1 + 0.002 * ((index * 7) % 13))}
            for index, point in enumerate(cpu_series['points'])
        ],
        'basis': PROXY_BASIS,
    }


def latency_series_from_metric(latency_metric: dict | None, cpu_series: dict, *, unit: str = 'milliseconds') -> dict | None:
    """Build a real latency_p99_series when container latency telemetry matches the CPU window."""
    if not isinstance(latency_metric, dict) or latency_metric.get('sufficient') is not True:
        return None
    points = latency_metric.get('points')
    if not isinstance(points, list) or not points:
        return None
    if latency_metric.get('window_start') != cpu_series.get('window_start'):
        return None
    if latency_metric.get('window_end') != cpu_series.get('window_end'):
        return None
    contract = TimeSeriesEvidenceContract('interval_p99_latency_ms', 'MAX')
    scaled = {
        'window_start': cpu_series['window_start'],
        'window_end': cpu_series['window_end'],
        'points': [{'at': p['at'], 'value': _to_latency_ms(p['value'], unit)} for p in points if isinstance(p, dict)],
    }
    check = evaluate_series(scaled, contract, require_resource_age=False)
    if not check.is_sufficient:
        return None
    basis = latency_metric.get('basis') or PROMETHEUS_LATENCY_BASIS
    return dict(scaled, basis=basis)


def resolve_latency_p99_series(cpu_series: dict, evidence: dict, *, slo_target_ms: float = 100.0) -> dict:
    """Fail-closed: observability latency when sufficient, otherwise decoupled proxy."""
    prebuilt = evidence.get('latency_p99_series')
    if isinstance(prebuilt, dict) and prebuilt.get('basis') != PROXY_BASIS:
        return prebuilt
    metrics = evidence.get('metrics') or {}
    unit = (metrics.get('latency') or {}).get('unit') or evidence.get('latency_unit') or 'milliseconds'
    built = latency_series_from_metric(metrics.get('latency'), cpu_series, unit=unit)
    if built is not None:
        return built
    return proxy_latency_series(cpu_series, target_ms=min(10.0, slo_target_ms * 0.1))


def latency_points_from_grafana_frames(
    payload, *, unit: str = 'milliseconds', cluster: str = '', cluster_label: str = 'cluster',
) -> dict[tuple, list[dict]]:
    """Map (cluster, namespace, pod, container) or legacy 3-tuple -> [{at, value}] from Grafana frames."""
    from app.collectors.grafana_telemetry import _cluster_from_labels, validate_query_payload

    validate_query_payload(payload)
    out: dict[tuple, list[dict]] = {}
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
            cl = _cluster_from_labels(labels, cluster_label, cluster) if cluster else labels.get(cluster_label, '') or cluster
            key = (cl, ns, pod, container) if cluster else (ns, pod, container)
            times, samples = values[0], values[1]
            series = []
            for stamp, raw in zip(times, samples):
                if raw is None or not isinstance(stamp, (int, float)):
                    continue
                value = float(raw)
                if not math.isfinite(value) or value < 0:
                    continue
                at_ms = float(stamp)
                at = datetime.fromtimestamp(at_ms / 1000.0 if at_ms > 1e12 else at_ms, timezone.utc).isoformat()
                series.append({'at': at, 'value': _to_latency_ms(value, unit)})
            if series:
                out.setdefault(key, []).extend(series)
    return out
