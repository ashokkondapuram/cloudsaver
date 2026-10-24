import hashlib
from uuid import uuid4

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.store import Store


def client(tmp_path, monkeypatch):
    monkeypatch.setenv('CLOUDSAVER_KEY_VERIFIER', 'local')
    monkeypatch.setenv('CLOUDSAVER_AUTH_MODE', 'workspace')
    key = 'private-offline-test-key'
    tenant = dict(tenant_id=str(uuid4()), name='Test', plan_tier='ENTERPRISE',
        subscription_ids=[str(uuid4())], api_key_sha256=hashlib.sha256(key.encode()).hexdigest())
    settings = Settings('azure', str(tmp_path / 'store.sqlite3'), (tenant,))
    store = Store(settings.database)
    snapshot = dict(scan_id=str(uuid4()), timestamp='2026-10-23T18:00:00Z', status='completed', mode='azure',
        total_items_found=1, total_monthly_waste_usd=None, subscriptions_scanned=1, findings=[],
        inventory=[dict(resource_id='/subscriptions/' + tenant['subscription_ids'][0] + '/disk/a',
                        resource_name='disk-a', resource_type='microsoft.compute/disks',
                        subscription_id=tenant['subscription_ids'][0])])
    store.save(tenant['tenant_id'], snapshot, workspace=tenant)
    return TestClient(create_app(settings)), {'Authorization': 'Bearer ' + key}, snapshot, tenant




def test_preview_does_not_write_policy_and_rejects_out_of_bounds(tmp_path, monkeypatch):
    api, headers, _, tenant = client(tmp_path, monkeypatch)
    calls = []
    def upstream(method, path, **kwargs):
        calls.append(method)
        assert path == f'/customer/v1/workspaces/{tenant["tenant_id"]}/analysis-rules'
        return {'version': 1, 'items': [{'id': 'AZURE_DISK_UNATTACHED_RETENTION', 'status': 'published',
            'enabled': True, 'parameters': {}, 'unavailable_reason': None}]}
    monkeypatch.setattr('app.settings_api._call', upstream)
    body = {'version': 1, 'rules': [{'rule_id': 'AZURE_DISK_UNATTACHED_RETENTION', 'enabled': False, 'parameters': {}}]}
    result = api.post('/api/v1/rules/preview', json=body, headers=headers)
    assert result.status_code == 200 and result.json()['resources_changed'] == 1
    assert calls == ['GET']
    body['rules'][0]['parameters'] = {'minimum_days': 1}
    assert api.post('/api/v1/rules/preview', json=body, headers=headers).status_code == 422
    body['version'] = 0
    assert api.put('/api/v1/rules/overrides', json=body, headers=headers).status_code == 422
