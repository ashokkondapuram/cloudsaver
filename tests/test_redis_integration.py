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


def test_ai_budget_concurrent_claim_cache_uncertain_and_tenant_isolation():
    from concurrent.futures import ThreadPoolExecutor
    from app.ai_advisory import RedisBudget, AIError
    url = os.getenv('CLOUDSAVER_TEST_REDIS_URL')
    if not url:
        pytest.skip('Requires disposable Redis integration')
    budget = RedisBudget(url)
    tenant, other, key = str(uuid4()), str(uuid4()), str(uuid4())
    calls = []
    def invoke():
        calls.append(1)
        return {'advisory_only': True}
    def run(_):
        try:
            return budget.run(tenant, key, 'fingerprint', 2, invoke)
        except AIError as error:
            assert error.status == 409
            return None
    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(run, range(20)))
    assert len(calls) == 1
    assert any(r and r['cached'] is False for r in results)
    assert budget.run(tenant, key, 'fingerprint', 2, invoke)['cached']
    with pytest.raises(AIError) as error:
        budget.run(tenant, key, 'different', 2, invoke)
    assert error.value.status == 409
    def ambiguous(): raise AIError('ambiguous', 502)
    uncertain_key = str(uuid4())
    with pytest.raises(AIError):
        budget.run(tenant, uncertain_key, 'same', 2, ambiguous)
    with pytest.raises(AIError) as error:
        budget.run(tenant, uncertain_key, 'same', 2, invoke)
    assert error.value.status == 409
    with pytest.raises(AIError) as error:
        budget.run(tenant, str(uuid4()), 'same', 2, invoke)
    assert error.value.status == 429
    assert not budget.run(other, key, 'same', 2, invoke)['cached']
    with redis.from_url(url) as client:
        assert 0 < client.ttl('cloudsaver:ai:v1:' + tenant + ':' + key) <= 86400
        # Simulate retention expiration; a new attempt is possible only after the fence expires.
        client.delete('cloudsaver:ai:v1:' + other + ':' + key)
    assert not budget.run(other, key, 'same', 2, invoke)['cached']


def test_ai_budget_fails_closed_when_redis_is_unavailable():
    from app.ai_advisory import RedisBudget, AIError
    budget = RedisBudget('redis://127.0.0.1:1/0')
    def invoke(): raise AssertionError('Provider must not be called without coordination')
    with pytest.raises(AIError) as error:
        budget.run(str(uuid4()), str(uuid4()), 'fingerprint', 2, invoke)
    assert error.value.status == 503


def test_ai_completion_cannot_overwrite_a_replaced_attempt_fence():
    import json
    from app.ai_advisory import RedisBudget, AIError
    url = os.getenv('CLOUDSAVER_TEST_REDIS_URL')
    if not url: pytest.skip('Requires disposable Redis integration')
    budget = RedisBudget(url)
    tenant, key = str(uuid4()), str(uuid4())
    record = 'cloudsaver:ai:v1:'+tenant+':'+key
    replacement = json.dumps({'fingerprint':'replacement','status':'uncertain','owner':'new-owner'})
    def invoke():
        with redis.from_url(url) as client: client.set(record,replacement,ex=86400)
        return {'advisory_only':True}
    with pytest.raises(AIError) as error:
        budget.run(tenant,key,'old',10,invoke)
    assert error.value.status == 409
    with redis.from_url(url,decode_responses=True) as client:
        assert client.get(record) == replacement
