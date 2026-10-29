"""Bounded retries for explicit read operations; shared cooldowns never replay mutations."""
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from functools import lru_cache
import hashlib
import json
import math
import os
import random
import threading
import time

import httpx


class ProviderDeferred(RuntimeError):
    def __init__(self, retry_after):
        super().__init__('Provider collection deferred by its quota or retry budget')
        self.retry_after = max(1, math.ceil(retry_after))


class ProviderReadError(RuntimeError):
    def __init__(self,message,status_code=None):
        super().__init__(message)
        self.status_code=status_code


def retry_after(headers, *, now=None):
    """Preserve provider minimum delays, including Azure millisecond headers and HTTP dates."""
    now = now or datetime.now(timezone.utc)
    values = []
    for name, scale in (('retry-after', 1), ('x-ms-retry-after-ms', .001), ('retry-after-ms', .001)):
        raw = headers.get(name)
        if raw is None:
            continue
        try:
            try:
                seconds = float(raw) * scale
            except (ValueError, TypeError):
                date = parsedate_to_datetime(raw)
                seconds = (date - now).total_seconds() if date.tzinfo else -1
            if math.isfinite(seconds) and seconds >= 0:
                # Values beyond a year are rejected, never shortened into an early retry.
                if seconds > 366 * 86400:
                    raise ProviderReadError('Provider retry delay requires operator review')
                values.append(seconds)
        except (ValueError, TypeError, OverflowError):
            continue
    return max(values) if values else None


class LocalBudget:
    """Development fallback; multi-replica deployments require Redis."""
    def __init__(self, clock=time.monotonic):
        self.clock, self.lock, self.entries = clock, threading.Lock(), {}

    def acquire(self, key, interval):
        with self.lock:
            now = self.clock()
            self.entries = {k: v for k, v in self.entries.items() if v > now}
            wait = max(0, self.entries.get(key, now) - now)
            if wait == 0:
                if len(self.entries) >= 10000:
                    raise ProviderReadError('Provider budget capacity is unavailable')
                self.entries[key] = now + interval
            return wait

    def defer(self, key, seconds):
        with self.lock:
            self.entries[key] = max(self.entries.get(key, 0), self.clock() + seconds)


class RedisBudget:
    # Redis TIME avoids disagreements between worker clocks. Claim only when due.
    SCRIPT = """
local t=redis.call('TIME'); local now=tonumber(t[1])*1000+tonumber(t[2])/1000
local due=tonumber(redis.call('GET',KEYS[1]) or now)
if ARGV[1]=='defer' then
  due=math.max(due,now+tonumber(ARGV[2]))
  redis.call('PSETEX',KEYS[1],math.max(1,math.ceil(due-now)),tostring(due))
  return math.ceil(due-now)
end
if due>now then return math.ceil(due-now) end
local interval=tonumber(ARGV[2])
if interval>0 then redis.call('PSETEX',KEYS[1],math.ceil(interval),tostring(now+interval)) end
return 0
"""
    def __init__(self, url):
        import redis
        self.client = redis.Redis.from_url(url, socket_connect_timeout=2, socket_timeout=2)

    def _call(self, key, action, seconds):
        digest = hashlib.sha256(key.encode()).hexdigest()
        try:
            return float(self.client.eval(self.SCRIPT, 1, 'cloudsaver:provider-budget:' + digest, action, seconds * 1000)) / 1000
        except Exception:
            raise ProviderReadError('Shared provider budget is unavailable') from None

    def acquire(self, key, interval):
        return self._call(key, 'acquire', interval)

    def defer(self, key, seconds):
        self._call(key, 'defer', seconds)


@lru_cache(maxsize=4)
def _budget(url, production):
    if url:
        return RedisBudget(url)
    if production:
        raise ProviderReadError('Production provider collection requires Redis coordination')
    return LocalBudget()


def shared_budget():
    return _budget(os.getenv('CLOUDSAVER_PROVIDER_REDIS_URL') or os.getenv('REDIS_URL', ''), os.getenv('CLOUDSAVER_ENVIRONMENT') == 'production')


def read_json(client, method, url, *, quota_key, interval=0, deadline_seconds=30,
              attempts=3, max_bytes=8_000_000, read_only_post=False, budget=None,
              clock=time.monotonic, sleep=time.sleep, jitter=random.uniform, parse_float=float, **kwargs):
    """Retries GET or an explicitly classified read-only POST; never arbitrary mutations.

    Long provider waits become durable-job deferrals at the caller. Bodies on failed
    attempts are closed unread. No token, URL, response body or quota key is logged.
    """
    if method != 'GET' and not (method == 'POST' and read_only_post):
        raise ValueError('Only registered read operations can retry')
    if not 1 <= attempts <= 5 or not 0 < deadline_seconds <= 120 or not 0 <= interval <= 60:
        raise ValueError('Invalid provider retry policy')
    budget = budget or shared_budget()
    deadline = clock() + deadline_seconds
    for attempt in range(attempts):
        while True:
            wait = budget.acquire(quota_key, interval)
            remaining = deadline - clock()
            if remaining <= 0 or wait >= remaining:
                raise ProviderDeferred(max(wait, 1))
            if wait <= 0:
                break
            sleep(wait)
        remaining = deadline - clock()
        delay = None
        try:
            with client.stream(method, url, timeout=httpx.Timeout(remaining, connect=min(5, remaining)), **kwargs) as response:
                if response.status_code in (429, 502, 503, 504):
                    floor = retry_after(response.headers)
                    delay = max(floor or 0, jitter(0.25, min(8, 2 ** attempt)))
                elif not 200 <= response.status_code < 300:
                    raise ProviderReadError('Provider rejected the read request',response.status_code)
                else:
                    raw = bytearray()
                    for chunk in response.iter_bytes():
                        raw.extend(chunk)
                        if len(raw) > max_bytes or clock() >= deadline:
                            raise ProviderReadError('Provider response exceeded its size or time budget')
                    try:
                        result = json.loads(raw, parse_float=parse_float)
                    except (ValueError, TypeError):
                        raise ProviderReadError('Provider returned an invalid JSON response') from None
                    if not isinstance(result, dict):
                        raise ProviderReadError('Provider returned an invalid JSON object')
                    return result
        except (httpx.TimeoutException, httpx.NetworkError):
            delay = jitter(0.25, min(8, 2 ** attempt))
        budget.defer(quota_key, delay)
        if attempt + 1 == attempts or delay >= deadline - clock():
            raise ProviderDeferred(delay)
    raise ProviderReadError('Provider retry budget exhausted')
