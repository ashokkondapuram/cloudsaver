from datetime import datetime, timezone

from app.azure_resource_registry import (
    all_monitored_types,
    all_registry_types,
    analysis_rule_ids_for,
    catalog_entries,
    evidence_fields_for_type,
    monitor_metrics_for_type,
    resolve_family_id,
    telemetry_rule_ids_for_type,
    utilization_metrics_for,
)
from app.collectors import azure_live
from app.multicloud_rules import condition
from app.resource_catalog import FAMILIES


def test_live_metrics_match_registry():
    assert set(azure_live.METRICS.keys()) == set(all_monitored_types())


def test_catalog_entry_covers_every_azure_family_type():
    catalog_types = all_registry_types()
    for provider, _fam, _cat, types, _rules in FAMILIES:
        if provider != 'azure':
            continue
        for rtype in types:
            assert rtype.lower() in catalog_types, rtype


def test_catalog_entries_include_rules_and_evidence():
    by_type = {row['resource_type']: row for row in catalog_entries()}
    disk = by_type['microsoft.compute/disks']
    assert 'AZURE_DISK_UNATTACHED_RETENTION' in disk['analysis_rule_ids']
    assert disk['evidence_fields']
    assert disk['monitor_metrics']
    assert 'AZURE_DISK_PROVISIONED_PERFORMANCE' in disk['telemetry_rule_ids']


def test_per_type_rules_do_not_cross_public_ip_and_nat():
    ip_rules = analysis_rule_ids_for(
        {'cloud_provider': 'azure', 'resource_type': 'microsoft.network/publicipaddresses'}
    )
    nat_rules = analysis_rule_ids_for(
        {'cloud_provider': 'azure', 'resource_type': 'microsoft.network/natgateways'}
    )
    assert 'AZURE_NAT_GATEWAY_SERVICE_ENDPOINT_BYPASS' not in ip_rules
    assert 'AZURE_NAT_GATEWAY_IDLE_LOW_TRAFFIC' not in ip_rules
    assert 'AZURE_PUBLIC_IP_UNASSOCIATED' not in nat_rules


def test_vmss_does_not_get_stopped_vm_rule():
    rules = analysis_rule_ids_for(
        {'cloud_provider': 'azure', 'resource_type': 'microsoft.compute/virtualmachinescalesets'}
    )
    assert 'AZURE_VM_STOPPED_RESIDUAL_COST' not in rules
    assert 'AZURE_VMSS_LOW_UTILIZATION_REVIEW' in rules


def test_load_balancer_and_aks_have_monitor_specs():
    assert monitor_metrics_for_type('microsoft.network/loadbalancers')
    assert monitor_metrics_for_type('microsoft.containerservice/managedclusters')


def test_resolve_family_for_orphan_nic_and_aks():
    nic = dict(cloud_provider='azure', resource_type='microsoft.network/networkinterfaces')
    assert resolve_family_id(nic) == 'network-orphan'
    aks = dict(cloud_provider='azure', resource_type='microsoft.containerservice/managedclusters')
    assert resolve_family_id(aks) == 'aks'
    assert utilization_metrics_for(aks)


def test_evidence_fields_listed_for_each_catalog_type():
    for row in catalog_entries():
        fields = evidence_fields_for_type(row['resource_type'])
        assert isinstance(fields, tuple)


def test_orphaned_nic_rule_from_configuration():
    now = datetime.now(timezone.utc)
    assert condition('ORPHANED_NIC', {'nic_orphaned': True}, {}, now) is True
    assert condition('ORPHANED_NSG', {'nsg_orphaned': True}, {}, now) is True


def test_telemetry_rule_ids_derived_from_analysis_rules():
    vm = telemetry_rule_ids_for_type('microsoft.compute/virtualmachines')
    assert 'AZURE_VM_RIGHTSIZING_UTILIZATION' in vm
    assert 'AZURE_VM_STOPPED_RESIDUAL_COST' not in vm
