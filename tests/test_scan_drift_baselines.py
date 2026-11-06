import hashlib
import json

from app.drift.baseline_store import baseline_hash
from app.drift.scan_baselines import (
    apply_drift_detected,
    capture_scan_drift_baselines,
    expected_state_from_inventory,
    human_activity_drift,
)
from app.resource_assessment import assessments, merge_inventory, resource_key


TENANT = '11111111-1111-4111-8111-111111111111'
SUB = '22222222-2222-4222-8222-222222222222'
VM = (
    f'/subscriptions/{SUB}/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/api-01'
)


class MemoryBaselineStore:
    def __init__(self):
        self.rows = {}

    def upsert_baseline(self, tenant_id, canonical_resource_id, provider, expected_state, *, now=None):
        digest = baseline_hash(expected_state)
        self.rows[(tenant_id, canonical_resource_id)] = dict(
            provider=provider,
            expected_state=expected_state,
            baseline_hash=digest,
            captured_at=now,
        )
        return digest


def _inventory_row(**evidence):
    return dict(
        cloud_provider='azure',
        resource_id=VM,
        resource_name='api-01',
        resource_type='microsoft.compute/virtualmachines',
        resource_group='rg',
        subscription_id=SUB,
        scope_id=SUB,
        region='eastus',
        configuration_snapshot=dict(vm_size='Standard_D2s_v5', tags={'env': 'prod'}, power_state='PowerState/running'),
        evidence=dict(
            vm_size='Standard_D2s_v5',
            power_state='PowerState/running',
            tags={'env': 'prod'},
            **evidence,
        ),
    )


def test_human_activity_drift_requires_non_iac_actor():
    evidence = dict(
        activity_events=[
            dict(event_id='1', event_name='write', actor_identity='terraform-ci', is_iac_authorized=True),
            dict(event_id='2', event_name='write', actor_identity='alice@example.com', is_iac_authorized=False),
        ]
    )
    assert human_activity_drift(evidence) is True
    assert human_activity_drift(dict(activity_events=[])) is False


def test_apply_drift_detected_mutates_inventory_evidence():
    row = _inventory_row(
        activity_events=[
            dict(
                event_id='evt-1',
                event_time='2026-11-01T00:00:00+00:00',
                event_name='Microsoft.Compute/virtualMachines/write',
                actor_identity='devops@contoso.com',
                changed_fields=['hardwareProfile'],
                is_iac_authorized=False,
            )
        ]
    )
    assert apply_drift_detected(row) is True
    assert row['evidence']['drift_detected'] is True


def test_expected_state_from_inventory_merges_snapshot_and_agent_fields():
    row = _inventory_row()
    state = expected_state_from_inventory(row)
    assert state['vm_size'] == 'Standard_D2s_v5'
    assert state['powerState'] == 'PowerState/running'
    assert state['tags'] == {'env': 'prod'}


def test_capture_scan_drift_baselines_upserts_and_counts():
    store = MemoryBaselineStore()
    row = _inventory_row(
        activity_events=[
            dict(
                event_id='evt-1',
                event_time='2026-11-01T00:00:00+00:00',
                event_name='write',
                actor_identity='human@contoso.com',
                changed_fields=['tags'],
                is_iac_authorized=False,
            )
        ]
    )
    scan = dict(timestamp='2026-11-06T00:00:00+00:00', inventory=[row])
    stats = capture_scan_drift_baselines(scan, tenant_id=TENANT, baseline_store=store, now=scan['timestamp'])
    assert stats == dict(baselines=1, drift_detected=1, skipped_empty=0)
    key = (TENANT, VM.lower())
    assert key in store.rows
    saved = store.rows[key]['expected_state']
    assert saved['vm_size'] == 'Standard_D2s_v5'
    assert row['evidence']['drift_detected'] is True


def test_assessment_surfaces_drift_detected_from_inventory():
    row = _inventory_row(
        activity_events=[
            dict(
                event_id='evt-1',
                event_time='2026-11-01T00:00:00+00:00',
                event_name='write',
                actor_identity='human@contoso.com',
                changed_fields=['tags'],
                is_iac_authorized=False,
            )
        ],
    )
    capture_scan_drift_baselines(
        dict(timestamp='2026-11-06T00:00:00+00:00', inventory=[row]),
        tenant_id=TENANT,
        baseline_store=MemoryBaselineStore(),
    )
    scan = dict(findings=[], inventory=[row], timestamp='2026-11-06T00:00:00+00:00', status='completed')
    key = resource_key(dict(cloud_provider='azure', resource_id=VM))
    assessment, _ = assessments(scan)[key]
    assert assessment.get('drift_detected') is True


def test_merge_inventory_includes_drift_detected():
    row = _inventory_row(drift_detected=True)
    key = resource_key(dict(cloud_provider='azure', resource_id=VM))
    assessment, _ = merge_inventory(key, row, observed_at='2026-11-06T00:00:00+00:00', list_view=True)
    assert assessment.get('drift_detected') is True


def test_baseline_hash_stable_for_expected_state():
    row = _inventory_row()
    state = expected_state_from_inventory(row)
    material = json.dumps(state, sort_keys=True, separators=(',', ':'))
    assert baseline_hash(state) == hashlib.sha256(material.encode()).hexdigest()
