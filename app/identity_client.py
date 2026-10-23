"""Caller side of the identity-service contract (platform/contracts/identity-v1.md).

Key verification with a short positive cache, directory reads for the tenant-service projector, and
cache eviction through the long-poll events endpoint. CloudSaver never imports platform code.
"""
import hashlib
import logging
import os
import threading
import time
from collections import OrderedDict

logger = logging.getLogger('cloudsaver.identity.client')
MAX_CACHE_SECONDS = 30


class IdentityUnavailable(Exception):
    pass


class KeyRejected(Exception):
    def __init__(self, reason, retry_after=None):
        super().__init__(reason)
        self.reason, self.retry_after = reason, retry_after


class GrantCache:
    """In-process positive cache. Entries are evicted by key_id or tenant_id on revocation events."""

    def __init__(self, ttl_seconds, size=10000, clock=time.monotonic):
        self.ttl, self.size, self.clock = min(int(ttl_seconds), MAX_CACHE_SECONDS), size, clock
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
                               if (key_id and g.get('key_id') == key_id) or (tenant_id and g.get('tenant_id') == tenant_id)]:
                del self.items[token_hash]

    def clear(self):
        with self.lock:
            self.items.clear()


class EventPoller(threading.Thread):
    """Long-polls GET /internal/v1/events. While polls fail the positive cache is disabled."""

    def __init__(self, client, cache, on_directory=None, *, wait=25):
        super().__init__(name='identity-events', daemon=True)
        self.client, self.cache, self.on_directory, self.wait = client, cache, on_directory, wait
        self.after = None
        self.stopped = threading.Event()
        cache.enabled = False

    def poll_once(self):
        """One request. Starts from the head when there is no cursor; raises IdentityUnavailable on failure."""
        params = None if self.after is None else {'after': self.after, 'wait': self.wait}
        response = self.client.get('/internal/v1/events', params=params, timeout=self.wait + 10)
        if response.status_code == 410:
            logger.warning('Identity event cursor expired; clearing the grant cache')
            self.cache.enabled = False
            self.cache.clear()
            self.after = None
            self._directory_changed()
            return
        if response.status_code != 200:
            raise IdentityUnavailable()
        try:
            data = response.json()
            items, seq = data['items'], int(data['seq'])
        except (ValueError, KeyError, TypeError):
            raise IdentityUnavailable() from None
        directory = False
        for item in items:
            if isinstance(item, dict):
                self.cache.evict(item)
                directory = directory or bool(item.get('directory'))
                if item.get('event') == 'access_check_requested':
                    check_id = (item.get('payload') or {}).get('check_id')
                    if check_id:
                        from app.access_worker import enqueue
                        enqueue(check_id)
        self.after = seq
        self.cache.enabled = True
        if directory:
            self._directory_changed()

    def _directory_changed(self):
        if self.on_directory:
            self.on_directory()

    def run(self):
        delay = 1
        while not self.stopped.is_set():
            try:
                self.poll_once()
                delay = 1
            except Exception:
                logger.warning('Identity events unavailable; grant caching is paused')
                self.cache.enabled = False
                self.cache.clear()
                self.stopped.wait(delay)
                delay = min(delay * 2, 30)

    def stop(self):
        self.stopped.set()


class IdentityClient:
    def __init__(self, base_url=None, token=None, *, cache_seconds=None, transport=None, timeout=2.0, subscribe=True):
        self.base_url = (base_url or os.getenv('CLOUDSAVER_IDENTITY_URL', 'http://identity-service:8005')).rstrip('/')
        self.token = token if token is not None else os.getenv('CLOUDSAVER_IDENTITY_TOKEN', '')
        if not self.token:
            raise RuntimeError('Set CLOUDSAVER_IDENTITY_TOKEN to call identity-service')
        seconds = int(cache_seconds if cache_seconds is not None else os.getenv('CLOUDSAVER_IDENTITY_CACHE_SECONDS', '15'))
        if not 0 <= seconds <= MAX_CACHE_SECONDS:
            raise ValueError('CLOUDSAVER_IDENTITY_CACHE_SECONDS must be between 0 and 30')
        self.cache = GrantCache(seconds)
        self.transport, self.timeout = transport, timeout
        self.directory_listeners = []
        self.poller = None
        if subscribe:
            self.poller = EventPoller(self, self.cache, self._directory_changed)
            self.poller.start()

    def _directory_changed(self):
        for listener in list(self.directory_listeners):
            try:
                listener()
            except Exception:
                logger.warning('Directory change listener failed')

    def _client(self, timeout=None):
        import httpx
        return httpx.Client(base_url=self.base_url, timeout=timeout or self.timeout, transport=self.transport,
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
        try:
            grant = response.json()
        except ValueError:
            raise IdentityUnavailable() from None
        if not grant.get('valid'):
            raise KeyRejected(grant.get('reason', 'unknown'))
        self.cache.put(token_hash, grant)
        return grant

    def get(self, path, params=None, timeout=None):
        import httpx
        try:
            with self._client(timeout) as client:
                response = client.get(path, params=params)
        except httpx.HTTPError:
            raise IdentityUnavailable() from None
        return response

    def request(self, method, path, *, json=None, timeout=None, headers=None, params=None):
        import httpx
        try:
            with self._client(timeout) as client:
                return client.request(method, path, json=json, headers=headers, params=params)
        except httpx.HTTPError:
            raise IdentityUnavailable() from None

    def close(self):
        if self.poller:
            self.poller.stop()


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
