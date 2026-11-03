from app.resource_action_items import derive_action_items
from app.resource_assessment import assessments, merge
from tests.support import azure_disk_finding

SUB = '22222222-2222-4222-8222-222222222222'


def test_derive_action_items_from_risk_and_gaps():
    disk = azure_disk_finding(SUB)
    disk['evidence'] = dict(disk.get('evidence') or {}, encrypted=False, publicly_accessible=True)
    assessment, _ = merge('k' * 64, [disk], observed_at='2026-10-22T00:00:00+00:00', now='2026-10-22T01:00:00+00:00')
    items = derive_action_items(assessment, [disk])
    kinds = {item['kind'] for item in items}
    assert items
    assert 'investigate' in kinds or 'configure' in kinds or 'verify' in kinds
    assert all(item['title'] and item['rationale'] for item in items)


def test_inventory_only_gets_full_checks_and_actions():
    scan = dict(
        scan_id='s1',
        status='completed',
        mode='azure',
        timestamp='2026-01-01T00:00:00+00:00',
        findings=[],
        inventory=[
            dict(
                cloud_provider='azure',
                resource_id=f'/subscriptions/{SUB}/resourceGroups/rg/providers/Microsoft.Compute/disks/only',
                resource_name='only',
                resource_type='Microsoft.Compute/disks',
                resource_group='rg',
                subscription_id=SUB,
                scope_id=SUB,
                evidence={'encrypted': True},
            )
        ],
    )
    assessment, _ = next(iter(assessments(scan, now='2026-01-01T12:00:00+00:00').values()))
    assert assessment['evidence_coverage']['total'] > 0
    items = derive_action_items(assessment)
    assert items
    assert any('guardrail' in item['rationale'].lower() or 'evidence' in item['rationale'].lower() for item in items)


def test_merge_rejects_invalid_findings():
    try:
        merge('k' * 64, [])
    except ValueError as error:
        assert 'At least one' in str(error)
    else:
        raise AssertionError('expected ValueError')
