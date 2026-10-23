"""Caller side of key verification: identity-service client, short positive cache and Redis eviction."""
import hashlib
import json
import logging
import os
import threading
import time
from collections import OrderedDict

from identity.events import CHANNEL

logger = logging.getLogger('cloudsaver.identity.client')


class IdentityUnavailable(Exception):
    pass


class KeyRejected(Exception):
    def __init__(self, reason, retry_after=None):
        super().__init__(reason)
        self.reason, self.retry_after = reason, retry_after


class GrantCache:
    """In-process positive cache. Entries are evicted by key_id or tenant_id on revocation events."""

    def __init__(self, ttl_seconds, size=10000, clock=time.monotonic):
        self.ttl, self.size, self.clock = ttl_seconds, size, clock
        self.items = OrderedDict()
        self.lock = threading.Lock()
        self.enabled = True

    def get(self, token_hash):
        with self.lock:
            item = self.items.get(token_hash)
            if not item:
                return None
            grant, expires = item
            if expires <= self.clock() or not self.enabled:
                self.items.pop(token_hash, None)
                return None
            self.items.move_to_end(token_hash)
            return grant

    def put(self, token_hash, grant):
        ttl = min(self.ttl, int(grant.get('cache_ttl_seconds', self.ttl)))
        if ttl <= 0 or not self.enabled:
            return
        with self.lock:
            self.items[token_hash] = (grant, self.clock() + ttl)
            self.items.move_to_end(token_hash)
            while len(self.items) > self.size:
                self.items.popitem(last=False)

    def evict(self, message):
        key_id, tenant_id = message.get('key_id'), message.get('tenant_id')
        if not key_id and not tenant_id:
            return
        with self.lock:
            for token_hash in [h for h, (g, _) in self.items.items()
                               if (key_id and g['key_id'] == key_id) or (tenant_id and g['tenant_id'] == tenant_id)]:
                del self.items[token_hash]

    def clear(self):
        with self.lock:
            self.items.clear()


class EvictionSubscriber(threading.Thread):
    """Listens for revocation broadcasts. While disconnected the positive cache is disabled."""

    def __init__(self, url, cache, on_directory=None):
        super().__init__(name='identity-evictions', daemon=True)
        self.url, self.cache, self.on_directory = url, cache, on_directory
        self.stopped = threading.Event()
        cache.enabled = False

    def run(self):
        import redis
        delay = 1
        while not self.stopped.is_set():
            try:
                client = redis.Redis.from_url(self.url, socket_connect_timeout=3, socket_timeout=30, health_check_interval=15)
                pubsub = client.pubsub(ignore_subscribe_messages=True)
                pubsub.subscribe(CHANNEL)
                self.cache.enabled, delay = True, 1
                while not self.stopped.is_set():
                    message = pubsub.get_message(timeout=1.0)
                    if message and message.get('type') == 'message':
                        self.handle(message['data'])
            except Exception:
                logger.warning('Identity eviction channel unavailable; caching is paused')
            self.cache.enabled = False
            self.cache.clear()
            self.stopped.wait(delay)
            delay = min(delay * 2, 30)

    def handle(self, data):
        try:
            message = json.loads(data)
        except (TypeError, ValueError):
            return
        if not isinstance(message, dict):
            return
        self.cache.evict(message)
        if message.get('directory') and self.on_directory:
            self.on_directory()

    def stop(self):
        self.stopped.set()


class IdentityClient:
    def __init__(self, base_url=None, token=None, *, cache_seconds=None, redis_url=None, transport=None, timeout=2.0,
                 subscribe=True):
        self.base_url = (base_url or os.getenv('CLOUDSAVER_IDENTITY_URL', 'http://identity-service:8005')).rstrip('/')
        self.token = token if token is not None else os.getenv('CLOUDSAVER_IDENTITY_TOKEN', '')
        if not self.token:
            raise RuntimeError('Set CLOUDSAVER_IDENTITY_TOKEN to call identity-service')
        seconds = int(cache_seconds if cache_seconds is not None else os.getenv('CLOUDSAVER_IDENTITY_CACHE_SECONDS', '15'))
        if not 0 <= seconds <= 30:
            raise ValueError('CLOUDSAVER_IDENTITY_CACHE_SECONDS must be between 0 and 30')
        self.cache = GrantCache(seconds)
        self.transport, self.timeout = transport, timeout
        self.subscriber = None
        self.directory_listeners = []
        if subscribe and seconds:
            url = redis_url or os.getenv('CLOUDSAVER_IDENTITY_REDIS_URL', 'redis://redis:6379/2')
            self.subscriber = EvictionSubscriber(url, self.cache, self._directory_changed)
            self.subscriber.start()

    def _directory_changed(self):
        for listener in list(self.directory_listeners):
            try:
                listener()
            except Exception:
                logger.warning('Directory change listener failed')

    def _client(self):
        import httpx
        return httpx.Client(base_url=self.base_url, timeout=self.timeout, transport=self.transport,
                            follow_redirects=False, trust_env=False, headers={'X-Service-Token': self.token})

    def verify(self, key, client_ip, request_id=None):
        token_hash = hashlib.sha256(key.encode()).hexdigest()
        cached = self.cache.get(token_hash)
        if cached:
            return cached
        import httpx
        try:
            with self._client() as client:
                response = client.post('/internal/v1/keys/verify', json={'key': key, 'client_ip': client_ip or '0.0.0.0',
                                                                         'request_id': request_id})
        except httpx.HTTPError:
            raise IdentityUnavailable() from None
        if response.status_code == 429:
            raise KeyRejected('throttled', response.headers.get('Retry-After', '60'))
        if response.status_code != 200:
            raise IdentityUnavailable()
        grant = response.json()
        if not grant.get('valid'):
            raise KeyRejected(grant.get('reason', 'unknown'))
        self.cache.put(token_hash, grant)
        return grant

    def get(self, path, params=None):
        import httpx
        try:
            with self._client() as client:
                response = client.get(path, params=params)
        except httpx.HTTPError:
            raise IdentityUnavailable() from None
        return response

    def close(self):
        if self.subscriber:
            self.subscriber.stop()


_client = None
_lock = threading.Lock()


def shared_client():
    global _client
    with _lock:
        if _client is None:
            _client = IdentityClient()
        return _client


def reset_shared_client(client=None):
    global _client
    with _lock:
        if _client is not None and _client is not client:
            _client.close()
        _client = client
