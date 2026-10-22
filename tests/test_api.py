import hashlib
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.support import stub_scanner

KEY_A = 'workspace-a-test-key-at-least-32-characters'
KEY_B = 'workspace-b-test-key-at-least-32-characters'


def tenant(tid, key):
    return dict(tenant_id=tid, name='Test workspace', subscription_ids=['22222222-2222-4222-8222-222222222222'],
                api_key_sha256=hashlib.sha256(key.encode()).hexdigest())


@pytest.fixture
def settings(tmp_path):
    return Settings('azure', str(tmp_path / 'history.sqlite'), (
        tenant('11111111-1111-4111-8111-111111111111', KEY_A),
        tenant('33333333-3333-4333-8333-333333333333', KEY_B)))


def headers(key=KEY_A):
    return {'Authorization': f'Bearer {key}'}


def test_scan_ownership_and_restart_persistence(settings):
    with TestClient(create_app(settings, scanner=stub_scanner)) as client:
        assert client.get('/api/v1/me').status_code == 401
        assert client.get('/api/v1/me', headers=headers('wrong')).status_code == 401
        response = client.post('/api/v1/scans', headers=headers())
        assert response.status_code == 201
        scan = response.json()
        assert scan['mode'] == 'azure' and scan['total_items_found'] == len(scan['findings'])
        assert client.get(f"/api/v1/scans/{scan['scan_id']}", headers=headers(KEY_B)).status_code == 404
        assert client.get('/api/v1/scans', headers=headers(KEY_B)).json() == []
        assert 'api_key_sha256' not in client.get('/api/v1/me', headers=headers()).json()
    with TestClient(create_app(settings, scanner=stub_scanner)) as restarted:
        assert restarted.get('/api/v1/scans', headers=headers()).json()[0]['scan_id'] == scan['scan_id']


def test_failed_scan_never_saves_partial_data(settings):
    def broken(_):
        raise RuntimeError('sensitive-azure-credential')
    with TestClient(create_app(settings, scanner=broken)) as client:  # noqa: same settings fixture
        response = client.post('/api/v1/scans', headers=headers())
        assert response.status_code == 502
        assert 'sensitive-azure-credential' not in response.text
        assert client.get('/api/v1/scans', headers=headers()).json() == []


def test_duplicate_concurrent_scan_rejected(settings):
    started, release = Event(), Event()
    def blocking(_):
        started.set()
        assert release.wait(timeout=10)
        return []
    with TestClient(create_app(settings, scanner=blocking)) as client, ThreadPoolExecutor() as executor:  # noqa
        future = executor.submit(client.post, '/api/v1/scans', headers=headers())
        assert started.wait(timeout=10)
        try:
            assert client.post('/api/v1/scans', headers=headers()).status_code == 409
        finally:
            release.set()
        assert future.result().status_code == 201


def test_live_costs_unknown_even_without_findings(settings):
    live = Settings('azure', settings.database, settings.tenants)
    with TestClient(create_app(live, scanner=lambda _: [])) as client:
        scan = client.post('/api/v1/scans', headers=headers()).json()
        assert scan['mode'] == 'azure'
        assert scan['total_monthly_waste_usd'] is None


def test_history_limits_security_headers_and_no_gemini(settings):
    with TestClient(create_app(settings, scanner=stub_scanner)) as client:
        assert client.get('/api/v1/scans?limit=101', headers=headers()).status_code == 422
        assert client.get('/api/v1/scans?limit=0', headers=headers()).status_code == 422
        response = client.get('/api/v1/me', headers=headers())
        assert response.headers['cache-control'] == 'no-store'
        assert "frame-ancestors 'none'" in response.headers['content-security-policy']
        assert client.post('/api/v1/scans/example/advice', headers=headers()).status_code == 404


def test_no_default_key_or_live_fallback(monkeypatch):
    monkeypatch.setenv('CLOUDSAVER_TENANTS', '[]')
    monkeypatch.setenv('CLOUDSAVER_MODE', 'demo')
    with pytest.raises(ValueError, match='must be azure'):
        Settings.load()
    monkeypatch.setenv('CLOUDSAVER_MODE', 'azure')
    with pytest.raises(ValueError, match='explicit CLOUDSAVER_TENANTS'):
        Settings.load()


def test_remediation_download_respects_ownership(settings):
    with TestClient(create_app(settings, scanner=stub_scanner)) as client:
        scan = client.post('/api/v1/scans', headers=headers()).json()
        path = f"/api/v1/scans/{scan['scan_id']}/remediation"
        selection = {'resource_ids': [scan['findings'][0]['resource_id']]}
        assert client.post(path, headers=headers(KEY_B), json=selection).status_code == 404
        owned = client.post(path, headers=headers(), json=selection)
        assert owned.status_code == 200
        assert 'read -r confirmation' in owned.json()['script']


def test_live_remediation_is_download_only(settings):
    sub = settings.tenants[0]['subscription_ids'][0]
    rid = f'/subscriptions/{sub}/resourceGroups/review/providers/Microsoft.Compute/disks/archive'
    finding = dict(rule_id='ORPHANED_DISK', severity='HIGH', resource_name='archive',
                   resource_type='Microsoft.Compute/disks', resource_group='review',
                   subscription_id=sub, resource_id=rid, estimated_monthly_waste_usd=None,
                   details='Verify retention before deletion')
    live = Settings('azure', settings.database, settings.tenants)
    with TestClient(create_app(live, scanner=lambda _: [finding])) as client:
        scan = client.post('/api/v1/scans', headers=headers()).json()
        response = client.post(f"/api/v1/scans/{scan['scan_id']}/remediation",
                               headers=headers(), json={'resource_ids': [rid]})
        assert response.status_code == 200
        assert response.json()['filename'].endswith('.sh')
        assert 'read -r confirmation' in response.json()['script']
        assert len(client.get('/api/v1/scans', headers=headers()).json()) == 1


def test_api_respects_scheduled_worker_distributed_lease(settings, monkeypatch):
    import workers.tasks
    class BusyLease:
        def __init__(self, _):
            pass
        def acquire(self, tenant_id, token):
            return False
    monkeypatch.setenv('CLOUDSAVER_DISTRIBUTED_SCAN_LOCK', 'true')
    monkeypatch.setattr(workers.tasks, 'RedisLease', BusyLease)
    def never_scan(_):
        raise AssertionError('API must not scan while worker owns lease')
    with TestClient(create_app(settings, scanner=never_scan)) as client:  # noqa
        assert client.post('/api/v1/scans', headers=headers()).status_code == 409
        assert client.get('/api/v1/scans', headers=headers()).json() == []
