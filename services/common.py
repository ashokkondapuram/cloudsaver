import hashlib
import hmac
import os
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

import httpx
from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import Settings


def service(title, settings=None, identity_validator=None):
    settings = settings or Settings.load()
    @asynccontextmanager
    async def lifespan(app):
        yield
        for client in getattr(app.state, 'closeables', []):
            await client.aclose()
        from database.connection import dispose
        dispose()
    app = FastAPI(title=title, version='1.5.1', lifespan=lifespan)
    from app.runtime import install
    install(app, settings, redis_required=title == 'api-gateway')
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


async def upstream(method, base, path, authorization, *, params=None, json=None, transport=None, evidence_signature=None):
    """Only callers supply fixed routes; never proxy visitor-provided URLs."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(120, connect=5),
                                     follow_redirects=False, transport=transport) as client:
            from app.runtime import CLIENT_IP_HEADER, client_ip, request_id
            headers = {'Authorization': authorization}
            if request_id.get():
                headers['X-Request-ID'] = request_id.get()
            if client_ip.get():
                headers[CLIENT_IP_HEADER] = client_ip.get()
            if evidence_signature:headers['X-Evidence-Signature']=evidence_signature
            response = await client.request(method, base + path, params=params, json=json, headers=headers)
        if response.status_code >= 400:
            status = response.status_code if response.status_code in (401, 402, 403, 404, 409, 410, 413, 422, 429, 501, 503) else 502
            detail = 'Upstream service could not complete the request'
            if status in (401, 402, 403, 409, 410, 422, 429, 503):
                # Internal services return sanitized, user-facing validation messages.
                try:
                    candidate = response.json().get('detail')
                    if isinstance(candidate, str) and 0 < len(candidate) <= 300:
                        detail = candidate
                except (ValueError, AttributeError):
                    pass
            retry = response.headers.get('Retry-After', '')
            extra = {'Retry-After': retry} if status in (429, 503) and retry.isdigit() and 1 <= int(retry) <= 86400 else None
            raise HTTPException(status, detail, headers=extra)
        if response.is_redirect:
            raise HTTPException(502, 'Unexpected upstream redirect')
        return response.json()
    except (httpx.HTTPError, ValueError):
        raise HTTPException(502, 'Upstream service unavailable or returned invalid data') from None
