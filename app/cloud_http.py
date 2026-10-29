"""Bounded read-only JSON transport; redirects and partial provider results fail."""
import json
import httpx
from urllib.parse import urlsplit
from app.provider_retry import read_json, ProviderReadError, ProviderDeferred
from app.scanner import ScanError


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
            result = read_json(self.client,'GET',url,params=params,headers=headers,quota_key=self.quota_key(url))
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
        # Google's log search is a read operation exposed as POST. Keep this
        # helper restricted to that exact API; it is not a generic action client.
        if url!='https://logging.googleapis.com/v2/entries:list':raise ScanError('Unsupported read-only POST endpoint')
        headers={}
        if self.credentials:
            from google.auth.transport.requests import Request
            self.credentials.before_request(Request(),'POST',url,headers)
        if self.token:headers['Authorization']='Bearer '+self.token
        value=read_json(self.client,'POST',url,json=body,headers=headers,quota_key=self.quota_key(url),read_only_post=True)
        if not isinstance(value,dict) or value.get('error'):raise ScanError('Invalid cloud audit response')
        return value


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
