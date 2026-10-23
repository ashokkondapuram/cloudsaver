import os
from uuid import UUID

import httpx
from fastapi import Depends, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from services.common import internal_url, service, upstream
from app.jobs_api import ScanSubmission
from app.schemas import RemediationRequest, BillingCheckoutRequest, MultiCloudScanRequest


class RedisLimiter:
    """Atomic sliding window uses Redis time and bounded, expiring tenant state."""
    SCRIPT = """
        local t=redis.call('TIME')
        local now=t[1]*1000+math.floor(t[2]/1000)
        redis.call('ZREMRANGEBYSCORE',KEYS[1],'-inf',now-60000)
        local count=redis.call('ZCARD',KEYS[1])
        if count>=tonumber(ARGV[1]) then
            local oldest=redis.call('ZRANGE',KEYS[1],0,0,'WITHSCORES')
            return math.max(1,math.ceil((tonumber(oldest[2])+60000-now)/1000))
        end
        redis.call('ZADD',KEYS[1],now,ARGV[2])
        redis.call('PEXPIRE',KEYS[1],60000)
        return 0
    """

    def __init__(self):
        import redis.asyncio as redis
        self.client = redis.from_url(os.getenv('REDIS_URL', 'redis://localhost:6379/0'),
                                     socket_connect_timeout=2, socket_timeout=2)

    async def check(self, tenant_id):
        try:
            from uuid import uuid4
            retry = await self.client.eval(self.SCRIPT, 1, 'cloudsaver:rate:v2:' + tenant_id, 120, str(uuid4()))
        except Exception:
            raise HTTPException(503, 'Rate limiting service unavailable') from None
        if retry:
            raise HTTPException(429, 'Workspace request limit exceeded', headers={'Retry-After': str(retry)})


def create_app(settings=None, limiter=None, transport=None, identity_validator=None):
    app, settings, tenant = service('api-gateway', settings, identity_validator)
    limiter = limiter or RedisLimiter()
    if hasattr(limiter, 'client'):
        app.state.closeables = [limiter.client]
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

    @app.get('/api/v1/providers')
    async def providers(row=Depends(allowed), authorization: str = Header()):
        return await forward('GET', 'scanner', '/api/v1/providers', authorization)

    @app.get('/api/v1/gitops/targets')
    async def gitops_targets(row=Depends(allowed),authorization:str=Header()):
        return await forward('GET','scanner','/api/v1/gitops/targets',authorization)

    @app.get('/api/v1/gitops/requests')
    async def gitops_requests(row=Depends(allowed),authorization:str=Header(),limit:int=Query(50,ge=1,le=100)):
        return await forward('GET','scanner','/api/v1/gitops/requests',authorization,{'limit':limit})

    @app.get('/api/v1/gitops/requests/{request_id}')
    async def gitops_request(request_id:UUID,row=Depends(allowed),authorization:str=Header()):
        return await forward('GET','scanner',f'/api/v1/gitops/requests/{request_id}',authorization)

    async def gitops_post(path,request,authorization):
        from app.gitops_api import bounded_json
        payload = await bounded_json(request)
        return await upstream('POST',targets['scanner'],path,authorization,json=payload,transport=transport)

    @app.post('/api/v1/gitops/preview')
    async def gitops_preview(request:Request,row=Depends(allowed),authorization:str=Header()):
        return await gitops_post('/api/v1/gitops/preview',request,authorization)

    @app.post('/api/v1/gitops/requests',status_code=201)
    async def gitops_publish(request:Request,row=Depends(allowed),authorization:str=Header()):
        return await gitops_post('/api/v1/gitops/requests',request,authorization)

    @app.post('/api/v1/policies/terraform/evaluate')
    async def terraform_policy(request:Request,row=Depends(allowed),authorization:str=Header()):
        return await gitops_post('/api/v1/policies/terraform/evaluate',request,authorization)

    @app.get('/api/v1/operations/reliability')
    async def reliability(row=Depends(allowed),authorization:str=Header()):
        return await forward('GET','scanner','/api/v1/operations/reliability',authorization)

    @app.get('/api/v1/operations/deliveries')
    async def deliveries(row=Depends(allowed),authorization:str=Header(),limit:int=Query(50,ge=1,le=100),status:str|None=Query(None,pattern='^(pending|leased|published|delivered|dead_letter)$'),before:UUID|None=None):
        params={'limit':limit}
        if status:
            params['status']=status
        if before:
            params['before']=str(before)
        return await forward('GET','scanner','/api/v1/operations/deliveries',authorization,params)

    @app.get('/api/v1/operations/deliveries/{event_id}/audit')
    async def delivery_audit(event_id:UUID,row=Depends(allowed),authorization:str=Header(),limit:int=Query(50,ge=1,le=100),before:UUID|None=None):
        params={'limit':limit}
        if before:
            params['before']=str(before)
        return await forward('GET','scanner',f'/api/v1/operations/deliveries/{event_id}/audit',authorization,params)

    @app.post('/api/v1/operations/deliveries/{event_id}/retry',status_code=202)
    async def delivery_retry(event_id:UUID,request:Request,row=Depends(allowed),authorization:str=Header()):
        return await gitops_post(f'/api/v1/operations/deliveries/{event_id}/retry',request,authorization)

    @app.get('/api/v1/trends')
    async def trends(row=Depends(allowed), authorization: str = Header(), days: int = Query(30, ge=1, le=365), scan_id: UUID | None = None):
        params = {'days': days}
        if scan_id:
            params['scan_id'] = str(scan_id)
        return await forward('GET', 'scanner', '/api/v1/trends', authorization, params)

    @app.post('/api/v1/scans/multi-cloud', status_code=201)
    async def multi_cloud(payload: MultiCloudScanRequest, row=Depends(allowed), authorization: str = Header()):
        return await upstream('POST', targets['scanner'], '/api/v1/scans/multi-cloud', authorization,
                              json=payload.model_dump(), transport=transport)

    @app.post('/api/v1/scan-jobs', status_code=202)
    async def submit_job(payload: ScanSubmission,
                         row=Depends(allowed), authorization: str = Header()):
        result = await upstream('POST', targets['scanner'], '/api/v1/scan-jobs', authorization,
                                json=payload.model_dump(mode='json'), transport=transport)
        return JSONResponse(result, status_code=202, headers={'Location': result['poll_url'], 'Retry-After': '3'})

    @app.get('/api/v1/scan-jobs')
    async def job_history(limit: int = Query(50, ge=1, le=100), row=Depends(allowed), authorization: str = Header()):
        return await forward('GET', 'scanner', '/api/v1/scan-jobs', authorization, {'limit': limit})

    @app.get('/api/v1/scan-jobs/{job_id}')
    async def job_status(job_id: UUID, row=Depends(allowed), authorization: str = Header()):
        result = await forward('GET', 'scanner', f'/api/v1/scan-jobs/{job_id}', authorization)
        return JSONResponse(result, headers={'Retry-After': '3'} if result['status'] in ('queued','running') else {})

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

    @app.post('/api/v1/notifications/{scan_id}',status_code=202)
    async def notify(scan_id: UUID, row=Depends(allowed), authorization: str = Header()):
        return await forward('POST', 'notification', f'/api/v1/notifications/{scan_id}', authorization)

    from app.auth import operator_dependency
    from app.gitops_api import bounded_json
    operator = operator_dependency()

    async def operator_allowed(identity=Depends(operator)):
        await limiter.check('platform-operator')
        return identity

    async def tenant_write(method, path, request, authorization):
        return await upstream(method, targets['tenant'], path, authorization,
                              json=await bounded_json(request), transport=transport)

    @app.get('/api/v1/settings')
    async def workspace_settings(row=Depends(allowed), authorization: str = Header()):
        return await forward('GET', 'tenant', '/api/v1/settings', authorization)

    @app.put('/api/v1/settings')
    async def update_workspace_settings(request: Request, row=Depends(allowed), authorization: str = Header()):
        return await tenant_write('PUT', '/api/v1/settings', request, authorization)

    @app.get('/api/v1/admin/tenants')
    async def admin_tenants(identity=Depends(operator_allowed), authorization: str = Header()):
        return await forward('GET', 'tenant', '/api/v1/admin/tenants', authorization)

    @app.post('/api/v1/admin/tenants', status_code=201)
    async def admin_create_tenant(request: Request, identity=Depends(operator_allowed), authorization: str = Header()):
        return await tenant_write('POST', '/api/v1/admin/tenants', request, authorization)

    @app.patch('/api/v1/admin/tenants/{tenant_id}')
    async def admin_update_tenant(tenant_id: UUID, request: Request, identity=Depends(operator_allowed), authorization: str = Header()):
        return await tenant_write('PATCH', f'/api/v1/admin/tenants/{tenant_id}', request, authorization)

    @app.get('/api/v1/admin/settings')
    async def admin_settings(identity=Depends(operator_allowed), authorization: str = Header()):
        return await forward('GET', 'tenant', '/api/v1/admin/settings', authorization)

    @app.put('/api/v1/admin/settings')
    async def admin_update_settings(request: Request, identity=Depends(operator_allowed), authorization: str = Header()):
        return await tenant_write('PUT', '/api/v1/admin/settings', request, authorization)

    return app
