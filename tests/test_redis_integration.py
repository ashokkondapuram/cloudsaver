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


def test_sliding_rate_limit_is_atomic_tenant_scoped_and_expires(monkeypatch):
    import asyncio
    from fastapi import HTTPException
    from services.gateway import RedisLimiter
    url = os.getenv('CLOUDSAVER_TEST_REDIS_URL')
    if not url:
        pytest.skip('Requires disposable Redis integration')
    monkeypatch.setenv('REDIS_URL', url)
    async def exercise():
        limiter = RedisLimiter()
        tenant, other = str(uuid4()), str(uuid4())
        key = 'cloudsaver:rate:v2:' + tenant
        try:
            results = await asyncio.gather(*(limiter.check(tenant) for _ in range(125)), return_exceptions=True)
            rejected = [result for result in results if isinstance(result, HTTPException)]
            assert len(rejected) == 5
            assert all(result.status_code == 429 and 1 <= int(result.headers['Retry-After']) <= 60 for result in rejected)
            assert await limiter.client.zcard(key) == 120
            assert 0 < await limiter.client.ttl(key) <= 60
            await limiter.check(other)
            # Advance all entries outside the window without a real-time sleep.
            now = await limiter.client.time()
            old = now[0] * 1000 + now[1] // 1000 - 60001
            members = await limiter.client.zrange(key, 0, -1)
            await limiter.client.zadd(key, {member: old for member in members})
            await limiter.check(tenant)
            assert await limiter.client.zcard(key) == 1
        finally:
            await limiter.client.aclose()
    asyncio.run(exercise())
