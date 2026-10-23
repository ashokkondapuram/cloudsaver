import hashlib
import secrets
from datetime import timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.directory_projector import DirectoryProjector
from app.main import create_app as scanner_app
from app.tenant_registry import MemoryRegistry
from identity.app import create_app as identity_app
from identity.auth import OperatorAuth
from identity.client import IdentityClient, reset_shared_client
from identity.domain import utcnow
from identity.events import MemoryEvents
from identity.keys import Peppers
from identity.service import IdentityService
from identity.store_memory import MemoryStore
from identity.throttle import MemoryBackend, Throttle
from identity.usage import UsageRecorder
from services.tenant import create_app as tenant_service

TID = '11111111-1111-4111-8111-111111111111'
SID = '33333333-3333-4333-8333-333333333333'
AWS = [{'account_id': '123456789012', 'region': 'us-east-1', 'role_arn': 'arn:aws:iam::123456789012:role/CloudSaverReader'}]
TOKENS = {name: secrets.token_urlsafe(32) for name in ('gateway', 'tenant', 'scanner', 'portal')}
OPERATOR = secrets.token_urlsafe(32)


def bearer(token):
    return {'Authorization': 'Bearer ' + token}


def admin():
    return bearer(OPERATOR) | {'X-Service-Token': TOKENS['portal']}


def forward(client):
    def handler(request):
        headers = {k: v for k, v in request.headers.items() if k.lower() in ('x-service-token', 'content-type')}
        result = client.request(request.method, request.url.path, params=dict(request.url.params),
                                content=request.content, headers=headers)
        return httpx.Response(result.status_code, headers={'content-type': result.headers.get('content-type', '')},
                              content=result.content)
    return httpx.MockTransport(handler)


@pytest.fixture
def identity(monkeypatch):
    monkeypatch.setenv('CLOUDSAVER_OPERATOR_KEY_SHA256', hashlib.sha256(OPERATOR.encode()).hexdigest())
    service = IdentityService(MemoryStore(), Peppers(1, b'a' * 32), Throttle(MemoryBackend()), MemoryEvents(), UsageRecorder(),
                              environment='development', cache_seconds=15, provider_scoped_keys=True)
    callers = {name: hashlib.sha256(token.encode()).digest() for name, token in TOKENS.items()}
    app = identity_app(service, callers=callers, operator_auth=OperatorAuth('operator_key', 'development'))
    return TestClient(app), service


def caller(client, name, cache_seconds=0):
    return IdentityClient('http://identity', TOKENS[name], cache_seconds=cache_seconds, transport=forward(client), subscribe=False)


def provision(client):
    customer = client.post('/admin/v1/customers', headers=admin(), json={'name': 'Contoso'})
    assert customer.status_code == 201, customer.text
    created = client.post('/admin/v1/workspaces', headers=admin(), json={
        'tenant_id': TID, 'customer_id': customer.json()['id'], 'name': 'Contoso prod', 'plan_tier': 'ENTERPRISE'})
    assert created.status_code == 201, created.text
    version = created.json()['version']
    for provider, items in (('azure', [SID]), ('aws', AWS)):
        result = client.put(f'/admin/v1/workspaces/{TID}/scopes/{provider}', headers=admin(), json={'version': version, 'items': items})
        assert result.status_code == 200, result.text
        version = result.json()['version']


def issue(client, **changes):
    payload = {'name': 'Dashboard', 'roles': ['TenantAdmin', 'Viewer'], 'all_providers': True,
               'expires_at': (utcnow() + timedelta(days=30)).isoformat()} | changes
    result = client.post(f'/admin/v1/workspaces/{TID}/keys', headers=admin(), json=payload)
    assert result.status_code == 201, result.text
    return result.json()


def test_verify_requires_a_known_caller_and_never_echoes_keys(identity):
    client, _ = identity
    body = {'key': 'cs_test_0123456789ab_' + 'A' * 43, 'client_ip': '203.0.113.7'}
    assert client.post('/internal/v1/keys/verify', json=body).status_code == 401
    assert client.post('/internal/v1/keys/verify', json=body, headers={'X-Service-Token': 'wrong'}).status_code == 401
    assert client.post('/internal/v1/keys/verify', json=body, headers={'X-Service-Token': TOKENS['portal']}).status_code == 403
    result = client.post('/internal/v1/keys/verify', json=body, headers={'X-Service-Token': TOKENS['gateway']})
    assert result.status_code == 200 and result.json() == {'valid': False, 'reason': 'unknown'}
    assert result.headers['cache-control'] == 'no-store'
    invalid = client.post('/internal/v1/keys/verify', json=body | {'extra': 1}, headers={'X-Service-Token': TOKENS['gateway']})
    assert invalid.status_code == 422 and body['key'] not in invalid.text
    assert client.get('/internal/v1/directory/changes', headers={'X-Service-Token': TOKENS['gateway']}).status_code == 403


def test_admin_api_requires_portal_caller_and_operator(identity):
    client, _ = identity
    assert client.get('/admin/v1/customers', headers=bearer(OPERATOR)).status_code == 401
    assert client.get('/admin/v1/customers', headers={'X-Service-Token': TOKENS['portal']}).status_code == 401
    assert client.get('/admin/v1/customers', headers=bearer(OPERATOR) | {'X-Service-Token': TOKENS['gateway']}).status_code == 403
    session = client.get('/admin/v1/session', headers=admin()).json()
    assert session['auth_mode'] == 'operator_key' and session['key_prefix'] == 'cs_test_'


def test_operator_key_fallback_is_refused_in_production():
    with pytest.raises(RuntimeError):
        OperatorAuth('operator_key', 'production')


def test_entra_operator_tokens_need_a_platform_role(monkeypatch):
    import time
    import jwt
    from cryptography.hazmat.primitives.asymmetric import rsa
    from fastapi import HTTPException
    tenant = '22222222-2222-4222-8222-222222222222'
    monkeypatch.setenv('CLOUDSAVER_OPERATOR_TENANT_ID', tenant)
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    auth = OperatorAuth('entra', 'production', key_resolver=lambda token: private.public_key())

    def token(**claims):
        now = int(time.time())
        body = {'iss': f'https://login.microsoftonline.com/{tenant}/v2.0', 'aud': 'api://cloudsaver-identity', 'tid': tenant,
                'oid': 'operator-1', 'iat': now, 'exp': now + 300, 'name': 'Avery'} | claims
        return jwt.encode(body, private, algorithm='RS256')
    assert auth.authenticate(token(roles=['PlatformAuditor']))['roles'] == ['PlatformAuditor']
    with pytest.raises(HTTPException) as missing:
        auth.authenticate(token(roles=[]))
    assert missing.value.status_code == 403
    with pytest.raises(HTTPException) as foreign:
        auth.authenticate(token(roles=['PlatformOperator'], tid='33333333-3333-4333-8333-333333333333'))
    assert foreign.value.status_code == 401


def test_issued_secret_is_returned_once_and_audited(identity):
    client, _ = identity
    provision(client)
    issued = issue(client)
    key_id = issued['key']['key_id']
    assert issued['secret'].startswith('cs_test_' + key_id)
    detail = client.get(f'/admin/v1/keys/{key_id}', headers=admin())
    assert detail.status_code == 200 and issued['secret'] not in detail.text
    audit = client.get('/admin/v1/audit', headers=admin(), params={'tenant_id': TID}).json()['items']
    assert any(item['action'] == 'issued' and item['key_id'] == key_id for item in audit)
    assert issued['secret'] not in str(audit)


@pytest.fixture
def cutover(identity, tmp_path, monkeypatch):
    client, service = identity
    monkeypatch.setenv('CLOUDSAVER_KEY_VERIFIER', 'identity')
    monkeypatch.setenv('CLOUDSAVER_DIRECTORY_MODE', 'cutover')
    provision(client)
    registry = MemoryRegistry(())
    DirectoryProjector(registry, caller(client, 'tenant')).run_once()
    settings = Settings('azure', str(tmp_path / 'cutover.sqlite3'), (), None, registry)
    reset_shared_client(caller(client, 'gateway'))
    tenant_app = tenant_service(settings, identity_client=caller(client, 'tenant'))
    yield client, service, settings, TestClient(tenant_app)
    tenant_app.state.projector.stop()
    reset_shared_client(None)


def test_projection_mirrors_directory_without_key_material(cutover):
    _, _, settings, _ = cutover
    tenant = settings.registry.get(TID)
    assert tenant['subscription_ids'] == [SID] and tenant['aws_accounts'][0]['account_id'] == '123456789012'
    assert tenant['api_key_sha256'] is None and tenant['directory_version'] >= 3


def test_workspace_key_signs_in_through_identity_and_revocation_applies(cutover):
    client, _, _, tenant = cutover
    issued = issue(client)
    me = tenant.get('/api/v1/me', headers=bearer(issued['secret']))
    assert me.status_code == 200, me.text
    data = me.json()
    assert data['tenant_id'] == TID and data['key_id'] == issued['key']['key_id'] and data['all_providers'] is True
    assert data['directory_mode'] == 'cutover' and data['scopes_editable'] is False
    assert 'api_key_sha256' not in data
    revoked = client.post(f"/admin/v1/keys/{issued['key']['key_id']}/revoke", headers=admin(), json={'reason': 'Rotation'})
    assert revoked.status_code == 200
    denied = tenant.get('/api/v1/me', headers=bearer(issued['secret']))
    assert denied.status_code == 401 and 'expired or was revoked' in denied.json()['detail']


def test_scoped_key_only_sees_its_providers(cutover):
    client, _, settings, tenant = cutover
    secret = issue(client, all_providers=False, allowed_providers=['aws'])['secret']
    data = tenant.get('/api/v1/me', headers=bearer(secret)).json()
    assert data['allowed_providers'] == ['aws'] and data['subscription_ids'] == [] and data['all_providers'] is False
    scanner = TestClient(scanner_app(settings, scanner=lambda t: []))
    assert scanner.get('/api/v1/scans', headers=bearer(secret)).status_code == 200
    azure = scanner.post('/api/v1/scans', headers=bearer(secret), json={})
    assert azure.status_code == 403 and azure.json()['detail'] == "This workspace key doesn't include Azure."
    full = scanner.get('/api/v1/ai/usage', headers=bearer(secret))
    assert full.status_code == 403 and 'all providers' in full.json()['detail']


def test_registry_writes_move_to_the_portal_after_cutover(cutover):
    client, _, _, tenant = cutover
    secret = issue(client)['secret']
    assert tenant.get('/api/v1/admin/tenants', headers=bearer(OPERATOR)).status_code == 404
    loaded = tenant.get('/api/v1/settings', headers=bearer(secret)).json()
    assert loaded['scopes_editable'] is False
    body = {'version': loaded['settings']['version'], 'subscription_ids': [], 'aws_accounts': [], 'gcp_projects': [],
            'schedule': loaded['settings']['schedule'], 'alerts': {'enabled': False, 'channel': None}}
    assert tenant.put('/api/v1/settings', headers=bearer(secret), json=body).status_code == 403


def test_sign_in_fails_closed_when_identity_is_unavailable(cutover):
    client, _, _, tenant = cutover
    secret = issue(client)['secret']

    def offline(request):
        raise httpx.ConnectError('down')
    reset_shared_client(IdentityClient('http://identity', TOKENS['gateway'], cache_seconds=0,
                                       transport=httpx.MockTransport(offline), subscribe=False))
    result = tenant.get('/api/v1/me', headers=bearer(secret))
    assert result.status_code == 503 and result.json()['detail'].startswith('Sign-in is temporarily unavailable')


def test_unprojected_workspace_asks_the_caller_to_retry(identity, tmp_path, monkeypatch):
    client, _ = identity
    monkeypatch.setenv('CLOUDSAVER_KEY_VERIFIER', 'identity')
    provision(client)
    secret = issue(client)['secret']
    settings = Settings('azure', str(tmp_path / 'empty.sqlite3'), (), None, MemoryRegistry(()))
    reset_shared_client(caller(client, 'gateway'))
    try:
        result = TestClient(tenant_service(settings)).get('/api/v1/me', headers=bearer(secret))
    finally:
        reset_shared_client(None)
    assert result.status_code == 503 and result.headers['retry-after'] == '5'


def test_shadow_mode_never_changes_the_local_answer(tmp_path, monkeypatch):
    monkeypatch.setenv('CLOUDSAVER_KEY_VERIFIER', 'shadow')
    key = secrets.token_urlsafe(32)
    tenant = dict(tenant_id=TID, name='Local', subscription_ids=[SID], api_key_sha256=hashlib.sha256(key.encode()).hexdigest())

    def offline(request):
        raise httpx.ConnectError('down')
    reset_shared_client(IdentityClient('http://identity', TOKENS['gateway'], cache_seconds=0,
                                       transport=httpx.MockTransport(offline), subscribe=False))
    try:
        client = TestClient(tenant_service(Settings('azure', str(tmp_path / 'shadow.sqlite3'), (tenant,))))
        assert client.get('/api/v1/me', headers=bearer(key)).status_code == 200
        assert client.get('/api/v1/me', headers=bearer('x' * 40)).status_code == 401
    finally:
        reset_shared_client(None)


@pytest.fixture
def registry_mode(identity, tmp_path, monkeypatch):
    client, _ = identity
    monkeypatch.setenv('CLOUDSAVER_KEY_VERIFIER', 'identity')
    provision(client)
    registry = MemoryRegistry(())
    DirectoryProjector(registry, caller(client, 'tenant')).run_once()
    settings = Settings('azure', str(tmp_path / 'registry.sqlite3'), (), None, registry)
    reset_shared_client(caller(client, 'gateway'))
    yield client, settings, TestClient(tenant_service(settings))
    reset_shared_client(None)


def settings_body(loaded, **changes):
    return {'version': loaded['settings']['version'], 'subscription_ids': loaded['settings']['subscription_ids'],
            'aws_accounts': loaded['settings']['aws_accounts'], 'gcp_projects': loaded['settings']['gcp_projects'],
            'schedule': loaded['settings']['schedule'], 'alerts': {'enabled': False, 'channel': None}} | changes


def test_viewer_key_cannot_change_settings(registry_mode):
    client, _, tenant = registry_mode
    secret = issue(client, roles=['Viewer'])['secret']
    loaded = tenant.get('/api/v1/settings', headers=bearer(secret)).json()
    assert loaded['editable'] is False
    assert tenant.put('/api/v1/settings', headers=bearer(secret), json=settings_body(loaded)).status_code == 403


def test_scoped_key_settings_update_preserves_other_providers(registry_mode):
    client, settings, tenant = registry_mode
    secret = issue(client, all_providers=False, allowed_providers=['aws'])['secret']
    loaded = tenant.get('/api/v1/settings', headers=bearer(secret)).json()
    assert loaded['settings']['subscription_ids'] == [] and loaded['scopes_editable'] is True
    moved = [dict(AWS[0], region='eu-west-1')]
    result = tenant.put('/api/v1/settings', headers=bearer(secret), json=settings_body(loaded, aws_accounts=moved))
    assert result.status_code == 200, result.text
    assert result.json()['settings']['subscription_ids'] == []
    stored = settings.registry.get(TID)
    assert stored['subscription_ids'] == [SID] and stored['aws_accounts'][0]['region'] == 'eu-west-1'


def test_scan_filtering_hides_other_providers():
    from app.provider_access import filter_scan
    scan = {'scan_id': 's', 'cloud_providers': ['azure', 'aws'], 'subscriptions_scanned': 1, 'total_items_found': 2,
            'findings': [{'cloud_provider': 'azure', 'estimated_monthly_waste_usd': 10.0},
                         {'cloud_provider': 'aws', 'estimated_monthly_waste_usd': 4.5}]}
    filtered = filter_scan(scan, frozenset({'aws'}))
    assert filtered['total_items_found'] == 1 and filtered['total_monthly_waste_usd'] == 4.5
    assert filtered['cloud_providers'] == ['aws'] and filtered['subscriptions_scanned'] == 0
    assert filter_scan({'scan_id': 'a', 'cloud_providers': ['azure'], 'findings': []}, frozenset({'aws'})) is None
    assert filter_scan(scan, frozenset({'aws'}), strict=True) is None


def test_projector_resyncs_when_the_cursor_is_too_old(identity):
    client, _ = identity
    provision(client)
    registry = MemoryRegistry(())
    real = caller(client, 'tenant')

    class Expired:
        def get(self, path, params=None):
            if path.endswith('/changes'):
                return httpx.Response(410, json={'detail': 'Resync'})
            return real.get(path, params)
    DirectoryProjector(registry, Expired()).run_once()
    assert registry.get(TID)['name'] == 'Contoso prod'
    assert registry.projection_cursor() > 0
