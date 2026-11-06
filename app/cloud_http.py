"""Bounded read-only JSON transport; redirects and partial provider results fail."""
import json
import os
import time
import httpx
from urllib.parse import urlsplit
from app.provider_retry import read_json, ProviderReadError, ProviderDeferred
from app.scan_errors import ScanError


def _json_reader_pacing_interval() -> float:
    if os.getenv('CLOUDSAVER_ENVIRONMENT', '').lower() == 'development':
        return 0.0
    raw = os.getenv('CLOUDSAVER_JSON_READER_INTERVAL_SECONDS', '0.25')
    return max(0.0, min(float(raw), 60.0))


class BearerTokenCache:
    """Attach one Authorization header per scan; refresh only when the token is near expiry."""

    def __init__(self, credential, scope, *, skew_seconds=300):
        self._credential = credential
        self._scope = scope
        self._skew = skew_seconds
        self._token = None
        self._expires_on = 0.0

    def __call__(self, _url=None):
        now = time.time()
        if self._token is None or now >= self._expires_on - self._skew:
            access = self._credential.get_token(self._scope)
            self._token = access.token
            self._expires_on = float(access.expires_on)
        return {'Authorization': 'Bearer ' + self._token}


class JSONReader:
    def __init__(self, *, token=None, credentials=None, transport=None, headers_factory=None, timeout_seconds=60):
        self.token, self.credentials = token, credentials
        self.headers_factory = headers_factory
        self.client = httpx.Client(timeout=httpx.Timeout(timeout_seconds, connect=min(10,timeout_seconds)), follow_redirects=False, transport=transport)

    def get(self, url, params=None):
        headers = {}
        if self.headers_factory:
            url = str(httpx.URL(url, params=params))
            params = None
            headers.update(self.headers_factory(url))
        if self.token:
            headers['Authorization'] = 'Bearer ' + self.token
        if self.credentials:
            from google.auth.transport.requests import Request
            self.credentials.before_request(Request(), 'GET', url, headers)
        try:
            result = read_json(
                self.client,
                'GET',
                url,
                params=params,
                headers=headers,
                quota_key=self.quota_key(url),
                interval=_json_reader_pacing_interval(),
            )
            if not isinstance(result, dict):
                raise ScanError('Cloud inventory returned an invalid object')
            return result
        except ProviderDeferred as deferred:
            error=ScanError('Cloud collection is deferred by the provider quota')
            error.retry_after=deferred.retry_after
            raise error from None
        except (httpx.HTTPError, ValueError, TypeError, ProviderReadError):
            raise ScanError('Cloud inventory source is unavailable or malformed') from None

    def close(self):
        self.client.close()

    @staticmethod
    def quota_key(url):
        parsed=urlsplit(url)
        parts=parsed.path.lower().split('/')
        scope='global'
        for kind in ('subscriptions','projects'):
            if kind in parts and len(parts)>parts.index(kind)+1:
                scope=kind+':'+parts[parts.index(kind)+1]
                break
        # Other registered endpoints share a host budget; conservative, not per token.
        return parsed.netloc.lower()+':'+scope

    def post_read(self,url,body):
        # Read-only provider queries exposed as POST. Not a generic action client.
        if not _allowed_read_post_url(url):
            raise ScanError('Unsupported read-only POST endpoint')
        headers={}
        if self.credentials:
            from google.auth.transport.requests import Request
            self.credentials.before_request(Request(),'POST',url,headers)
        if self.token:headers['Authorization']='Bearer '+self.token
        value=read_json(
            self.client,
            'POST',
            url,
            json=body,
            headers=headers,
            quota_key=self.quota_key(url),
            read_only_post=True,
            interval=_json_reader_pacing_interval(),
        )
        if not isinstance(value,dict) or value.get('error'):raise ScanError('Invalid cloud read response')
        return value


def _allowed_read_post_url(url):
    if url == 'https://logging.googleapis.com/v2/entries:list':
        return True
    if url.startswith('https://cloudasset.googleapis.com/v1/projects/') and url.endswith(':searchAllResources'):
        return True
    parsed = urlsplit(url)
    host = (parsed.hostname or '').lower()
    path = parsed.path or ''
    # Wiz — OAuth token (read-only client credentials) and GraphQL issue queries only.
    if host in ('auth.app.wiz.io', 'auth.gov.wiz.io') and path.rstrip('/') == '/oauth/token':
        return True
    if host.endswith('.app.wiz.io') and path.rstrip('/').endswith('/graphql'):
        return True
    return False


def pages(reader, url, params=None, *, token_key='nextPageToken', param_key='pageToken'):
    params, seen = dict(params or {}), set()
    for _ in range(1000):
        page = reader.get(url, params)
        if not isinstance(page, dict) or page.get('error') or page.get('unreachables'):
            raise ScanError('Cloud inventory returned a partial or invalid result')
        yield page
        token = page.get(token_key)
        if not token:
            return
        if not isinstance(token, str) or len(token) > 10000 or token in seen:
            raise ScanError('Cloud inventory repeated an invalid continuation token')
        seen.add(token)
        params[param_key] = token
    raise ScanError('Cloud inventory exceeded its page limit')


def post_pages(reader, url, body, *, token_key='nextPageToken', param_key='pageToken'):
    body, seen = dict(body or {}), set()
    for _ in range(1000):
        page = reader.post_read(url, body)
        if not isinstance(page, dict) or page.get('error') or page.get('unreachables'):
            raise ScanError('Cloud inventory returned a partial or invalid result')
        yield page
        token = page.get(token_key)
        if not token:
            return
        if not isinstance(token, str) or len(token) > 10000 or token in seen:
            raise ScanError('Cloud inventory repeated an invalid continuation token')
        seen.add(token)
        body[param_key] = token
    raise ScanError('Cloud inventory exceeded its page limit')
