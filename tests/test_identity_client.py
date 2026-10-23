import logging
import secrets

import httpx
import pytest

from app.identity_client import (EventPoller, GrantCache, IdentityClient, IdentityUnavailable, KeyRejected,
                                 MAX_CACHE_SECONDS)
from tests.identity_fake import TID, FakeIdentity, fixture


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def test_cache_expires_caps_ttl_and_evicts_by_key_or_tenant():
    clock = Clock()
    cache = GrantCache(60, size=2, clock=clock)
    assert cache.ttl == MAX_CACHE_SECONDS
    cache.put('a', {'key_id': 'k1', 'tenant_id': 't1', 'cache_ttl_seconds': 10})
    cache.put('b', {'key_id': 'k2', 'tenant_id': 't2'})
    clock.now = 11
    assert cache.get('a') is None and cache.get('b') is not None
    cache.put('c', {'key_id': 'k3', 'tenant_id': 't2'})
    cache.evict({'key_id': None, 'tenant_id': 't2'})
    assert cache.get('b') is None and cache.get('c') is None
    cache.put('d', {'key_id': 'k4', 'tenant_id': 't3'})
    cache.evict({'key_id': 'k4', 'tenant_id': None})
    assert cache.get('d') is None
    for name in 'xyz':
        cache.put(name, {'key_id': name})
    assert cache.get('x') is None and cache.get('z') is not None


def test_disabled_cache_neither_stores_nor_serves():
    cache = GrantCache(15)
    cache.put('a', {'key_id': 'k'})
    cache.enabled = False
    assert cache.get('a') is None
    cache.put('b', {'key_id': 'k'})
    cache.enabled = True
    assert cache.get('b') is None


def test_client_requires_a_token_and_a_bounded_cache(monkeypatch):
    monkeypatch.delenv('CLOUDSAVER_IDENTITY_TOKEN', raising=False)
    with pytest.raises(RuntimeError):
        IdentityClient('http://identity', subscribe=False)
    with pytest.raises(ValueError):
        IdentityClient('http://identity', 'token', cache_seconds=31, subscribe=False)
    monkeypatch.setenv('CLOUDSAVER_IDENTITY_TOKEN', secrets.token_urlsafe(32))
    monkeypatch.setenv('CLOUDSAVER_IDENTITY_URL', 'http://identity.example:8005/')
    client = IdentityClient(subscribe=False)
    assert client.base_url == 'http://identity.example:8005' and client.cache.ttl == 15


def test_verify_caches_valid_grants_and_maps_failures():
    fake = FakeIdentity()
    client = fake.client(cache_seconds=15)
    key = 'cs_test_0example0000_' + secrets.token_urlsafe(32)
    assert client.verify(key, '203.0.113.7')['key_id'] == '0example0000'
    client.verify(key, '203.0.113.7')
    assert len(fake.requests) == 1
    fake.verify = fixture('verify_invalid')
    with pytest.raises(KeyRejected) as rejected:
        client.verify('another-' + key, None)
    assert rejected.value.reason == 'revoked'
    fake.verify_status = 429
    with pytest.raises(KeyRejected) as throttled:
        client.verify('third-' + key, None)
    assert throttled.value.reason == 'throttled'
    fake.verify_status = 503
    with pytest.raises(IdentityUnavailable):
        client.verify('fourth-' + key, None)


def test_wrong_service_token_fails_closed():
    fake = FakeIdentity()
    client = IdentityClient('http://identity', 'not-the-caller-token', cache_seconds=0, transport=fake.transport,
                            subscribe=False)
    with pytest.raises(IdentityUnavailable):
        client.verify('cs_test_0example0000_' + secrets.token_urlsafe(32), None)


def test_poller_starts_at_head_then_evicts_and_notifies():
    fake = FakeIdentity()
    client = fake.client(cache_seconds=15)
    woken = []
    poller = EventPoller(client, client.cache, lambda: woken.append(True))
    assert client.cache.enabled is False
    poller.poll_once()
    assert 'after' not in fake.requests[-1].url.params
    assert poller.after == 102 and client.cache.enabled is True and woken == []
    client.cache.put('revoked', {'key_id': '0example0000', 'tenant_id': None})
    client.cache.put('tenant', {'key_id': 'other', 'tenant_id': TID})
    client.cache.put('kept', {'key_id': 'other', 'tenant_id': '99999999-9999-4999-8999-999999999999'})
    poller.poll_once()
    params = fake.requests[-1].url.params
    assert params['after'] == '102' and params['wait'] == '25'
    assert client.cache.get('revoked') is None and client.cache.get('tenant') is None
    assert client.cache.get('kept') is not None and woken == [True]


def test_poller_flushes_and_restarts_from_head_on_410():
    fake = FakeIdentity()
    client = fake.client(cache_seconds=15)
    woken = []
    poller = EventPoller(client, client.cache, lambda: woken.append(True))
    poller.poll_once()
    client.cache.put('grant', {'key_id': 'k', 'tenant_id': TID})
    fake.events_status = 410
    poller.poll_once()
    assert poller.after is None and client.cache.enabled is False and client.cache.items == {} and woken == [True]
    fake.events_status = 200
    poller.poll_once()
    assert poller.after == 102 and client.cache.enabled is True


def test_poller_failures_raise_so_run_pauses_caching():
    fake = FakeIdentity()
    client = fake.client(cache_seconds=15)
    poller = EventPoller(client, client.cache)
    poller.poll_once()
    fake.events_status = 500
    with pytest.raises(IdentityUnavailable):
        poller.poll_once()


def test_run_loop_disables_the_cache_while_identity_is_down():
    calls = []

    class Down:
        def get(self, path, params=None, timeout=None):
            calls.append(path)
            poller.stop()
            raise IdentityUnavailable()
    cache = GrantCache(15)
    poller = EventPoller(Down(), cache)
    cache.enabled = True
    cache.put('grant', {'key_id': 'k'})
    poller.run()
    assert calls == ['/internal/v1/events'] and cache.enabled is False and cache.items == {}


def test_subscribed_client_starts_and_stops_its_poller():
    fake = FakeIdentity()
    fake.events_status = 503
    client = IdentityClient('http://identity', fake.token, cache_seconds=0, transport=fake.transport)
    try:
        assert client.poller.is_alive() and client.poller.daemon
    finally:
        client.close()
    assert client.poller.stopped.is_set()


def test_log_redaction_hides_keys_and_tokens(caplog):
    from app.runtime import install_log_redaction, redact
    key = 'cs_live_0example0000_' + 'A1b2' * 10 + 'xyz'
    token = secrets.token_urlsafe(32)
    digest = 'ab' * 32
    text = f'key={key} token={token} digest={digest} tenant={TID}'
    cleaned = redact(text)
    assert key not in cleaned and token not in cleaned and digest not in cleaned and TID in cleaned
    install_log_redaction()
    with caplog.at_level(logging.WARNING, logger='cloudsaver.test'):
        logging.getLogger('cloudsaver.test').warning('verify failed for %s', key)
    assert key not in caplog.text


def test_runtime_does_not_import_platform_code():
    import app.runtime
    source = open(app.runtime.__file__).read()
    assert 'from identity' not in source and 'import identity' not in source
