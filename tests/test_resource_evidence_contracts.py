from dataclasses import asdict
from datetime import timedelta

import pytest

from app.analysis_rules import RULES, evaluate_inventory
from app.dependencies import canonical_inventory, group_opportunities
from app.inventory import coverage_manifest
from app.pricing import opportunity_totals
from app.provider_access import filter_scan
from app.telemetry_contract import TimeSeriesEvidenceContract, evaluate_series
from tests.test_expanded_rules import NOW, metric


def test_contract_reports_gap_reason_without_replacing_missing_intervals():
    contract = TimeSeriesEvidenceContract('cpu_percent')
    values = metric(5)
    result = evaluate_series(values, contract, now=NOW, resource_created_at=NOW-timedelta(days=40))
    assert result.is_sufficient and result.expected_samples == result.valid_samples == 8640
    values['points'] = values['points'][20:]
    result = evaluate_series(values, contract, now=NOW, resource_created_at=NOW-timedelta(days=40))
    assert result.gap_reason == 'unexplained_telemetry_gap'
    assert result.coverage_ratio > .95 and result.observed_value is None
    assert result.valid_samples == 8620


@pytest.mark.parametrize('created_at', [None, NOW-timedelta(days=10), NOW+timedelta(days=1)])
def test_resource_age_must_cover_the_whole_observation_window(created_at):
    result = evaluate_series(metric(), TimeSeriesEvidenceContract('cpu'), now=NOW, resource_created_at=created_at)
    assert result.gap_reason == 'resource_age_unverified_or_too_short' and not result.is_sufficient


def test_peak_contract_cannot_silently_substitute_an_average():
    values = metric(1)
    values['points'][-1]['value'] = 800
    result = evaluate_series(values, TimeSeriesEvidenceContract('iops', 'MAX'), now=NOW, resource_created_at=NOW-timedelta(days=50))
    assert result.observed_value == 800
    with pytest.raises(ValueError):
        TimeSeriesEvidenceContract('iops', 'AVG')


def node(name, kind, edges=(), **changes):
    sub = changes.get('subscription_id', 's')
    return dict(resource_id=f'/subscriptions/{sub}/resourceGroups/r/providers/' + kind + '/' + name,
                resource_type=kind, subscription_id=sub, dependency_refs=list(edges)) | changes


def edge(a, b, kind, state='verified', observed_at=NOW):
    return dict(relationship=kind, from_resource_id=a['resource_id'], to_resource_id=b['resource_id'],
                verification_state=state, observed_at=observed_at.isoformat())


def test_verified_vm_disk_alternatives_share_one_opaque_financial_group():
    vm, disk = node('vm', 'microsoft.compute/virtualmachines'), node('disk', 'microsoft.compute/disks')
    vm['dependency_refs'] = [edge(vm, disk, 'vm_to_disk')]
    inventory = canonical_inventory([vm, disk], NOW.isoformat())
    findings = [dict(vm, estimated_monthly_waste_usd=100), dict(disk, estimated_monthly_waste_usd=40)]
    grouped = group_opportunities(findings, inventory)
    assert grouped[0]['opportunity_group_id'] == grouped[1]['opportunity_group_id']
    assert vm['resource_id'] not in grouped[0]['opportunity_group_id']
    assert opportunity_totals(grouped)['total_monthly_opportunity_usd'] == 100


@pytest.mark.parametrize('state,age', [('inferred', 0), ('unavailable', 0), ('verified', 25)])
def test_inferred_stale_or_unavailable_relationships_cannot_establish_workload_group(state, age):
    vm, disk = node('vm', 'microsoft.compute/virtualmachines'), node('disk', 'microsoft.compute/disks')
    vm['dependency_refs'] = [edge(vm, disk, 'vm_to_disk', state, NOW-timedelta(hours=age))]
    rows = canonical_inventory([vm, disk], NOW.isoformat())
    grouped = group_opportunities([dict(vm, estimated_monthly_waste_usd=100), dict(disk, estimated_monthly_waste_usd=40)], rows)
    assert all('opportunity_group_id' not in finding for finding in grouped)


def test_scoped_inventory_removes_dependencies_to_unseen_resource_nodes():
    vm, disk = node('vm', 'microsoft.compute/virtualmachines'), node('disk', 'microsoft.compute/disks', subscription_id='private')
    vm['dependency_refs'] = [edge(vm, disk, 'vm_to_disk')]
    inventory = canonical_inventory([vm, disk], NOW.isoformat())
    scan = {'cloud_providers': ['azure'], 'findings': [], 'inventory': inventory,
            'coverage_manifest': {'private': 'must not be retained'}}
    scoped = filter_scan(scan, {'azure'}, scopes={'azure': {'s'}})
    assert len(scoped['inventory']) == 1 and scoped['inventory'][0]['dependency_refs'] == []
    assert scoped['coverage_manifest'] is None


def test_scoped_scan_with_only_allowed_rows_still_hides_unobserved_private_edges():
    vm, private_disk = node('vm', 'microsoft.compute/virtualmachines'), node('disk', 'microsoft.compute/disks', subscription_id='private')
    vm['dependency_refs'] = [edge(vm, private_disk, 'vm_to_disk')]
    scan = {'cloud_providers': ['azure'], 'findings': [], 'inventory': [vm], 'coverage_manifest': {'failed_scopes': ['private']}}
    scoped = filter_scan(scan, {'azure'}, scopes={'azure': {'s'}})
    assert scoped['inventory'][0]['dependency_refs'] == []
    assert scoped['coverage_manifest'] is None
    assert filter_scan(scan, {'azure'}, strict=True, scopes={'azure': {'s'}}) is None


def test_canonical_deduplication_and_per_service_coverage_preserve_unknown_evidence():
    disk = node('disk', 'microsoft.compute/disks')
    inventory = canonical_inventory([disk, disk], NOW.isoformat())
    evaluations = evaluate_inventory(inventory, observed_at=NOW, now=NOW)
    manifest = coverage_manifest(inventory, [], evaluations)
    assert len(inventory) == 1 and inventory[0]['evidence_schema_version'] == '2'
    assert manifest['by_provider_service'][0]['service'] == 'storage'
    assert manifest['total']['discovered_count'] == manifest['total']['insufficient_evidence_count'] == 1
    assert manifest['total']['evaluated_count'] == 0


def test_a_broken_rule_evaluation_does_not_become_a_pass():
    disk = node('disk', 'microsoft.compute/disks', evidence={'disk_state': 'Unattached'})
    outcomes = evaluate_inventory([disk], policies={RULES[0][0]: {'parameters': {'minimum_days': True}}}, observed_at=NOW, now=NOW)
    assert outcomes[0]['outcome'] == 'evaluation_failed'
