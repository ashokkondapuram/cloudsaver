import hashlib
import logging
import secrets
from datetime import timedelta
from pathlib import Path

import httpx
import pytest

from identity import keys as keyfmt
from identity.client import GrantCache, IdentityClient, IdentityUnavailable, KeyRejected
from identity.domain import Conflict, IdentityError, Throttled, utcnow
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
    from app.runtime import install_log_redaction
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


def test_token_db_is_internal_and_portal_is_loopback_only():
    text = (ROOT / 'compose.yaml').read_text()
    services, networks = compose_blocks(text, 'services'), compose_blocks(text, 'networks')
    assert not any(line.startswith('ports:') for line in services['token-db'])
    assert not any(line.startswith('ports:') for line in services['identity-service'])
    assert 'internal: true' in networks['identity-db'] and 'internal: true' in networks['portal']
    def listed(body, field):
        line = next((l for l in body if l.startswith(field + ':')), None)
        return [] if line is None else [v.strip(' \'"') for v in line.split(':', 1)[1].strip(' []').split(',') if v.strip()]

    assert listed(services['token-db'], 'networks') == ['identity-db']
    members = {name for name, body in services.items() if 'identity-db' in listed(body, 'networks')}
    assert {'token-db', 'identity-service'} <= members <= {'token-db', 'identity-migrate', 'identity-service', 'identity-import'}
    assert listed(services['platform-portal'], 'ports') == ['127.0.0.1:3100:3100']
    for name, body in services.items():
        for port in listed(body, 'ports'):
            assert port.startswith('127.0.0.1:'), (name, port)


def test_node_images_are_pinned():
    for path in ('web-dashboard/Dockerfile', 'platform-portal/Dockerfile'):
        froms = [line for line in (ROOT / path).read_text().splitlines() if line.startswith('FROM ')]
        assert froms and all('node:24.22.1-alpine' in line for line in froms), path
    assert (ROOT / '.nvmrc').read_text().strip() == '24.22.1'
