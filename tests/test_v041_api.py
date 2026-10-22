import hashlib
import time
from uuid import uuid4

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
import pytest

from app.auth import EntraIdConfig, EntraTokenValidator
from app.config import Settings
from app.main import create_app
from services.gateway import create_app as gateway

TENANT = '11111111-1111-4111-8111-111111111111'
SUB = '22222222-2222-4222-8222-222222222222'
KEY = 'workspace-key-with-more-than-32-characters'


@pytest.fixture
def context(tmp_path, monkeypatch):
    monkeypatch.setenv('CLOUDSAVER_AUTH_MODE', 'entra')
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    validator = EntraTokenValidator(EntraIdConfig(client_id='api', allowed_tenants={TENANT}),
                                    key_resolver=lambda tenant, token: key.public_key())
    settings = Settings('azure', str(tmp_path/'history.sqlite'), (dict(tenant_id=TENANT, name='Workspace',
                        subscription_ids=[SUB], plan_tier='GROWTH', api_key_sha256=hashlib.sha256(KEY.encode()).hexdigest()),))
    def headers(roles):
        now = int(time.time())
        token = jwt.encode(dict(tid=TENANT, oid=str(uuid4()), sub='user', aud='api',
                          iss=f'https://login.microsoftonline.com/{TENANT}/v2.0', ver='2.0',
                          exp=now+300, nbf=now-1, iat=now-1, scp='access_as_user', roles=roles),
                          key, algorithm='RS256', headers={'kid':'test'})
        return {'Authorization':'Bearer '+token, 'X-Tenant-ID':str(uuid4())}
    return settings, validator, headers


def finding():
    return dict(resource_id=f'/subscriptions/{SUB}/resourceGroups/test/providers/Microsoft.Compute/disks/archive',
                rule_id='ORPHANED_DISK', resource_name='archive', resource_group='test', subscription_id=SUB,
                resource_type='Microsoft.Compute/disks', severity='HIGH', details='Review retention', estimated_monthly_waste_usd=999)


def test_viewer_reads_but_cannot_scan_export_or_checkout(context):
    settings, validator, headers = context
    with TestClient(create_app(settings, scanner=lambda _: [finding()], identity_validator=validator)) as client:
        assert client.get('/api/v1/me', headers=headers(['Viewer'])).json()['tenant_id'] == TENANT
        assert client.post('/api/v1/scans', headers=headers(['Viewer'])).status_code == 403
        assert client.post('/api/v1/billing/checkout', headers=headers(['Viewer']),
                           json={'target_tier':'GROWTH','idempotency_key':'test-key-12345678'}).status_code == 403
        assert client.get('/api/v1/me', headers={'X-Workspace-Key':'anything','X-Tenant-ID':TENANT}).status_code == 401
        assert client.get('/api/v1/me', headers={'Authorization':'Bearer '+KEY}).status_code == 401


def test_admin_live_scan_unknown_cost_import_review_and_honest_cancel(context):
    settings, validator, headers = context
    auth = headers(['TenantAdmin'])
    with TestClient(create_app(settings, scanner=lambda _: [finding()], identity_validator=validator)) as client:
        response = client.post('/api/v1/scans', headers=auth)
        assert response.status_code == 201
        record = response.json()
        assert record['total_monthly_waste_usd'] is None and record['realizable_monthly_savings_usd'] is None
        assert record['findings'][0]['estimated_monthly_waste_usd'] is None
        result = client.post('/api/v1/scans/'+record['scan_id']+'/remediation-terraform', headers=auth,
                             json={'resource_ids':[finding()['resource_id']]})
        assert result.status_code == 200 and 'import {' in result.json()['hcl']
        assert client.post('/api/v1/scans/'+record['scan_id']+'/cancel', headers=auth).status_code == 409
        assert client.post('/api/v1/scans/'+str(uuid4())+'/cancel', headers=auth).status_code == 404
        assert client.get('/api/v1/auth/consent-url', headers=auth).status_code == 501


def test_billing_admin_cannot_scan_and_workspace_key_has_no_entra_fallback(context):
    settings, validator, headers = context
    with TestClient(create_app(settings, scanner=lambda _: [], identity_validator=validator)) as client:
        assert client.post('/api/v1/scans', headers=headers(['BillingAdmin'])).status_code == 403
        assert client.post('/api/v1/billing/checkout', headers=headers(['BillingAdmin']),
                           json={'target_tier':'GROWTH','idempotency_key':'test-key-12345678'}).status_code == 503


def test_delivery_viewer_and_billing_roles_cannot_enqueue_or_replay(context):
    settings,validator,headers=context
    with TestClient(create_app(settings,identity_validator=validator)) as client:
        for role in ('Viewer','BillingAdmin'):
            auth=headers([role])
            assert client.get('/api/v1/operations/reliability',headers=auth).json()['available'] is False
            assert client.post('/api/v1/notifications/'+str(uuid4()),headers=auth).status_code==403
            assert client.post('/api/v1/operations/deliveries/'+str(uuid4())+'/retry',headers=auth,json={'acknowledge_duplicate_risk':True}).status_code==403
        response=client.post('/api/v1/operations/deliveries/'+str(uuid4())+'/retry',headers=headers(['TenantAdmin']),json={'acknowledge_duplicate_risk':'private-do-not-echo'})
        assert response.status_code==422 and 'private-do-not-echo' not in response.text
        assert client.post('/api/v1/operations/deliveries/'+str(uuid4())+'/retry',headers=headers(['TenantAdmin']),content=b' '*1025).status_code==413


def test_gateway_verifies_identity_before_forwarding(context):
    settings, validator, headers = context
    seen = []
    class Limiter:
        async def check(self, tenant):
            assert tenant == TENANT
    def transport(request):
        seen.append(request)
        return httpx.Response(200, json={'tenant_id':TENANT})
    with TestClient(gateway(settings, Limiter(), httpx.MockTransport(transport), validator)) as client:
        assert client.get('/api/v1/me', headers=headers(['Viewer'])).status_code == 200
        assert len(seen) == 1 and 'x-tenant-id' not in seen[0].headers
        assert client.get('/api/v1/me', headers={'Authorization':'Bearer forged.jwt.token'}).status_code == 401
        assert len(seen) == 1


def test_new_provider_routes_preserve_role_boundaries(context):
    settings, validator, headers = context
    with TestClient(create_app(settings, identity_validator=validator)) as client:
        viewer = headers(['Viewer'])
        assert client.get('/api/v1/providers', headers=viewer).json()['providers'] == ['azure']
        assert client.get('/api/v1/trends', headers=viewer).status_code == 200
        assert client.post('/api/v1/scans/multi-cloud', headers=viewer, json={'providers':['azure']}).status_code == 403


def test_gitops_and_policy_routes_preserve_roles(context):
    settings,validator,headers=context
    with TestClient(create_app(settings,identity_validator=validator)) as client:
        viewer=headers(['Viewer'])
        selection=dict(scan_id=str(uuid4()),target_id='infra',resource_ids=['anything'])
        assert client.get('/api/v1/gitops/targets',headers=viewer).status_code==200
        assert client.get('/api/v1/gitops/requests',headers=viewer).status_code==200
        assert client.post('/api/v1/gitops/preview',headers=viewer,json=selection).status_code==403
        assert client.post('/api/v1/gitops/requests',headers=viewer,json=selection|{'idempotency_key':'test-key-12345678'}).status_code==403
        minimal=dict(format_version='1.2',configuration={'root_module':{}},resource_changes=[])
        response=client.post('/api/v1/policies/terraform/evaluate',headers=viewer,json={'plan':minimal})
        assert response.status_code==200 and response.json()['decision']=='pass'
        assert client.post('/api/v1/policies/terraform/evaluate',headers=viewer,json={'plan':minimal,'policy':{}}).status_code==422
        assert client.post('/api/v1/policies/terraform/evaluate',headers=viewer,content=b'x'*2000001).status_code==413
