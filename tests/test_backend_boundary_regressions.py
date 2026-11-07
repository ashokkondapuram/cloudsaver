"""Evidence and authorization boundaries found during backend revalidation."""
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

from app.provider_access import ScopedStore, access, filter_scan


def scan_with_private_analysis():
    visible = dict(cloud_provider='azure', subscription_id='allowed', resource_id='/visible')
    hidden = dict(visible, subscription_id='private', resource_id='/private')
    return dict(cloud_providers=['azure'], inventory=[visible, hidden], findings=[], rule_evaluations=[],
                pillar_analysis=dict(version='1', engine='analysis-service', finding_count=1,
                    account_pillar_scores={'cost': 50}, resources=[
                        dict(provider='azure', canonical_id='/visible', pillar_scores={'cost': 100}, findings=[]),
                        dict(provider='azure', canonical_id='/private', pillar_scores={'cost': 0}, findings=[{'reason': 'private'}])]))


def test_scope_projection_removes_private_analysis_and_recomputes_totals():
    scan = scan_with_private_analysis()
    filtered = filter_scan(scan, {'azure'}, scopes={'azure': {'allowed'}})
    block = filtered['pillar_analysis']
    assert [r['canonical_id'] for r in block['resources']] == ['/visible']
    assert block['finding_count'] == 0
    assert block['account_pillar_scores'] == {'cost': 100}
    assert len(scan['pillar_analysis']['resources']) == 2


def test_provider_projection_disambiguates_identical_native_ids():
    scan = scan_with_private_analysis()
    scan['inventory'][1] = dict(cloud_provider='aws', scope_id='private', resource_id='/visible')
    scan['pillar_analysis']['resources'][1].update(provider='aws', canonical_id='/visible')
    filtered = filter_scan(scan, {'azure'})
    assert [r['provider'] for r in filtered['pillar_analysis']['resources']] == ['azure']


def test_bundle_evaluations_are_filtered_to_authorized_target():
    visible = dict(cloud_provider='azure', subscription_id='allowed', resource_id='/visible')
    bundle = dict(observation=visible, findings=[], rule_evaluations=[visible,
        dict(visible, resource_id='/private'), dict(visible, cloud_provider='aws')])
    store = ScopedStore(SimpleNamespace(scan_resource_bundle=lambda *args: bundle))
    token = access.set((frozenset({'azure'}), False, {'azure': frozenset({'allowed'})}))
    try:
        result = store.scan_resource_bundle('tenant', 'scan', 'azure', '/visible')
        assert result['rule_evaluations'] == [visible]
        assert len(bundle['rule_evaluations']) == 3
    finally:
        access.reset(token)


def test_partial_billing_days_cannot_produce_booked_savings():
    from app.azure_json_profile import build_financial_snapshot
    def fetch(scope, rid, tenant, start, end):
        return [dict(day=start, currency='USD', billed=100, effective=100)]
    snapshot = build_financial_snapshot(tenant={'tenant_id': 'test'}, scope_id='s', resource_id='/visible',
        observation_start=date(2026, 8, 3), observation_end=date(2026, 8, 5),
        baseline_start=date(2026, 8, 1), baseline_end=date(2026, 8, 3), fetch_rows=fetch)
    assert snapshot['booked_savings_usd'] is None
    assert snapshot['booked_savings_comparable'] is False


def test_missing_billing_component_does_not_imply_complete_coverage():
    from app.azure_json_profile import aggregate_rows
    result = aggregate_rows([dict(day=date(2026, 8, 1), currency='USD', billed=0, effective=0),
                             dict(day=date(2026, 8, 2), currency='USD', billed=None, effective=1)], expected_days=2)
    assert result['billed_cost_usd'] == 0
    assert result['coverage_complete'] is False


def test_high_sample_coverage_does_not_override_excessive_gap():
    from app.collectors.live_common import summary
    now = datetime(2026, 11, 7, tzinfo=timezone.utc)
    start = now - timedelta(days=30)
    points = [dict(at=(start + timedelta(minutes=5 * i)).isoformat(), value=1)
              for i in range(1, 8641) if not 4000 <= i <= 4020]
    result = summary(dict(window_start=start.isoformat(), window_end=now.isoformat(), points=points), 'cpu_percent', now)
    assert result['coverage_ratio'] > .95
    assert result['sufficient'] is False
    assert result['gap_reason'] == 'unexplained_telemetry_gap'


def test_analysis_loader_uses_canonical_metric_envelope_and_preserves_zero_cost():
    from app.analysis_service.loader import context_from_inventory_row
    now = datetime(2026, 11, 7, tzinfo=timezone.utc)
    start = now - timedelta(days=30)
    metric = dict(window_start=start.isoformat(), window_end=now.isoformat(),
                  points=[dict(at=(start + timedelta(minutes=5 * i)).isoformat(), value=10)
                          for i in range(1, 8641)])
    row = dict(cloud_provider='azure', resource_id='/visible', resource_type='microsoft.compute/virtualmachines',
               evidence=dict(metrics={'cpu_percent': metric}, effective_cost_usd=0, amortized_cost_usd=99,
                             retail_monthly_usd=0, retail_estimate_usd=100))
    context = context_from_inventory_row(row, observed_at=now.isoformat())
    assert context.metrics.cpu_p95_pct == context.metrics.cpu_max_pct == 10
    assert context.cost.actual_amortized_30d_usd == 0
    assert context.cost.retail_monthly_equivalent_usd == 0
    row['evidence']['metrics']['cpu_percent']['points'] = []
    assert context_from_inventory_row(row, observed_at=now.isoformat()).metrics.cpu_p95_pct is None


def test_analysis_loader_rejects_non_finite_numbers():
    from app.analysis_service.loader import _float, _int
    for value in [float('inf'), float('-inf'), float('nan'), 'Infinity']:
        assert _float(value) is None
        assert _int(value) is None
