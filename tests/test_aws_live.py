"""AWS live collector enrichment ordering and contracts."""
from datetime import datetime, timezone

from app.collectors.aws_live import enrich, live_enrichment_priority, select_live_enrichment_targets

NOW = datetime(2026, 11, 6, tzinfo=timezone.utc)
ACCOUNT = '123456789012'
REGION = 'us-east-1'


def _row(kind, name, *, rule_id='MULTICLOUD_INVENTORY', evidence=None):
    return dict(
        cloud_provider='aws',
        scope_id=ACCOUNT,
        subscription_id=ACCOUNT,
        region=REGION,
        resource_id=f'arn:aws:ec2:{REGION}:{ACCOUNT}:instance/{name}' if kind == 'aws:ec2:instance' else f'synthetic/{kind}/{name}',
        resource_name=name,
        resource_group=REGION,
        resource_type=kind,
        inventory_rule_id=rule_id,
        evidence=dict(evidence or {}),
    )


def test_live_enrichment_priority_prefers_ec2_over_legacy_volume_list_order():
    legacy = _row('aws:ec2:volume', 'vol-legacy', rule_id='AWS_UNATTACHED_EBS', evidence={'disk_state': 'available'})
    expanded = _row('aws:ec2:instance', 'i-priority')
    assert live_enrichment_priority(expanded) < live_enrichment_priority(legacy)


def test_select_live_enrichment_targets_includes_ec2_at_high_index():
    inventory = []
    for index in range(3):
        inventory.append(_row('aws:ec2:volume', f'vol-{index}', rule_id='AWS_UNATTACHED_EBS', evidence={'disk_state': 'available'}))
    for index in range(27):
        inventory.append(_row('aws:ec2:vpc', f'vpc-{index}'))
    ec2 = _row('aws:ec2:instance', 'i-late')
    inventory.append(ec2)
    assert len(inventory) == 31 and inventory.index(ec2) == 30

    selected = select_live_enrichment_targets(inventory, 25)
    assert ec2 in selected
    assert len(selected) == 25


def test_enrich_applies_cloudwatch_to_ec2_after_legacy_rows(monkeypatch):
    monkeypatch.setenv('CLOUDSAVER_LIVE_EVIDENCE_MAX_RESOURCES', '25')
    touched = []

    def record_cloudwatch(cloudwatch, namespace, metric_name, dimensions, now, window_days=30, period=300):
        touched.append(dimensions[0]['Value'])
        start = (now.replace(day=1)).isoformat()
        return dict(window_start=start, window_end=now.isoformat(), points=[])

    monkeypatch.setattr('app.collectors.aws_live.fetch_cloudwatch_series', record_cloudwatch)
    monkeypatch.setattr('app.collectors.aws_live.fetch_cloudtrail_transition_age', lambda *a, **k: None)

    inventory = []
    for index in range(3):
        inventory.append(_row('aws:ec2:volume', f'vol-{index}', rule_id='AWS_UNATTACHED_EBS', evidence={'disk_state': 'available'}))
    for index in range(27):
        inventory.append(_row('aws:ec2:vpc', f'vpc-{index}'))
    ec2 = _row('aws:ec2:instance', 'i-late')
    inventory.append(ec2)

    class Client:
        def __call__(self, _service):
            return object()

    enrich(Client(), inventory, now=NOW)

    assert 'i-late' in touched
    assert ec2['evidence'].get('live_sources', {}).get('telemetry') != 'resource_budget_exceeded'
    over_budget = [r for r in inventory if r['evidence'].get('live_sources', {}).get('telemetry') == 'resource_budget_exceeded']
    assert len(over_budget) == len(inventory) - 25
    assert ec2 not in over_budget
