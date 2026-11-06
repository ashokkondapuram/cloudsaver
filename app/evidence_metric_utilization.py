"""Use saved Monitor series and summaries for rules, registry telemetry, and assessment."""
from __future__ import annotations

from datetime import datetime, timezone

from app.telemetry_contract import TimeSeriesEvidenceContract, evaluate_series


def _now(now):
    return now or datetime.now(timezone.utc)


def metric_has_sufficient(evidence: dict, key: str, *, now=None) -> bool:
    summaries = (evidence.get('metric_summaries') or {}).get(key)
    if isinstance(summaries, dict) and summaries.get('sufficient') is True:
        return True
    series = (evidence.get('metrics') or {}).get(key)
    if not isinstance(series, dict):
        return False
    contract = TimeSeriesEvidenceContract(key)
    return evaluate_series(series, contract, now=_now(now), require_resource_age=False).is_sufficient


def metric_window(evidence: dict, key: str, *, now=None) -> dict | None:
    """Validated p95/p99/maximum from metric_summaries or raw metrics."""
    now = _now(now)
    summary = (evidence.get('metric_summaries') or {}).get(key)
    if isinstance(summary, dict) and summary.get('sufficient') is True:
        out = {}
        for stat in ('p95', 'p99', 'maximum', 'average'):
            if summary.get(stat) is not None:
                out[stat] = summary[stat]
        if summary.get('coverage_ratio') is not None:
            out['coverage'] = summary['coverage_ratio']
        return out or None
    series = (evidence.get('metrics') or {}).get(key)
    if not isinstance(series, dict):
        return None
    stats = {}
    coverage = None
    for label, agg in (('p95', 'P95'), ('p99', 'P99'), ('maximum', 'MAX')):
        result = evaluate_series(
            series,
            TimeSeriesEvidenceContract(key, agg),
            now=now,
            require_resource_age=False,
        )
        if not result.is_sufficient:
            return None
        stats[label] = result.observed_value
        coverage = result.coverage_ratio
    if coverage is not None:
        stats['coverage'] = coverage
    return stats


def metric_stat(evidence: dict, key: str, stat: str = 'p95', *, now=None):
    window = metric_window(evidence, key, now=now)
    if not window:
        return None
    return window.get(stat)


def apply_metrics_to_evidence_fields(evidence: dict, *, now=None) -> None:
    """Copy validated metric rollups into top-level evidence keys rules and registry read."""
    now = _now(now)
    rollups = evidence.setdefault('metric_rollups', {})

    for key in (
        'cpu_percent',
        'memory_percent',
        'memory_free_bytes',
        'requests',
        'healthy_targets',
        'connections',
        'network_bytes',
        'iops',
        'throughput',
        'ingress_bytes',
        'normalized_ru_consumption',
        'ptu_utilization',
        'invocations',
    ):
        window = metric_window(evidence, key, now=now)
        if window:
            rollups[key] = window

    ru = rollups.get('normalized_ru_consumption')
    if ru and evidence.get('ru_average_percent') is None:
        value = ru.get('p95')
        if value is None:
            value = ru.get('maximum')
        if type(value) in (int, float):
            evidence['ru_average_percent'] = value

    healthy = rollups.get('healthy_targets')
    if healthy and type(healthy.get('maximum')) in (int, float):
        evidence['healthy_target_count'] = int(healthy['maximum'])

    backends = evidence.get('backend_pool_count')
    if evidence.get('dependencies_verified') is None and type(backends) is int:
        if backends == 0:
            evidence['dependencies_verified'] = False
        elif healthy and type(healthy.get('maximum')) in (int, float):
            evidence['dependencies_verified'] = healthy['maximum'] >= 1
        else:
            evidence['dependencies_verified'] = True

    if evidence.get('throttling_observed') is None:
        iops = rollups.get('iops') or rollups.get('disk_iops')
        if iops and type(iops.get('maximum')) in (int, float):
            evidence['throttling_observed'] = iops['maximum'] > 0
