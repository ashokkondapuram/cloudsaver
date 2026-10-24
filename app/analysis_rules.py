"""Evidence contracts for eight Azure reviews. Unknown data never becomes a pass or approval."""
from datetime import datetime, timedelta, timezone
import math

from app.assessment import protection

VERSION = '2026-10-23.2'
# id, resource type suffix, name, configurable parameters with (default, min, max)
RULES = (
    ('AZURE_DISK_UNATTACHED_RETENTION', 'disks', 'Retained unattached managed disk review', {'minimum_days': (14, 7, 90)}),
    ('AZURE_DISK_PROVISIONED_PERFORMANCE', 'disks', 'Disk recovery and provisioned performance review', {'headroom_percent': (30, 20, 100)}),
    ('AZURE_PUBLIC_IP_UNASSOCIATED', 'publicipaddresses', 'Unassociated public IP review', {'minimum_days': (7, 7, 90)}),
    ('AZURE_PUBLIC_IP_ASSOCIATED_IDLE', 'publicipaddresses', 'Associated public IP traffic review', {'maximum_bytes': (0, 0, 1024)}),
    ('AZURE_VM_STOPPED_RESIDUAL_COST', 'virtualmachines', 'Stopped VM residual charge review', {'minimum_days': (14, 7, 90)}),
    ('AZURE_VM_RIGHTSIZING_UTILIZATION', 'virtualmachines', 'Evidence-based VM rightsizing review', {'cpu_percent': (10, 1, 20)}),
    ('AZURE_ASP_EMPTY_PAID_PLAN', 'serverfarms', 'Empty paid App Service plan review', {'minimum_days': (7, 7, 90)}),
    ('AZURE_ASP_UNDERUTILIZED_SKU', 'serverfarms', 'App Service capacity review', {'cpu_percent': (15, 1, 30), 'memory_percent': (30, 1, 40)}),
)


def moment(value):
    try:
        value = datetime.fromisoformat(value.replace('Z', '+00:00')) if isinstance(value, str) else value
        return value.astimezone(timezone.utc) if isinstance(value, datetime) and value.tzinfo else None
    except (ValueError, TypeError):
        return None


def parameters(rule_id, overrides=None):
    rule = next(rule for rule in RULES if rule[0] == rule_id)
    bounds = rule[3]
    if not isinstance(overrides or {}, dict) or set(overrides or {}) - set(bounds):
        raise ValueError('Unknown rule parameter')
    result = {}
    for key, (default, low, high) in bounds.items():
        value = (overrides or {}).get(key, default)
        if type(value) is not int or not low <= value <= high:
            raise ValueError(f'{key} must be an integer between {low} and {high}')
        result[key] = value
    return result


def series(values, now):
    """30 days, five-minute buckets, >=95% coverage, no gap over an hour; no zero filling."""
    if not isinstance(values, dict):
        return None
    start, end = moment(values.get('window_start')), moment(values.get('window_end'))
    points = values.get('points')
    if not start or not end or end - start != timedelta(days=30) or not 0 <= (now - end).total_seconds() < 86400:
        return None
    if not isinstance(points, list) or len(points) > 8640 or len(points) < math.ceil(8640 * .95):
        return None
    parsed = {}
    for point in points:
        if not isinstance(point, dict):
            return None
        stamp, value = moment(point.get('at')), point.get('value')
        if (not stamp or stamp <= start or stamp > end or (stamp - start).total_seconds() % 300
                or stamp in parsed or type(value) not in (int, float) or not math.isfinite(value) or value < 0):
            return None
        parsed[stamp] = value
    times = [start, *sorted(parsed), end]
    if max((b - a).total_seconds() for a, b in zip(times, times[1:])) > 3600:
        return None
    ordered = sorted(parsed.values())
    return {'p95': ordered[math.ceil(len(ordered) * .95) - 1],
            'p99': ordered[math.ceil(len(ordered) * .99) - 1], 'maximum': ordered[-1],
            'coverage': len(ordered) / 8640}


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


def evaluate(resource, rule, *, policy=None, observed_at=None, now=None):
    now = now or datetime.now(timezone.utc)
    rule_id, suffix, name, _ = rule
    policy = policy or {}
    output = dict(rule_id=rule_id, rule_version=VERSION, name=name, cloud_provider='azure',
                  resource_id=resource['resource_id'], subscription_id=resource.get('subscription_id'),
                  resource_type=resource['resource_type'], outcome='insufficient_evidence',
                  reason='Required fresh configuration, history, or telemetry is unavailable.',
                  automatic_execution=False, estimated_savings=None)

    def finish(state, reason):
        return dict(output, outcome=state, reason=reason)

    if policy.get('enabled') is False:
        return finish('disabled_by_policy', 'Disabled in the frozen workspace policy.')
    if policy.get('unavailable_reason'):
        return finish('unavailable', 'Unavailable under the frozen workspace policy.')
    if protection(resource):
        return finish('excluded', 'Retention, recovery, or deletion protection requires independent review.')
    observed = moment(observed_at)
    if not observed or not 0 <= (now - observed).total_seconds() < 86400:
        return output
    p = parameters(rule_id, policy.get('parameters'))
    evidence = resource.get('evidence') or {}
    metrics = evidence.get('metrics') or {}
    known = lambda key: type(evidence.get(key)) is bool
    detected = None
    if rule_id == 'AZURE_DISK_UNATTACHED_RETENTION':
        if evidence.get('disk_state') == 'Unattached':
            detected = continuous(evidence, 'Unattached', p['minimum_days'], now)
        elif evidence.get('disk_state') in ('Attached', 'Reserved'):
            detected = False
    elif rule_id == 'AZURE_DISK_PROVISIONED_PERFORMANCE':
        if evidence.get('disk_state') == 'Unattached':
            if known('recent_snapshot_verified'):
                detected = not evidence['recent_snapshot_verified']
        else:
            io, throughput = series(metrics.get('iops'), now), series(metrics.get('throughput'), now)
            target = evidence.get('target_disk') or {}
            if io and throughput and all(type(target.get(k)) in (int, float) and target[k] > 0 for k in ('iops', 'throughput')):
                factor = 1 + p['headroom_percent'] / 100
                detected = (evidence.get('target_compatible') is True and io['maximum'] * factor <= target['iops']
                            and throughput['maximum'] * factor <= target['throughput']
                            and evidence.get('throttling_observed') is False)
    elif rule_id == 'AZURE_PUBLIC_IP_UNASSOCIATED':
        if known('association_verified'):
            detected = False if evidence['association_verified'] else continuous(evidence, 'Unassociated', p['minimum_days'], now)
    elif rule_id == 'AZURE_PUBLIC_IP_ASSOCIATED_IDLE':
        traffic = [series(metrics.get(key), now) for key in ('ingress_bytes', 'egress_bytes')]
        if evidence.get('association_verified') is True and all(traffic):
            detected = all(item['maximum'] <= p['maximum_bytes'] for item in traffic)
    elif rule_id == 'AZURE_VM_STOPPED_RESIDUAL_COST':
        state = evidence.get('power_state')
        if state == 'PowerState/stopped':
            detected = True
        elif state == 'PowerState/deallocated':
            detected = continuous(evidence, state, p['minimum_days'], now)
        elif state == 'PowerState/running':
            detected = False
    elif rule_id in ('AZURE_VM_RIGHTSIZING_UTILIZATION', 'AZURE_ASP_UNDERUTILIZED_SKU'):
        cpu, memory = series(metrics.get('cpu_percent'), now), series(metrics.get('memory_percent'), now)
        created = moment(evidence.get('created_at'))
        if cpu and memory and created and now - created >= timedelta(days=30):
            # Low utilization is a review signal. It cannot establish target compatibility or cash savings.
            detected = cpu['p95'] < p['cpu_percent'] and memory['p95'] < p.get('memory_percent', 40)
            if rule_id == 'AZURE_VM_RIGHTSIZING_UTILIZATION':
                if not series(metrics.get('disk_iops'), now) or not series(metrics.get('network_bytes'), now):
                    return output
                if not known('burst_credits_depleted'):
                    return output
                detected = detected and evidence['burst_credits_depleted'] is False
    elif rule_id == 'AZURE_ASP_EMPTY_PAID_PLAN':
        tier, apps, slots = evidence.get('sku_tier'), evidence.get('hosted_app_count'), evidence.get('deployment_slot_count')
        if tier in ('Free', 'Shared'):
            return finish('not_applicable', 'This rule reviews independently billable dedicated plans.')
        if isinstance(tier, str) and type(apps) is int and type(slots) is int:
            detected = False if apps > 0 or slots > 0 else continuous(evidence, 'Empty', p['minimum_days'], now)
    if detected is None:
        return output
    return finish('condition_detected' if detected else 'condition_not_detected',
                  'Evidence meets the review condition; dependencies, target compatibility and cost require review.'
                  if detected else 'Available evidence does not meet this rule condition.')


def evaluate_inventory(inventory, *, policies=None, observed_at=None, now=None):
    outcomes = []
    for resource in inventory:
        if resource.get('cloud_provider', 'azure') != 'azure':
            continue
        for rule in RULES:
            if resource['resource_type'].lower().rsplit('/', 1)[-1] == rule[1]:
                outcomes.append(evaluate(resource, rule, policy=(policies or {}).get(rule[0]), observed_at=observed_at, now=now))
    return outcomes
