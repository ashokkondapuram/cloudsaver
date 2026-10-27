import os
from uuid import UUID

from fastapi import Depends, Header, HTTPException, Path, Query, Request
from fastapi.responses import JSONResponse

from services.common import internal_url, service, upstream
from app.jobs_api import ScanSubmission
from app.schemas import MultiCloudScanRequest, RemediationRequest

CHECKOUT_GONE = 'Plan changes are handled by your account manager.'
WEBHOOK_GONE = 'Billing webhooks are handled by the platform.'


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
        'tenant': internal_url('SCANNER_SERVICE_URL', 'http://scanner-service:8002'),
        'scanner': internal_url('SCANNER_SERVICE_URL', 'http://scanner-service:8002'),
        'analytics': internal_url('SCANNER_SERVICE_URL', 'http://scanner-service:8002'),
        'notification': internal_url('SCANNER_SERVICE_URL', 'http://scanner-service:8002'),
        'agent': internal_url('AGENT_GATEWAY_URL', 'http://agent-gateway:8006'),
    }

    async def core_ready():
        async with __import__('httpx').AsyncClient(timeout=2,transport=transport) as client:
            response=await client.get(targets['scanner']+'/readyz')
            if response.status_code!=200:raise RuntimeError('Core service unavailable')
    app.state.readiness_checks['core']=core_ready

    async def allowed(row=Depends(tenant)):
        await limiter.check(row['tenant_id'])
        return row

    async def forward(method, target, path, authorization, params=None):
        return await upstream(method, targets[target], path, authorization, params=params, transport=transport)

    from services.governance_routes import register as register_governance
    register_governance(app,allowed,targets,transport)
    from app.onboarding_api import customer_access_router, onboarding_router
    app.include_router(onboarding_router())
    app.include_router(customer_access_router(allowed))

    @app.get('/api/v1/outcomes/summary')
    async def outcome_summary(request:Request,row=Depends(allowed),authorization:str=Header()):
        return await forward('GET','scanner','/api/v1/outcomes/summary',authorization,dict(request.query_params))

    @app.get('/api/v1/outcomes/cases')
    async def outcome_cases(request:Request,row=Depends(allowed),authorization:str=Header()):
        return await forward('GET','scanner','/api/v1/outcomes/cases',authorization,dict(request.query_params))

    @app.post('/api/v1/outcomes/cases',status_code=201)
    async def create_outcome_case(request:Request,row=Depends(allowed),authorization:str=Header()):
        from app.gitops_api import bounded_json
        return await upstream('POST',targets['scanner'],'/api/v1/outcomes/cases',authorization,json=await bounded_json(request),transport=transport)

    @app.get('/api/v1/outcomes/cases/{case_id}')
    async def outcome_case(case_id:UUID,request:Request,row=Depends(allowed),authorization:str=Header()):
        return await forward('GET','scanner',f'/api/v1/outcomes/cases/{case_id}',authorization,dict(request.query_params))

    @app.post('/api/v1/outcomes/cases/{case_id}/actions')
    async def outcome_case_action(case_id:UUID,request:Request,row=Depends(allowed),authorization:str=Header()):
        from app.gitops_api import bounded_json
        return await upstream('POST',targets['scanner'],f'/api/v1/outcomes/cases/{case_id}/actions',authorization,json=await bounded_json(request),transport=transport)

    @app.get('/api/v1/outcomes/cases/{case_id}/billing-evidence')
    async def outcome_billing_evidence(case_id:UUID,request:Request,row=Depends(allowed),authorization:str=Header()):
        return await forward('GET','scanner',f'/api/v1/outcomes/cases/{case_id}/billing-evidence',authorization,dict(request.query_params))

    @app.post('/api/v1/outcomes/evidence/receipts',status_code=201)
    async def outcome_evidence_receipt(request:Request,row=Depends(allowed),authorization:str=Header()):
        from app.gitops_api import bounded_json
        return await upstream('POST',targets['scanner'],'/api/v1/outcomes/evidence/receipts',authorization,json=await bounded_json(request),transport=transport,evidence_signature=request.headers.get('X-Evidence-Signature'))

    @app.get('/api/v1/outcomes/ownership')
    async def outcome_ownership(request:Request,row=Depends(allowed),authorization:str=Header()):
        return await forward('GET','scanner','/api/v1/outcomes/ownership',authorization,dict(request.query_params))

    @app.put('/api/v1/outcomes/ownership')
    async def update_outcome_ownership(request:Request,row=Depends(allowed),authorization:str=Header()):
        from app.gitops_api import bounded_json
        return await upstream('PUT',targets['scanner'],'/api/v1/outcomes/ownership',authorization,json=await bounded_json(request),transport=transport)

    @app.get('/api/v1/outcomes/ownership/history')
    async def outcome_ownership_history(request:Request,row=Depends(allowed),authorization:str=Header()):
        return await forward('GET','scanner','/api/v1/outcomes/ownership/history',authorization,dict(request.query_params))

    @app.get('/api/v1/outcomes/anomalies')
    async def outcome_investigations(request:Request,row=Depends(allowed),authorization:str=Header()):
        return await forward('GET','scanner','/api/v1/outcomes/anomalies',authorization,dict(request.query_params))

    @app.post('/api/v1/outcomes/anomalies/detect')
    async def detect_outcome_anomalies(request:Request,row=Depends(allowed),authorization:str=Header()):
        from app.gitops_api import bounded_json
        return await upstream('POST',targets['scanner'],'/api/v1/outcomes/anomalies/detect',authorization,json=await bounded_json(request),transport=transport)

    @app.get('/api/v1/outcomes/anomalies/metrics')
    async def outcome_investigation_metrics(request:Request,row=Depends(allowed),authorization:str=Header()):
        return await forward('GET','scanner','/api/v1/outcomes/anomalies/metrics',authorization,dict(request.query_params))

    @app.get('/api/v1/outcomes/anomalies/{anomaly_id}')
    async def outcome_investigation(anomaly_id:UUID,request:Request,row=Depends(allowed),authorization:str=Header()):
        return await forward('GET','scanner',f'/api/v1/outcomes/anomalies/{anomaly_id}',authorization,dict(request.query_params))

    @app.post('/api/v1/outcomes/anomalies/{anomaly_id}/actions')
    async def outcome_investigation_action(anomaly_id:UUID,request:Request,row=Depends(allowed),authorization:str=Header()):
        from app.gitops_api import bounded_json
        return await upstream('POST',targets['scanner'],f'/api/v1/outcomes/anomalies/{anomaly_id}/actions',authorization,json=await bounded_json(request),transport=transport)

    @app.post('/api/v1/outcomes/suppressions',status_code=201)
    async def approve_outcome_exception(request:Request,row=Depends(allowed),authorization:str=Header()):
        from app.gitops_api import bounded_json
        return await upstream('POST',targets['scanner'],'/api/v1/outcomes/suppressions',authorization,json=await bounded_json(request),transport=transport)

    @app.get('/api/v1/services/{service_name}')
    async def service_matrix(service_name:str,scan_id:UUID|None=None,row=Depends(allowed),authorization:str=Header()):
        from app.v150_analysis import SERVICES
        if service_name not in SERVICES:raise HTTPException(404,'Unknown service family')
        return await forward('GET','scanner','/api/v1/services/'+service_name,authorization,
                             {'scan_id':str(scan_id)} if scan_id else {})

    @app.get('/api/v1/optimization/scans/{scan_id}/auto-scenarios')
    async def planning_inputs(scan_id:UUID,row=Depends(allowed),authorization:str=Header()):
        return await forward('GET','scanner',f'/api/v1/optimization/scans/{scan_id}/auto-scenarios',authorization)

    @app.get('/api/v1/gitops/syncs')
    async def linked_history(row=Depends(allowed),authorization: str=Header()):
        return await forward('GET','scanner','/api/v1/gitops/syncs',authorization)

    @app.post('/api/v1/finops/sync',status_code=202)
    async def billing_sync(request:Request,currency:str=Query('USD',pattern=r'^[A-Z]{3}$'),row=Depends(allowed),authorization:str=Header()):
        from app.schemas import bounded_json
        result=await upstream('POST',targets['scanner'],'/api/v1/finops/sync',authorization,params={'currency':currency},json=await bounded_json(request),transport=transport)
        return JSONResponse(result,status_code=202,headers={'Location':result['poll_url'],'Retry-After':'3'})

    @app.get('/api/v1/finops/sync-jobs/{job_id}')
    async def billing_job(job_id:UUID,row=Depends(allowed),authorization:str=Header()):
        return await forward('GET','scanner',f'/api/v1/finops/sync-jobs/{job_id}',authorization)

    @app.post('/api/v1/finops/sync-jobs/{job_id}/cancel')
    async def cancel_billing_job(job_id:UUID,row=Depends(allowed),authorization:str=Header()):
        return await forward('POST','scanner',f'/api/v1/finops/sync-jobs/{job_id}/cancel',authorization)

    @app.get('/api/v1/finops/sync-status')
    async def billing_sync_status(row=Depends(allowed),authorization: str=Header()):
        return await forward('GET','scanner','/api/v1/finops/sync-status',authorization)

    @app.get('/api/v1/observability/connectors')
    async def observability_connectors(row=Depends(allowed),authorization: str=Header()):
        return await forward('GET','scanner','/api/v1/observability/connectors',authorization)

    @app.post('/api/v1/observability/connectors',status_code=201)
    async def create_observability_connector(request:Request,row=Depends(allowed),authorization: str=Header()):
        return await post_json('/api/v1/observability/connectors',request,authorization)

    @app.post('/api/v1/observability/connectors/test')
    async def test_observability_draft(request:Request,row=Depends(allowed),authorization: str=Header()):
        return await post_json('/api/v1/observability/connectors/test',request,authorization)

    @app.post('/api/v1/observability/connectors/{connector_id}')
    async def update_observability_connector(connector_id:UUID,request:Request,row=Depends(allowed),authorization: str=Header()):
        return await post_json(f'/api/v1/observability/connectors/{connector_id}',request,authorization)

    @app.post('/api/v1/observability/connectors/{connector_id}/disable')
    @app.post('/api/v1/observability/connectors/{connector_id}/enable')
    @app.post('/api/v1/observability/connectors/{connector_id}/test')
    async def observability_connector_action(connector_id:UUID,request:Request,row=Depends(allowed),authorization: str=Header()):
        action=request.url.path.rsplit('/',1)[-1]
        return await forward('POST','scanner',f'/api/v1/observability/connectors/{connector_id}/{action}',authorization)

    @app.post('/api/v1/observability/sync',status_code=202)
    async def observability_sync(request:Request,row=Depends(allowed),authorization: str=Header()):
        from app.schemas import bounded_json
        result=await upstream('POST',targets['scanner'],'/api/v1/observability/sync',authorization,json=await bounded_json(request),transport=transport)
        return JSONResponse(result,status_code=202,headers={'Location':result['poll_url'],'Retry-After':'3'})

    @app.get('/api/v1/observability/sync-jobs/{job_id}')
    async def observability_job(job_id:UUID,row=Depends(allowed),authorization: str=Header()):
        return await forward('GET','scanner',f'/api/v1/observability/sync-jobs/{job_id}',authorization)

    @app.get('/api/v1/observability/summary')
    async def observability_summary(row=Depends(allowed),authorization: str=Header()):
        return await forward('GET','scanner','/api/v1/observability/summary',authorization)

    @app.get('/api/v1/finops/commitments')
    async def billing_commitments(row=Depends(allowed),authorization: str=Header()):
        return await forward('GET','scanner','/api/v1/finops/commitments',authorization)

    @app.post('/api/v1/gitops/sync-agent')
    @app.post('/api/v1/gitops/preview-and-evaluate')
    async def linked_gitops(request: Request,row=Depends(allowed),authorization: str=Header()):
        from app.schemas import bounded_json
        return await upstream('POST',targets['scanner'],request.url.path,authorization,
                              json=await bounded_json(request),transport=transport)

    @app.get('/api/v1/ai/governance')
    async def data_governance(row=Depends(allowed),authorization: str = Header()):
        return await forward('GET','scanner','/api/v1/ai/governance',authorization)

    @app.post('/api/v1/ai/governance/records/{attempt_id}/{decision}')
    async def data_privacy(attempt_id:UUID,decision:str,request:Request,row=Depends(allowed),authorization:str=Header()):
        if decision not in ('erase','hold'):raise HTTPException(404,'Privacy operation not found')
        from app.schemas import bounded_json
        return await upstream('POST',targets['scanner'],f'/api/v1/ai/governance/records/{attempt_id}/{decision}',authorization,
            json=await bounded_json(request),transport=transport)

    @app.post('/api/v1/ai/governance/holds/{hold_id}/release')
    async def release_hold(hold_id:UUID,request:Request,row=Depends(allowed),authorization:str=Header()):
        from app.schemas import bounded_json
        return await upstream('POST',targets['scanner'],f'/api/v1/ai/governance/holds/{hold_id}/release',authorization,
            json=await bounded_json(request),transport=transport)

    @app.get('/api/v1/agents/catalog')
    async def agent_catalog(row=Depends(allowed), authorization: str = Header()):
        return await forward('GET','agent','/api/v1/agents/catalog',authorization)

    @app.get('/api/v1/agents/tasks')
    async def agent_tasks(row=Depends(allowed), authorization: str = Header()):
        return await forward('GET','agent','/api/v1/agents/tasks',authorization)

    @app.get('/api/v1/agents/tasks/{task_id}')
    async def agent_task(task_id: UUID,row=Depends(allowed), authorization: str = Header()):
        return await forward('GET','agent',f'/api/v1/agents/tasks/{task_id}',authorization)

    @app.post('/api/v1/agents/tasks',status_code=201)
    async def agent_submit(request: Request,row=Depends(allowed),authorization: str = Header()):
        from app.schemas import bounded_json
        return await upstream('POST',targets['agent'],'/api/v1/agents/tasks',authorization,json=await bounded_json(request),transport=transport)

    @app.post('/api/v1/agents/tasks/{task_id}/review')
    async def agent_review(task_id: UUID,request: Request,row=Depends(allowed),authorization: str = Header()):
        from app.schemas import bounded_json
        return await upstream('POST',targets['agent'],f'/api/v1/agents/tasks/{task_id}/review',authorization,json=await bounded_json(request),transport=transport)

    @app.get('/api/v1/auth/consent-url')
    async def consent_url(row=Depends(allowed), authorization: str = Header()):
        return await forward('GET', 'scanner', '/api/v1/auth/consent-url', authorization)

    @app.post('/api/v1/billing/webhook')
    def billing_webhook():
        raise HTTPException(410, WEBHOOK_GONE)

    @app.get('/api/v1/billing/entitlements')
    async def billing_entitlements(row=Depends(allowed), authorization: str = Header()):
        return await forward('GET', 'scanner', '/api/v1/billing/entitlements', authorization)

    @app.post('/api/v1/billing/checkout')
    def billing_checkout():
        raise HTTPException(410, CHECKOUT_GONE)

    @app.get('/api/v1/billing/plans')
    async def billing_plans(row=Depends(allowed), authorization: str = Header()):
        return await forward('GET', 'tenant', '/api/v1/billing/plans', authorization)

    @app.get('/api/v1/billing/plan-requests')
    async def billing_plan_requests(row=Depends(allowed), authorization: str = Header()):
        return await forward('GET', 'tenant', '/api/v1/billing/plan-requests', authorization)

    @app.post('/api/v1/billing/plan-requests')
    async def billing_plan_request_submit(request: Request, row=Depends(allowed), authorization: str = Header()):
        return await tenant_write('POST', '/api/v1/billing/plan-requests', request, authorization)

    @app.get('/api/v1/me')
    async def me(row=Depends(allowed), authorization: str = Header()):
        return await forward('GET', 'tenant', '/api/v1/me', authorization)

    @app.get('/api/v1/scans')
    async def scans(row=Depends(allowed), authorization: str = Header(), limit: int = Query(50, ge=1, le=100)):
        return await forward('GET', 'scanner', '/api/v1/scans', authorization, {'limit': limit})

    @app.get('/api/v1/providers')
    async def providers(row=Depends(allowed), authorization: str = Header()):
        return await forward('GET', 'scanner', '/api/v1/providers', authorization)




    async def post_json(path,request,authorization):
        from app.schemas import bounded_json
        payload = await bounded_json(request)
        return await upstream('POST',targets['scanner'],path,authorization,json=payload,transport=transport)




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
        return await post_json(f'/api/v1/operations/deliveries/{event_id}/retry',request,authorization)

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

    @app.get('/api/v1/ai/targets')
    async def ai_targets(row=Depends(allowed), authorization: str = Header()):
        return await forward('GET', 'scanner', '/api/v1/ai/targets', authorization)

    @app.get('/api/v1/settings/ai')
    async def foundry_settings(row=Depends(allowed), authorization: str = Header()):
        return await forward('GET', 'scanner', '/api/v1/settings/ai', authorization)

    @app.put('/api/v1/settings/ai')
    async def save_foundry_settings(request: Request, row=Depends(allowed), authorization: str = Header()):
        from app.schemas import bounded_json
        return await upstream('PUT', targets['scanner'], '/api/v1/settings/ai', authorization,
                              json=await bounded_json(request), transport=transport)

    @app.post('/api/v1/settings/ai/test-connection')
    async def test_foundry_connection(request: Request, row=Depends(allowed), authorization: str = Header()):
        return await post_json('/api/v1/settings/ai/test-connection', request, authorization)

    @app.get('/api/v1/ai/assessments')
    async def ai_history(request: Request, row=Depends(allowed), authorization: str = Header()):
        params={k:v for k,v in request.query_params.items() if k in ('limit','before','scan_id','resource_reference')}
        return await forward('GET','scanner','/api/v1/ai/assessments',authorization,params)

    @app.get('/api/v1/ai/assessments/{assessment_id}')
    async def ai_record(assessment_id: UUID,row=Depends(allowed),authorization: str = Header()):
        return await forward('GET','scanner',f'/api/v1/ai/assessments/{assessment_id}',authorization)

    @app.get('/api/v1/ai/usage')
    async def ai_usage(days: int = Query(30,ge=1,le=90),row=Depends(allowed),authorization: str = Header()):
        return await forward('GET','scanner','/api/v1/ai/usage',authorization,{'days':days})

    @app.get('/api/v1/finops/imports')
    async def billing_imports(limit: int = Query(25,ge=1,le=100),row=Depends(allowed),authorization: str = Header()):
        return await forward('GET','scanner','/api/v1/finops/imports',authorization,{'limit':limit})

    @app.post('/api/v1/finops/imports',status_code=201)
    async def billing_import(request: Request,row=Depends(allowed),authorization: str = Header()):
        return await post_json('/api/v1/finops/imports',request,authorization)

    @app.get('/api/v1/finops/summary')
    async def billing_summary(request: Request,row=Depends(allowed),authorization: str = Header()):
        params={k:v for k,v in request.query_params.items() if k in ('start','end','currency','budget')}
        return await forward('GET','scanner','/api/v1/finops/summary',authorization,params)

    @app.post('/api/v1/finops/resource-cost')
    async def resource_cost(request: Request, row=Depends(allowed), authorization: str = Header()):
        params = {k: v for k, v in request.query_params.items() if k in ('resource_id', 'scope_id')}
        return await forward('POST', 'scanner', '/api/v1/finops/resource-cost', authorization, params)

    @app.get('/api/v1/finops/unit-economics/preview')
    async def unit_economics_preview(request: Request, row=Depends(allowed), authorization: str = Header()):
        params = {k: v for k, v in request.query_params.items() if k in ('prior_cost', 'current_cost', 'prior_volume', 'current_volume')}
        return await forward('GET', 'scanner', '/api/v1/finops/unit-economics/preview', authorization, params)




    resource_filters = ('provider', 'service_category', 'review_priority', 'ai_status', 'ai_risk', 'decision', 'pillar_status', 'q', 'limit', 'offset')
    resource_key = Path(pattern=r'^[a-f0-9]{64}$')












    @app.get('/api/v1/scans/{scan_id}/kubernetes')
    async def kubernetes_view(scan_id: UUID, row=Depends(allowed), authorization: str = Header()):
        return await forward('GET', 'scanner', f'/api/v1/scans/{scan_id}/kubernetes', authorization)

    @app.post('/api/v1/scans/{scan_id}/kubernetes/patch-preview')
    async def kubernetes_patch(scan_id: UUID, request: Request, row=Depends(allowed), authorization: str = Header()):
        return await post_json(f'/api/v1/scans/{scan_id}/kubernetes/patch-preview', request, authorization)

    def selected_params(request, names):
        return {k: v for k, v in request.query_params.items() if k in names}

    @app.get('/api/v1/rules/effective')
    async def effective_rules(row=Depends(allowed), authorization: str = Header()):
        return await forward('GET', 'scanner', '/api/v1/rules/effective', authorization)

    @app.post('/api/v1/rules/preview')
    async def preview_rules(request: Request, row=Depends(allowed), authorization: str = Header()):
        return await post_json('/api/v1/rules/preview', request, authorization)

    @app.put('/api/v1/rules/overrides')
    async def save_rules(request: Request, row=Depends(allowed), authorization: str = Header()):
        from app.schemas import bounded_json
        return await upstream('PUT', targets['scanner'], '/api/v1/rules/overrides', authorization,
                              json=await bounded_json(request), transport=transport)



    @app.get('/api/v1/scans/{scan_id}/resources')
    async def resources(scan_id: UUID, request: Request, row=Depends(allowed), authorization: str = Header()):
        return await forward('GET', 'scanner', f'/api/v1/scans/{scan_id}/resources', authorization, selected_params(request, resource_filters))

    @app.get('/api/v1/scans/{scan_id}/resources/export')
    async def resources_export(scan_id: UUID, request: Request, row=Depends(allowed), authorization: str = Header()):
        return await forward('GET', 'scanner', f'/api/v1/scans/{scan_id}/resources/export', authorization,
                             selected_params(request, resource_filters[:-2]))

    @app.get('/api/v1/scans/{scan_id}/resources/{key}')
    async def resource_detail(scan_id: UUID, key: str = resource_key, row=Depends(allowed), authorization: str = Header()):
        return await forward('GET', 'scanner', f'/api/v1/scans/{scan_id}/resources/{key}', authorization)

    @app.post('/api/v1/scans/{scan_id}/resources/{key}/questions')
    async def resource_question(scan_id: UUID, request: Request, key: str = resource_key, row=Depends(allowed), authorization: str = Header()):
        return await post_json(f'/api/v1/scans/{scan_id}/resources/{key}/questions', request, authorization)

    @app.post('/api/v1/scans/{scan_id}/ai-batches')
    async def create_ai_batch(scan_id: UUID, request: Request, row=Depends(allowed), authorization: str = Header()):
        return await post_json(f'/api/v1/scans/{scan_id}/ai-batches', request, authorization)

    @app.get('/api/v1/ai-batches')
    async def ai_batches(request: Request, row=Depends(allowed), authorization: str = Header()):
        return await forward('GET', 'scanner', '/api/v1/ai-batches', authorization, selected_params(request, ('scan_id', 'limit')))

    @app.get('/api/v1/ai-batches/{batch_id}')
    async def ai_batch(batch_id: UUID, row=Depends(allowed), authorization: str = Header()):
        return await forward('GET', 'scanner', f'/api/v1/ai-batches/{batch_id}', authorization)

    @app.post('/api/v1/ai-batches/{batch_id}/cancel')
    async def cancel_ai_batch(batch_id: UUID, row=Depends(allowed), authorization: str = Header()):
        return await forward('POST', 'scanner', f'/api/v1/ai-batches/{batch_id}/cancel', authorization)

    @app.get('/api/v1/resources/{key}/history')
    async def resource_history(key: str = resource_key, row=Depends(allowed), authorization: str = Header()):
        return await forward('GET', 'scanner', f'/api/v1/resources/{key}/history', authorization)

    @app.get('/api/v1/resources/{key}/decisions')
    async def resource_decisions(key: str = resource_key, row=Depends(allowed), authorization: str = Header()):
        return await forward('GET', 'scanner', f'/api/v1/resources/{key}/decisions', authorization)

    @app.post('/api/v1/resources/{key}/decisions')
    async def record_resource_decision(request: Request, key: str = resource_key, row=Depends(allowed), authorization: str = Header()):
        return await post_json(f'/api/v1/resources/{key}/decisions', request, authorization)

    @app.get('/api/v1/analytics')
    async def analytics(row=Depends(allowed), authorization: str = Header()):
        return await forward('GET', 'analytics', '/api/v1/analytics', authorization)



    @app.post('/api/v1/scans/{scan_id}/cancel')
    async def cancel_scan(scan_id: UUID, row=Depends(allowed), authorization: str = Header()):
        return await forward('POST', 'scanner', f'/api/v1/scans/{scan_id}/cancel', authorization)

    @app.post('/api/v1/notifications/{scan_id}',status_code=202)
    async def notify(scan_id: UUID, row=Depends(allowed), authorization: str = Header()):
        return await forward('POST', 'notification', f'/api/v1/notifications/{scan_id}', authorization)

    from app.schemas import bounded_json

    async def tenant_write(method, path, request, authorization):
        return await upstream(method, targets['tenant'], path, authorization,
                              json=await bounded_json(request), transport=transport)

    @app.get('/api/v1/settings')
    async def workspace_settings(row=Depends(allowed), authorization: str = Header()):
        return await forward('GET', 'tenant', '/api/v1/settings', authorization)

    @app.put('/api/v1/settings')
    async def update_workspace_settings(request: Request, row=Depends(allowed), authorization: str = Header()):
        return await tenant_write('PUT', '/api/v1/settings', request, authorization)

    @app.post('/api/v1/settings/access-test')
    async def workspace_access_test(row=Depends(allowed), authorization: str = Header()):
        return await forward('POST', 'tenant', '/api/v1/settings/access-test', authorization)

    @app.get('/api/v1/gitops/targets')
    async def gitops_targets(row=Depends(allowed),authorization:str=Header()):
        return await forward('GET','scanner','/api/v1/gitops/targets',authorization)


    @app.get('/api/v1/gitops/requests')
    async def gitops_requests(row=Depends(allowed),authorization:str=Header(),limit:int=Query(50,ge=1,le=100)):
        return await forward('GET','scanner','/api/v1/gitops/requests',authorization,{'limit':limit})


    @app.get('/api/v1/gitops/requests/{request_id}')
    async def gitops_request(request_id:UUID,row=Depends(allowed),authorization:str=Header()):
        return await forward('GET','scanner',f'/api/v1/gitops/requests/{request_id}',authorization)

    @app.get('/api/v1/gitops/resource-mapping')
    async def gitops_resource_mapping(resource_id: str = Query(..., min_length=1, max_length=2048), row=Depends(allowed), authorization: str = Header()):
        return await forward('GET', 'scanner', '/api/v1/gitops/resource-mapping', authorization, {'resource_id': resource_id})


    @app.post('/api/v1/gitops/preview')
    async def gitops_preview(request:Request,row=Depends(allowed),authorization:str=Header()):
        return await post_json('/api/v1/gitops/preview',request,authorization)


    @app.post('/api/v1/gitops/requests',status_code=201)
    async def gitops_publish(request:Request,row=Depends(allowed),authorization:str=Header()):
        return await post_json('/api/v1/gitops/requests',request,authorization)


    @app.post('/api/v1/policies/terraform/evaluate')
    async def terraform_policy(request:Request,row=Depends(allowed),authorization:str=Header()):
        return await post_json('/api/v1/policies/terraform/evaluate',request,authorization)


    @app.get('/api/v1/scans/{scan_id}/analysis')
    async def analysis(scan_id: UUID, row=Depends(allowed), authorization: str = Header()):
        return await forward('GET', 'scanner', f'/api/v1/scans/{scan_id}/analysis', authorization)


    @app.post('/api/v1/scans/{scan_id}/analysis/resource')
    async def resource_analysis(scan_id: UUID, request: Request, row=Depends(allowed), authorization: str = Header()):
        return await post_json(f'/api/v1/scans/{scan_id}/analysis/resource', request, authorization)


    @app.post('/api/v1/scans/{scan_id}/ai-risk-evaluation')
    async def ai_review(scan_id: UUID, request: Request, row=Depends(allowed), authorization: str = Header()):
        return await post_json(f'/api/v1/scans/{scan_id}/ai-risk-evaluation', request, authorization)


    @app.post('/api/v1/scans/{scan_id}/remediation')
    async def remediation(scan_id: UUID, payload: RemediationRequest, row=Depends(allowed), authorization: str = Header()):
        return await upstream('POST', targets['scanner'], f'/api/v1/scans/{scan_id}/remediation',
                              authorization, json=payload.model_dump(), transport=transport)


    @app.post('/api/v1/scans/{scan_id}/remediation-terraform')
    async def remediation_terraform(scan_id: UUID, payload: RemediationRequest, row=Depends(allowed), authorization: str = Header()):
        return await upstream('POST', targets['scanner'], f'/api/v1/scans/{scan_id}/remediation-terraform',
                              authorization, json=payload.model_dump(), transport=transport)


    return app
