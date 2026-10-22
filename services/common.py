import hashlib
import hmac
import os
from urllib.parse import urlsplit

import httpx
from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import Settings


def service(title, settings=None, identity_validator=None):
    settings = settings or Settings.load()
    app = FastAPI(title=title, version='0.6.0')
    from app.auth import tenant_dependency
    tenant = tenant_dependency(settings, identity_validator)

    @app.get('/healthz')
    def health():
        return {'status': 'healthy', 'service': title}

    @app.middleware('http')
    async def headers(request, call_next):
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        return response

    return app, settings, tenant


def internal_url(name, default):
    value = os.getenv(name, default).rstrip('/')
    parsed = urlsplit(value)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError(f'{name} must be an operator-configured service URL')
    return value


async def upstream(method, base, path, authorization, *, params=None, json=None, transport=None):
    """Only callers supply fixed routes; never proxy visitor-provided URLs."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(120, connect=5),
                                     follow_redirects=False, transport=transport) as client:
            response = await client.request(method, base + path, params=params, json=json,
                                            headers={'Authorization': authorization})
        if response.status_code >= 400:
            status = response.status_code if response.status_code in (401, 402, 403, 404, 409, 422, 429, 501, 503) else 502
            raise HTTPException(status, 'Upstream service could not complete the request')
        if response.is_redirect:
            raise HTTPException(502, 'Unexpected upstream redirect')
        return response.json()
    except (httpx.HTTPError, ValueError):
        raise HTTPException(502, 'Upstream service unavailable or returned invalid data') from None
