import hashlib

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from services.analytics import summarize
from services.gateway import create_app as gateway
from services.notification import create_app as notification, webhook_url
from services.tenant import create_app as tenant_service

KEY = 'test-workspace-key-with-32-characters'
TID = '11111111-1111-4111-8111-111111111111'
SID = '33333333-3333-4333-8333-333333333333'


def configuration(tmp_path):
    return Settings('azure', str(tmp_path / 'test.sqlite3'), (
        dict(tenant_id=TID, name='Test workspace', subscription_ids=[SID],
             api_key_sha256=hashlib.sha256(KEY.encode()).hexdigest()),
    ))


class Limiter:
    async def check(self, tenant_id):
        assert tenant_id == TID


def test_gateway_auth_and_fixed_routing(tmp_path):
    called = []

    def handler(request):
        called.append(request)
        assert request.headers['authorization'] == 'Bearer ' + KEY
        return httpx.Response(200, json={'tenant_id': TID})

    client = TestClient(gateway(configuration(tmp_path), Limiter(), httpx.MockTransport(handler)))
    assert client.get('/api/v1/me').status_code == 401
    assert not called
    result = client.get('/api/v1/me', headers={'Authorization': 'Bearer ' + KEY})
    assert result.json()['tenant_id'] == TID
    assert str(called[0].url) == 'http://tenant-service:8001/api/v1/me'
    assert client.get('/api/v1/anything', headers={'Authorization': 'Bearer ' + KEY}).status_code == 404


def test_gateway_rejects_invalid_scan_and_limit(tmp_path):
    client = TestClient(gateway(configuration(tmp_path), Limiter(), httpx.MockTransport(lambda r: httpx.Response(200))))
    headers = {'Authorization': 'Bearer ' + KEY}
    assert client.get('/api/v1/scans/not-a-uuid', headers=headers).status_code == 422
    assert client.get('/api/v1/scans?limit=101', headers=headers).status_code == 422


def test_tenant_service_returns_no_key_hash(tmp_path):
    client = TestClient(tenant_service(configuration(tmp_path)))
    assert client.get('/api/v1/me').status_code == 401
    data = client.get('/api/v1/me', headers={'Authorization': 'Bearer ' + KEY}).json()
    assert data['tenant_id'] == TID and data['mode'] == 'azure' and data['plan_tier'] == 'STARTER'
    assert 'api_key_sha256' not in data


def test_snapshot_analytics_does_not_sum_old_snapshots():
    snapshot = dict(scan_id='latest', timestamp='2026-10-22T00:00:00Z', mode='azure',
                    total_items_found=1, total_monthly_waste_usd=None,
                    findings=[{'rule_id': 'ORPHANED_DISK'}])
    result = summarize([snapshot, snapshot])
    assert result['total_items_found'] == 1
    assert result['categories'] == {'ORPHANED_DISK': 1}
    assert result['monthly_opportunity_usd'] is None


@pytest.mark.parametrize('url', ['http://hooks.slack.com/services/secret', 'https://example.com/services/x',
                                 'https://hooks.slack.com.evil.com/services/x', 'https://127.0.0.1/',
                                 'https://user:pass@hooks.slack.com/services/x'])
def test_webhook_destination_rejected(url):
    with pytest.raises(ValueError):
        webhook_url(url)


def test_notification_owner_lookup_before_send(tmp_path, monkeypatch):
    monkeypatch.setenv('CLOUDSAVER_NOTIFICATION_WEBHOOK', 'https://hooks.slack.com/services/test/test/test')
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(404, json={'detail': 'Scan not found'})

    client = TestClient(notification(configuration(tmp_path), httpx.MockTransport(handler)))
    response = client.post('/api/v1/notifications/44444444-4444-4444-8444-444444444444',
                           headers={'Authorization': 'Bearer ' + KEY})
    assert response.status_code == 404
    assert len(seen) == 1
    assert seen[0].url.host == 'scanner-service'


def test_notification_commits_intent_through_scanner_without_direct_webhook_io(tmp_path):
    seen = []
    def handler(request):
        seen.append(request)
        assert request.url.host == 'scanner-service'
        assert request.method == 'POST'
        assert request.headers['authorization'] == 'Bearer ' + KEY
        return httpx.Response(202,json={'status':'queued','delivery_ids':['test-id']})
    client = TestClient(notification(configuration(tmp_path),httpx.MockTransport(handler)))
    response = client.post('/api/v1/notifications/44444444-4444-4444-8444-444444444444',headers={'Authorization':'Bearer '+KEY})
    assert response.status_code == 202 and response.json()['status']=='queued'
    assert len(seen)==1


def test_gateway_no_longer_forwards_billing_webhooks(tmp_path):
    def handler(request):
        raise AssertionError('Webhooks must not reach the tenant service')
    client = TestClient(gateway(configuration(tmp_path), Limiter(), httpx.MockTransport(handler)))
    response = client.post('/api/v1/billing/webhook', content=b'{"type": "test"}', headers={'Stripe-Signature': 't=1,v1=x'})
    assert response.status_code == 410 and response.json()['detail'] == 'Billing webhooks are handled by the platform.'


def test_gateway_routes_service_and_ai_review_without_visitor_destinations(tmp_path):
    import json
    calls = []
    scan_id = '44444444-4444-4444-8444-444444444444'
    def handler(request):
        calls.append(request)
        assert request.url.host == 'scanner-service'
        assert request.headers['authorization'] == 'Bearer '+KEY
        if request.url.path.endswith('ai-risk-evaluation'):
            assert json.loads(request.content) == {'target_id':'approved'}
            return httpx.Response(429,json={'detail':'Workspace AI hourly attempt budget reached'},headers={'Retry-After':'3600'})
        return httpx.Response(200,json={'ok':True})
    with TestClient(gateway(configuration(tmp_path),Limiter(),httpx.MockTransport(handler))) as client:
        headers = {'Authorization':'Bearer '+KEY}
        assert client.get('/api/v1/ai/targets',headers=headers).status_code == 200
        assert client.get(f'/api/v1/scans/{scan_id}/analysis',headers=headers).status_code == 200
        assert client.post(f'/api/v1/scans/{scan_id}/analysis/resource',headers=headers,json={'rule_id':'ORPHANED_DISK'}).status_code == 200
        result = client.post(f'/api/v1/scans/{scan_id}/ai-risk-evaluation',headers=headers,json={'target_id':'approved'})
        assert result.status_code == 429 and result.headers['Retry-After'] == '3600'
        assert result.json()['detail'] == 'Workspace AI hourly attempt budget reached'
        assert len(calls) == 4
        assert client.get('/api/v1/ai/anything',headers=headers).status_code == 404
