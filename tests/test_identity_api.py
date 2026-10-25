"""CloudSaver as an identity-service caller, against the contract fixtures in platform/contracts/fixtures."""
import hashlib
import logging
import secrets

import httpx
import pytest
from fastapi.testclient import TestClient

import app.entitlements as entitlements
from app.config import Settings
from app.directory_projector import DirectoryProjector
from app.identity_client import IdentityClient, reset_shared_client
from app.main import create_app as scanner_app
from app.tenant_registry import MemoryRegistry
from app.main import create_app as tenant_service
from tests.identity_fake import TID, FakeIdentity

SID = '33333333-3333-4333-8333-333333333333'
REVOKED = 'This workspace key has expired or was revoked. Ask your CloudSaver administrator for a new key.'
SUSPENDED = 'This workspace is suspended. Contact your CloudSaver administrator.'


def bearer(token):
    return {'Authorization': 'Bearer ' + token}


@pytest.fixture
def fake():
    yield FakeIdentity()
    reset_shared_client(None)


@pytest.fixture
def secret():
    return 'cs_test_0example0000_' + secrets.token_urlsafe(32)


def project(fake):
    registry = MemoryRegistry(())
    DirectoryProjector(registry, fake.client()).run_once()
    return registry


@pytest.fixture
def cutover(fake, tmp_path, monkeypatch):
    monkeypatch.setenv('CLOUDSAVER_KEY_VERIFIER', 'identity')
    monkeypatch.setenv('CLOUDSAVER_DIRECTORY_MODE', 'cutover')
    registry = project(fake)
    settings = Settings('azure', str(tmp_path / 'cutover.sqlite3'), (), None, registry)
    reset_shared_client(fake.client())
    tenant_app = tenant_service(settings, identity_client=fake.client())
    with TestClient(tenant_app) as client:
        yield settings, client


def test_caller_sends_its_service_token_and_the_key_only_in_the_body(fake, secret):
    grant = fake.client().verify(secret, '203.0.113.7', 'request-1')
    assert grant['tenant_id'] == TID and grant['plan']['billing_state'] == 'grace'
    request = fake.requests[-1]
    assert request.headers['x-service-token'] == fake.token
    assert secret not in str(request.url) and secret in request.content.decode()


def test_projection_carries_the_plan_block_and_no_key_material(cutover):
    settings, _ = cutover
    tenant = settings.registry.get(TID)
    assert tenant['subscription_ids'] == [SID] and tenant['aws_accounts'][0]['account_id'] == '123456789012'
    assert tenant['api_key_sha256'] is None and tenant['directory_version'] == 4
    assert tenant['plan']['code'] == 'GROWTH' and tenant['plan']['entitlements_version'] == 7
    assert tenant['plan']['billing_state'] == 'active' and tenant['plan']['current_period_end'] == '2026-11-30T00:00:00Z'
    assert settings.registry.platform()['scheduled_scans_enabled'] is True
    assert settings.registry.projection_cursor() == 42


def test_verified_plan_wins_over_the_projection(cutover, secret):
    settings, tenant = cutover
    data = tenant.get('/api/v1/me', headers=bearer(secret)).json()
    assert data['tenant_id'] == TID and data['key_id'] == '0example0000'
    assert data['plan_tier'] == 'GROWTH' and data['plan_name'] == 'Growth' and data['billing_state'] == 'grace'
    assert data['directory_mode'] == 'cutover' and data['scopes_editable'] is False and 'api_key_sha256' not in data
    summary = TestClient(scanner_app(settings)).get('/api/v1/billing/entitlements', headers=bearer(secret)).json()
    assert summary == {
        'tenant_id': TID, 'tier': 'GROWTH', 'plan_name': 'Growth', 'billing_state': 'grace',
        'current_period_end': '2026-11-30T00:00:00Z', 'grace_ends_at': '2026-12-14T00:00:00Z',
        'subscription_plan_name': None, 'manage_billing_url': 'https://billing.example.com/acme',
        'max_subscriptions': 10, 'current_subscriptions': 2, 'max_resources_per_scan': 2500,
        'allowed_scan_frequencies': ['manual', 'daily'], 'allowed_providers': ['azure', 'aws', 'gcp', 'kubernetes'],
        'can_export_terraform': True, 'can_use_keyvault': False, 'can_dispatch_automated_alerts': True,
        'retention_days': 90, 'entitlements_source': 'platform', 'plan_change_allowed': True, 'settings_version': 1}


def test_scoped_key_only_sees_its_providers(cutover, secret):
    settings, tenant = cutover
    data = tenant.get('/api/v1/me', headers=bearer(secret)).json()
    assert data['allowed_providers'] == ['aws'] and data['subscription_ids'] == [] and data['all_providers'] is False
    scanner = TestClient(scanner_app(settings, scanner=lambda t: []))
    assert scanner.get('/api/v1/scans', headers=bearer(secret)).status_code == 200
    azure = scanner.post('/api/v1/scans', headers=bearer(secret), json={})
    assert azure.status_code == 403 and azure.json()['detail'] == "This workspace key doesn't include Azure."
    full = scanner.get('/api/v1/ai/usage', headers=bearer(secret))
    assert full.status_code == 200 and full.json().get('groups') == []


def test_plan_without_a_provider_blocks_scans_of_it(cutover, secret, fake):
    settings, _ = cutover
    fake.verify.update(all_providers=True, allowed_providers=None)
    fake.verify['plan']['entitlements']['allowed_providers'] = ['aws']
    result = TestClient(scanner_app(settings, scanner=lambda t: [])).post('/api/v1/scans', headers=bearer(secret), json={})
    assert result.status_code == 403
    assert result.json()['detail'] == "Azure isn't included in your plan. Contact your account manager."


@pytest.mark.parametrize('reason,status,detail', [('revoked', 401, REVOKED), ('expired', 401, REVOKED),
                                                  ('suspended', 403, SUSPENDED), ('workspace_suspended', 403, SUSPENDED),
                                                  ('unknown', 401, 'Invalid workspace access key')])
def test_rejected_keys_map_to_user_facing_errors(cutover, secret, fake, reason, status, detail):
    _, tenant = cutover
    fake.verify = {'valid': False, 'reason': reason}
    result = tenant.get('/api/v1/me', headers=bearer(secret))
    assert result.status_code == status and result.json()['detail'] == detail


def test_invalid_fixture_is_a_revocation(cutover, secret, fake):
    from tests.identity_fake import fixture
    _, tenant = cutover
    fake.verify = fixture('verify_invalid')
    denied = tenant.get('/api/v1/me', headers=bearer(secret))
    assert denied.status_code == 401 and denied.json()['detail'] == REVOKED


def test_resync_applies_a_lapsed_snapshot(fake):
    fake.changes_status = 410
    registry = project(fake)
    tenant = registry.get(TID)
    assert tenant['directory_version'] == 5 and registry.projection_cursor() == 42
    summary = entitlements.billing_summary(tenant)
    assert summary['tier'] == 'STARTER' and summary['billing_state'] == 'lapsed'
    assert summary['subscription_plan_name'] == 'Growth' and summary['grace_ends_at'] == '2026-10-14T00:00:00Z'
    assert summary['max_subscriptions'] == 2 and summary['entitlements_source'] == 'platform'


def test_entitlements_changed_updates_an_existing_projection(fake):
    registry = project(fake)
    change = fake.changes['items'][0]
    change.update(seq=43, version=5)
    change['snapshot'].update(version=5)
    change['snapshot']['plan'].update(code='ENTERPRISE', name='Enterprise', entitlements_version=8)
    change['snapshot']['plan']['entitlements'].update(can_use_keyvault=True, max_subscriptions=1000)
    DirectoryProjector(registry, fake.client()).run_once()
    plan = entitlements.entitlements_for(registry.get(TID))
    assert plan.tier == 'ENTERPRISE' and plan.can_use_keyvault and plan.entitlements_version == 8
    assert registry.get(TID)['plan_tier'] == 'ENTERPRISE'


def test_unknown_change_types_are_ignored(fake):
    fake.changes['items'].append({'seq': 43, 'tenant_id': TID, 'change_type': 'billing_note', 'version': 9, 'snapshot': {}})
    registry = project(fake)
    assert registry.projection_cursor() == 43 and registry.get(TID)['directory_version'] == 4


def test_missing_plan_block_falls_back_to_tier_limits(cutover, secret, fake, monkeypatch, caplog):
    settings, _ = cutover
    monkeypatch.setattr(entitlements, '_warned', set())
    fake.verify.pop('plan')
    settings.registry._tenants[TID].pop('plan')
    settings.registry.invalidate()
    scanner = TestClient(scanner_app(settings))
    with caplog.at_level(logging.WARNING, logger='cloudsaver.entitlements'):
        for _ in range(2):
            summary = scanner.get('/api/v1/billing/entitlements', headers=bearer(secret)).json()
    assert summary['entitlements_source'] == 'fallback' and summary['billing_state'] == 'none'
    assert summary['tier'] == 'GROWTH' and summary['max_subscriptions'] == 10 and summary['manage_billing_url'] is None
    assert [r.getMessage() for r in caplog.records].count(f'entitlements_fallback tenant_id={TID} plan=GROWTH') == 1


def test_malformed_plan_block_is_ignored(cutover, secret, fake):
    settings, tenant = cutover
    fake.verify['plan']['billing_state'] = 'overdue'
    data = tenant.get('/api/v1/me', headers=bearer(secret)).json()
    assert data['billing_state'] == 'active'


def test_registry_writes_move_to_the_portal_after_cutover(cutover, secret, fake):
    _, tenant = cutover
    fake.verify.update(all_providers=True, allowed_providers=None)
    assert tenant.get('/api/v1/admin/tenants', headers=bearer(secret)).status_code == 404
    loaded = tenant.get('/api/v1/settings', headers=bearer(secret)).json()
    assert loaded['scopes_editable'] is False
    body = {'version': loaded['settings']['version'], 'subscription_ids': [], 'aws_accounts': [], 'gcp_projects': [],
            'schedule': loaded['settings']['schedule'], 'alerts': {'enabled': False, 'channel': None}}
    assert tenant.put('/api/v1/settings', headers=bearer(secret), json=body).status_code == 403


def test_sign_in_fails_closed_when_identity_is_unavailable(cutover, secret, fake):
    _, tenant = cutover

    def offline(request):
        raise httpx.ConnectError('down')
    reset_shared_client(IdentityClient('http://identity', fake.token, cache_seconds=0,
                                       transport=httpx.MockTransport(offline), subscribe=False))
    result = tenant.get('/api/v1/me', headers=bearer(secret))
    assert result.status_code == 503 and result.json()['detail'].startswith('Sign-in is temporarily unavailable')
    fake.verify_status = 500
    reset_shared_client(fake.client())
    assert tenant.get('/api/v1/me', headers=bearer(secret)).status_code == 503


def test_unprojected_workspace_asks_the_caller_to_retry(fake, secret, tmp_path, monkeypatch):
    monkeypatch.setenv('CLOUDSAVER_KEY_VERIFIER', 'identity')
    settings = Settings('azure', str(tmp_path / 'empty.sqlite3'), (), None, MemoryRegistry(()))
    reset_shared_client(fake.client())
    result = TestClient(tenant_service(settings)).get('/api/v1/me', headers=bearer(secret))
    assert result.status_code == 503 and result.headers['retry-after'] == '5'


def test_shadow_mode_never_changes_the_local_answer(tmp_path, monkeypatch, fake):
    monkeypatch.setenv('CLOUDSAVER_KEY_VERIFIER', 'shadow')
    key = secrets.token_urlsafe(32)
    tenant = dict(tenant_id=TID, name='Local', subscription_ids=[SID], api_key_sha256=hashlib.sha256(key.encode()).hexdigest())

    def offline(request):
        raise httpx.ConnectError('down')
    reset_shared_client(IdentityClient('http://identity', fake.token, cache_seconds=0,
                                       transport=httpx.MockTransport(offline), subscribe=False))
    client = TestClient(tenant_service(Settings('azure', str(tmp_path / 'shadow.sqlite3'), (tenant,))))
    assert client.get('/api/v1/me', headers=bearer(key)).status_code == 200
    assert client.get('/api/v1/me', headers=bearer('x' * 40)).status_code == 401


@pytest.fixture
def registry_mode(fake, tmp_path, monkeypatch):
    monkeypatch.setenv('CLOUDSAVER_KEY_VERIFIER', 'identity')
    settings = Settings('azure', str(tmp_path / 'registry.sqlite3'), (), None, project(fake))
    reset_shared_client(fake.client())
    return settings, TestClient(tenant_service(settings))


def settings_body(loaded, **changes):
    return {'version': loaded['settings']['version'], 'subscription_ids': loaded['settings']['subscription_ids'],
            'aws_accounts': loaded['settings']['aws_accounts'], 'gcp_projects': loaded['settings']['gcp_projects'],
            'schedule': loaded['settings']['schedule'], 'alerts': {'enabled': False, 'channel': None}} | changes


def test_viewer_key_cannot_change_settings(registry_mode, fake, secret):
    _, tenant = registry_mode
    fake.verify['roles'] = ['Viewer']
    loaded = tenant.get('/api/v1/settings', headers=bearer(secret)).json()
    assert loaded['editable'] is False
    assert tenant.put('/api/v1/settings', headers=bearer(secret), json=settings_body(loaded)).status_code == 403


def test_scoped_key_settings_update_preserves_other_providers(registry_mode, secret):
    settings, tenant = registry_mode
    loaded = tenant.get('/api/v1/settings', headers=bearer(secret)).json()
    assert loaded['settings']['subscription_ids'] == [] and loaded['scopes_editable'] is True
    moved = [dict(loaded['settings']['aws_accounts'][0], region='eu-west-1')]
    result = tenant.put('/api/v1/settings', headers=bearer(secret), json=settings_body(loaded, aws_accounts=moved))
    assert result.status_code == 200, result.text
    assert result.json()['settings']['subscription_ids'] == []
    stored = settings.registry.get(TID)
    assert stored['subscription_ids'] == [SID] and stored['aws_accounts'][0]['region'] == 'eu-west-1'


def test_plan_limits_apply_to_settings_changes(registry_mode, fake, secret):
    _, tenant = registry_mode
    fake.verify.update(all_providers=True, allowed_providers=None)
    loaded = tenant.get('/api/v1/settings', headers=bearer(secret)).json()
    hourly = settings_body(loaded, schedule=dict(loaded['settings']['schedule'], frequency='hourly'))
    result = tenant.put('/api/v1/settings', headers=bearer(secret), json=hourly)
    assert result.status_code == 402 and result.json()['detail'] == "Hourly scans aren't included in your plan. Contact your account manager."
    fake.verify['plan']['entitlements']['max_subscriptions'] = 2
    extra = settings_body(loaded, subscription_ids=[SID, '44444444-4444-4444-8444-444444444444'])
    result = tenant.put('/api/v1/settings', headers=bearer(secret), json=extra)
    assert result.status_code == 402
    assert result.json()['detail'] == 'Your Growth plan allows up to 2 cloud scopes. Contact your account manager to change your plan.'


def test_scan_filtering_hides_other_providers():
    from app.provider_access import filter_scan
    scan = {'scan_id': 's', 'cloud_providers': ['azure', 'aws'], 'subscriptions_scanned': 1, 'total_items_found': 2,
            'findings': [{'cloud_provider': 'azure', 'resource_id': '/subscriptions/example/disks/a', 'estimated_monthly_waste_usd': 10.0},
                         {'cloud_provider': 'aws', 'resource_id': 'arn:aws:ec2:us-east-1:123456789012:volume/vol-a', 'estimated_monthly_waste_usd': 4.5}]}
    filtered = filter_scan(scan, frozenset({'aws'}))
    assert filtered['total_items_found'] == 1 and filtered['total_monthly_waste_usd'] == 4.5
    assert filtered['cloud_providers'] == ['aws'] and filtered['subscriptions_scanned'] == 0
    assert filter_scan({'scan_id': 'a', 'cloud_providers': ['azure'], 'findings': []}, frozenset({'aws'})) is None
    assert filter_scan(scan, frozenset({'aws'}), strict=True) is None


def test_scope_limited_key_only_sees_its_scopes(cutover, secret, fake):
    fake.verify = dict(fake.verify, all_providers=True, allowed_providers=['azure', 'aws'],
                       scope_restrictions={'aws': ['999999999999']}, customer_roles=['CustomerAdmin'])
    settings, tenant = cutover
    data = tenant.get('/api/v1/me', headers=bearer(secret)).json()
    assert data['scope_restrictions'] == {'aws': ['999999999999']} and data['customer_roles'] == ['CustomerAdmin']
    assert data['configured_scope_count'] == 1 and data['subscription_ids'] == [SID]
    scanner = TestClient(scanner_app(settings, scanner=lambda t: []))
    full = scanner.get('/api/v1/ai/usage', headers=bearer(secret))
    assert full.status_code == 200 and full.json().get('groups') == []


def test_gateway_pins_customer_calls_to_the_callers_workspace(cutover, secret, fake):
    from services.gateway import create_app as gateway

    class Limiter:
        async def check(self, tenant_id):
            return None

    settings, _ = cutover
    client = TestClient(gateway(settings, Limiter()))
    members = client.get('/api/v1/customer/members', headers=bearer(secret)).json()
    assert 'path' in members, members
    assert members['path'] == f'/customer/v1/workspaces/{TID}/members'
    assert members['authorization'] == 'Bearer ' + secret
    invite = client.post('/api/v1/customer/users/invite', headers=bearer(secret),
                         json={'display_name': 'Lin', 'email': 'Lin@Contoso.com'}).json()
    assert invite['body']['idp_issuer'] == 'urn:cloudsaver:email' and invite['body']['idp_subject'] == 'lin@contoso.com'
    assert client.get('/api/v1/customer/members').status_code == 401
    bad = client.post('/api/v1/customer/keys/../../admin/revoke', headers=bearer(secret), json={})
    assert bad.status_code == 404
    claim = client.post('/api/v1/onboarding/claim', json={'key': 'k', 'display_name': 'Ada', 'email': 'ada@contoso.com'})
    assert claim.json()['path'] == '/customer/v1/claim' and claim.json()['authorization'] is None


def test_scan_filtering_hides_out_of_scope_findings():
    from app.provider_access import filter_scan, restrict
    scan = {'scan_id': 's', 'cloud_providers': ['azure', 'aws'], 'subscriptions_scanned': 1,
            'findings': [{'cloud_provider': 'azure', 'resource_id': '/subscriptions/example/disks/a', 'subscription_id': SID, 'estimated_monthly_waste_usd': 10.0},
                         {'cloud_provider': 'aws', 'resource_id': 'arn:aws:ec2:us-east-1:123456789012:volume/vol-a', 'scope_id': '123456789012', 'estimated_monthly_waste_usd': 4.5},
                         {'cloud_provider': 'aws', 'resource_id': 'arn:aws:ec2:us-east-1:999999999999:volume/vol-b', 'scope_id': '999999999999', 'estimated_monthly_waste_usd': 1.0}]}
    allowed = frozenset({'azure', 'aws'})
    filtered = filter_scan(scan, allowed, scopes={'aws': frozenset({'999999999999'})})
    assert [f.get('scope_id') or f['subscription_id'] for f in filtered['findings']] == [SID, '999999999999']
    assert filtered['total_monthly_waste_usd'] == 11.0 and filtered['scope_filtered'] is True
    assert filter_scan(scan, allowed, strict=True, scopes={'aws': frozenset({'999999999999'})}) is None
    tenant = {'subscription_ids': [SID], 'aws_accounts': [{'account_id': '123456789012', 'region': 'us-east-1'}]}
    assert restrict(tenant, {'aws': ['999999999999']})['aws_accounts'] == []
    assert restrict(tenant, {'aws': ['123456789012']})['subscription_ids'] == [SID]


def test_directory_events_wake_the_tenant_projector(cutover, fake):
    from app.identity_client import EventPoller
    settings, _ = cutover
    client = fake.client()
    tenant_app = tenant_service(settings, identity_client=client)
    with TestClient(tenant_app):
        assert tenant_app.state.projector.nudge in client.directory_listeners
        woken = []
        client.directory_listeners.append(lambda: woken.append(True))
        poller = EventPoller(client, client.cache, client._directory_changed)
        poller.poll_once()
        assert woken == []
        poller.poll_once()
        assert woken == [True]
