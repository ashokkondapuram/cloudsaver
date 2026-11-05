from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.provider_access import ScopedStore, access, filter_scan
from app.store import Store


def test_inventory_only_scan_is_narrowed_even_without_findings():
    scan = {'cloud_providers': ['azure'], 'findings': [], 'inventory': [
        {'resource_id': 'allowed', 'subscription_id': 'a'},
        {'resource_id': 'private', 'subscription_id': 'b'}],
        'coverage': {'discovered_count': 2}}
    result = filter_scan(scan, {'azure'}, scopes={'azure': {'a'}})
    assert [r['resource_id'] for r in result['inventory']] == ['allowed']
    assert result['coverage']['discovered_count'] == 1
    assert result['coverage_manifest']['total']['discovered_count'] == 1
    assert len(scan['inventory']) == 2


def test_provider_filter_applies_to_inventory_and_rule_evaluations():
    scan = {'cloud_providers': ['azure', 'aws'], 'findings': [],
            'inventory': [{'cloud_provider': 'aws', 'scope_id': 'a', 'resource_id': 'vol-a'},
                          {'cloud_provider': 'azure', 'subscription_id': 'private', 'resource_id': 'disk-private'}],
            'rule_evaluations': [{'cloud_provider': 'azure', 'resource_id': 'disk-private'}]}
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


def _workspace():
    import hashlib
    tid = '11111111-1111-4111-8111-111111111111'
    allowed = '22222222-2222-4222-8222-222222222222'
    private = '33333333-3333-4333-8333-333333333333'
    return dict(tenant_id=tid, name='Scope test', subscription_ids=[allowed, private],
                plan_tier='GROWTH', api_key_sha256=hashlib.sha256(b'x' * 40).hexdigest()), allowed, private


def _inventory_scan(allowed_sub, private_sub):
    allowed = dict(cloud_provider='azure', subscription_id=allowed_sub, resource_id=f'/subscriptions/{allowed_sub}/providers/Microsoft.Compute/disks/allowed',
                   resource_name='allowed', resource_type='Microsoft.Compute/disks', resource_group='rg')
    private = dict(cloud_provider='azure', subscription_id=private_sub, resource_id=f'/subscriptions/{private_sub}/providers/Microsoft.Compute/disks/private',
                    resource_name='private', resource_type='Microsoft.Compute/disks', resource_group='rg')
    finding = dict(cloud_provider='azure', subscription_id=allowed_sub, resource_id=allowed['resource_id'], resource_name='allowed',
                   resource_type='Microsoft.Compute/disks', resource_group='rg', rule_id='AZURE_DISK_UNATTACHED', severity='LOW',
                   details='ok', estimated_monthly_waste_usd=None)
    return dict(scan_id=str(uuid4()), timestamp=datetime.now(timezone.utc).isoformat(), status='completed', cloud_providers=['azure'],
                subscriptions_scanned=2, total_items_found=2, findings=[finding], inventory=[allowed, private])


def test_scoped_store_running_inventory_page_filters_before_pagination(tmp_path):
    inner = Store(str(tmp_path / 'scope.db'))
    store = ScopedStore(inner)
    workspace, allowed_sub, _private_sub = _workspace()
    scan = _inventory_scan(allowed_sub, _private_sub)
    inner.save(workspace['tenant_id'], scan, workspace=workspace)
    token = access.set((frozenset({'azure'}), False, {'azure': frozenset({allowed_sub})}))
    try:
        page = store.running_inventory_page(workspace['tenant_id'], scan['scan_id'], offset=0, limit=10)
        assert page['inventory_total'] == 1
        assert [row['resource_name'] for row in page['inventory']] == ['allowed']
        assert len(page['findings']) == 1
    finally:
        access.reset(token)


def test_scoped_store_scan_resource_bundle_hides_out_of_scope_resource(tmp_path):
    inner = Store(str(tmp_path / 'scope.db'))
    store = ScopedStore(inner)
    workspace, allowed_sub, private_sub = _workspace()
    scan = _inventory_scan(allowed_sub, private_sub)
    inner.save(workspace['tenant_id'], scan, workspace=workspace)
    token = access.set((frozenset({'azure'}), False, {'azure': frozenset({allowed_sub})}))
    try:
        allowed = store.scan_resource_bundle(workspace['tenant_id'], scan['scan_id'], 'azure', scan['inventory'][0]['resource_id'])
        assert allowed['observation']['resource_name'] == 'allowed'
        blocked = store.scan_resource_bundle(workspace['tenant_id'], scan['scan_id'], 'azure', scan['inventory'][1]['resource_id'])
        assert blocked is None
    finally:
        access.reset(token)


def test_scoped_store_list_light_uses_full_scan_for_filtering(tmp_path):
    inner = Store(str(tmp_path / 'scope.db'))
    store = ScopedStore(inner)
    workspace, allowed_sub, _private_sub = _workspace()
    scan = _inventory_scan(allowed_sub, _private_sub)
    inner.save(workspace['tenant_id'], scan, workspace=workspace)
    token = access.set((frozenset({'azure'}), False, {'azure': frozenset({allowed_sub})}))
    try:
        rows = store.list_light(workspace['tenant_id'], 10)
        assert len(rows) == 1
        assert rows[0]['scan_id'] == scan['scan_id']
        assert 'inventory' not in rows[0]
    finally:
        access.reset(token)
