"""Tenant-owned service analysis and explicit, operator-bound AI advisory requests."""
import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool, ValidationError

from app.assessment import assess, ai_context, summarize
from app.auth import Role, require_workspace_role
from app.cloud_scope import validate_finding_scope
from app.gitops_api import bounded_json
from app.ai_advisory import AIGateway, AIError


class Selection(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    resource_id: str = Field(min_length=1, max_length=2048)
    rule_id: str = Field(pattern=r'^[A-Z0-9_]{1,80}$')


class Evaluation(Selection):
    evidence_digest: str = Field(pattern=r'^[a-f0-9]{64}$')
    target_id: str = Field(pattern=r'^[a-z0-9-]{1,40}$')
    idempotency_key: UUID
    acknowledge_external_processing: StrictBool


async def payload(request, schema):
    try:
        # UUID parsing from JSON is intentional even though the remaining model is strict.
        return schema.model_validate_json(json.dumps(await bounded_json(request)))
    except ValidationError:
        raise HTTPException(422, 'Invalid analysis request; exact resource selection and explicit acknowledgement are required') from None


def create_router(settings, store, current_tenant, gateway=None, ledger=None):
    router = APIRouter(prefix='/api/v1')
    if ledger is None:
        from app.enterprise_store import EnterpriseStore
        from app.inference_ledger import InferenceLedger
        ledger = InferenceLedger(EnterpriseStore(settings))
    gateway = gateway or AIGateway(budget=ledger, settings=settings)

    def owned(scan_id, tenant):
        scan = store.get(tenant['tenant_id'], str(scan_id))
        if scan is None:
            raise HTTPException(404, 'Scan not found')
        if scan['status'] != 'completed' or scan.get('data_origin') == 'legacy_synthetic':
            raise HTTPException(409, 'Analysis requires a completed live scan observation')
        try:
            for finding in scan['findings']:
                validate_finding_scope(finding, tenant)
        except (ValueError, KeyError):
            raise HTTPException(409, 'The saved scan is outside the current workspace scope') from None
        return scan

    def selected(scan, selection, tenant):
        matches = [f for f in scan['findings'] if f['resource_id'] == selection.resource_id and f['rule_id'] == selection.rule_id]
        if len(matches) != 1:
            raise HTTPException(404, 'Unique finding not found in this scan')
        try:
            validate_finding_scope(matches[0], tenant)
        except (ValueError, KeyError):
            raise HTTPException(409, 'The saved finding is outside the current workspace scope') from None
        return matches[0]

    @router.get('/scans/{scan_id}/analysis')
    def service_analysis(scan_id: UUID, tenant=Depends(current_tenant)):
        return summarize(owned(scan_id, tenant))

    @router.post('/scans/{scan_id}/analysis/resource')
    async def resource_analysis(scan_id: UUID, request: Request, tenant=Depends(current_tenant)):
        selection = await payload(request, Selection)
        scan = owned(scan_id, tenant)
        finding = selected(scan, selection, tenant)
        result = assess(finding, observed_at=scan.get('timestamp'))
        return dict(assessment=result, ai_context=ai_context(finding, result))

    @router.get('/ai/targets')
    def ai_targets(tenant=Depends(current_tenant)):
        return gateway.available(tenant)

    @router.get('/ai/assessments')
    def assessment_history(limit: int = Query(25,ge=1,le=50), before: UUID | None = None,
                           scan_id: UUID | None = None, resource_reference: str | None = Query(None,pattern=r'^[a-f0-9]{64}$'),
                           tenant=Depends(current_tenant)):
        try:
            return ledger.page(tenant['tenant_id'],limit,str(before) if before else None,str(scan_id) if scan_id else None,resource_reference)
        except AIError as error:
            raise HTTPException(error.status,str(error)) from None

    @router.get('/ai/assessments/{assessment_id}')
    def assessment_record(assessment_id: UUID,tenant=Depends(current_tenant)):
        result=ledger.get(tenant['tenant_id'],str(assessment_id))
        if result is None:
            raise HTTPException(404,'Assessment not found')
        return result

    @router.get('/ai/usage')
    def usage(days: int = Query(30,ge=1,le=90),tenant=Depends(current_tenant)):
        try:
            return ledger.usage(tenant['tenant_id'],days)
        except AIError as error:
            raise HTTPException(error.status,str(error)) from None

    @router.post('/scans/{scan_id}/ai-risk-evaluation')
    async def ai_review(scan_id: UUID, request: Request, tenant=Depends(current_tenant)):
        require_workspace_role(tenant, Role.TENANT_ADMIN)
        selection = await payload(request, Evaluation)
        if selection.acknowledge_external_processing is not True:
            raise HTTPException(422, 'Acknowledge external processing of the displayed sanitized context')
        scan = owned(scan_id, tenant)
        finding = selected(scan, selection, tenant)
        result = assess(finding, observed_at=scan.get('timestamp'))
        if selection.evidence_digest != result['evidence_digest']:
            raise HTTPException(409, 'Assessment evidence changed; refresh and acknowledge the updated context')
        from app.inference_ledger import attribution
        from starlette.concurrency import run_in_threadpool
        try:
            return await run_in_threadpool(gateway.evaluate, tenant, selection.target_id, selection.idempotency_key,
                                           str(scan_id), ai_context(finding, result), result, attribution=attribution(finding))
        except AIError as error:
            raise HTTPException(error.status, str(error), headers={'Retry-After': '3600'} if error.status == 429 else None) from None
    return router
