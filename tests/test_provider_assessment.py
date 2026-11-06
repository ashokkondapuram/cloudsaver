from app.assessment import assess
from app.provider_rules import group_checks, rule_provider


def test_azure_vm_skips_aws_instance_metadata_check():
    finding = dict(
        cloud_provider='azure',
        resource_id='/subscriptions/s/resourceGroups/r/providers/Microsoft.Compute/virtualMachines/vm1',
        resource_type='microsoft.compute/virtualmachines',
        subscription_id='s',
        rule_id='INVENTORY_OBSERVATION',
        evidence={'public_admin_ingress': False},
    )
    result = assess(finding, observed_at='2026-11-05T12:00:00+00:00')
    codes = {check['code'] for pillar in result['pillars'] for check in pillar['checks']}
    assert 'INSTANCE_METADATA' not in codes
    groups = {group['scope']: group for group in result['check_groups']}
    assert groups['provider']['provider'] == 'azure'


def test_aws_ec2_includes_instance_metadata_check():
    finding = dict(
        cloud_provider='aws',
        resource_id='i-123',
        resource_type='aws:ec2:instance',
        scope_id='123456789012',
        rule_id='INVENTORY_OBSERVATION',
        evidence={'imds_v2_required': True, 'public_admin_ingress': False},
    )
    result = assess(finding, observed_at='2026-11-05T12:00:00+00:00')
    codes = {check['code'] for pillar in result['pillars'] for check in pillar['checks']}
    assert 'INSTANCE_METADATA' in codes


def test_rule_provider_prefixes():
    assert rule_provider('AZURE_DISK_UNATTACHED_RETENTION') == 'azure'
    assert rule_provider('AWS_UNATTACHED_EBS') == 'aws'
    assert rule_provider('GCP_UNATTACHED_DISK') == 'gcp'
    assert rule_provider('K8S_CPU_OVERSIZED') == 'kubernetes'


def test_group_checks_splits_shared_and_provider():
    checks = [
        dict(code='BILLED_COST', pillar='cost', status='unknown', providers=['*']),
        dict(code='FLOW_LOGS', pillar='operations', status='unknown', providers=['azure', 'aws', 'gcp']),
    ]
    groups = group_checks(checks, 'azure')
    assert len(groups) == 2
    assert groups[0]['scope'] == 'shared'
    assert groups[1]['provider'] == 'azure'
