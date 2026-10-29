"""REST surface for the control-plane plan/assessment/financial-scenario schema.

Business logic lives in app/control_plane/*; this module only translates HTTP
requests into those function calls and maps their exceptions to status codes."""
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.auth import Role, require_workspace_role
from app.control_plane import store as cp_store
from app.control_plane.action_safety import evaluate as evaluate_action_safety
from app.control_plane.contracts import ActionAssessmentRequest, FinancialScenarioRequest
from app.control_plane.financial_scenarios import ScenarioInput, evaluate as evaluate_scenario
from app.control_plane.plans import PlanVersion, digest
from app.control_plane.store import ConflictError, NotFoundError
from app.observability_store import actor


class _Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class PlanRequest(_Strict):
    objective: str = Field(min_length=1, max_length=500)


class PlanVersionRequest(_Strict):
    # exclusive_targets/consumes_ha_headroom/skus are deliberately not accepted: PlanVersion.identity()
    # would hash them, but cp_plan_versions has no columns to persist them, which would make the
    # stored digest unreproducible. Add them once a migration adds the columns.
    expected_version: int = Field(ge=0)
    targets: list[str] = Field(min_length=1, max_length=200)
    parameters: dict = Field(default_factory=dict)


class TransitionRequest(_Strict):
    from_state: str
    to_state: str


class ApprovalRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expires_at: datetime
    identity_digest: str = Field(min_length=1, max_length=64)


def _require_human_approver(tenant):
    """Reject machine identities and offline bearer licences for 'not a human'
    (see app/data_governance_api.py's owner() check); a bare workspace API key is treated as an
    operator-held credential, consistent with how other TENANT_ADMIN routes in this app authorize."""
    if tenant.get('subject_type') in ('service_account','license'):
        raise HTTPException(403, 'A human approver is required; service accounts and bearer licences cannot approve plans.')


def create_router(store, current_tenant):
    router = APIRouter(prefix='/api/v1/control-plane', tags=['Control plane'])

    def admin(tenant=Depends(current_tenant)):
        require_workspace_role(tenant, Role.TENANT_ADMIN)
        return tenant

    @router.post('/plans', status_code=201)
    def create_plan(body: PlanRequest, tenant=Depends(admin)):
        plan_id = cp_store.create_plan(store, tenant['tenant_id'], body.objective, actor(tenant))
        return {'id': plan_id, 'objective': body.objective}

    @router.post('/plans/{plan_id}/versions', status_code=201)
    def create_plan_version(plan_id: UUID, body: PlanVersionRequest, tenant=Depends(admin)):
        policy_digest = digest({'parameters': body.parameters})
        evidence_digest = digest({'targets': sorted(body.targets)})
        version = PlanVersion(plan_id=str(plan_id), version=body.expected_version + 1, targets=tuple(body.targets),
                              parameters=body.parameters, policy_digest=policy_digest, evidence_digest=evidence_digest)
        try:
            result = cp_store.add_plan_version(store, tenant['tenant_id'], str(plan_id), body.expected_version,
                                               version.identity(), body.targets, body.parameters, policy_digest,
                                               evidence_digest, actor(tenant))
        except NotFoundError:
            raise HTTPException(404, 'Plan not found') from None
        except ConflictError as error:
            raise HTTPException(409, str(error)) from None
        return dict(result, plan_id=str(plan_id), state='draft', identity_digest=version.identity())

    @router.post('/plan-versions/{version_id}/transitions')
    def transition(version_id: UUID, body: TransitionRequest, tenant=Depends(admin)):
        try:
            cp_store.transition_state(store, tenant['tenant_id'], str(version_id), body.from_state, body.to_state)
        except ConflictError as error:
            raise HTTPException(409, str(error)) from None
        try:
            return cp_store.get_plan_version(store, tenant['tenant_id'], str(version_id))
        except NotFoundError:
            raise HTTPException(404, 'Plan version not found') from None

    @router.post('/plan-versions/{version_id}/approvals', status_code=201)
    def approve(version_id: UUID, body: ApprovalRequest, tenant=Depends(admin)):
        _require_human_approver(tenant)
        try:
            # The caller attests which identity_digest they reviewed; record_approval itself
            # rejects a mismatch against the version's current digest, so an edited plan cannot
            # inherit an approval the approver never actually saw.
            approval_id = cp_store.record_approval(store, tenant['tenant_id'], str(version_id),
                                                   body.identity_digest, actor(tenant), True, body.expires_at)
        except NotFoundError:
            raise HTTPException(404, 'Plan version not found') from None
        except ConflictError as error:
            raise HTTPException(409, str(error)) from None
        return {'id': approval_id}

    @router.post('/action-assessments', status_code=201)
    def create_action_assessment(body: ActionAssessmentRequest, tenant=Depends(admin)):
        tid = tenant['tenant_id']
        with store.transaction(tid) as db:
            existing = db.execute('SELECT id FROM cp_action_assessments WHERE tenant_id=%s AND idempotency_key=%s',
                                  (tid, body.idempotency_key)).fetchone()
        outcome = evaluate_action_safety({'id': body.action_id, 'supported': body.supported}, body.evidence)
        # supported changes the computed decision; fold it into the digest so a replay with the same
        # idempotency_key but a flipped supported flag is detected as a conflict, not served stale.
        evidence_digest = digest({'evidence': body.evidence, 'supported': body.supported})
        policy_digest = digest({'rule_version': outcome['rule_version']})
        try:
            assessment_id = cp_store.save_action_assessment(store, tid, body.idempotency_key, body.action_id, outcome,
                                                            evidence_digest, policy_digest, actor(tenant))
        except ConflictError as error:
            raise HTTPException(409, str(error)) from None
        response = cp_store.get_action_assessment(store, tid, assessment_id)
        if existing:
            return JSONResponse(content=jsonable_encoder(response), status_code=200)
        return response

    @router.post('/financial-scenarios', status_code=201)
    def create_financial_scenario(body: FinancialScenarioRequest, tenant=Depends(admin)):
        tid = tenant['tenant_id']
        with store.transaction(tid) as db:
            existing = db.execute('SELECT id FROM cp_financial_scenarios WHERE tenant_id=%s AND idempotency_key=%s',
                                  (tid, body.idempotency_key)).fetchone()
        request = body.model_dump(exclude={'idempotency_key'})
        scenario = ScenarioInput(currency=body.currency, commitment_fee=body.commitment_fee,
                                 uncommitted_baseline=body.uncommitted_baseline,
                                 uncommitted_if_absorbed=body.uncommitted_if_absorbed,
                                 absorption_proven=body.absorption_proven, new_recurring=body.new_recurring,
                                 one_time=body.one_time)
        result = evaluate_scenario(scenario)
        evidence_digest = digest(request)
        try:
            scenario_id = cp_store.save_financial_scenario(store, tid, body.idempotency_key, body.currency, request,
                                                           result, actor(tenant), evidence_digest)
        except ConflictError as error:
            raise HTTPException(409, str(error)) from None
        response = cp_store.get_financial_scenario(store, tid, scenario_id)
        if existing:
            return JSONResponse(content=jsonable_encoder(response), status_code=200)
        return response

    return router
