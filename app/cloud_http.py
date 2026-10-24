"""Bounded read-only JSON transport; redirects and partial provider results fail."""
import json
import httpx
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
            with self.client.stream('GET', url, params=params, headers=headers) as response:
                if not 200 <= response.status_code < 300:
                    raise ScanError('Cloud inventory source rejected the read request')
                content = bytearray()
                for chunk in response.iter_bytes():
                    content.extend(chunk)
                    if len(content) > 8_000_000:
                        raise ScanError('Cloud inventory response exceeds the page limit')
            result = json.loads(content)
            if not isinstance(result, dict):
                raise ScanError('Cloud inventory returned an invalid object')
            return result
        except (httpx.HTTPError, ValueError, TypeError):
            raise ScanError('Cloud inventory source is unavailable or malformed') from None

    def close(self):
        self.client.close()


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
