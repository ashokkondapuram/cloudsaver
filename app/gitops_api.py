"""Authenticated CI evaluation and explicit owned-scan GitOps review actions."""
import os
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.concurrency import run_in_threadpool

from app.auth import Role, require_workspace_role
from app.entitlements import enforce_terraform_export
from app.gitops import GitHubApp, GitOpsConfig, GitOpsFailure, GitOpsUnavailable, build_review
from app.gitops_vcs import repository_label
from app.gitops_store import ReviewConflict, ReviewRepository
from app.plan_policy import MAX_BYTES, InvalidPlan, PlanPolicy, evaluate_plan, load_json


class ReviewRequest(BaseModel):
    scan_id: UUID
    target_id: str = Field(pattern=r'^[a-z][a-z0-9_-]{0,39}$')
    resource_ids: list[str] = Field(min_length=1,max_length=50)
    model_config = ConfigDict(extra='forbid')


class PublishRequest(ReviewRequest):
    idempotency_key: str = Field(min_length=16,max_length=128,pattern=r'^[A-Za-z0-9_-]+$')


class PullRequestRemediation(BaseModel):
    canonical_resource_id: str = Field(min_length=1, max_length=2048)
    target_id: str = Field(pattern=r'^[a-z][a-z0-9_-]{0,39}$')
    attribute: str = Field(min_length=1, max_length=80, pattern=r'^[A-Za-z0-9_.]+$')
    new_value_token: str = Field(min_length=1, max_length=120)
    base_file_sha: str = Field(min_length=40, max_length=40, pattern=r'^[0-9a-f]{40}$')
    branch_suffix: str | None = Field(default=None, max_length=80, pattern=r'^[a-z0-9-]+$')
    model_config = ConfigDict(extra='forbid')


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
        rows = []
        for t in config.targets:
            if t['tenant_id'] != tenant['tenant_id']:
                continue
            rows.append(
                dict(
                    target_id=t['target_id'],
                    vcs_provider=t.get('vcs_provider', 'github'),
                    repository=repository_label(t),
                    base_branch=t['base_branch'],
                )
            )
        return dict(publishing_enabled=config.enabled, targets=rows)

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

    @router.get('/api/v1/gitops/resource-mapping')
    def resource_mapping(resource_id: str = Query(..., min_length=1, max_length=2048), tenant=Depends(current_tenant)):
        from app.cloud_scope import validate_finding_scope
        from app.data_scope import resource_visible
        from app.enterprise_store import EnterpriseStore
        from app.gitops_ast_mapper import GitOpsAstMapper
        scan = next(iter(store.list(tenant['tenant_id'], 50)), None)
        rows = (scan or {}).get('inventory') or (scan or {}).get('findings') or []
        def matches(row):
            candidate = row.get('resource_id', '')
            return candidate.lower() == resource_id.lower() if row.get('cloud_provider', 'azure') == 'azure' else candidate == resource_id
        owned = next((row for row in rows if matches(row)), None)
        if owned is None:
            raise HTTPException(404, 'Resource mapping not found')
        persistence = EnterpriseStore(settings)
        mapper = GitOpsAstMapper.for_tenant(persistence, tenant["tenant_id"])
        try:
            validate_finding_scope(owned, tenant)
            provider = owned.get('cloud_provider', 'azure')
            if not resource_visible(tenant, provider, owned.get('scope_id') or owned.get('subscription_id')):
                raise ValueError('Resource is outside the current scope')
            mapping = mapper.lookup(owned['resource_id'])
            repositories = {repository_label(row) for row in config.targets if row['tenant_id'] == tenant['tenant_id']}
            if mapping.repository not in repositories:
                raise ValueError('Repository is not granted')
            return mapping
        except (ValueError, KeyError):
            raise HTTPException(404, 'Resource mapping not found') from None

    @router.post('/api/v1/gitops/requests',status_code=201)
    async def publish(request:Request,tenant=Depends(current_tenant)):
        raw = await bounded_json(request)
        try:
            payload = PublishRequest.model_validate(raw)
        except ValidationError:
            raise HTTPException(422,'Provide review selection and a 16–128 character idempotency key') from None
        return await run_in_threadpool(publish_request,payload,tenant)

    def queue_pull_request(payload: PullRequestRemediation, tenant):
        from app.drift.outbox_store import (
            GitOpsRemediationStore,
            gitops_pr_idempotency_key,
            new_request_id,
        )
        from app.enterprise_store import EnterpriseStore
        from app.gitops_ast_mapper import GitOpsAstMapper
        from app.cloud_scope import validate_finding_scope
        from app.data_scope import resource_visible

        require_workspace_role(tenant, Role.TENANT_ADMIN)
        enforce_terraform_export(tenant)
        scan = next(iter(store.list(tenant['tenant_id'], 50)), None)
        rows = (scan or {}).get('inventory') or (scan or {}).get('findings') or []

        def matches(row):
            candidate = row.get('resource_id', '')
            rid = payload.canonical_resource_id
            return candidate.lower() == rid.lower() if row.get('cloud_provider', 'azure') == 'azure' else candidate == rid

        owned = next((row for row in rows if matches(row)), None)
        if owned is None:
            raise HTTPException(404, 'Resource not found for GitOps remediation')
        persistence = EnterpriseStore(settings)
        mapper = GitOpsAstMapper.for_tenant(persistence, tenant['tenant_id'])
        try:
            validate_finding_scope(owned, tenant)
            provider = owned.get('cloud_provider', 'azure')
            if not resource_visible(tenant, provider, owned.get('scope_id') or owned.get('subscription_id')):
                raise ValueError('Resource is outside the current scope')
            mapping = mapper.lookup(owned["resource_id"]).model_dump()
            if not mapping.get('start_line') or not mapping.get('indexed_commit_sha'):
                raise ValueError('AST mapping is incomplete; reindex required')
            repositories = {repository_label(row) for row in config.targets if row['tenant_id'] == tenant['tenant_id']}
            if mapping['repository'] not in repositories:
                raise ValueError('Repository is not granted')
            config.target(tenant['tenant_id'], payload.target_id)
        except (ValueError, KeyError):
            raise HTTPException(404, 'Resource mapping not found or not granted') from None

        diff_key = f"{payload.attribute}={payload.new_value_token}"
        idem = gitops_pr_idempotency_key(
            tenant['tenant_id'],
            payload.canonical_resource_id,
            diff_key,
            mapping['indexed_commit_sha'],
        )
        request_id = new_request_id(tenant['tenant_id'], idem)
        body = dict(
            canonical_resource_id=payload.canonical_resource_id.lower()
            if owned.get('cloud_provider', 'azure') == 'azure'
            else payload.canonical_resource_id,
            target_id=payload.target_id,
            attribute=payload.attribute,
            new_value_token=payload.new_value_token,
            base_file_sha=payload.base_file_sha,
            branch_suffix=payload.branch_suffix,
            mapping=mapping,
        )
        persistence = EnterpriseStore(settings)
        queued = GitOpsRemediationStore(persistence).queue_with_outbox(
            tenant['tenant_id'],
            dict(id=request_id, idempotency_key=idem, canonical_resource_id=body['canonical_resource_id'], payload=body),
        )
        return queued

    @router.post('/api/v1/gitops/pull-requests', status_code=202)
    async def pull_requests(request: Request, tenant=Depends(current_tenant)):
        raw = await bounded_json(request)
        try:
            payload = PullRequestRemediation.model_validate(raw)
        except ValidationError:
            raise HTTPException(422, 'Provide resource, target, attribute patch, and base file SHA') from None
        return await run_in_threadpool(queue_pull_request, payload, tenant)

    @router.post('/api/v1/gitops/pre-merge/evaluate')
    async def pre_merge_evaluate(request: Request, tenant=Depends(current_tenant)):
        from app.gitops_pre_merge_firewall import score_pull_request, webhook_comment_body

        require_workspace_role(tenant, Role.TENANT_ADMIN)
        raw = await bounded_json(request)
        if not isinstance(raw, dict):
            raise HTTPException(422, "Invalid pre-merge payload")
        try:
            score = score_pull_request(
                plan_json=raw.get("plan"),
                files_changed=list(raw.get("files_changed") or []),
            )
        except (TypeError, ValueError) as error:
            raise HTTPException(422, str(error)) from None
        return dict(scorecard=score, comment=webhook_comment_body(score))

    @router.post("/api/v1/gitops/ast/sync", status_code=202)
    async def ast_sync(tenant=Depends(current_tenant)):
        from app.enterprise_store import EnterpriseStore
        from app.gitops_ast_sync import GitOpsAstSyncService

        require_workspace_role(tenant, Role.TENANT_ADMIN)
        targets = tuple(row for row in config.targets if row["tenant_id"] == tenant["tenant_id"])
        if not targets:
            raise HTTPException(422, "Configure at least one GitOps target before AST sync")
        service = GitOpsAstSyncService(EnterpriseStore(settings))
        return await run_in_threadpool(service.sync_env_index, tenant["tenant_id"], targets)

    return router
