import json
from unittest.mock import MagicMock

import httpx
import pytest

from app.domain.pricing import retail_cache
from app.pricing import AzurePricingClient


@pytest.fixture(autouse=True)
def _reset_retail_cache(monkeypatch):
    monkeypatch.delenv('REDIS_URL', raising=False)
    monkeypatch.delenv('CLOUDSAVER_PROVIDER_REDIS_URL', raising=False)
    retail_cache.reset_shared_cache()
    yield
    retail_cache.reset_shared_cache()


def test_stable_key_hashes_filter_fields():
    filters = retail_cache.azure_discover_filters(
        region='eastus',
        product_name='Public IP',
        sku_name='Standard',
        meter_name='Static IP',
        unit_of_measure='1 Hour',
    )
    key = retail_cache.stable_key(provider='azure', region='eastus', op='discover', filters=filters)
    assert key.startswith('azure:eastus:discover:')
    assert key == retail_cache.stable_key(provider='azure', region='eastus', op='discover', filters=dict(filters))


def test_local_get_set_roundtrip():
    key = 'azure:eastus:discover:test'
    assert retail_cache.get(key) is retail_cache.CACHE_MISS
    payload = dict(region='eastus', meter_id='m1')
    retail_cache.set(key, payload)
    assert retail_cache.get(key) == payload
    retail_cache.set(key, None)
    assert retail_cache.get(key) is None


def test_ttl_from_env(monkeypatch):
    monkeypatch.setenv('CLOUDSAVER_RETAIL_CACHE_TTL_SECONDS', '3600')
    retail_cache.reset_shared_cache()
    assert retail_cache.ttl_seconds() == 3600
    monkeypatch.setenv('CLOUDSAVER_RETAIL_CACHE_TTL_SECONDS', 'invalid')
    assert retail_cache.ttl_seconds() == retail_cache.DEFAULT_TTL_SECONDS


def test_redis_get_set(monkeypatch):
    store = {}

    class FakeRedis:
        def __init__(self, *args, **kwargs):
            pass

        def get(self, key):
            return store.get(key)

        def setex(self, key, ttl, value):
            store[key] = value
            store[f'ttl:{key}'] = ttl

    monkeypatch.setenv('REDIS_URL', 'redis://127.0.0.1:6379/0')
    import redis

    monkeypatch.setattr(redis.Redis, 'from_url', FakeRedis)
    retail_cache.reset_shared_cache()

    logical = retail_cache.stable_key(
        provider='azure',
        region='eastus',
        op='discover',
        filters=retail_cache.azure_discover_filters(
            region='eastus',
            product_name='P',
            sku_name='S',
            meter_name='M',
            unit_of_measure='1 Hour',
        ),
    )
    retail_cache.set(logical, {'meter_id': 'abc'})
    assert retail_cache.get(logical) == {'meter_id': 'abc'}
    storage = retail_cache._storage_key(logical)
    assert json.loads(store[storage]) == {'v': {'meter_id': 'abc'}}


def test_redis_failure_falls_back_to_memory(monkeypatch):
    monkeypatch.setenv('REDIS_URL', 'redis://127.0.0.1:6379/0')

    class BrokenRedis:
        def __init__(self, *args, **kwargs):
            raise ConnectionError('down')

    import redis

    monkeypatch.setattr(redis.Redis, 'from_url', BrokenRedis)
    retail_cache.reset_shared_cache()

    key = 'azure:westus:price:fallback'
    retail_cache.set(key, {'unitPrice': 1.0})
    assert retail_cache.get(key) == {'unitPrice': 1.0}


def test_discover_meter_uses_cache_without_second_http_call():
    calls = []

    def handler(request):
        calls.append(request)
        item = dict(
            armRegionName='eastus',
            skuName='Standard',
            meterName='Static IP',
            productName='Public IP',
            meterId='meter-1',
            type='Consumption',
            currencyCode='USD',
            unitOfMeasure='1 Hour',
            tierMinimumUnits=0,
            isPrimaryMeterRegion=True,
            effectiveStartDate='2026-01-01T00:00:00Z',
            unitPrice=0.005,
        )
        return httpx.Response(200, json={'Items': [item], 'NextPageLink': None})

    api = AzurePricingClient(transport=httpx.MockTransport(handler))
    kwargs = dict(
        region='eastus',
        product_name='Public IP',
        sku_name='Standard',
        meter_name='Static IP',
        unit_of_measure='1 Hour',
    )
    first = api.discover_meter(**kwargs)
    second = api.discover_meter(**kwargs)
    assert first == second
    assert first['meter_id'] == 'meter-1'
    assert len(calls) == 1

    other = AzurePricingClient(transport=httpx.MockTransport(handler))
    assert other.discover_meter(**kwargs) == first
    assert len(calls) == 1


def test_fetch_price_uses_shared_cache():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            200,
            json={
                'Items': [
                    dict(
                        armRegionName='eastus',
                        skuName='Standard',
                        meterName='Static IP',
                        productName='Public IP',
                        meterId='meter-1',
                        type='Consumption',
                        currencyCode='USD',
                        unitOfMeasure='1 Hour',
                        tierMinimumUnits=0,
                        isPrimaryMeterRegion=True,
                        effectiveStartDate='2026-01-01T00:00:00Z',
                        unitPrice=0.005,
                    )
                ],
                'NextPageLink': None,
            },
        )

    evidence = dict(
        region='eastus',
        sku_name='Standard',
        meter_name='Static IP',
        product_name='Public IP',
        meter_id='meter-1',
        unit_of_measure='1 Hour',
    )
    transport = httpx.MockTransport(handler)
    first_client = AzurePricingClient(transport=transport)
    second_client = AzurePricingClient(transport=transport)

    assert first_client.fetch_price(evidence)['unitPrice'] == 0.005
    assert second_client.fetch_price(evidence)['unitPrice'] == 0.005
    assert len(calls) == 1


def test_mock_redis_client_used_when_available(monkeypatch):
    client = MagicMock()
    client.get.return_value = None
    monkeypatch.setenv('REDIS_URL', 'redis://127.0.0.1:6379/0')
    import redis

    monkeypatch.setattr(redis.Redis, 'from_url', lambda *args, **kwargs: client)
    retail_cache.reset_shared_cache()

    key = 'azure:eastus:discover:mock'
    assert retail_cache.get(key) is retail_cache.CACHE_MISS
    retail_cache.set(key, {'ok': True})
    client.setex.assert_called_once()
    args = client.setex.call_args[0]
    assert args[1] == retail_cache.ttl_seconds()
