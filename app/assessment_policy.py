"""Versioned evidence rules. Thresholds are review policy, never approval criteria."""
from datetime import datetime, timezone
import math

POLICY_VERSION = '2026-10-23.1'
MAX_OBSERVATION_AGE_HOURS = 24


def number(value):
    return value if type(value) in (int, float) and 0 <= value <= 1e15 and math.isfinite(value) else None


def timestamp(value):
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00')) if isinstance(value, str) else value
        return parsed.astimezone(timezone.utc) if isinstance(parsed, datetime) and parsed.tzinfo is not None else None
    except (ValueError, OverflowError):
        return None


def freshness(observed_at, now=None):
    observed, current = timestamp(observed_at), timestamp(now) if now is not None else datetime.now(timezone.utc)
    age = (current - observed).total_seconds() / 3600 if observed and current else None
    return dict(status='unknown' if age is None else 'invalid' if age < 0 else 'stale' if age > MAX_OBSERVATION_AGE_HOURS else 'recent',
                observed_at=observed.isoformat() if observed else None, max_age_hours=MAX_OBSERVATION_AGE_HOURS)


def utilization(evidence, observed_at):
    """Validate the saved collector contract; sample count alone cannot prove raw series."""
    start, end, observed = (timestamp(evidence.get('window_start')), timestamp(evidence.get('window_end')), timestamp(observed_at))
    dimension, unit = evidence.get('dimension'), evidence.get('unit')
    p95, request = number(evidence.get('p95_usage')), number(evidence.get('minimum_request'))
    valid = (evidence.get('window_days') == 14 and type(evidence.get('window_days')) is int
             and type(evidence.get('samples')) is int and evidence['samples'] == 337
             and type(evidence.get('step_seconds')) is int and evidence['step_seconds'] == 3600
             and evidence.get('percentile_method') == 'nearest_rank_0.95'
             and (dimension, unit) in (('cpu', 'cores'), ('memory', 'bytes'))
             and p95 is not None and request is not None and request > 0
             and start is not None and end is not None and (end - start).total_seconds() == 14 * 86400
             and (observed is None or 0 <= (observed - end).total_seconds() <= 3600))
    return bool(valid)


# kind(s), pillar, code, evidence field, desired boolean, positive/negative description
BOOLEAN_RULES = (
    (('compute',), 'security', 'INSTANCE_METADATA', 'imds_v2_required', True, 'Instance metadata v2 is required.', 'Instance metadata v2 is not required.'),
    (('compute',), 'security', 'ADMIN_INGRESS', 'public_admin_ingress', False, 'No public administrative ingress is reported.', 'Public administrative ingress is reported.'),
    (('compute',), 'operations', 'MONITORING_AGENT', 'monitoring_enabled', True, 'Monitoring is reported enabled.', 'Monitoring is explicitly disabled.'),
    (('database',), 'security', 'DATABASE_TLS', 'tls_required', True, 'Database TLS is reported required.', 'Database TLS is not required.'),
    (('database',), 'operations', 'ENGINE_SUPPORT', 'engine_supported', True, 'Engine support is reported current.', 'Engine support is reported expired.'),
    (('database',), 'operations', 'AUTO_MINOR_UPGRADE', 'auto_minor_upgrade', True, 'Automatic minor upgrades are enabled.', 'Automatic minor upgrades are disabled.'),
    (('application',), 'reliability', 'HEALTH_PROBES', 'health_probes_enabled', True, 'Health probes are configured.', 'Health probes are explicitly disabled.'),
    (('application',), 'security', 'MANAGED_SECRETS', 'managed_secrets', True, 'Managed secret injection is reported.', 'Unmanaged secret configuration requires review.'),
    (('network',), 'operations', 'FLOW_LOGS', 'flow_logs_enabled', True, 'Flow logging is reported enabled.', 'Flow logging is explicitly disabled.'),
    (('storage',), 'security', 'SNAPSHOT_EXPOSURE', 'public_snapshot', False, 'Snapshot exposure is reported private.', 'Public snapshot exposure is reported.'),
)


def service_checks(kind, evidence, add):
    for kinds, pillar, code, field, positive, yes, no in BOOLEAN_RULES:
        if kind in kinds:
            value = evidence.get(field)
            known = type(value) is bool
            add(pillar, code, 'unknown' if not known else 'observed' if value is positive else 'risk',
                (yes if value is positive else no) if known else 'This control was not collected; independent verification is required.', [field])
    if kind == 'application':
        sites = number(evidence.get('hosted_app_count'))
        add('cost', 'APPLICATION_DENSITY', 'unknown' if sites is None or int(sites) != sites else 'risk' if sites == 0 else 'observed',
            'Hosted application count is unavailable.' if sites is None else f'Observed hosted applications: {sites:g}. Capacity intent and tier pricing need review.', ['hosted_app_count'])
    if kind == 'compute':
        age = number(evidence.get('patch_age_days'))
        add('operations', 'PATCH_CURRENCY', 'unknown' if age is None else 'risk' if age > 90 else 'observed',
            'Patch age is unavailable.' if age is None else f'Observed patch age: {age:g} days; workload patch policy still applies.', ['patch_age_days'])
    if kind == 'storage':
        days = number(evidence.get('unattached_days'))
        add('cost', 'UNATTACHED_DURATION', 'unknown' if days is None else 'risk' if days > 14 else 'observed',
            'Unattached duration was not measured; current unattached state is insufficient.' if days is None else f'Observed unattached duration: {days:g} days; retention intent must be checked.', ['unattached_days'])
        age = number(evidence.get('snapshot_age_hours'))
        add('reliability', 'SNAPSHOT_FRESHNESS', 'unknown' if age is None else 'risk' if age > 24 else 'observed',
            'Snapshot age is unavailable.' if age is None else f'Observed snapshot age: {age:g} hours; restore acceptance is unverified.', ['snapshot_age_hours'])

MODEL_BASE_CODES={r[2] for r in BOOLEAN_RULES}|{'RETAIL_ESTIMATE','BILLED_COST','RECOVERY_SNAPSHOT','FAILOVER_TOPOLOGY','DATABASE_RECOVERY','UTILIZATION_WINDOW','ENCRYPTION_AT_REST','PUBLIC_DATABASE','APPLICATION_DENSITY','PATCH_CURRENCY','UNATTACHED_DURATION','SNAPSHOT_FRESHNESS','OWNERSHIP','DEPENDENCY_GRAPH','PROTECTED_INTENT','REQUEST_HEADROOM'}
