"""TTL cache for retail price API payloads (Azure today; AWS/GCP later)."""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from functools import lru_cache

DEFAULT_TTL_SECONDS = 86400
_PREFIX = 'cloudsaver:retail:v1:'


class CacheMiss:
    """Sentinel returned when a key is not present."""


CACHE_MISS = CacheMiss()


def ttl_seconds() -> int:
    raw = os.getenv('CLOUDSAVER_RETAIL_CACHE_TTL_SECONDS', str(DEFAULT_TTL_SECONDS))
    try:
        value = int(raw)
        if 1 <= value <= 7 * 86400:
            return value
    except (TypeError, ValueError):
        pass
    return DEFAULT_TTL_SECONDS


def _redis_url() -> str:
    return os.getenv('CLOUDSAVER_PROVIDER_REDIS_URL') or os.getenv('REDIS_URL', '')


def filter_digest(filters: dict) -> str:
    canonical = json.dumps(filters, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(canonical.encode()).hexdigest()


def stable_key(*, provider: str, region: str, filters: dict, op: str) -> str:
    """Stable logical key: provider, region, operation, hash of filter fields."""
    return f'{provider}:{region}:{op}:{filter_digest(filters)}'


def _storage_key(logical_key: str) -> str:
    return _PREFIX + hashlib.sha256(logical_key.encode()).hexdigest()


def _encode(value) -> str:
    return json.dumps({'v': value}, separators=(',', ':'))


def _decode(raw: str):
    payload = json.loads(raw)
    if not isinstance(payload, dict) or list(payload.keys()) != ['v']:
        raise ValueError('invalid retail cache payload')
    return payload['v']


class LocalRetailCache:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.lock = threading.Lock()
        self.entries: dict[str, tuple[float, str]] = {}

    def get(self, logical_key: str):
        now = self.clock()
        with self.lock:
            entry = self.entries.get(logical_key)
            if not entry:
                return CACHE_MISS
            expires, raw = entry
            if expires <= now:
                del self.entries[logical_key]
                return CACHE_MISS
            return _decode(raw)

    def set(self, logical_key: str, value) -> None:
        raw = _encode(value)
        expires = self.clock() + ttl_seconds()
        with self.lock:
            if len(self.entries) >= 10000 and logical_key not in self.entries:
                self.entries = {
                    key: item
                    for key, item in self.entries.items()
                    if item[0] > self.clock()
                }
            self.entries[logical_key] = (expires, raw)


class RedisRetailCache:
    def __init__(self, url: str):
        import redis

        self.client = redis.Redis.from_url(
            url, socket_connect_timeout=2, socket_timeout=2, decode_responses=True
        )
        self.ttl = ttl_seconds()

    def get(self, logical_key: str):
        raw = self.client.get(_storage_key(logical_key))
        if raw is None:
            return CACHE_MISS
        return _decode(raw)

    def set(self, logical_key: str, value) -> None:
        self.client.setex(_storage_key(logical_key), self.ttl, _encode(value))


class RetailCache:
    """Prefer Redis when configured; fall back to in-process memory on Redis errors."""

    def __init__(self, url: str, local: LocalRetailCache | None = None):
        self.local = local or LocalRetailCache()
        self.redis = None
        if url:
            try:
                self.redis = RedisRetailCache(url)
            except Exception:
                self.redis = None

    def get(self, logical_key: str):
        if self.redis is not None:
            try:
                return self.redis.get(logical_key)
            except Exception:
                pass
        return self.local.get(logical_key)

    def set(self, logical_key: str, value) -> None:
        if self.redis is not None:
            try:
                self.redis.set(logical_key, value)
                return
            except Exception:
                pass
        self.local.set(logical_key, value)


@lru_cache(maxsize=4)
def _shared(url: str) -> RetailCache:
    return RetailCache(url)


def shared_cache() -> RetailCache:
    return _shared(_redis_url())


def get(logical_key: str):
    return shared_cache().get(logical_key)


def set(logical_key: str, value) -> None:
    shared_cache().set(logical_key, value)


def reset_shared_cache() -> None:
    _shared.cache_clear()


def azure_discover_filters(*, region, product_name, sku_name, meter_name, unit_of_measure):
    return {
        'armRegionName': region,
        'productName': product_name,
        'skuName': sku_name,
        'meterName': meter_name,
        'priceType': 'Consumption',
        'unitOfMeasure': unit_of_measure,
    }


def azure_price_filters(evidence: dict):
    return {
        'armRegionName': evidence['region'],
        'skuName': evidence['sku_name'],
        'meterName': evidence['meter_name'],
        'productName': evidence['product_name'],
        'meterId': evidence['meter_id'],
        'priceType': 'Consumption',
        'unitOfMeasure': evidence.get('unit_of_measure', '1 Hour'),
    }
