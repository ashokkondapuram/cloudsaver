from app.evidence_derived_facts import apply_derived_facts


def test_burst_credit_from_metrics():
    resource = {
        'resource_type': 'Microsoft.Compute/virtualMachines',
        'resource_id': '/subscriptions/s/resourceGroups/r/providers/Microsoft.Compute/virtualMachines/vm1',
        'evidence': {
            'metrics': {
                'burst_credits': {
                    'points': [{'value': 15}, {'value': 42}],
                }
            }
        },
        'dependency_refs': [],
    }
    apply_derived_facts(resource)
    assert resource['evidence']['burst_credit_balance_min'] == 15


def test_commitment_lock_conflict():
    resource = {'resource_type': 'Microsoft.Compute/disks', 'evidence': {'commitment_locked': True}}
    apply_derived_facts(resource)
    assert resource['evidence']['commitment_lock_conflict'] is True


def test_unattached_days_from_created_at():
    resource = {
        'resource_type': 'Microsoft.Compute/disks',
        'evidence': {
            'disk_state': 'Unattached',
            'created_at': '2026-01-01T00:00:00+00:00',
        },
    }
    apply_derived_facts(resource)
    assert resource['evidence']['unattached_days'] >= 300


def test_public_snapshot_from_blob_access():
    resource = {
        'resource_type': 'Microsoft.Storage/storageAccounts',
        'evidence': {'allow_blob_public_access': False},
    }
    apply_derived_facts(resource)
    assert resource['evidence']['public_snapshot'] is False


def test_public_ingress_from_edges():
    resource = {
        'resource_type': 'Microsoft.Compute/virtualMachines',
        'resource_id': '/vm',
        'evidence': {'typed_configuration': {'networkProfile': {'networkInterfaces': [{'id': '/nic'}]}}},
        'dependency_refs': [
            {'relationship': 'nic_to_ip', 'from_resource_id': '/nic', 'to_resource_id': '/pip', 'verification_state': 'verified'}
        ],
    }
    apply_derived_facts(resource)
    assert resource['evidence']['public_admin_ingress'] is True
