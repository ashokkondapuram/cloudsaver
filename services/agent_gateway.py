"""Human approval API and private worker assignment gateway. No MCP protocol."""
import hashlib
import hmac
import json
import os
import re
from typing import Literal
from uuid import UUID

from fastapi import Depends, Header, HTTPException
from pydantic import Field, field_validator

from app.agent_contract import Strict, connectors, render_code
from app.agent_store import AgentConflict, AgentRepository
from app.auth import Role, require_workspace_role
from app.enterprise_store import EnterpriseStore
from app.principals import visible
from app.telemetry_contract import moment
from services.common import service


class TaskRequest(Strict):
    scan_id: str
    resource_id: str = Field(min_length=1,max_length=2048)
    request_key: str
    intent: str = Field(min_length=5,max_length=1500)
    target_id: str = Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,59}$')
    connector_ids: list[str] = Field(min_length=1,max_length=8)

    @field_validator('scan_id','request_key')
    @classmethod
    def identifier(cls,value): return str(UUID(value))


class Review(Strict):
    version: int = Field(ge=1)
    decision: Literal['approve','reject','cancel','redraft']
    plan_hash: str | None = Field(default=None,pattern=r'^[a-f0-9]{64}$')
    expires_in_minutes: int = Field(default=15,ge=1,le=60)


class Claim(Strict):
    tenant_id: str

    @field_validator('tenant_id')
    @classmethod
    def identifier(cls,value): return str(UUID(value))


class Lease(Claim):
    lease_token: str = Field(min_length=32,max_length=128)


class Outcome(Strict):
    status: Literal['succeeded','failed','uncertain']
    code: str = Field(pattern=r'^[A-Z0-9_]{1,60}$')
    http_status: int | None = Field(default=None,ge=100,le=599)
    evidence_digest: str | None = Field(default=None,pattern=r'^[a-f0-9]{64}$')


class StepResult(Lease):
    plan_hash: str = Field(pattern=r'^[a-f0-9]{64}$')
    outcome: Outcome | None = None


def create_app(settings=None, identity_validator=None, planner=None, repository=None):
    app, settings, tenant = service('agent-gateway',settings,identity_validator)
    persistence = EnterpriseStore(settings)
    repo = repository or AgentRepository(persistence)
    if planner is None:
        from app.ai_advisory import AIGateway
        from app.inference_ledger import InferenceLedger
        from app.agent_planner import AgentPlanner
        planner = AgentPlanner(AIGateway(settings=settings,budget=InferenceLedger(persistence)))
    from app.provider_access import ScopedStore
    from app.store import Store, PostgresStore
    scans = ScopedStore(PostgresStore(settings.database_url) if settings.database_url else Store(settings.database))

    def catalog():
        try: return connectors()
        except (ValueError,TypeError): raise HTTPException(503,'Agent connector configuration is unavailable.') from None

    def enabled():
        if os.getenv('CLOUDSAVER_AGENT_ENABLED','false').lower() != 'true':
            raise HTTPException(503,'Agent execution is disabled by the deployment operator.')

    def required(task):
        if task is None: raise HTTPException(404,'Agent task not found')
        return task

    def call(fn,*args):
        try: return fn(*args)
        except AgentConflict as error: raise HTTPException(409,str(error)) from None
        except ValueError: raise HTTPException(422,'Agent plan or connector arguments failed validation.') from None

    def human(row):
        require_workspace_role(row,Role.TENANT_ADMIN)
        if row.get('key_id') or row.get('subject_type')=='service_account' or not (row.get('user_id') or row.get('subject_type')=='user' and row.get('subject_id')):
            raise HTTPException(403,'A verified human workspace administrator session must review this plan.')

    def worker_auth(authorization: str = Header(default='')):
        enabled()
        supplied = authorization.removeprefix('Bearer ')
        try:
            grants = json.loads(os.getenv('CLOUDSAVER_AGENT_WORKERS','[]'))
            if not isinstance(grants,list) or len(grants)>100: raise ValueError()
            matches = [g for g in grants if authorization.startswith('Bearer ') and len(supplied)>=32
                and hmac.compare_digest(g.get('token_sha256',''),hashlib.sha256(supplied.encode()).hexdigest())]
            if len(matches) != 1: raise HTTPException(401,'Invalid agent worker credential')
            grant = matches[0]
            if (set(grant)!={'id','token_sha256','tenant_ids','connector_ids'} or not re.fullmatch(r'[a-z][a-z0-9-]{0,59}',grant['id'])
                    or not isinstance(grant['tenant_ids'],list) or not isinstance(grant['connector_ids'],list)): raise ValueError()
            return grant
        except (ValueError,TypeError,KeyError): raise HTTPException(503,'Agent worker grants are unavailable.') from None

    def workspace(tid, worker):
        if tid not in worker['tenant_ids']: raise HTTPException(403,'Worker is not assigned to this workspace.')
        row = next((t for t in settings.tenants if t['tenant_id']==tid),None)
        if row is None: raise HTTPException(403,'Workspace is unavailable.')
        if (row.get('plan') or {}).get('access_suspended') is True: raise HTTPException(403,'Workspace product access is suspended.')
        return dict(row,roles=[],allowed_providers=None)

    @app.get('/api/v1/agents/catalog')
    def connector_catalog(row=Depends(tenant)):
        items = [c.model_dump() for c in catalog() if c.kind!='http_json' and c.tenant_id==row['tenant_id'] and visible({'provider':c.provider,'scope_id':c.scope_id},row)]
        return dict(enabled=os.getenv('CLOUDSAVER_AGENT_ENABLED','false').lower()=='true',connectors=items,
            runtime='typescript-runCode',approval_required=True,arbitrary_code=False,external_action_data_allowed=False)

    @app.get('/api/v1/agents/tasks')
    def tasks(row=Depends(tenant)): return dict(items=repo.list(row))

    @app.get('/api/v1/agents/tasks/{task_id}')
    def task_detail(task_id: UUID,row=Depends(tenant)):
        task = required(repo.get(row,str(task_id)))
        return dict(task,code=render_code(task['payload']['plan']) if task['payload']['plan'] else None)

    @app.post('/api/v1/agents/tasks',status_code=201)
    def create(body: TaskRequest,row=Depends(tenant)):
        enabled(); require_workspace_role(row,Role.TENANT_ADMIN)
        snapshot = scans.get(row['tenant_id'],body.scan_id)
        if not snapshot: raise HTTPException(404,'Owned scan not found')
        if snapshot.get('status')!='completed' or snapshot.get('mode')=='demo' or snapshot.get('data_origin')=='legacy_synthetic':
            raise HTTPException(409,'Agent tasks require a completed live scan.')
        if not moment(snapshot.get('timestamp')) or not 0 <= (repo.clock()-moment(snapshot['timestamp'])).total_seconds()<86400:
            raise HTTPException(409,'Run a fresh scan before requesting an agent task.')
        resource = next((r for r in snapshot.get('inventory',[]) if r['resource_id']==body.resource_id),None)
        if not resource: raise HTTPException(404,'Resource not found in the owned scan')
        provider = resource.get('cloud_provider','azure'); scope = resource.get('scope_id') or resource['subscription_id']
        if provider=='azure' and (any(p in {'.','..'} for p in body.resource_id.split('/')) or not re.fullmatch(r'/subscriptions/[a-fA-F0-9-]{36}/resourceGroups/[A-Za-z0-9_.()-]+/providers/[A-Za-z0-9.]+(?:/[A-Za-z0-9_.()-]+){2,}',body.resource_id,re.I)):
            raise HTTPException(422,'Unsupported ARM resource identifier.')
        selected = [c for c in catalog() if c.id in body.connector_ids and c.tenant_id==row['tenant_id'] and c.provider==provider and c.scope_id==scope]
        if len(set(body.connector_ids))!=len(body.connector_ids) or len(selected)!=len(body.connector_ids):
            raise HTTPException(403,'Choose connectors bound to this workspace and resource scope.')
        from app.agent_contract import supports_resource
        if any(not supports_resource(c,body.resource_id) for c in selected):raise HTTPException(403,'A connector does not support this resource type. Use a typed adapter binding for the selected resource.')
        from app.data_governance import DataGovernor,sanitize,DataDenied
        from app.ai_advisory import AIError
        governor=DataGovernor(persistence)
        try:
            sanitize({'instruction':body.intent},purpose='agent_planning')
            if any(c.kind=='http_json' for c in selected):raise DataDenied('EXTERNAL_ACTION_DATA_PROHIBITED')
            _,policy,_=governor.policy()
        except DataDenied as error:
            governor.event(row,'agent_planning','blocked',error.code,target_id=body.target_id,source_provider=provider,scope_id=scope)
            raise HTTPException(403,str(error)) from None
        except AIError as error:raise HTTPException(error.status,str(error)) from None
        return call(repo.create,row,snapshot,resource,dict(body.model_dump(),_retention_days=policy['response_retention_days']))

    @app.post('/api/v1/agents/tasks/{task_id}/review')
    def review(task_id: UUID,body: Review,row=Depends(tenant)):
        human(row)
        if body.decision in {'approve','redraft'}: enabled()
        return required(call(repo.review,row,str(task_id),body.version,body.decision,body.plan_hash,body.expires_in_minutes,catalog()))

    @app.post('/internal/v1/agent/claim')
    def claim(body: Claim,worker=Depends(worker_auth)):
        return dict(assignment=call(repo.claim,workspace(body.tenant_id,worker),worker,catalog()))

    @app.post('/internal/v1/agent/tasks/{task_id}/heartbeat')
    def heartbeat(task_id: UUID,body: Lease,worker=Depends(worker_auth)):
        return call(repo.heartbeat,workspace(body.tenant_id,worker),str(task_id),worker,body.lease_token)

    @app.post('/internal/v1/agent/tasks/{task_id}/draft')
    def draft(task_id: UUID,body: Lease,worker=Depends(worker_auth)):
        row = workspace(body.tenant_id,worker)
        task = call(repo.draft_input,row,str(task_id),worker,body.lease_token)
        from app.ai_advisory import AIError
        try: plan = planner(row,task,catalog())
        except AIError as error: raise HTTPException(error.status,str(error)) from None
        return call(repo.save_draft,row,str(task_id),worker,body.lease_token,plan,catalog())

    @app.post('/internal/v1/agent/tasks/{task_id}/steps/{index}/{action}')
    def step(task_id: UUID,index: int,action: Literal['start','complete'],body: StepResult,worker=Depends(worker_auth)):
        if index<0 or index>7 or (action=='start' and body.outcome is not None) or (action=='complete' and body.outcome is None):
            raise HTTPException(422,'Invalid step report')
        return call(repo.step,workspace(body.tenant_id,worker),str(task_id),worker,body.lease_token,index,action,body.plan_hash,
            body.outcome.model_dump() if body.outcome else None,catalog())

    @app.post('/internal/v1/agent/tasks/{task_id}/fail')
    def fail(task_id: UUID,body: Lease,worker=Depends(worker_auth)):
        return call(repo.fail,workspace(body.tenant_id,worker),str(task_id),worker,body.lease_token)

    return app
