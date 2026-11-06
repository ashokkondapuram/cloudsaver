from app.analysis_rule_catalog import (
    PILLAR_LABELS,
    azure_compute_rule_matrix,
    azure_rules_by_resource_type,
    catalog_by_pillar,
    rule_pillar,
)
from app.assessment import PILLARS


def test_vm_and_vmss_rules_are_distinct():
    by_type = azure_rules_by_resource_type()
    vm = set(by_type['microsoft.compute/virtualmachines'])
    vmss = set(by_type['microsoft.compute/virtualmachinescalesets'])
    assert 'AZURE_VM_STOPPED_RESIDUAL_COST' in vm
    assert 'AZURE_VM_RIGHTSIZING_UTILIZATION' in vm
    assert 'AZURE_VMSS_LOW_UTILIZATION_REVIEW' in vmss
    assert 'AZURE_VM_STOPPED_RESIDUAL_COST' not in vmss
    assert 'AZURE_VMSS_LOW_UTILIZATION_REVIEW' not in vm
    assert vm != vmss


def test_catalog_by_pillar_has_five_pillars():
    payload = catalog_by_pillar(provider='azure')
    assert [p['pillar'] for p in payload['pillars']] == list(PILLARS)
    assert all(p['label'] == PILLAR_LABELS[p['pillar']] for p in payload['pillars'])
    ids = {rule['id'] for group in payload['pillars'] for rule in group['rules']}
    assert 'AZURE_VM_RIGHTSIZING_UTILIZATION' in ids
    assert rule_pillar('AZURE_VM_RIGHTSIZING_UTILIZATION') == 'performance'
    assert rule_pillar('AZURE_VM_STOPPED_RESIDUAL_COST') == 'cost'
    assert rule_pillar('AZURE_DATABASE_PUBLIC_NETWORK_REVIEW') == 'security'


def test_compute_matrix_labels_vm_vs_vmss():
    matrix = {row['resource_type']: row for row in azure_compute_rule_matrix()}
    assert matrix['microsoft.compute/virtualmachines']['label'] == 'Virtual machine'
    assert matrix['microsoft.compute/virtualmachinescalesets']['label'] == 'Virtual machine scale set'
    assert 'AZURE_AKS_CLUSTER_UTILIZATION_REVIEW' in matrix['microsoft.containerservice/managedclusters']['analysis_rule_ids']
