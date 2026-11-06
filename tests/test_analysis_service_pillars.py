"""Deterministic 5-pillar AnalysisService tests (AWS, Azure, GCP fixtures)."""
from __future__ import annotations

from app.analysis_service.context import (
    ActivityEvent,
    ConfigMetadata,
    CostSnapshot,
    MetricsSummary,
    UnifiedResourceContext,
)
from app.analysis_service.finding import Pillar
from app.analysis_service.service import AnalysisService


def _idle_drifted_vm_aws() -> UnifiedResourceContext:
    return UnifiedResourceContext(
        provider='aws',
        resource_id='arn:aws:ec2:us-east-1:123456789012:instance/i-abc',
        resource_type='ec2/instance',
        region='us-east-1',
        current_sku='t3.large',
        tags={'env': 'dev'},
        config=ConfigMetadata(encrypted_at_rest=False, publicly_accessible=True, burstable_sku=True),
        metrics=MetricsSummary(cpu_max_pct=2.0, cpu_p95_pct=4.0, memory_p95_pct=10.0, runtime_hours_30d=720),
        cost=CostSnapshot(actual_amortized_30d_usd=85.0, retail_monthly_equivalent_usd=85.0, cost_source='ACTUAL_BILLED'),
        activity=[
            ActivityEvent(
                event_id='evt-1',
                event_time='2026-10-01T12:00:00Z',
                event_name='ModifyInstanceAttribute',
                actor_identity='console-user@example.com',
                is_iac_authorized=False,
            )
        ],
        drift_detected=True,
    )


def _unattached_disk_azure() -> UnifiedResourceContext:
    return UnifiedResourceContext(
        provider='azure',
        resource_id='/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg/providers/Microsoft.Compute/disks/d1',
        resource_type='microsoft.compute/disks',
        region='eastus',
        current_sku='P30',
        tags={'owner': 'team-a'},
        config=ConfigMetadata(disk_state='Unattached', encrypted_at_rest=True),
        cost=CostSnapshot(actual_amortized_30d_usd=42.0, cost_source='ACTUAL_BILLED'),
    )


def _throttled_burstable_gcp() -> UnifiedResourceContext:
    return UnifiedResourceContext(
        provider='gcp',
        resource_id='//compute.googleapis.com/projects/p/zones/us-central1-a/instances/vm1',
        resource_type='compute.googleapis.com/Instance',
        region='us-central1',
        current_sku='e2-micro',
        config=ConfigMetadata(burstable_sku=True, legacy_sku_generation=True),
        metrics=MetricsSummary(
            burst_credit_balance_min_pct=5.0,
            cpu_p95_pct=92.0,
            throttled_requests_count=12,
        ),
        cost=CostSnapshot(retail_monthly_equivalent_usd=12.0, cost_source='RETAIL_ESTIMATED'),
    )


def _untagged_prod_db_aws() -> UnifiedResourceContext:
    return UnifiedResourceContext(
        provider='aws',
        resource_id='arn:aws:rds:us-east-1:123456789012:db:prod-db',
        resource_type='rds/db',
        region='us-east-1',
        current_sku='db.r5.large',
        tags={'env': 'prod'},
        config=ConfigMetadata(multi_az_or_ha=False, backup_retention_days=0, deletion_protection=False),
        cost=CostSnapshot(actual_amortized_30d_usd=320.0, retail_monthly_equivalent_usd=400.0, cost_source='ACTUAL_BILLED'),
    )


def test_analysis_service_emits_all_pillars():
    service = AnalysisService()
    contexts = [
        _idle_drifted_vm_aws(),
        _unattached_disk_azure(),
        _throttled_burstable_gcp(),
        _untagged_prod_db_aws(),
    ]
    result = service.analyze_account(contexts)
    assert result.finding_count > 0
    pillars_seen = {f.pillar for r in result.resources for f in r.findings}
    for pillar in Pillar:
        assert pillar in pillars_seen, pillar
    for r in result.resources:
        assert len(r.pillar_scores) == 5
        for score in r.pillar_scores.values():
            assert 0 <= score <= 100


def test_finding_ids_are_deterministic():
    service = AnalysisService()
    ctx = _unattached_disk_azure()
    first = service.analyze_resource(ctx)
    second = service.analyze_resource(ctx)
    assert [f.finding_id for f in first.findings] == [f.finding_id for f in second.findings]


def test_orphan_disk_cost_savings_equals_monthly_cost():
    service = AnalysisService()
    ctx = _unattached_disk_azure()
    analysis = service.analyze_resource(ctx)
    orphan = next(f for f in analysis.findings if f.rule_id == 'COST_ORPHAN_DISK')
    assert orphan.financial_impact.estimated_monthly_savings_usd == 42.0
    assert orphan.remediation_action == 'DELETE_ORPHAN'


def test_prod_single_az_db_triggers_critical_reliability():
    service = AnalysisService()
    analysis = service.analyze_resource(_untagged_prod_db_aws())
    spof = next(f for f in analysis.findings if f.rule_id == 'REL_SPOF_PROD')
    assert spof.severity.value == 'CRITICAL'
    assert spof.financial_impact.projected_monthly_cost_usd == 320.0 * 1.8


def test_loader_from_scan_inventory():
    from app.analysis_service.loader import contexts_from_scan

    scan = {
        'timestamp': '2026-10-15T12:00:00Z',
        'inventory': [
            {
                'cloud_provider': 'azure',
                'resource_id': '/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg/providers/Microsoft.Compute/disks/d1',
                'resource_type': 'microsoft.compute/disks',
                'region': 'eastus',
                'evidence': {
                    'disk_state': 'Unattached',
                    'effective_cost_usd': 10.0,
                    'cost_source': 'ACTUAL_BILLED',
                    'tags': {'env': 'dev'},
                },
            }
        ],
    }
    contexts = contexts_from_scan(scan)
    assert len(contexts) == 1
    analysis = AnalysisService().analyze_resource(contexts[0])
    assert any(f.rule_id == 'COST_ORPHAN_DISK' for f in analysis.findings)


def test_aws_ec2_imdsv2_not_required_finding():
    from app.analysis_service.loader import contexts_from_scan

    scan = {
        'timestamp': '2026-10-15T12:00:00Z',
        'inventory': [
            {
                'cloud_provider': 'aws',
                'resource_id': 'arn:aws:ec2:us-east-1:123456789012:instance/i-imds',
                'resource_type': 'aws:ec2:instance',
                'region': 'us-east-1',
                'evidence': {'imds_v2_required': False},
            }
        ],
    }
    ctx = contexts_from_scan(scan)[0]
    assert ctx.config.imds_v2_required is False
    analysis = AnalysisService().analyze_resource(ctx)
    imds = next(f for f in analysis.findings if f.rule_id == 'AWS_EC2_IMDSV2_NOT_REQUIRED')
    assert imds.pillar == Pillar.SECURITY
    assert imds.remediation_action == 'REQUIRE_IMDSV2'
