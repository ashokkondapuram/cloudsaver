"""Evidence contracts for eight Azure reviews. Unknown data never becomes a pass or approval."""
from datetime import datetime, timedelta, timezone
import math

from app.assessment import protection
from app.telemetry_contract import TimeSeriesEvidenceContract, evaluate_series

VERSION = '1.4.0'
OUTCOMES = ('condition_detected', 'condition_not_detected', 'insufficient_evidence', 'not_applicable',
            'disabled_by_policy', 'excluded_by_exception', 'unsupported_by_collector', 'evaluation_failed')

from app.resource_catalog import AZURE_EVIDENCE_CONTRACT_IDS as LEGACY_AZURE_RULE_IDS


def moment(value):
    try:
        value = datetime.fromisoformat(value.replace('Z', '+00:00')) if isinstance(value, str) else value
        return value.astimezone(timezone.utc) if isinstance(value, datetime) and value.tzinfo else None
    except (ValueError, TypeError):
        return None


def parameters(rule_id, overrides=None):
    from app.resource_catalog import validate_rule_parameters

    return validate_rule_parameters(rule_id, overrides)


def series(values, now):
    """30 days, five-minute buckets, >=95% coverage, no gap over an hour; no zero filling."""
    results = {label: evaluate_series(values, TimeSeriesEvidenceContract('metric', aggregation),
                                     now=now, require_resource_age=False)
               for label, aggregation in (('p95', 'P95'), ('p99', 'P99'), ('maximum', 'MAX'))}
    if not all(result.is_sufficient for result in results.values()):
        return None
    return {label: result.observed_value for label, result in results.items()} | {'coverage': results['p95'].coverage_ratio}


def continuous(evidence, expected, minimum_days, now):
    history = evidence.get('state_history')
    if not isinstance(history, list) or not history:
        return None
    intervals = []
    for item in history:
        if not isinstance(item, dict):
            return None
        start, end = moment(item.get('start')), moment(item.get('end'))
        if not start or not end or end <= start or item.get('complete') is not True:
            return None
        intervals.append((start, end, item.get('state')))
    intervals.sort()
    if intervals[-1][1] > now or now - intervals[-1][1] >= timedelta(hours=24):
        return None
    if any(a[1] != b[0] for a, b in zip(intervals, intervals[1:])):
        return None
    if intervals[0][0] > now - timedelta(days=minimum_days):
        return None
    return all(state == expected for _, _, state in intervals)


def legacy_azure_detect(rule_id, evidence, params, now):
    """Shared condition logic for the eight Azure contracts (catalog + unit tests)."""
    metrics = evidence.get('metrics') or {}
    known = lambda key: type(evidence.get(key)) is bool
    detected = None
    if rule_id == 'AZURE_DISK_UNATTACHED_RETENTION':
        if evidence.get('disk_state') == 'Unattached':
            detected = continuous(evidence, 'Unattached', params['minimum_days'], now)
        elif evidence.get('disk_state') in ('Attached', 'Reserved'):
            detected = False
    elif rule_id == 'AZURE_DISK_PROVISIONED_PERFORMANCE':
        if evidence.get('disk_state') == 'Unattached':
            if known('recent_snapshot_verified'):
                detected = not evidence['recent_snapshot_verified']
        else:
            io, throughput = series(metrics.get('iops'), now), series(metrics.get('throughput'), now)
            target = evidence.get('target_disk') or {}
            if (io and throughput and all(type(target.get(k)) in (int, float) and math.isfinite(target[k]) and target[k] > 0 for k in ('iops', 'throughput'))
                    and known('target_compatible') and known('throttling_observed')):
                factor = 1 + params['headroom_percent'] / 100
                detected = (evidence.get('target_compatible') is True and io['maximum'] * factor <= target['iops']
                            and throughput['maximum'] * factor <= target['throughput']
                            and evidence.get('throttling_observed') is False)
    elif rule_id == 'AZURE_PUBLIC_IP_UNASSOCIATED':
        if known('association_verified'):
            detected = False if evidence['association_verified'] else continuous(evidence, 'Unassociated', params['minimum_days'], now)
    elif rule_id == 'AZURE_PUBLIC_IP_ASSOCIATED_IDLE':
        traffic = [series(metrics.get(key), now) for key in ('ingress_bytes', 'egress_bytes')]
        if evidence.get('association_verified') is True and all(traffic):
            detected = all(item['maximum'] <= params['maximum_bytes'] for item in traffic)
    elif rule_id == 'AZURE_VM_STOPPED_RESIDUAL_COST':
        state = evidence.get('power_state')
        if state == 'PowerState/stopped':
            detected = True
        elif state == 'PowerState/deallocated':
            detected = continuous(evidence, state, params['minimum_days'], now)
        elif state == 'PowerState/running':
            detected = False
    elif rule_id in ('AZURE_VM_RIGHTSIZING_UTILIZATION', 'AZURE_ASP_UNDERUTILIZED_SKU'):
        cpu, memory = series(metrics.get('cpu_percent'), now), series(metrics.get('memory_percent'), now)
        created = moment(evidence.get('created_at'))
        if cpu and memory and created and now - created >= timedelta(days=30):
            detected = cpu['p95'] < params['cpu_percent'] and memory['p95'] < params.get('memory_percent', 40)
            if rule_id == 'AZURE_VM_RIGHTSIZING_UTILIZATION':
                if not series(metrics.get('disk_iops'), now) or not series(metrics.get('network_bytes'), now):
                    return None
                if not known('burst_credits_depleted'):
                    return None
                detected = detected and evidence['burst_credits_depleted'] is False
    elif rule_id == 'AZURE_ASP_EMPTY_PAID_PLAN':
        tier, apps, slots = evidence.get('sku_tier'), evidence.get('hosted_app_count'), evidence.get('deployment_slot_count')
        if tier in ('Free', 'Shared'):
            return 'not_applicable'
        if isinstance(tier, str) and type(apps) is int and type(slots) is int:
            detected = False if apps > 0 or slots > 0 else continuous(evidence, 'Empty', params['minimum_days'], now)
    if rule_id in ('AZURE_VM_RIGHTSIZING_UTILIZATION', 'AZURE_ASP_UNDERUTILIZED_SKU') and detected:
        from app.multicloud_rules import slo_gate
        safe = slo_gate(evidence, now)
        if safe is None:
            return 'slo_required'
        if not safe:
            return 'slo_blocked'
    return detected


def evaluate(resource, rule, *, policy=None, observed_at=None, now=None):
    now = now or datetime.now(timezone.utc)
    rule_id, suffix, name, _ = rule
    policy = policy or {}
    output = dict(rule_id=rule_id, rule_version=VERSION, name=name, cloud_provider='azure',
                  resource_id=resource['resource_id'], subscription_id=resource.get('subscription_id'),
                  resource_type=resource['resource_type'], outcome='insufficient_evidence',
                  reason='Required fresh configuration, history, or telemetry is unavailable.',
                  automatic_execution=False, estimated_savings=None, protected_reasons=protection(resource),
                  destructive_actions_blocked=bool(protection(resource)))

    def finish(state, reason):
        return dict(output, outcome=state, reason=reason)

    if policy.get('enabled') is False:
        return finish('disabled_by_policy', 'Disabled in the frozen workspace policy.')
    if policy.get('unavailable_reason'):
        return finish('disabled_by_policy', 'Unavailable under the frozen workspace policy.')
    if rule_id in resource.get('unsupported_rule_ids', []):
        return finish('unsupported_by_collector', 'This collector does not acquire the required evidence contract.')
    if resource.get('reconciliation_status')=='source_conflict':
        return finish('insufficient_evidence','Conflicting inventory sources require reconciliation before this rule can be evaluated.')
    observed = moment(observed_at)
    if not observed or not 0 <= (now - observed).total_seconds() < 86400:
        return output
    p = parameters(rule_id, policy.get('parameters'))
    evidence = resource.get('evidence') or {}
    detected = legacy_azure_detect(rule_id, evidence, p, now)
    if detected == 'not_applicable':
        return finish('not_applicable', 'This rule reviews independently billable dedicated plans.')
    if detected == 'slo_required':
        return dict(output, safety_blocks=['SLO_EVIDENCE_REQUIRED'])
    if detected == 'slo_blocked':
        return dict(finish('condition_not_detected', 'SLO or saturation evidence blocks capacity reduction.'), safety_blocks=['SLO_ERROR_BUDGET_RISK'])
    if detected is None:
        return output
    return finish('condition_detected' if detected else 'condition_not_detected',
                  'Evidence meets the review condition; dependencies, target compatibility and cost require review.'
                  if detected else 'Available evidence does not meet this rule condition.')


def evaluate_inventory(inventory, *, policies=None, observed_at=None, now=None):
    from app.kubernetes_rules import evaluate_inventory as evaluate_kubernetes
    from app.multicloud_rules import evaluate_inventory as evaluate_catalog
    return evaluate_kubernetes(inventory, policies=policies, observed_at=observed_at, now=now) + evaluate_catalog(
        inventory, policies=policies, observed_at=observed_at, now=now
    )
