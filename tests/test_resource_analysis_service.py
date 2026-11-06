from datetime import datetime, timezone

from app.resource_analysis_service import analyze_resource, build_scan_rule_policies


def test_analyze_resource_one_disk():
    now = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)
    resource = dict(
        cloud_provider='azure',
        resource_id='/subscriptions/x/resourceGroups/rg/providers/Microsoft.Compute/disks/d1',
        resource_type='Microsoft.Compute/disks',
        resource_name='d1',
        resource_group='rg',
        subscription_id='x',
        evidence=dict(disk_state='Unattached', source='test'),
    )
    arg = [
        dict(
            rule_id='AZURE_DISK_UNATTACHED_RETENTION',
            severity='HIGH',
            cloud_provider='azure',
            resource_id=resource['resource_id'],
            resource_type=resource['resource_type'],
            resource_name='d1',
            resource_group='rg',
            subscription_id='x',
            estimated_monthly_waste_usd=None,
            evidence=dict(disk_state='Unattached'),
            details='test',
        )
    ]
    policies = build_scan_rule_policies(None, {'AZURE_DISK_UNATTACHED_RETENTION'})
    result = analyze_resource(resource, arg_findings=arg, policies=policies, observed_at=now.isoformat(), now=now)
    assert result['evaluations']
    assert any(e['rule_id'] == 'AZURE_DISK_UNATTACHED_RETENTION' for e in result['evaluations'])
    assert result['findings']
    assert resource.get('recommendations') is not None
    assert resource['evidence']['fetch_stages']['analysis'] == 'completed'
    assert resource['evidence']['fetch_stages']['recommendations'] == 'completed'
