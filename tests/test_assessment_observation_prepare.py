from app.resource_assessment import _prepare_observation_for_assessment, merge_inventory, resource_key


def test_prepare_empty_dependencies_and_billing_coverage():
    obs = {
        'cloud_provider': 'azure',
        'resource_id': '/subscriptions/x/resourceGroups/rg/providers/Microsoft.Web/serverFarms/plan1',
        'resource_type': 'Microsoft.Web/serverFarms',
        'resource_name': 'plan1',
        'resource_group': 'rg',
        'subscription_id': 'x',
        'dependency_refs': [],
        'evidence': {
            'billed_cost_usd': 12.5,
            'effective_cost_usd': 12.5,
            'currency': 'CAD',
            'billing_coverage': False,
            'commitment_locked': False,
            'hosted_app_count': 0,
            'sku_name': 'P1v3',
            'created_at': '2026-10-01T00:00:00Z',
        },
    }
    prepared = _prepare_observation_for_assessment(obs)
    ev = prepared['evidence']
    assert ev['billing_coverage'] is True
    assert ev['commitment_lock_conflict'] is False
    assert ev.get('dependency_inventory_complete') is True
    assert ev.get('verified_dependencies') == []


def test_merge_inventory_drops_billed_cost_gap():
    obs = {
        'cloud_provider': 'azure',
        'resource_id': '/subscriptions/x/resourceGroups/rg/providers/Microsoft.Web/serverFarms/plan1',
        'resource_type': 'Microsoft.Web/serverFarms',
        'resource_name': 'plan1',
        'resource_group': 'rg',
        'subscription_id': 'x',
        'region': 'eastus',
        'dependency_refs': [],
        'evidence': {
            'billed_cost_usd': 12.5,
            'effective_cost_usd': 12.5,
            'currency': 'CAD',
            'billing_coverage': False,
            'commitment_locked': False,
            'hosted_app_count': 0,
            'sku_name': 'P1v3',
            'https_only': False,
            'created_at': '2026-10-01T00:00:00Z',
        },
    }
    key = resource_key(obs)
    assessment, _ = merge_inventory(key, obs, observed_at='2026-11-05T12:00:00Z', list_view=True)
    assert 'BILLED_COST' not in assessment['evidence_gap_codes']
    assert 'COMMITMENT_LOCK' not in assessment['evidence_gap_codes']
    assert 'DEPENDENCY_GRAPH' not in assessment['evidence_gap_codes']
