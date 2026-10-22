import os
from uuid import UUID

import httpx
from fastapi import Depends, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from services.common import internal_url, service, upstream
from app.schemas import RemediationRequest, BillingCheckoutRequest


class RedisLimiter:
    """Atomic fixed window with a TTL: no immortal counters after crashes."""
    SCRIPT = "local n=redis.call('INCR',KEYS[1]); if n==1 then redis.call('EXPIRE',KEYS[1],60) end; return n"

    def __init__(self):
        import redis.asyncio as redis
        self.client = redis.from_url(os.getenv('REDIS_URL', 'redis://localhost:6379/0'),
                                     socket_connect_timeout=2, socket_timeout=2)

    async def check(self, tenant_id):
        try:
            count = await self.client.eval(self.SCRIPT, 1, 'cloudsaver:rate:' + tenant_id)
        except Exception:
            raise HTTPException(503, 'Rate limiting service unavailable') from None
        if count > 120:
            raise HTTPException(429, 'Workspace request limit exceeded', headers={'Retry-After': '60'})


def create_app(settings=None, limiter=None, transport=None, identity_validator=None):
    app, settings, tenant = service('api-gateway', settings, identity_validator)
    limiter = limiter or RedisLimiter()
    targets = {
        'tenant': internal_url('TENANT_SERVICE_URL', 'http://tenant-service:8001'),
        'scanner': internal_url('SCANNER_SERVICE_URL', 'http://scanner-service:8002'),
        'analytics': internal_url('ANALYTICS_SERVICE_URL', 'http://analytics-service:8003'),
        'notification': internal_url('NOTIFICATION_SERVICE_URL', 'http://notification-service:8004'),
    }

    async def allowed(row=Depends(tenant)):
        await limiter.check(row['tenant_id'])
        return row

    async def forward(method, target, path, authorization, params=None):
        return await upstream(method, targets[target], path, authorization, params=params, transport=transport)

    @app.get('/api/v1/auth/consent-url')
    async def consent_url(row=Depends(allowed), authorization: str = Header()):
        return await forward('GET', 'scanner', '/api/v1/auth/consent-url', authorization)

    @app.post('/api/v1/billing/webhook')
    async def billing_webhook(request: Request):
        # This public endpoint authenticates by Stripe signature, not workspace bearer.
        signature = request.headers.get('stripe-signature')
        if not signature:
            raise HTTPException(400, 'Stripe signature required')
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 1_048_576:
                raise HTTPException(413, 'Webhook payload too large')
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=False, transport=transport) as client:
                response = await client.post(targets['tenant'] + '/api/v1/billing/webhook',
                    content=bytes(body), headers={'Stripe-Signature': signature, 'Content-Type': 'application/json'})
            if response.status_code not in (200, 400, 413, 503):
                raise HTTPException(502, 'Billing service could not complete the request')
            return JSONResponse(response.json(), status_code=response.status_code)
        except (httpx.HTTPError, ValueError):
            raise HTTPException(502, 'Billing service unavailable') from None

    @app.get('/api/v1/billing/entitlements')
    async def billing_entitlements(row=Depends(allowed), authorization: str = Header()):
        return await forward('GET', 'scanner', '/api/v1/billing/entitlements', authorization)

    @app.post('/api/v1/billing/checkout')
    async def billing_checkout(payload: BillingCheckoutRequest, row=Depends(allowed), authorization: str = Header()):
        return await upstream('POST', targets['scanner'], '/api/v1/billing/checkout', authorization,
                              json=payload.model_dump(), transport=transport)

    @app.get('/api/v1/me')
    async def me(row=Depends(allowed), authorization: str = Header()):
        return await forward('GET', 'tenant', '/api/v1/me', authorization)

    @app.get('/api/v1/scans')
    async def scans(row=Depends(allowed), authorization: str = Header(), limit: int = Query(50, ge=1, le=100)):
        return await forward('GET', 'scanner', '/api/v1/scans', authorization, {'limit': limit})

    @app.post('/api/v1/scans', status_code=201)
    async def scan(row=Depends(allowed), authorization: str = Header()):
        return await forward('POST', 'scanner', '/api/v1/scans', authorization)

    @app.get('/api/v1/scans/{scan_id}')
    async def detail(scan_id: UUID, row=Depends(allowed), authorization: str = Header()):
        return await forward('GET', 'scanner', f'/api/v1/scans/{scan_id}', authorization)

    @app.get('/api/v1/analytics')
    async def analytics(row=Depends(allowed), authorization: str = Header()):
        return await forward('GET', 'analytics', '/api/v1/analytics', authorization)

    @app.post('/api/v1/scans/{scan_id}/remediation')
    async def remediation(scan_id: UUID, payload: RemediationRequest, row=Depends(allowed), authorization: str = Header()):
        return await upstream('POST', targets['scanner'], f'/api/v1/scans/{scan_id}/remediation',
                              authorization, json=payload.model_dump(), transport=transport)

    @app.post('/api/v1/scans/{scan_id}/remediation-terraform')
    async def remediation_terraform(scan_id: UUID, payload: RemediationRequest, row=Depends(allowed), authorization: str = Header()):
        return await upstream('POST', targets['scanner'], f'/api/v1/scans/{scan_id}/remediation-terraform',
                              authorization, json=payload.model_dump(), transport=transport)

    @app.post('/api/v1/scans/{scan_id}/cancel')
    async def cancel_scan(scan_id: UUID, row=Depends(allowed), authorization: str = Header()):
        return await forward('POST', 'scanner', f'/api/v1/scans/{scan_id}/cancel', authorization)

    @app.post('/api/v1/notifications/{scan_id}')
    async def notify(scan_id: UUID, row=Depends(allowed), authorization: str = Header()):
        return await forward('POST', 'notification', f'/api/v1/notifications/{scan_id}', authorization)

    return app
