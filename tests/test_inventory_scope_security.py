from app.provider_access import filter_scan


def test_inventory_only_scan_is_narrowed_even_without_findings():
    scan = {'cloud_providers': ['azure'], 'findings': [], 'inventory': [
        {'resource_id': 'allowed', 'subscription_id': 'a'},
        {'resource_id': 'private', 'subscription_id': 'b'}],
        'coverage': {'discovered_count': 2}}
    result = filter_scan(scan, {'azure'}, scopes={'azure': {'a'}})
    assert [r['resource_id'] for r in result['inventory']] == ['allowed']
    assert result['coverage'] is None
    assert len(scan['inventory']) == 2


def test_provider_filter_applies_to_inventory_and_rule_evaluations():
    scan = {'cloud_providers': ['azure', 'aws'], 'findings': [],
            'inventory': [{'cloud_provider': 'aws', 'scope_id': 'a'},
                          {'cloud_provider': 'azure', 'subscription_id': 'private'}],
            'rule_evaluations': [{'cloud_provider': 'azure', 'resource_id': 'private'}]}
    result = filter_scan(scan, {'aws'})
    assert len(result['inventory']) == 1 and result['inventory'][0]['cloud_provider'] == 'aws'
    assert result['rule_evaluations'] == []


def test_strict_write_rejects_out_of_scope_inventory_without_findings():
    scan = {'cloud_providers': ['azure'], 'findings': [],
            'inventory': [{'subscription_id': 'private'}]}
    assert filter_scan(scan, {'azure'}, strict=True, scopes={'azure': {'allowed'}}) is None


def test_scoped_financial_summary_excludes_private_groups_and_overlapping_alternatives():
    scan = {'cloud_providers': ['azure'], 'findings': [
        {'resource_id': 'disk', 'subscription_id': 'allowed', 'estimated_monthly_waste_usd': 30},
        {'resource_id': 'disk', 'subscription_id': 'allowed', 'estimated_monthly_waste_usd': 50},
        {'resource_id': 'private', 'subscription_id': 'private', 'estimated_monthly_waste_usd': 900}],
        'opportunity_summary': {'total_monthly_opportunity_usd': 950, 'opportunity_group_count': 2}}
    result = filter_scan(scan, {'azure'}, scopes={'azure': {'allowed'}})
    assert result['total_monthly_waste_usd'] == 50
    assert result['opportunity_summary']['total_monthly_opportunity_usd'] == 50
    assert result['opportunity_summary']['opportunity_group_count'] == 1
