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


# providers, kind(s), pillar, code, evidence field, desired boolean, positive/negative description
BOOLEAN_RULES = (
    (('aws',), ('compute',), 'security', 'INSTANCE_METADATA', 'imds_v2_required', True, 'Instance metadata v2 is required.', 'Instance metadata v2 is not required.'),
    (('azure', 'aws', 'gcp'), ('compute',), 'security', 'ADMIN_INGRESS', 'public_admin_ingress', False, 'No public administrative ingress is reported.', 'Public administrative ingress is reported.'),
    (('azure', 'aws', 'gcp'), ('compute',), 'operations', 'MONITORING_AGENT', 'monitoring_enabled', True, 'Monitoring is reported enabled.', 'Monitoring is explicitly disabled.'),
    (('azure', 'aws', 'gcp'), ('database',), 'security', 'DATABASE_TLS', 'tls_required', True, 'Database TLS is reported required.', 'Database TLS is not required.'),
    (('azure', 'aws', 'gcp'), ('database',), 'operations', 'ENGINE_SUPPORT', 'engine_supported', True, 'Engine support is reported current.', 'Engine support is reported expired.'),
    (('azure', 'aws', 'gcp'), ('database',), 'operations', 'AUTO_MINOR_UPGRADE', 'auto_minor_upgrade', True, 'Automatic minor upgrades are enabled.', 'Automatic minor upgrades are disabled.'),
    (('azure', 'aws', 'gcp'), ('application',), 'reliability', 'HEALTH_PROBES', 'health_probes_enabled', True, 'Health probes are configured.', 'Health probes are explicitly disabled.'),
    (('azure', 'aws', 'gcp'), ('application',), 'security', 'MANAGED_SECRETS', 'managed_secrets', True, 'Managed secret injection is reported.', 'Unmanaged secret configuration requires review.'),
    (('azure', 'aws', 'gcp'), ('network',), 'operations', 'FLOW_LOGS', 'flow_logs_enabled', True, 'Flow logging is reported enabled.', 'Flow logging is explicitly disabled.'),
    (('azure', 'aws', 'gcp'), ('storage',), 'security', 'SNAPSHOT_EXPOSURE', 'public_snapshot', False, 'Snapshot exposure is reported private.', 'Public snapshot exposure is reported.'),
)


def service_checks(kind, evidence, add, provider, *, profile=None):
    from app.resource_evidence_scope import check_allowed

    def gated(pillar, code, state, message, fields=None, *, providers=('*',)):
        if profile is not None and not check_allowed(code, profile):
            return
        add(pillar, code, state, message, fields, providers=providers)

    for providers, kinds, pillar, code, field, positive, yes, no in BOOLEAN_RULES:
        if provider not in providers or kind not in kinds:
            continue
        value = evidence.get(field)
        known = type(value) is bool
        gated(
            pillar,
            code,
            'unknown' if not known else 'observed' if value is positive else 'risk',
            (yes if value is positive else no) if known else 'This control was not collected; independent verification is required.',
            [field],
            providers=providers,
        )
    if kind == 'application' and provider in ('azure', 'aws', 'gcp'):
        sites = number(evidence.get('hosted_app_count'))
        gated(
            'cost',
            'APPLICATION_DENSITY',
            'unknown' if sites is None or int(sites) != sites else 'risk' if sites == 0 else 'observed',
            'Hosted application count is unavailable.' if sites is None else f'Observed hosted applications: {sites:g}. Capacity intent and tier pricing need review.',
            ['hosted_app_count'],
            providers=('azure', 'aws', 'gcp'),
        )
    if kind == 'compute' and provider in ('azure', 'aws', 'gcp', 'kubernetes'):
        age = number(evidence.get('patch_age_days'))
        gated(
            'operations',
            'PATCH_CURRENCY',
            'unknown' if age is None else 'risk' if age > 90 else 'observed',
            'Patch age is unavailable.' if age is None else f'Observed patch age: {age:g} days; workload patch policy still applies.',
            ['patch_age_days'],
            providers=('azure', 'aws', 'gcp', 'kubernetes'),
        )
    if kind == 'storage' and provider in ('azure', 'aws', 'gcp'):
        days = number(evidence.get('unattached_days'))
        gated(
            'cost',
            'UNATTACHED_DURATION',
            'unknown' if days is None else 'risk' if days > 14 else 'observed',
            'Unattached duration was not measured; current unattached state is insufficient.' if days is None else f'Observed unattached duration: {days:g} days; retention intent must be checked.',
            ['unattached_days'],
            providers=('azure', 'aws', 'gcp'),
        )
        age = number(evidence.get('snapshot_age_hours'))
        gated(
            'reliability',
            'SNAPSHOT_FRESHNESS',
            'unknown' if age is None else 'risk' if age > 24 else 'observed',
            'Snapshot age is unavailable.' if age is None else f'Observed snapshot age: {age:g} hours; restore acceptance is unverified.',
            ['snapshot_age_hours'],
            providers=('azure', 'aws', 'gcp'),
        )

MODEL_BASE_CODES={r[3] for r in BOOLEAN_RULES}|{'RETAIL_ESTIMATE','BILLED_COST','RECOVERY_SNAPSHOT','FAILOVER_TOPOLOGY','DATABASE_RECOVERY','UTILIZATION_WINDOW','ENCRYPTION_AT_REST','PUBLIC_DATABASE','APPLICATION_DENSITY','PATCH_CURRENCY','UNATTACHED_DURATION','SNAPSHOT_FRESHNESS','OWNERSHIP','DEPENDENCY_GRAPH','PROTECTED_INTENT','REQUEST_HEADROOM'}
