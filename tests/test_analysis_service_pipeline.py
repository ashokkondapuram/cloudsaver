import pytest

from app.analysis_service.context import ConfigMetadata, CostSnapshot, MetricsSummary, UnifiedResourceContext
from app.analysis_service.pipeline import attach_pillar_analysis, run_pillar_analysis
from app.analysis_service.service import AnalysisService


def test_run_pillar_analysis_on_scan_inventory():
    scan = {
        'inventory': [
            {
                'cloud_provider': 'aws',
                'resource_id': 'arn:aws:ec2:us-east-1:1:instance/i-1',
                'resource_type': 'ec2/instance',
                'evidence': {'encrypted': False, 'publicly_accessible': True},
            }
        ]
    }
    block = run_pillar_analysis(scan)
    assert block['finding_count'] >= 1
    assert block['account_pillar_scores']['SECURITY'] < 100


def test_attach_pillar_analysis_mutates_scan():
    scan = {'inventory': []}
    attach_pillar_analysis(scan)
    assert scan['pillar_analysis']['finding_count'] == 0


def test_cost_daily_spike_and_orphan_ip_rules():
    ctx = UnifiedResourceContext(
        provider='azure',
        resource_id='/subscriptions/x/resourceGroups/rg/providers/Microsoft.Network/publicIPAddresses/pip',
        resource_type='microsoft.network/publicipaddresses',
        config=ConfigMetadata(ip_associated=False),
        cost=CostSnapshot(actual_amortized_30d_usd=12.0, daily_cost_spike_pct=40.0),
    )
    findings = AnalysisService().analyze_resource(ctx).findings
    rules = {f.rule_id for f in findings}
    assert 'COST_ORPHAN_PUBLIC_IP' in rules
    assert 'COST_DAILY_SPIKE' in rules


def test_rightsizing_uses_target_retail_when_present():
    ctx = UnifiedResourceContext(
        provider='aws',
        resource_id='arn:aws:ec2:us-east-1:1:instance/i-2',
        resource_type='ec2/instance',
        metrics=MetricsSummary(cpu_p95_pct=10.0, memory_p95_pct=20.0),
        cost=CostSnapshot(
            actual_amortized_30d_usd=100.0,
            retail_monthly_equivalent_usd=100.0,
            target_sku_retail_monthly_usd=60.0,
            effective_discount_rate=0.1,
        ),
    )
    rightsize = next(f for f in AnalysisService().analyze_resource(ctx).findings if f.rule_id == 'COST_RIGHTSIZE')
    assert rightsize.financial_impact.estimated_monthly_savings_usd == pytest.approx(46.0)
