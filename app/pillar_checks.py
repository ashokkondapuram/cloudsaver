"""Resource-specific evidence checks; absence never establishes a safe control."""
from datetime import datetime, timezone

from app.assessment_policy import number, timestamp
from app.resource_evidence_scope import check_allowed, exposure_field_keys
from app.telemetry_contract import TimeSeriesEvidenceContract, evaluate_series

NUMERIC_FACTS = (
    'stopped_days',
    'cfs_throttling_p95_pct',
    'oom_kill_count_30d',
    'burst_credit_balance_min',
    'surplus_credits_charged',
    'disk_queue_length_p99',
    'throttle_events',
    'http_429_count',
    'slo_burn_rate',
    'cpu_latency_correlation_r',
    'disruptions_allowed',
)

_THRESHOLD_SPECS = (
    ('CFS_THROTTLING', 'cfs_throttling_p95_pct', 2, False),
    ('OOM_HISTORY', 'oom_kill_count_30d', 0, False),
    ('BURST_CREDITS', 'burst_credit_balance_min', 20, True),
    ('SURPLUS_CREDITS', 'surplus_credits_charged', 0, False),
    ('DISK_QUEUE', 'disk_queue_length_p99', 1, False),
    ('SERVICE_THROTTLING', 'throttle_events', 0, False),
    ('HTTP_THROTTLING', 'http_429_count', 0, False),
    ('SLO_BURN', 'slo_burn_rate', 1, False),
)


def checks(kind, e, add, *, observed_at=None, now=None, protected=(), profile=None):
    now = timestamp(now) or datetime.now(timezone.utc)
    from app.assessment_policy import utilization

    legacy = utilization(e, observed_at)

    def result(pillar, code, fields, value, message):
        add(pillar, code, 'unknown' if value is None else 'observed' if value else 'risk', message, fields)

    def threshold(pillar, code, field, limit, minimum=False):
        if profile is not None and not check_allowed(code, profile):
            return
        v = number(e.get(field))
        result(
            pillar,
            code,
            [field],
            None if v is None else v >= limit if minimum else v <= limit,
            'Measured ' + field + ' must be ' + ('at least ' if minimum else 'at most ') + str(limit) + '; missing values require collection.',
        )

    if check_allowed('PROTECTION_METADATA', profile):
        result(
            'reliability',
            'PROTECTION_METADATA',
            ['management_locks', 'backup_enrolled', 'replication_enrolled'],
            False
            if protected
            else None
            if not any(k in e for k in ('management_locks', 'backup_enrolled', 'replication_enrolled'))
            else True,
            'Protection and preservation requirements take precedence over optimization.',
        )
    if check_allowed('COMMITMENT_LOCK', profile):
        result(
            'cost',
            'COMMITMENT_LOCK',
            ['commitment_lock_conflict'],
            None if type(e.get('commitment_lock_conflict')) is not bool else not e['commitment_lock_conflict'],
            'Locked commitments can prevent physical cleanup from reducing the bill.',
        )
    if check_allowed('SNAPSHOT_VERIFICATION', profile):
        age = number(e.get('snapshot_age_hours'))
        verified = e.get('recent_snapshot_verified')
        value = (
            False
            if verified is False or age is not None and age >= 24
            else True
            if verified is True and age is not None and age < 24
            else None
        )
        result(
            'reliability',
            'SNAPSHOT_VERIFICATION',
            ['recent_snapshot_verified', 'snapshot_age_hours'],
            value,
            'Recovery requires a verified snapshot less than 24 hours old; restore acceptance remains independent.',
        )
    if check_allowed('MULTI_AZ_INTENT', profile):
        tags = e.get('tags') or e.get('labels') or {}
        env = tags.get('environment', tags.get('env'))
        intentional = env in ('dev', 'development', 'test', 'sandbox', 'staging')
        ha = e.get('multi_az', e.get('zone_redundant'))
        floor = e.get('proposed_replica_count')
        value = True if intentional else ha if type(ha) is bool and env in ('prod', 'production') else None
        if env in ('prod', 'production') and type(floor) is int and floor < 2:
            value = False
        result(
            'reliability',
            'MULTI_AZ_INTENT',
            ['tags', 'multi_az', 'proposed_replica_count'],
            value,
            'Availability requirements depend on explicit environment and verified replica topology.',
        )
    if check_allowed('BACKUP_RETENTION', profile):
        tags = e.get('tags') or e.get('labels') or {}
        floor = 14 if tags.get('environment') in ('production', 'prod') else 7
        threshold('reliability', 'BACKUP_RETENTION', 'backup_retention_days', floor, True)
    if check_allowed('REPLICATION_LAG', profile):
        threshold('performance', 'REPLICATION_LAG', 'replication_lag_seconds', 60)
    for code, field, limit, minimum in _THRESHOLD_SPECS:
        if profile is not None and not check_allowed(code, profile):
            continue
        if not legacy or field in e:
            threshold('performance', code, field, limit, minimum)
    if check_allowed('SLO_LATENCY_CORRELATION', profile) and (not legacy or 'cpu_latency_correlation_r' in e):
        r = e.get('cpu_latency_correlation_r')
        valid = type(r) in (int, float) and -1 <= r <= 1
        result(
            'performance',
            'SLO_LATENCY_CORRELATION',
            ['cpu_latency_correlation_r'],
            r <= 0.60 if valid else None,
            'CPU/latency sensitivity above 0.60 blocks unreviewed capacity reduction.',
        )
    if check_allowed('OBSERVED_LATENCY_SENSITIVITY', profile) and type(e.get('latency_sensitive')) is bool:
        result(
            'performance',
            'OBSERVED_LATENCY_SENSITIVITY',
            ['latency_sensitive', 'observed_latency_p95_ms', 'observed_error_rate_pct'],
            not e['latency_sensitive'],
            'Linked traces or latency metrics above connector thresholds block unreviewed capacity reduction.',
        )
    if check_allowed('FIVE_MINUTE_UTILIZATION', profile):
        from app.collectors.live_common import metrics_utilization_complete

        metrics = e.get('metrics') or {}
        complete = metrics_utilization_complete(
            e,
            profile.utilization_metrics if profile else (),
            now=now,
        )
        if not complete:
            metric_keys = profile.utilization_metrics if profile else (
                'cpu_percent',
                'memory_percent',
                'iops',
                'normalized_ru_consumption',
                'ptu_utilization',
            )
            for key in metric_keys:
                value = metrics.get(key)
                if not isinstance(value, dict):
                    continue
                contract = TimeSeriesEvidenceContract(key)
                if evaluate_series(value, contract, now=now, require_resource_age=False).is_sufficient:
                    complete = True
                    break
        result(
            'performance',
            'FIVE_MINUTE_UTILIZATION',
            ['metrics'],
            True if complete or legacy else None,
            'Measured 14-day hourly or 30-day five-minute evidence requires 95% coverage and no gap over one hour; target compatibility remains separate.',
        )
    if check_allowed('PUBLIC_EXPOSURE', profile) and profile is not None:
        keys = exposure_field_keys(profile, kind)
        values = [e[k] for k in keys if type(e.get(k)) is bool]
        result(
            'security',
            'PUBLIC_EXPOSURE',
            list(keys),
            False if True in values else True if values and all(v is False for v in values) else None,
            'Exposure checks require explicit provider evidence; one known private property cannot establish all access paths.',
        )
    if check_allowed('ENCRYPTION_AT_REST', profile):
        value = e.get('encrypted')
        result(
            'security',
            'ENCRYPTION_AT_REST',
            ['encrypted'],
            value if type(value) is bool else None,
            'Provider encryption state must be explicit.',
        )
        if e.get('customer_managed_key_required') is True and check_allowed('CUSTOMER_MANAGED_KEY', profile):
            cmk = e.get('customer_managed_key_verified')
            result(
                'security',
                'CUSTOMER_MANAGED_KEY',
                ['customer_managed_key_verified'],
                cmk if type(cmk) is bool else None,
                'Policy-required customer keys need verified provider configuration.',
            )
    if check_allowed('TRANSPORT_TLS', profile):
        value = e.get('tls_required')
        result(
            'security',
            'TRANSPORT_TLS',
            ['tls_required'],
            value if type(value) is bool else None,
            'Transport policy requires TLS 1.2 or stronger; unspecified settings remain unknown.',
        )
    if kind == 'ai':
        for code, field in (('KEYLESS_LOCAL_AUTH', 'managed_secrets'), ('MODEL_GUARDRAIL', 'guardrail_enforced')):
            if not check_allowed(code, profile):
                continue
            value = e.get(field)
            result(
                'security',
                code,
                [field],
                value if type(value) is bool else None,
                'Model identity and safety policy require explicit evidence.',
            )
    if check_allowed('STATE_TRANSITION_AUDIT', profile):
        history = e.get('state_history')
        verified = False
        if isinstance(history, list) and history:
            end = timestamp(history[-1].get('end'))
            start = timestamp(history[0].get('start'))
            verified = bool(
                start and end and start < end and 0 <= (now - end).total_seconds() < 86400 and all(i.get('complete') is True for i in history)
            )
        result(
            'operations',
            'STATE_TRANSITION_AUDIT',
            ['state_history'],
            True if verified else None,
            'Creation time and missing audit events cannot prove continuous resource state.',
        )
    if check_allowed('MANAGEMENT_LOCK', profile):
        locks = e.get('management_locks')
        result(
            'operations',
            'MANAGEMENT_LOCK',
            ['management_locks'],
            not bool(set(locks) & {'CanNotDelete', 'ReadOnly'})
            if isinstance(locks, list) and all(isinstance(v, str) for v in locks)
            else None,
            'Inherited management locks must be reviewed before changes.',
        )
    if check_allowed('PDB_DRAIN_LOCK', profile) and 'disruptions_allowed' in e:
        threshold('operations', 'PDB_DRAIN_LOCK', 'disruptions_allowed', 1, True)
