import hashlib
import logging
import secrets
from datetime import timedelta
from pathlib import Path

import httpx
import pytest

from identity import keys as keyfmt
from identity.client import GrantCache, IdentityClient, IdentityUnavailable, KeyRejected
from identity.domain import Conflict, IdentityError, NotFound, StaleVersion, Throttled, utcnow
from identity.events import MemoryEvents
from identity.importer import customer_id_for, import_directory
from identity.keys import Peppers
from identity.service import IdentityService
from identity.store_memory import MemoryStore
from identity.throttle import MemoryBackend, Throttle
from identity.usage import UsageRecorder

TID = '11111111-1111-4111-8111-111111111111'
SID = '33333333-3333-4333-8333-333333333333'
ROLE = 'arn:aws:iam::123456789012:role/CloudSaverReader'
AWS = [{'account_id': '123456789012', 'region': 'us-east-1', 'role_arn': ROLE}]
OPERATOR = {'actor': 'operator-key', 'actor_type': 'operator'}
IP = '203.0.113.7'
ROOT = Path(__file__).resolve().parents[1]


class Clock:
    def __init__(self):
        self.value = utcnow()

    def __call__(self):
        return self.value


def build(store=None, peppers=None, clock=None, scoped=True):
    return IdentityService(store or MemoryStore(), peppers or Peppers(1, b'a' * 32), Throttle(MemoryBackend()),
                           MemoryEvents(), UsageRecorder(), environment='development', clock=clock or utcnow,
                           cache_seconds=15, provider_scoped_keys=scoped)


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def service(clock):
    return build(clock=clock)


def workspace(service, scopes=None):
    customer = service.create_customer({'name': 'Contoso'}, OPERATOR)
    service.create_workspace({'tenant_id': TID, 'customer_id': customer['id'], 'name': 'Contoso prod',
                              'plan_tier': 'ENTERPRISE'}, OPERATOR,
                             scopes=scopes or {'subscription_ids': [SID], 'aws_accounts': AWS})
    return customer


def issue(service, clock, **changes):
    payload = {'name': 'CI key', 'roles': ['Viewer'], 'all_providers': True,
               'expires_at': (clock() + timedelta(days=30)).isoformat()} | changes
    return service.issue_key(TID, payload, OPERATOR)


def test_issued_key_format_and_only_digest_is_stored(service, clock):
    workspace(service)
    issued = issue(service, clock)
    secret = issued['secret']
    assert keyfmt.V1.fullmatch(secret) and secret.startswith('cs_test_')
    assert issued['key']['key_id'] == secret.split('_')[2]
    assert secret not in repr(service.store.state)
    assert 'secret' not in service.get_key(issued['key']['key_id'])


def test_verify_grant_and_rejection_reasons(service, clock):
    workspace(service)
    secret = issue(service, clock)['secret']
    grant = service.verify(secret, IP, 'gateway')
    assert grant['valid'] and grant['tenant_id'] == TID and grant['roles'] == ['Viewer']
    assert grant['allowed_providers'] == ['azure', 'aws'] and grant['cache_ttl_seconds'] == 15
    assert service.verify(secret[:-1] + ('A' if secret[-1] != 'A' else 'B'), IP, 'gateway')['reason'] == 'secret_mismatch'
    assert service.verify('cs_test_bad', IP, 'gateway')['reason'] == 'malformed'
    assert service.verify(secrets.token_hex(32), IP, 'gateway')['reason'] == 'unknown'


def test_provider_scoped_key_narrows_grant(service, clock):
    workspace(service)
    grant = service.verify(issue(service, clock, all_providers=False, allowed_providers=['aws'])['secret'], IP, 'gateway')
    assert grant['all_providers'] is False and grant['allowed_providers'] == ['aws']
    with pytest.raises(IdentityError):
        issue(service, clock, all_providers=False, allowed_providers=['gcp'])


def test_scoped_keys_require_flag(clock):
    service = build(clock=clock, scoped=False)
    workspace(service)
    with pytest.raises(IdentityError, match='Provider-scoped keys'):
        issue(service, clock, all_providers=False, allowed_providers=['aws'])


def test_revoke_expire_and_rotate(service, clock):
    workspace(service)
    issued = issue(service, clock)
    key_id = issued['key']['key_id']
    rotated = service.rotate_key(key_id, {'overlap_hours': 1}, OPERATOR)
    assert service.verify(issued['secret'], IP, 'gateway')['valid']
    clock.value += timedelta(hours=2)
    assert service.verify(issued['secret'], IP, 'gateway')['reason'] == 'rotated_out'
    assert service.verify(rotated['secret'], IP, 'gateway')['valid']
    service.revoke_key(rotated['key']['key_id'], {'reason': 'Leaked'}, OPERATOR)
    assert service.verify(rotated['secret'], IP, 'gateway')['reason'] == 'revoked'
    assert {'key_id': rotated['key']['key_id'], 'event': 'revoked'} in service.events.published
    other = issue(service, clock)
    clock.value += timedelta(days=31)
    assert service.verify(other['secret'], IP, 'gateway')['reason'] == 'expired'


def test_suspended_workspace_and_customer_are_rejected(service, clock):
    customer = workspace(service)
    secret = issue(service, clock)['secret']
    view = service.set_workspace_status(TID, {'version': 1}, 'suspended', OPERATOR)
    assert service.verify(secret, IP, 'gateway')['reason'] == 'workspace_suspended'
    service.set_workspace_status(TID, {'version': view['version']}, 'active', OPERATOR)
    assert service.verify(secret, IP, 'gateway')['valid']
    service.set_customer_status(customer['id'], {'version': 1}, 'suspended', OPERATOR)
    assert service.verify(secret, IP, 'gateway')['reason'] == 'workspace_suspended'


def test_repeated_mismatches_throttle_the_key_and_ip(service, clock):
    workspace(service)
    secret = issue(service, clock)['secret']
    wrong = secret[:-4] + 'zzzz' if not secret.endswith('zzzz') else secret[:-4] + 'yyyy'
    for _ in range(5):
        assert service.verify(wrong, IP, 'gateway')['reason'] == 'secret_mismatch'
    with pytest.raises(Throttled) as blocked:
        service.verify(secret, IP, 'gateway')
    assert blocked.value.retry_after > 0
    assert service.verify(secret, '198.51.100.1', 'gateway')['valid']


def test_active_key_limit_and_expiry_bounds(service, clock):
    workspace(service)
    with pytest.raises(IdentityError, match='at most 365 days'):
        issue(service, clock, expires_at=(clock() + timedelta(days=400)).isoformat())
    for _ in range(20):
        issue(service, clock)
    with pytest.raises(Conflict):
        issue(service, clock)


def test_import_is_idempotent_and_legacy_keys_upgrade_on_use(clock):
    store = MemoryStore()
    service = build(store, clock=clock)
    legacy = secrets.token_hex(32)
    tenant = {'tenant_id': TID, 'name': 'Contoso', 'plan_tier': 'GROWTH', 'subscription_ids': [SID], 'aws_accounts': AWS,
              'api_key_sha256': hashlib.sha256(legacy.encode()).hexdigest(), 'active': True}
    deadline = clock() + timedelta(days=90)
    counts = import_directory(service, [tenant], 'registry_import', deadline=deadline)
    assert counts == {'customers': 1, 'workspaces': 1, 'keys': 1, 'skipped_keys': 0}
    assert service.get_workspace(TID)['customer_id'] == customer_id_for(TID)
    grant = service.verify(legacy, IP, 'gateway')
    assert grant['valid'] and grant['all_providers'] and grant['roles'] == ['TenantAdmin', 'BillingAdmin', 'Viewer']
    assert grant['expires_at'].startswith(deadline.date().isoformat())
    row = next(iter(store.state['keys'].values()))
    assert row['hash_scheme'] == 'hmac_sha256' and row['legacy_sha256'] is None and row['secret_digest']
    assert import_directory(service, [tenant], 'registry_import', deadline=deadline)['skipped_keys'] == 1
    assert service.verify(legacy, IP, 'gateway')['valid']
    actions = [e['action'] for e in store.state['events']]
    assert 'imported' in actions and 'hash_upgraded' in actions


def test_pepper_rotation_keeps_keys_valid_and_rehashes(clock):
    store = MemoryStore()
    first = build(store, Peppers(1, b'a' * 32), clock)
    workspace(first)
    issued = issue(first, clock)
    second = build(store, Peppers(2, b'b' * 32, {1: b'a' * 32}), clock)
    assert second.verify(issued['secret'], IP, 'gateway')['valid']
    assert store.state['keys'][issued['key']['key_id']]['pepper_version'] == 2
    assert build(store, Peppers(2, b'b' * 32), clock).verify(issued['secret'], IP, 'gateway')['valid']


def test_change_feed_and_snapshot(service, clock):
    workspace(service)
    changes = service.changes(0)['items']
    assert changes[-1]['tenant_id'] == TID and changes[-1]['snapshot']['aws_accounts'] == AWS
    snap = service.directory_snapshot()
    assert snap['seq'] == changes[-1]['seq'] and snap['workspaces'][0]['active'] is True


def test_grant_cache_ttl_and_eviction():
    now = [0.0]
    cache = GrantCache(15, clock=lambda: now[0])
    grant = {'key_id': 'abc', 'tenant_id': TID, 'cache_ttl_seconds': 5}
    cache.put('h1', grant)
    assert cache.get('h1') == grant
    now[0] = 6
    assert cache.get('h1') is None
    cache.put('h1', grant)
    cache.evict({'tenant_id': TID})
    assert cache.get('h1') is None
    cache.enabled = False
    cache.put('h1', grant)
    assert cache.get('h1') is None


def test_identity_client_caches_and_fails_closed():
    calls = []
    responses = iter([httpx.Response(200, json={'valid': True, 'key_id': 'k', 'tenant_id': TID, 'cache_ttl_seconds': 15}),
                      httpx.Response(200, json={'valid': False, 'reason': 'revoked'}),
                      httpx.Response(429, headers={'Retry-After': '60'}),
                      httpx.Response(500)])

    def handler(request):
        calls.append(request)
        assert request.headers['x-service-token'] == 'caller-token'
        return next(responses)

    client = IdentityClient('http://identity', 'caller-token', cache_seconds=15, transport=httpx.MockTransport(handler), subscribe=False)
    assert client.verify('first-key-' + 'x' * 30, IP)['tenant_id'] == TID
    assert client.verify('first-key-' + 'x' * 30, IP)['tenant_id'] == TID
    assert len(calls) == 1
    with pytest.raises(KeyRejected, match='revoked'):
        client.verify('second-key-' + 'x' * 30, IP)
    with pytest.raises(KeyRejected) as throttled:
        client.verify('third-key-' + 'x' * 30, IP)
    assert throttled.value.reason == 'throttled' and throttled.value.retry_after == '60'
    with pytest.raises(IdentityUnavailable):
        client.verify('fourth-key-' + 'x' * 30, IP)

    def offline(request):
        raise httpx.ConnectError('down')
    down = IdentityClient('http://identity', 'caller-token', cache_seconds=0, transport=httpx.MockTransport(offline), subscribe=False)
    with pytest.raises(IdentityUnavailable):
        down.verify('fifth-key-' + 'x' * 30, IP)


def test_logs_never_contain_workspace_keys(caplog):
    from identity.redaction import install_log_redaction
    install_log_redaction()
    key = keyfmt.new_key('development')[1]
    legacy = secrets.token_hex(32)
    with caplog.at_level(logging.INFO):
        logging.getLogger('cloudsaver.test').info('presented %s and %s', key, legacy)
        logging.getLogger('cloudsaver.test').info('inline ' + key)
    assert key not in caplog.text and legacy not in caplog.text
    assert caplog.text.count('[redacted]') == 3


def compose_blocks(text, parent):
    """Top-level children of a compose section, as {name: [lines]}; avoids a YAML dependency in tests."""
    lines, blocks, inside, name = text.splitlines(), {}, False, None
    for line in lines:
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        if not line.startswith(' '):
            inside, name = line.rstrip() == parent + ':', None
            continue
        if inside and line.startswith('  ') and not line.startswith('   '):
            name = line.strip().rstrip(':')
            blocks[name] = []
        elif inside and name:
            blocks[name].append(line.strip())
    return blocks


def test_platform_db_is_internal_and_portal_is_loopback_only():
    text = (ROOT / 'compose.yaml').read_text()
    services, networks = compose_blocks(text, 'services'), compose_blocks(text, 'networks')
    for name in ('platform-db', 'identity-service', 'platform-redis'):
        assert not any(line.startswith('ports:') for line in services[name]), name
    for name in ('platform-db', 'platform-internal', 'platform-link'):
        assert 'internal: true' in networks[name], name
    def listed(body, field):
        line = next((l for l in body if l.startswith(field + ':')), None)
        return [] if line is None else [v.strip(' \'"') for v in line.split(':', 1)[1].strip(' []').split(',') if v.strip()]

    assert listed(services['platform-db'], 'networks') == ['platform-db']
    members = {name for name, body in services.items() if 'platform-db' in listed(body, 'networks')}
    assert {'platform-db', 'identity-service'} <= members <= {'platform-db', 'identity-migrate', 'identity-service'}
    assert listed(services['platform-portal'], 'ports') == ['127.0.0.1:3100:3100']
    for name, body in services.items():
        for port in listed(body, 'ports'):
            assert port.startswith('127.0.0.1:'), (name, port)


def test_resource_access_validation_and_platform_view(service):
    workspace(service)
    with pytest.raises(IdentityError):
        service.update_platform({'version': 1, 'resource_access': {'unknown': 'x'}}, OPERATOR)
    updated = service.update_platform({'version': 1, 'resource_access': {
        'azure_app_client_id': '55555555-5555-4555-8555-555555555555',
        'aws_hub_role_arn': 'arn:aws:iam::123456789012:role/CloudSaverHub'}}, OPERATOR)
    assert updated['resource_access']['aws_hub_role_arn'].endswith('CloudSaverHub')
    assert updated['resource_access_effective']['aws_hub_role_arn']['source'] == 'platform'


def test_node_images_are_pinned():
    froms = [line for line in (ROOT / 'portal/Dockerfile').read_text().splitlines() if line.startswith('FROM ')]
    assert froms and all('node:24.22.1-alpine' in line for line in froms)


def test_billing_session_flags(monkeypatch):
    from identity.config import billing_session_flags
    monkeypatch.delenv('PLATFORM_BILLING_ENABLED', raising=False)
    monkeypatch.delenv('CLOUDSAVER_BILLING_ENABLED', raising=False)
    assert billing_session_flags() == {'billing_enabled': False, 'billing_provider': 'manual'}
    monkeypatch.setenv('PLATFORM_BILLING_ENABLED', 'true')
    monkeypatch.setenv('PLATFORM_BILLING_PROVIDER', 'manual')
    assert billing_session_flags() == {'billing_enabled': True, 'billing_provider': 'manual'}


def test_list_plans_for_portal(service):
    workspace(service)
    plans = service.list_plans()
    assert len(plans['items']) == 3
    assert plans['items'][0]['entitlements']['max_subscriptions'] >= 2


def test_plan_change_request_flow(service):
    workspace(service)
    created = service.create_plan_change_request(TID, {'requested_plan_code': 'GROWTH', 'requested_by': 'billing@contoso.com'},
                                                 'tenant-service')
    assert created['status'] == 'pending_approval'
    listed = service.list_plan_change_requests('pending_approval', 10)
    assert any(item['id'] == created['id'] for item in listed['items'])
    approved = service.approve_plan_change_request(created['id'], {'version': 1}, OPERATOR)
    assert approved['status'] == 'approved'
    assert service.get_workspace(TID)['plan_tier'] == 'GROWTH'


def test_billing_provider_configured(monkeypatch):
    from identity.billing.providers import billing_provider_configured
    monkeypatch.delenv('PLATFORM_STRIPE_SECRET_KEY', raising=False)
    monkeypatch.delenv('PLATFORM_STRIPE_WEBHOOK_SECRET', raising=False)
    assert billing_provider_configured('manual') is True
    assert billing_provider_configured('stripe') is False
    monkeypatch.setenv('PLATFORM_STRIPE_SECRET_KEY', 'sk_test_x')
    monkeypatch.setenv('PLATFORM_STRIPE_WEBHOOK_SECRET', 'whsec_x')
    assert billing_provider_configured('stripe') is True


def test_subscription_patch_plan_code(service, monkeypatch):
    monkeypatch.setenv('PLATFORM_BILLING_ENABLED', 'true')
    customer = workspace(service)
    now = service.now()
    sub = service.create_customer_subscription(customer['id'], {
        'plan_code': 'STARTER', 'status': 'active', 'current_period_start': now.isoformat(),
        'current_period_end': (now + timedelta(days=30)).isoformat(), 'amount_minor': 0, 'currency': 'USD',
        'interval': 'month',
    }, OPERATOR)
    updated = service.update_subscription(sub['id'], {'version': 1, 'plan_code': 'GROWTH'}, OPERATOR)
    assert updated['plan_code'] == 'GROWTH'


def test_issuance_blocked_without_active_subscription(service, clock, monkeypatch):
    monkeypatch.setenv('PLATFORM_BILLING_ENABLED', 'true')
    customer = workspace(service)
    with pytest.raises(IdentityError, match='active billing subscription'):
        issue(service, clock)
    now = service.now()
    service.create_customer_subscription(customer['id'], {
        'plan_code': 'STARTER', 'status': 'active', 'current_period_start': now.isoformat(),
        'current_period_end': (now + timedelta(days=30)).isoformat(), 'amount_minor': 0, 'currency': 'USD',
        'interval': 'month',
    }, OPERATOR)
    issue(service, clock)


def test_directory_snapshot_includes_plan_block(service, monkeypatch):
    monkeypatch.setenv('PLATFORM_BILLING_ENABLED', 'true')
    customer = workspace(service)
    now = service.now()
    service.create_customer_subscription(customer['id'], {
        'plan_code': 'GROWTH', 'status': 'active', 'current_period_start': now.isoformat(),
        'current_period_end': (now + timedelta(days=30)).isoformat(), 'amount_minor': 0, 'currency': 'USD',
        'interval': 'month',
    }, OPERATOR)
    snap = service.directory_snapshot()
    plan = snap['workspaces'][0]['plan']
    assert plan['code'] == 'GROWTH' and plan['entitlements']['max_resources_per_scan'] == 2500


def test_get_and_cancel_subscription(service, monkeypatch):
    monkeypatch.setenv('PLATFORM_BILLING_ENABLED', 'true')
    customer = workspace(service)
    now = service.now()
    sub = service.create_customer_subscription(customer['id'], {
        'plan_code': 'STARTER', 'status': 'active', 'current_period_start': now.isoformat(),
        'current_period_end': (now + timedelta(days=30)).isoformat(), 'amount_minor': 0, 'currency': 'USD',
        'interval': 'month',
    }, OPERATOR)
    loaded = service.get_subscription(sub['id'])
    assert loaded['id'] == sub['id']
    canceled = service.cancel_subscription(sub['id'], {'version': 1, 'at_period_end': False, 'reason': 'Test'}, OPERATOR)
    assert canceled['status'] == 'canceled'


def test_plan_approval_updates_manual_subscription(service, monkeypatch):
    monkeypatch.setenv('PLATFORM_BILLING_ENABLED', 'true')
    customer = workspace(service)
    now = service.now()
    sub = service.create_customer_subscription(customer['id'], {
        'plan_code': 'STARTER', 'status': 'active', 'current_period_start': now.isoformat(),
        'current_period_end': (now + timedelta(days=30)).isoformat(), 'amount_minor': 0, 'currency': 'USD',
        'interval': 'month',
    }, OPERATOR)
    created = service.create_plan_change_request(TID, {'requested_plan_code': 'GROWTH', 'requested_by': 'billing@contoso.com'},
                                                 'tenant-service')
    service.approve_plan_change_request(created['id'], {'version': 1}, OPERATOR)
    subs = service.list_customer_subscriptions(customer['id'])
    assert subs['current']['plan_code'] == 'GROWTH'
    assert service.get_workspace(TID)['plan_tier'] == 'GROWTH'


def test_bootstrap_claim_and_customer_admin_key(service, clock):
    customer = workspace(service)
    assert customer['claim_status'] == 'pending'
    bootstrap = service.issue_bootstrap_key(customer['id'], {'tenant_id': TID}, OPERATOR)
    secret = bootstrap['secret']
    assert bootstrap['key']['purpose'] == 'bootstrap'
    assert service.verify(secret, IP, 'gateway')['valid'] is False
    claimed = service.claim_customer({
        'key': secret,
        'idp_issuer': 'https://login.example.com',
        'idp_subject': 'owner-subject',
        'display_name': 'Ada Owner',
        'email': 'ada@contoso.com',
    })
    assert claimed['valid'] and claimed['customer_id'] == customer['id']
    owner_key = claimed['secret']
    grant = service.verify(owner_key, IP, 'gateway')
    assert grant['valid'] and grant['customer_roles'] == ['CustomerOwner']
    assert grant['subject_type'] == 'user'
    users = service.list_customer_users(customer['id'], grant)
    assert len(users['items']) == 1 and users['items'][0]['display_name'] == 'Ada Owner'
    refreshed = service.get_customer(customer['id'])
    assert refreshed['customer']['claim_status'] == 'claimed'


def claimed_owner(service):
    customer = workspace(service)
    secret = service.issue_bootstrap_key(customer['id'], {'tenant_id': TID}, OPERATOR)['secret']
    claimed = service.claim_customer({'key': secret, 'idp_issuer': 'https://login.example.com',
                                      'idp_subject': 'owner', 'display_name': 'Ada Owner'})
    return customer, service.verify(claimed['secret'], IP, 'gateway'), claimed['secret']


def invite_member(service, grant, subject, roles=('Viewer',), role='CustomerAdmin'):
    user = service.invite_customer_user(None, {'idp_issuer': 'https://login.example.com', 'idp_subject': subject,
                                               'display_name': subject.title(), 'role': role}, grant)
    service.update_workspace_member(TID, user['user_id'], {'version': 0, 'roles': list(roles)}, grant)
    return user


def test_bootstrap_key_is_single_use_and_lifetime_is_capped(service, clock):
    customer = workspace(service)
    with pytest.raises(IdentityError, match='72 hours'):
        service.issue_bootstrap_key(customer['id'], {'tenant_id': TID,
                                                     'expires_at': (clock() + timedelta(hours=80)).isoformat()}, OPERATOR)
    secret = service.issue_bootstrap_key(customer['id'], {'tenant_id': TID}, OPERATOR)['secret']
    with pytest.raises(Conflict):
        service.issue_bootstrap_key(customer['id'], {'tenant_id': TID}, OPERATOR)
    claim = {'key': secret, 'idp_issuer': 'https://login.example.com', 'idp_subject': 'a', 'display_name': 'A'}
    assert service.claim_customer(claim)['valid']
    assert service.claim_customer(dict(claim, idp_subject='b'))['valid'] is False
    with pytest.raises(Conflict, match='already claimed'):
        service.issue_bootstrap_key(customer['id'], {'tenant_id': TID}, OPERATOR)


def test_customer_admin_cannot_escalate_or_act_on_other_customers(service, clock):
    customer, owner, _ = claimed_owner(service)
    admin = invite_member(service, owner, 'grace', roles=('Viewer',))
    key = service.issue_customer_workspace_key(TID, {'name': 'Grace', 'roles': ['Viewer'], 'all_providers': True,
                                                     'subject_user_id': admin['user_id'],
                                                     'expires_at': (clock() + timedelta(days=10)).isoformat()}, owner)
    grace = service.verify(key['secret'], IP, 'gateway')
    assert grace['customer_roles'] == ['CustomerAdmin']
    with pytest.raises(IdentityError) as denied:
        service.issue_customer_workspace_key(TID, {'name': 'Escalate', 'roles': ['TenantAdmin'], 'all_providers': True,
                                                   'expires_at': (clock() + timedelta(days=10)).isoformat()}, grace)
    assert denied.value.status == 403
    with pytest.raises(IdentityError) as denied:
        service.update_workspace_member(TID, admin['user_id'], {'version': 1, 'roles': ['TenantAdmin']}, grace)
    assert denied.value.status == 403
    with pytest.raises(IdentityError, match='Only the owner'):
        service.transfer_ownership(None, {'user_id': owner['subject_id']}, grace)
    with pytest.raises(IdentityError):
        service.list_customer_users('22222222-2222-4222-8222-222222222222', grace)
    auditor = invite_member(service, owner, 'audit', role='CustomerAuditor')
    audit_key = service.issue_customer_workspace_key(TID, {'name': 'Audit', 'roles': ['Viewer'], 'all_providers': True,
                                                           'subject_user_id': auditor['user_id'],
                                                           'expires_at': (clock() + timedelta(days=10)).isoformat()}, owner)
    audit_grant = service.verify(audit_key['secret'], IP, 'gateway')
    assert len(service.list_customer_users(None, audit_grant)['items']) == 3
    with pytest.raises(IdentityError) as denied:
        service.create_service_account(None, {'name': 'CI'}, audit_grant)
    assert denied.value.status == 403


def test_suspending_a_user_revokes_keys_and_verify_rejects_them(service, clock):
    customer, owner, _ = claimed_owner(service)
    member = invite_member(service, owner, 'lin')
    key = service.issue_customer_workspace_key(TID, {'name': 'Lin', 'roles': ['Viewer'], 'all_providers': True,
                                                     'subject_user_id': member['user_id'],
                                                     'expires_at': (clock() + timedelta(days=10)).isoformat()}, owner)
    assert service.verify(key['secret'], IP, 'gateway')['valid']
    invite_member(service, owner, 'other')
    other = service.verify(issue_for(service, clock, owner)['secret'], IP, 'gateway')
    with pytest.raises(IdentityError, match='Transfer ownership'):
        service.set_customer_user_status(None, owner['subject_id'], {}, 'suspended', other)
    with pytest.raises(IdentityError, match='your own access'):
        service.set_customer_user_status(None, owner['subject_id'], {}, 'suspended', owner)
    service.set_customer_user_status(None, member['user_id'], {'reason': 'Left the team'}, 'suspended', owner)
    assert service.verify(key['secret'], IP, 'gateway') == {'valid': False, 'reason': 'revoked'}
    assert service.get_key(key['key']['key_id'])['status'] == 'revoked'
    actions = [e['action'] for e in service.customer_audit(owner)['items']]
    assert 'user_suspended' in actions and 'user_invited' in actions


def issue_for(service, clock, owner):
    users = service.list_customer_users(None, owner)['items']
    other = next(u for u in users if u['display_name'] == 'Other')
    return service.issue_customer_workspace_key(TID, {'name': 'Other', 'roles': ['Viewer'], 'all_providers': True,
                                                      'subject_user_id': other['user_id'],
                                                      'expires_at': (clock() + timedelta(days=10)).isoformat()}, owner)


def test_removing_workspace_access_and_customer_key_lifecycle(service, clock):
    customer, owner, _ = claimed_owner(service)
    member = invite_member(service, owner, 'kim')
    account = service.create_service_account(None, {'name': 'CI pipeline'}, owner)
    ci = service.issue_customer_workspace_key(TID, {'name': 'CI', 'roles': ['Viewer'], 'all_providers': True,
                                                    'service_account_id': account['service_account_id'],
                                                    'expires_at': (clock() + timedelta(days=10)).isoformat()}, owner)
    rotated = service.rotate_customer_key(ci['key']['key_id'], {'overlap_hours': 0}, owner)
    assert rotated['key']['subject_type'] == 'service_account'
    service.revoke_customer_key(rotated['key']['key_id'], {}, owner)
    assert service.verify(rotated['secret'], IP, 'gateway')['valid'] is False
    operator_key = issue(service, clock)
    with pytest.raises(IdentityError, match='platform operator'):
        service.revoke_customer_key(operator_key['key']['key_id'], {}, owner)
    kim = service.issue_customer_workspace_key(TID, {'name': 'Kim', 'roles': ['Viewer'], 'all_providers': True,
                                                     'subject_user_id': member['user_id'],
                                                     'expires_at': (clock() + timedelta(days=10)).isoformat()}, owner)
    version = next(m['version'] for m in service.list_workspace_members(TID, owner)['items']
                   if m['user_id'] == member['user_id'])
    service.remove_workspace_member(TID, member['user_id'], {'version': version}, owner)
    assert service.verify(kim['secret'], IP, 'gateway')['valid'] is False
    second = service.create_service_account(None, {'name': 'Nightly'}, owner)
    service.update_service_account(second['service_account_id'], {'version': 1, 'status': 'suspended'}, owner)
    csv_text = service.export_customer_access(owner)
    assert csv_text.startswith('record,') and 'Ada Owner' in csv_text and 'cs_' not in csv_text


def test_ownership_transfer_keeps_one_owner(service, clock):
    customer, owner, _ = claimed_owner(service)
    member = invite_member(service, owner, 'noor')
    service.transfer_ownership(None, {'user_id': member['user_id']}, owner)
    roles = {u['display_name']: u['customer_role'] for u in service.list_customer_users(None, owner)['items']}
    assert roles == {'Ada Owner': 'CustomerAdmin', 'Noor': 'CustomerOwner'}
    assert 'ownership_transferred' in [e['action'] for e in service.customer_audit(owner)['items']]


def test_scope_restricted_keys_are_validated_and_returned_by_verify(service, clock):
    workspace(service)
    with pytest.raises(IdentityError, match='configured for this workspace'):
        issue(service, clock, scope_restrictions={'azure': ['44444444-4444-4444-8444-444444444444']})
    with pytest.raises(IdentityError, match='providers this key includes'):
        issue(service, clock, all_providers=False, allowed_providers=['aws'], scope_restrictions={'azure': [SID]})
    issued = issue(service, clock, scope_restrictions={'aws': ['123456789012']})
    assert issued['key']['scope_restrictions'] == {'aws': ['123456789012']}
    grant = service.verify(issued['secret'], IP, 'gateway')
    assert grant['scope_restrictions'] == {'aws': ['123456789012']}
    assert grant['allowed_providers'] == ['azure', 'aws']
    updated = service.update_key(issued['key']['key_id'], {'version': 1, 'scope_restrictions': None}, OPERATOR)
    assert updated['scope_restrictions'] is None


def test_customer_limits(service, clock, monkeypatch):
    import identity.customer.admin as admin
    customer, owner, _ = claimed_owner(service)
    monkeypatch.setattr(admin, 'MAX_SERVICE_ACCOUNTS', 1)
    monkeypatch.setattr(admin, 'MAX_INVITES_PER_DAY', 1)
    service.create_service_account(None, {'name': 'One'}, owner)
    with pytest.raises(Conflict, match='at most 1 service'):
        service.create_service_account(None, {'name': 'Two'}, owner)
    invite_member(service, owner, 'first')
    with pytest.raises(IdentityError) as limited:
        invite_member(service, owner, 'second')
    assert limited.value.status == 429


def test_workspace_admin_key_can_add_users_to_its_workspace(service, clock):
    workspace(service)
    admin = service.customer_context_from_key(issue(service, clock, roles=['TenantAdmin'])['secret'], IP, 'gateway')
    viewer = issue(service, clock, roles=['Viewer'])['secret']
    with pytest.raises(IdentityError) as denied:
        service.customer_context_from_key(viewer, IP, 'gateway')
    assert denied.value.status == 403

    member = invite_member(service, admin, 'lee', roles=('BillingAdmin',))
    assert [m['user_id'] for m in service.list_workspace_members(TID, admin)['items']] == [member['user_id']]
    key = service.issue_customer_workspace_key(TID, {'name': 'Lee', 'roles': ['BillingAdmin'], 'all_providers': True,
                                                     'subject_user_id': member['user_id'],
                                                     'expires_at': (clock() + timedelta(days=10)).isoformat()}, admin)
    assert service.verify(key['secret'], IP, 'gateway')['subject_id'] == member['user_id']

    with pytest.raises(IdentityError, match='Choose the user'):
        service.issue_customer_workspace_key(TID, {'name': 'Self', 'roles': ['Viewer'], 'all_providers': True,
                                                   'expires_at': (clock() + timedelta(days=10)).isoformat()}, admin)
    with pytest.raises(IdentityError) as suspend:
        service.set_customer_user_status(None, member['user_id'], {}, 'suspended', admin)
    assert suspend.value.status == 403
    with pytest.raises(NotFound):
        service.list_workspace_members('33333333-3333-4333-8333-333333333333', admin)


def test_workspace_analysis_rules_default_enabled_and_overridable(service, clock):
    workspace(service)
    catalog = service.list_analysis_rules()['items']
    assert len(catalog) > 0 and all(r['status'] == 'published' for r in catalog)
    effective = service.list_workspace_analysis_rules(TID)
    assert effective['tenant_id'] == TID
    assert all(r['enabled'] is True and r['override_version'] is None for r in effective['items'])
    rule_id = catalog[0]['id']
    updated = service.update_workspace_analysis_rules(
        TID, {'version': 1, 'rules': [{'rule_id': rule_id, 'enabled': False, 'unavailable_reason': 'No collector evidence'}]}, OPERATOR)
    row = next(r for r in updated['items'] if r['id'] == rule_id)
    assert row['enabled'] is False and row['unavailable_reason'] == 'No collector evidence'
    live = service.effective_analysis_rules(TID)
    assert rule_id not in live['enabled_rule_ids']
    with pytest.raises(IdentityError, match='published rule from the catalog'):
        service.update_workspace_analysis_rules(TID, {'version': 1, 'rules': [{'rule_id': 'bogus'}]}, OPERATOR)
    with pytest.raises(StaleVersion):
        service.update_workspace_analysis_rules(TID, {'version': 2, 'rules': [{'rule_id': rule_id, 'enabled': True}]}, OPERATOR)


def test_knowledge_publication_lifecycle_and_pagination(service, clock):
    created = [service.create_knowledge_publication(
        {'title': f'Pattern {i}', 'summary': 'Observed across fleet', 'body': 'Generalized guidance.'}, OPERATOR)
        for i in range(3)]
    page = service.list_knowledge_publications(limit=2)
    assert len(page['items']) == 2 and page['next_cursor'] == '2'
    rest = service.list_knowledge_publications(limit=2, cursor=page['next_cursor'])
    assert len(rest['items']) == 1 and rest['next_cursor'] is None
    pub = created[0]
    updated = service.update_knowledge_publication(pub['id'], {'version': 1, 'status': 'published', 'quality_score': 80}, OPERATOR)
    assert updated['status'] == 'published' and updated['quality_score'] == 80
    with pytest.raises(StaleVersion):
        service.update_knowledge_publication(pub['id'], {'version': 1, 'status': 'deprecated'}, OPERATOR)
    with pytest.raises(IdentityError, match='valid publication status'):
        service.update_knowledge_publication(pub['id'], {'version': 2, 'status': 'bogus'}, OPERATOR)
    with pytest.raises(NotFound):
        service.update_knowledge_publication('00000000-0000-0000-0000-000000000000', {'version': 1, 'status': 'published'}, OPERATOR)
