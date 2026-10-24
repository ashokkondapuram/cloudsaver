from datetime import datetime, timedelta, timezone
import math

import pytest

from app.analysis_rules import RULES, evaluate, evaluate_inventory, parameters, series
from app.inventory import coverage

NOW = datetime(2026, 10, 23, 18, tzinfo=timezone.utc)


def resource(kind='disks', **evidence):
    return dict(resource_id='resource', subscription_id='scope', resource_type='microsoft.compute/' + kind,
                evidence=evidence)


def rule(rule_id, observation, **kwargs):
    return evaluate(observation, next(r for r in RULES if r[0] == rule_id), observed_at=NOW, now=NOW, **kwargs)


def metric(value=1):
    start = NOW - timedelta(days=30)
    return dict(window_start=start.isoformat(), window_end=NOW.isoformat(),
                points=[{'at': (start + timedelta(seconds=300 * i)).isoformat(), 'value': value} for i in range(1, 8641)])


@pytest.mark.parametrize('definition', RULES)
def test_missing_required_evidence_is_never_a_pass(definition):
    result = evaluate(resource(definition[1]), definition, observed_at=NOW, now=NOW)
    assert result['outcome'] == 'insufficient_evidence'
    assert result['estimated_savings'] is None and result['automatic_execution'] is False


def test_creation_date_cannot_prove_unattached_duration():
    r = resource(disk_state='Unattached', created_at=(NOW - timedelta(days=100)).isoformat())
    assert rule('AZURE_DISK_UNATTACHED_RETENTION', r)['outcome'] == 'insufficient_evidence'
    r['evidence']['state_history'] = [{'start': (NOW - timedelta(days=14)).isoformat(),
        'end': NOW.isoformat(), 'state': 'Unattached', 'complete': True}]
    assert rule('AZURE_DISK_UNATTACHED_RETENTION', r)['outcome'] == 'condition_detected'
    r['evidence']['state_history'][0]['complete'] = False
    assert rule('AZURE_DISK_UNATTACHED_RETENTION', r)['outcome'] == 'insufficient_evidence'


def test_protection_and_policy_are_separate_from_approval():
    r = resource(power_state='PowerState/stopped', tags={'legalhold': 'true'})
    evaluated = rule('AZURE_VM_STOPPED_RESIDUAL_COST', r)
    assert evaluated['outcome'] == 'condition_detected'
    assert evaluated['destructive_actions_blocked'] is True and evaluated['protected_reasons']
    assert rule('AZURE_VM_STOPPED_RESIDUAL_COST', r, policy={'enabled': False})['outcome'] == 'disabled_by_policy'


def test_strict_parameter_bounds_reject_bool_and_unrecognized_names():
    for payload in ({'minimum_days': True}, {'minimum_days': 1}, {'query': 'anything'}):
        with pytest.raises(ValueError):
            parameters('AZURE_DISK_UNATTACHED_RETENTION', payload)


def test_metrics_coverage_and_peak_contract():
    data = metric(5)
    assert series(data, NOW) == {'p95': 5, 'p99': 5, 'maximum': 5, 'coverage': 1}
    data['points'][-1]['value'] = 100
    assert series(data, NOW)['maximum'] == 100
    data['points'] = data['points'][20:]
    assert series(data, NOW) is None  # Long gap despite >95% samples.


@pytest.mark.parametrize('value', [True, -1, float('nan'), float('inf')])
def test_invalid_metric_values_do_not_establish_utilization(value):
    data = metric()
    data['points'][0]['value'] = value
    assert series(data, NOW) is None


def test_missing_guest_memory_blocks_vm_rightsizing():
    r = resource('virtualmachines', created_at=(NOW - timedelta(days=40)).isoformat(), metrics={'cpu_percent': metric(1)})
    assert rule('AZURE_VM_RIGHTSIZING_UTILIZATION', r)['outcome'] == 'insufficient_evidence'


def test_coverage_keeps_unsupported_unknown_and_disabled_separate():
    rows = [resource('disks'), dict(resource('networkinterfaces'), resource_id='unsupported')]
    results = evaluate_inventory(rows, observed_at=NOW, now=NOW)
    manifest = coverage(rows, [], results)
    assert manifest['discovered_count'] == 2
    assert manifest['evaluated_count'] == 0 and manifest['insufficient_evidence_count'] == 1
    assert manifest['unsupported_count'] == 1


def test_stale_and_future_observations_cannot_produce_a_risk_or_pass():
    for when in (NOW - timedelta(days=2), NOW + timedelta(seconds=1)):
        result = evaluate(resource(power_state='PowerState/stopped'), RULES[4], observed_at=when, now=NOW)
        assert result['outcome'] == 'insufficient_evidence'
