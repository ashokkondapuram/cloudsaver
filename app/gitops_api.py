"""Authenticated CI evaluation and explicit owned-scan GitOps review actions."""
import os
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.concurrency import run_in_threadpool

from app.auth import Role, require_workspace_role
from app.entitlements import enforce_terraform_export
from app.gitops import GitHubApp, GitOpsConfig, GitOpsFailure, GitOpsUnavailable, build_review
from app.gitops_store import ReviewConflict, ReviewRepository
from app.plan_policy import MAX_BYTES, InvalidPlan, PlanPolicy, evaluate_plan, load_json


class ReviewRequest(BaseModel):
    scan_id: UUID
    target_id: str = Field(pattern=r'^[a-z][a-z0-9_-]{0,39}$')
    resource_ids: list[str] = Field(min_length=1,max_length=50)
    model_config = ConfigDict(extra='forbid')


class PublishRequest(ReviewRequest):
    idempotency_key: str = Field(min_length=16,max_length=128,pattern=r'^[A-Za-z0-9_-]+$')


async def bounded_json(request):
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw)>MAX_BYTES:
            raise HTTPException(413,'Request exceeds the 2 MB limit')
    try:
        return load_json(bytes(raw))
    except InvalidPlan:
        raise HTTPException(422,'Invalid or unsupported JSON request') from None


def create_router(settings,store,current_tenant,*,config=None,client=None):
    router = APIRouter()
    config = config or GitOpsConfig.load()
    repository = ReviewRepository(store)
    policy = PlanPolicy.from_dict(load_json(os.getenv('CLOUDSAVER_PLAN_POLICY') or '{}'))

    def package(payload,tenant):
        require_workspace_role(tenant,Role.TENANT_ADMIN)
        enforce_terraform_export(tenant)
        scan = store.get(tenant['tenant_id'],str(payload.scan_id))
        if scan is None:
            raise HTTPException(404,'Scan not found')
        try:
            target = config.target(tenant['tenant_id'],payload.target_id)
            result = build_review(scan,payload.resource_ids,tenant,target)
        except ValueError as exc:
            raise HTTPException(422,str(exc)) from None
        return target,result

    @router.post('/api/v1/gitops/sync-agent')
    async def sync_agent(request:Request,tenant=Depends(current_tenant)):
        require_workspace_role(tenant,Role.TENANT_ADMIN)
        enforce_terraform_export(tenant)
        from app.agent_store import AgentRepository
        from app.agent_contract import connectors
        from app.agent_gitops_sync import build_synchronized_agent_gitops_bundle
        from app.enterprise_store import EnterpriseStore
        raw=await bounded_json(request)
        try:
            if not isinstance(raw,dict) or set(raw)!={'task_id','plan_hash'}:raise ValueError()
            task_id=str(UUID(raw['task_id']))
            task=AgentRepository(EnterpriseStore(settings)).get(tenant,task_id)
            if not task:raise HTTPException(404,'Owned agent task not found')
            if raw['plan_hash']!=task['payload'].get('plan_hash'):raise HTTPException(409,'Task plan changed')
            scan=store.get(tenant['tenant_id'],task['scan_id'])
            return build_synchronized_agent_gitops_bundle(task,tenant,scan,config,connectors())
        except (ValueError,KeyError,TypeError):
            raise HTTPException(422,'An owned drafted task, exact plan hash and configured paired connector are required') from None

    @router.post('/api/v1/gitops/preview-and-evaluate')
    async def automatic_preview(request:Request,tenant=Depends(current_tenant)):
        raw=await bounded_json(request)
        try:payload=ReviewRequest.model_validate(raw)
        except ValidationError:raise HTTPException(422,'Provide an owned scan, target and selected resources') from None
        _,result=await run_in_threadpool(package,payload,tenant)
        return dict(review=result,policy=dict(decision='review_required',projection_only=True,automatic_apply=False,
            reasons=['Import/configuration review is generated automatically. Repository CI must supply the actual Terraform plan.']),
            monthly_cost_delta_usd=None)

    @router.get('/api/v1/gitops/targets')
    def targets(tenant=Depends(current_tenant)):
        return dict(publishing_enabled=config.enabled,targets=[{k:t[k] for k in ('target_id','repository','base_branch')}
                    for t in config.targets if t['tenant_id']==tenant['tenant_id']])

    @router.get('/api/v1/gitops/syncs')
    def linked_history(tenant=Depends(current_tenant)):
        from app.enterprise_store import EnterpriseStore
        from app.v150_store import WorkflowStore
        return dict(items=WorkflowStore(EnterpriseStore(settings)).rows(tenant['tenant_id'],'agent_gitops_syncs'))

    @router.post('/api/v1/policies/terraform/evaluate')
    async def evaluate(request:Request,tenant=Depends(current_tenant)):
        payload = await bounded_json(request)
        try:
            if not isinstance(payload,dict) or set(payload)-{'plan','infracost'} or 'plan' not in payload:
                raise InvalidPlan('Invalid evaluation request')
            return await run_in_threadpool(evaluate_plan,payload['plan'],policy=policy,infracost=payload.get('infracost'))
        except (InvalidPlan,ValueError,TypeError,KeyError,AttributeError,RecursionError):
            raise HTTPException(422,'Invalid, incomplete or unsupported Terraform/Infracost input; raw values were not retained') from None

    @router.post('/api/v1/gitops/preview')
    async def preview(request:Request,tenant=Depends(current_tenant)):
        raw = await bounded_json(request)
        try:
            payload = ReviewRequest.model_validate(raw)
        except ValidationError:
            raise HTTPException(422,'Provide a scan UUID, configured target and 1–50 resource IDs') from None
        _,result = await run_in_threadpool(package,payload,tenant)
        return result

    @router.get('/api/v1/gitops/requests')
    def history(limit:int=50,tenant=Depends(current_tenant)):
        from app.data_scope import scan_visible
        if not 1<=limit<=100:
            raise HTTPException(422,'limit must be between 1 and 100')
        items = [row for row in repository.list(tenant['tenant_id'],limit) if scan_visible(store, tenant, row['scan_id'])]
        return items

    @router.get('/api/v1/gitops/requests/{request_id}')
    def detail(request_id:UUID,tenant=Depends(current_tenant)):
        from app.data_scope import scan_visible
        row = repository.get(tenant['tenant_id'],str(request_id))
        if row is None or not scan_visible(store, tenant, row['scan_id']):
            raise HTTPException(404,'Review request not found')
        return row

    def publish_request(payload,tenant):
        target,result = package(payload,tenant)
        if not config.enabled:
            raise HTTPException(503,'GitHub draft publishing is disabled; configure an operator-approved target and GitHub App')
        token = str(uuid4())
        try:
            id = repository.reserve(tenant['tenant_id'],payload.idempotency_key,result)
            if not repository.claim(tenant['tenant_id'],id,token):
                return repository.get(tenant['tenant_id'],id)
            try:
                published = (client or GitHubApp(config.app_id)).publish(target,result)
            except (GitOpsFailure,GitOpsUnavailable):
                repository.finish(tenant['tenant_id'],id,token)
                raise HTTPException(502,'GitHub result is uncertain. Inspect request history and retry with the same key; no branch was force-updated') from None
            except Exception:
                repository.finish(tenant['tenant_id'],id,token)
                raise HTTPException(502,'GitHub publishing did not complete; inspect history and retry with the same key') from None
            repository.finish(tenant['tenant_id'],id,token,published)
            return repository.get(tenant['tenant_id'],id)
        except ReviewConflict as exc:
            raise HTTPException(409,str(exc)) from None

    @router.post('/api/v1/gitops/requests',status_code=201)
    async def publish(request:Request,tenant=Depends(current_tenant)):
        raw = await bounded_json(request)
        try:
            payload = PublishRequest.model_validate(raw)
        except ValidationError:
            raise HTTPException(422,'Provide review selection and a 16–128 character idempotency key') from None
        return await run_in_threadpool(publish_request,payload,tenant)

    return router
