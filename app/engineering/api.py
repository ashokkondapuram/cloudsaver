"""Review-only engineering routes preserve existing /api/v1 contracts."""
import json
import re
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from pydantic import ValidationError
from app.auth import Role, require_workspace_role
from app.gitops_api import bounded_json
from app.engineering.contracts import WorkloadCreate, WorkloadUpdate, MemberCreate, PlanCreate, PlanRevision
from app.engineering.readiness import POLICY, RULES
from app.engineering import responses as out
from app.engineering.repository import Engineering, EngineeringError, scopes


def request_schema(model):
    return {'requestBody':{'required':True,'content':{'application/json':{'schema':model.model_json_schema()}}}}


def create_router(evidence_store, current_tenant):
    router=APIRouter(prefix='/api/v1/engineering',tags=['Engineering reviews'])
    repo=Engineering(evidence_store)

    def admin(tenant=Depends(current_tenant)):
        require_workspace_role(tenant,Role.TENANT_ADMIN)
        return tenant

    def command(idempotency_key: str = Header(default='',max_length=36), if_match: str | None = Header(default=None,max_length=20)):
        try:
            key=str(UUID(idempotency_key))
        except ValueError:
            raise HTTPException(422,'A UUID Idempotency-Key is required') from None
        if if_match is not None and not re.fullmatch(r'"[1-9][0-9]{0,9}"',if_match):
            raise HTTPException(422,'If-Match must be a quoted positive version')
        return key,int(if_match[1:-1]) if if_match else None

    async def body(request,model):
        try:
            return model.model_validate_json(json.dumps(await bounded_json(request),allow_nan=False))
        except (ValidationError,ValueError):
            raise HTTPException(422,'Invalid engineering input; check the fields and identifiers') from None

    def call(fn,*args):
        try:
            return fn(*args)
        except EngineeringError as error:
            raise HTTPException(error.status,str(error)) from None

    @router.get('/capabilities',response_model=out.Capabilities)
    def capabilities(tenant=Depends(current_tenant)):
        return dict(schema_version=1,stage='local_review',execution_enabled=False,policy=POLICY,
                    scopes=[dict(provider='azure',scope_id=s) for s in scopes(tenant)],
                    actions=[dict(id=k,rule_id=v,rule_version='1',mode='review_only',sandbox_verified=False) for k,v in RULES.items()],
                    limits=dict(workloads=1000,members_per_workload=1000,plans_per_workload=1000,versions_per_plan=1000),
                    acceptance_required=['native_api_permissions','resource_incarnation','historical_guest_memory','application_slo',
                                         'terraform_state_ownership','protected_pipeline_attestation','independent_approval','billing_reconciliation'])

    @router.get('/workloads',response_model=out.Page[out.Workload])
    def workloads(limit:int=Query(50,ge=1,le=200),cursor:str|None=Query(None,max_length=1000),tenant=Depends(current_tenant)):
        return call(repo.workloads,tenant,limit,cursor)

    @router.post('/workloads',status_code=201,openapi_extra=request_schema(WorkloadCreate),response_model=out.Workload)
    async def create(request:Request,response:Response,tenant=Depends(admin),headers=Depends(command)):
        value=call(repo.create,tenant,await body(request,WorkloadCreate),headers[0])
        response.headers['Location']='/api/v1/engineering/workloads/'+value['id']
        response.headers['ETag']='"'+str(value['version'])+'"'
        return value

    @router.get('/workloads/{workload_id}',response_model=out.Workload)
    def detail(workload_id:UUID,response:Response,tenant=Depends(current_tenant)):
        value=call(repo.detail,tenant,str(workload_id))
        response.headers['ETag']='"'+str(value['version'])+'"'
        return value

    @router.patch('/workloads/{workload_id}',openapi_extra=request_schema(WorkloadUpdate),response_model=out.Workload)
    async def update(workload_id:UUID,request:Request,response:Response,tenant=Depends(admin),headers=Depends(command)):
        value=call(repo.update,tenant,str(workload_id),await body(request,WorkloadUpdate),*headers)
        response.headers['ETag']='"'+str(value['version'])+'"'
        return value

    @router.get('/workloads/{workload_id}/members',response_model=out.Page[out.Member],response_model_exclude_unset=True)
    def members(workload_id:UUID,limit:int=Query(50,ge=1,le=200),cursor:str|None=Query(None,max_length=1000),tenant=Depends(current_tenant)):
        return call(repo.members,tenant,str(workload_id),limit,cursor)

    @router.post('/workloads/{workload_id}/members',status_code=201,openapi_extra=request_schema(MemberCreate),response_model=out.MemberCreated)
    async def member(workload_id:UUID,request:Request,tenant=Depends(admin),headers=Depends(command)):
        return call(repo.add_member,tenant,str(workload_id),await body(request,MemberCreate),*headers)

    @router.get('/workloads/{workload_id}/plans',response_model=out.Page[out.Plan],response_model_exclude_unset=True)
    def plans(workload_id:UUID,limit:int=Query(50,ge=1,le=200),cursor:str|None=Query(None,max_length=1000),tenant=Depends(current_tenant)):
        return call(repo.plans,tenant,str(workload_id),limit,cursor)

    @router.post('/workloads/{workload_id}/plans',status_code=201,openapi_extra=request_schema(PlanCreate),response_model=out.Version,response_model_exclude_unset=True)
    async def plan(workload_id:UUID,request:Request,tenant=Depends(admin),headers=Depends(command)):
        return call(repo.save_plan,tenant,str(workload_id),await body(request,PlanCreate),*headers)

    @router.get('/plans/{plan_id}/versions',response_model=out.Page[out.Version],response_model_exclude_unset=True)
    def versions(plan_id:UUID,limit:int=Query(50,ge=1,le=200),cursor:str|None=Query(None,max_length=1000),tenant=Depends(current_tenant)):
        return call(repo.versions,tenant,str(plan_id),limit,cursor)

    @router.post('/workloads/{workload_id}/plans/{plan_id}/versions',status_code=201,openapi_extra=request_schema(PlanRevision),response_model=out.Version,response_model_exclude_unset=True)
    async def revision(workload_id:UUID,plan_id:UUID,request:Request,tenant=Depends(admin),headers=Depends(command)):
        return call(repo.save_plan,tenant,str(workload_id),await body(request,PlanRevision),*headers,str(plan_id))

    @router.get('/workloads/{workload_id}/events',response_model=out.Page[out.Event],response_model_exclude_unset=True)
    def events(workload_id:UUID,limit:int=Query(50,ge=1,le=200),cursor:str|None=Query(None,max_length=1000),tenant=Depends(current_tenant)):
        return call(repo.events,tenant,str(workload_id),limit,cursor)

    return router
