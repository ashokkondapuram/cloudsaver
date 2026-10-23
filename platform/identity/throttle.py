"""Brute-force limits per source IP and per (key_id, IP). State holds no key material."""
import threading
import time

from identity.config import env
from identity.domain import Unavailable

PREFIX = 'cloudsaver:identity:'


def _int(name, default):
    return int(env(name, str(default)))


class MemoryBackend:
    def __init__(self, clock=time.monotonic):
        self.clock, self._lock, self._values = clock, threading.Lock(), {}

    def _live(self, key):
        item = self._values.get(key)
        if item and item[1] <= self.clock():
            self._values.pop(key, None)
            return None
        return item

    def incr(self, key, ttl):
        with self._lock:
            item = self._live(key)
            count = (item[0] if item else 0) + 1
            self._values[key] = (count, item[1] if item else self.clock() + ttl)
            return count

    def block(self, key, ttl):
        with self._lock:
            self._values[key] = (1, self.clock() + ttl)

    def blocked_for(self, key):
        with self._lock:
            item = self._live(key)
            return max(1, int(item[1] - self.clock())) if item else 0


class RedisBackend:
    def __init__(self, url=None):
        import redis
        from identity.events import redis_url
        self.client = redis.from_url(url or redis_url(), socket_connect_timeout=2, socket_timeout=2)

    def _call(self, fn):
        try:
            return fn()
        except Exception:
            raise Unavailable('Sign-in is temporarily unavailable. Try again in a few minutes.', 503) from None

    def incr(self, key, ttl):
        def run():
            pipe = self.client.pipeline()
            pipe.incr(key)
            pipe.expire(key, ttl, nx=True)
            return int(pipe.execute()[0])
        return self._call(run)

    def block(self, key, ttl):
        self._call(lambda: self.client.set(key, '1', ex=ttl))

    def blocked_for(self, key):
        ttl = self._call(lambda: self.client.ttl(key))
        return int(ttl) if ttl and ttl > 0 else 0


class Throttle:
    def __init__(self, backend, *, ip_limit=None, pair_limit=None, window=None, block=None):
        self.backend = backend
        self.ip_limit = ip_limit or _int('IDENTITY_IP_FAILURES', 30)
        self.pair_limit = pair_limit or _int('IDENTITY_PAIR_FAILURES', 5)
        self.window = window or _int('IDENTITY_FAILURE_WINDOW_SECONDS', 300)
        self.block_seconds = block or _int('IDENTITY_BLOCK_SECONDS', 900)

    def blocked(self, ip, key_id=None):
        retry = self.backend.blocked_for(PREFIX + 'block:ip:' + ip)
        if not retry and key_id:
            retry = self.backend.blocked_for(PREFIX + f'block:pair:{key_id}:{ip}')
        return retry

    def failure(self, ip, key_id=None, mismatch=False):
        if self.backend.incr(PREFIX + 'fail:ip:' + ip, self.window) >= self.ip_limit:
            self.backend.block(PREFIX + 'block:ip:' + ip, self.block_seconds)
        if mismatch and key_id and self.backend.incr(PREFIX + f'fail:pair:{key_id}:{ip}', self.window) >= self.pair_limit:
            self.backend.block(PREFIX + f'block:pair:{key_id}:{ip}', self.block_seconds)
