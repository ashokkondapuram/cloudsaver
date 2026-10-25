import hashlib

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.analytics import summarize
from services.gateway import create_app as gateway
from app.delivery_config import webhook_url
from app.main import create_app as tenant_service

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
    assert str(called[0].url) == 'http://scanner-service:8002/api/v1/me'
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






def test_gateway_no_longer_forwards_billing_webhooks(tmp_path):
    def handler(request):
        raise AssertionError('Webhooks must not reach the tenant service')
    client = TestClient(gateway(configuration(tmp_path), Limiter(), httpx.MockTransport(handler)))
    response = client.post('/api/v1/billing/webhook', content=b'{"type": "test"}', headers={'Stripe-Signature': 't=1,v1=x'})
    assert response.status_code == 410 and response.json()['detail'] == 'Billing webhooks are handled by the platform.'

@pytest.mark.parametrize(('method','path'),[
    ('GET','/summary'),('GET','/cases'),('POST','/cases'),
    ('GET',f'/cases/{SID}'),('POST',f'/cases/{SID}/actions'),('GET',f'/cases/{SID}/billing-evidence'),
    ('POST','/evidence/receipts'),('GET','/ownership'),('PUT','/ownership'),('GET','/ownership/history'),
    ('GET','/anomalies'),('POST','/anomalies/detect'),('GET','/anomalies/metrics'),
    ('GET',f'/anomalies/{SID}'),('POST',f'/anomalies/{SID}/actions'),('POST','/suppressions'),
])
def test_outcome_gateway_exact_routes_signature_and_bodies(tmp_path,method,path):
    import json
    calls=[];payload={'version':7,'note':'Synthetic route contract'}
    def handler(request):
        calls.append(request)
        assert request.url.host=='scanner-service' and request.url.path=='/api/v1/outcomes'+path
        assert request.headers['authorization']=='Bearer '+KEY and request.headers.get('x-request-id')
        if method=='GET':assert request.url.params['currency']=='USD'
        else:assert json.loads(request.content)==payload
        if path=='/evidence/receipts':assert request.headers['x-evidence-signature']=='a'*64
        else:assert 'x-evidence-signature' not in request.headers
        return httpx.Response(200,json={'status':'bounded-core-response'})
    client=TestClient(gateway(configuration(tmp_path),Limiter(),httpx.MockTransport(handler)))
    response=client.request(method,'/api/v1/outcomes'+path+('?currency=USD' if method=='GET' else ''),headers={'Authorization':'Bearer '+KEY,'X-Evidence-Signature':'a'*64},**({'json':payload} if method!='GET' else {}))
    expected=201 if method=='POST' and path in ('/cases','/evidence/receipts','/suppressions') else 200
    assert response.status_code==expected and response.json()=={'status':'bounded-core-response'} and len(calls)==1


def test_outcome_gateway_rejects_duplicate_json_without_forwarding(tmp_path):
    client=TestClient(gateway(configuration(tmp_path),Limiter(),httpx.MockTransport(lambda _:pytest.fail('No ambiguous evidence may be forwarded'))))
    response=client.post('/api/v1/outcomes/evidence/receipts',headers={'Authorization':'Bearer '+KEY,'Content-Type':'application/json'},content='{"tenant_id":"one","tenant_id":"two"}')
    assert response.status_code==422


@pytest.mark.parametrize(('method','path'),[
    ('GET','/capabilities'),('GET','/access'),('PUT','/access'),('GET','/directory'),('GET','/controls'),('POST','/controls'),('POST','/assessments'),('GET','/summary'),('GET','/findings'),('GET',f'/findings/{SID}'),('POST',f'/findings/{SID}/actions'),('GET',f'/findings/{SID}/export'),('GET','/risks'),('POST','/risks'),('POST',f'/risks/{SID}/actions'),('GET','/exceptions'),('POST','/exceptions'),('POST',f'/exceptions/{SID}/actions'),('POST','/evidence/receipts'),('POST','/monitor')
])
def test_governance_gateway_keeps_fixed_destinations_and_evidence_binding(tmp_path,method,path):
    import json
    calls=[];payload={'version':3,'note':'Synthetic HTTP governance transport contract'}
    def handler(request):
        calls.append(request)
        assert request.url.host=='scanner-service' and request.url.path=='/api/v1/governance'+path
        assert request.headers['authorization']=='Bearer '+KEY and request.headers.get('x-request-id')
        if method!='GET' and path!='/monitor':assert json.loads(request.content)==payload
        if path=='/evidence/receipts':assert request.headers['x-evidence-signature']=='a'*64
        else:assert 'x-evidence-signature' not in request.headers
        return httpx.Response(200,json={'status':'governance-forwarded'})
    client=TestClient(gateway(configuration(tmp_path),Limiter(),httpx.MockTransport(handler)))
    result=client.request(method,'/api/v1/governance'+path,headers={'Authorization':'Bearer '+KEY,'X-Evidence-Signature':'a'*64},**({'json':payload} if method!='GET' else {}))
    expected=201 if method=='POST' and path in ('/controls','/assessments','/risks','/exceptions','/evidence/receipts') else 200
    assert result.status_code==expected and result.json()=={'status':'governance-forwarded'} and len(calls)==1
    if path.endswith('/export'):assert result.headers['content-disposition'].startswith('attachment;') and result.headers['cache-control']=='no-store'
