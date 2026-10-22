import os
from threading import Event
from uuid import uuid4

import pytest
import redis

from workers.tasks import RedisLease
from workers.lease import LeaseHeartbeat, LeaseLost


@pytest.fixture
def leases():
    url = os.getenv('CLOUDSAVER_TEST_REDIS_URL')
    if not url:
        pytest.skip('Use scripts/test_postgres.py for disposable Redis integration')
    a, b = RedisLease(url,ttl=2), RedisLease(url,ttl=2)
    try:
        yield a,b
    finally:
        a.close();b.close()


def test_real_redis_exclusion_owner_renewal_and_stale_release(leases):
    a,b = leases
    tenant = str(uuid4())
    assert a.acquire(tenant,'owner-a')
    assert not b.acquire(tenant,'owner-b')
    assert not b.renew(tenant,'owner-b')
    a.client.delete('cloudsaver:scan-lease:'+tenant)  # Simulate expiry/recovery.
    assert b.acquire(tenant,'owner-b')
    assert not a.renew(tenant,'owner-a')
    a.release(tenant,'owner-a')
    assert b.renew(tenant,'owner-b')
    b.release(tenant,'owner-b')


def test_heartbeat_detects_lost_lease_and_redis_failure(leases,monkeypatch):
    a,b = leases
    tenant = str(uuid4())
    assert a.acquire(tenant,'owner-a')
    heartbeat = LeaseHeartbeat(a,tenant,'owner-a',interval=0.03)
    heartbeat.start()
    try:
        heartbeat.ensure_owned()
        a.client.delete('cloudsaver:scan-lease:'+tenant)
        assert b.acquire(tenant,'owner-b')
        assert heartbeat.lost.wait(1)
        with pytest.raises(LeaseLost):
            heartbeat.ensure_owned()
        assert b.renew(tenant,'owner-b')
    finally:
        heartbeat.stop();b.release(tenant,'owner-b')
