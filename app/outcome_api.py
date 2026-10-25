"""Finance outcomes: tenant-owned evidence, explicit review and no infrastructure execution."""

import json
from datetime import date
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Request, Header, Query
from pydantic import ValidationError
from app.auth import Role, require_workspace_role
from app.gitops_api import bounded_json
from app.outcome_contracts import (
    CaseCreate,
    CaseAction,
    Ownership,
    Detection,
    AnomalyAction,
    Suppression,
    human,
)
from app.outcome_store import Outcomes, OutcomeConflict
from app.outcome_anomalies import Investigations
from app.cloud_scope import validate_finding_scope


def create_router(
    store, evidence_store, current_tenant, *, outcomes=None, investigations=None
):
    router = APIRouter(prefix="/api/v1/outcomes", tags=["Financial outcomes"])
    repo = outcomes or Outcomes(evidence_store)
    anomalies = investigations or Investigations(evidence_store)

    def finance(tenant=Depends(current_tenant)):
        require_workspace_role(tenant, Role.BILLING_ADMIN)
        return tenant

    def admin(tenant):
        require_workspace_role(tenant, Role.TENANT_ADMIN)

    def required(value):
        if value is None:
            raise HTTPException(404, "Owned outcome record not found")
        return value

    def call(fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except OutcomeConflict as error:
            raise HTTPException(409, str(error)) from None
        except (ValueError, KeyError, TypeError):
            raise HTTPException(
                422, "Evidence or workflow input is invalid or incomplete"
            ) from None

    async def body(request, model):
        try:
            return model.model_validate_json(
                json.dumps(await bounded_json(request), allow_nan=False)
            )
        except (ValidationError, ValueError):
            raise HTTPException(
                422,
                "Invalid outcome request; check the selected resource, version and evidence fields",
            ) from None

    def scan(tenant, id):
        value = store.get(tenant["tenant_id"], str(id))
        if value is None:
            raise HTTPException(404, "Owned scan not found")
        if (
            value.get("status") != "completed"
            or value.get("data_origin") == "legacy_synthetic"
        ):
            raise HTTPException(
                409, "A completed live resource observation is required"
            )
        return value

    def resource(tenant, id, rid):
        snapshot = scan(tenant, id)
        value = next(
            (
                r
                for r in [*snapshot.get("inventory", []), *snapshot.get("findings", [])]
                if r["resource_id"] == rid
            ),
            None,
        )
        if value is None:
            raise HTTPException(404, "Resource is not in the selected scan")
        try:
            validate_finding_scope(value, tenant)
        except (ValueError, KeyError):
            raise HTTPException(403, "Resource is outside the current scope") from None
        return snapshot, value

    @router.get("/summary")
    def summary(tenant=Depends(finance)):
        return call(repo.summary, tenant)

    @router.get("/cases")
    def cases(tenant=Depends(finance)):
        return dict(items=call(repo.cases, tenant))

    @router.post("/cases", status_code=201)
    async def create_case(request: Request, tenant=Depends(finance)):
        admin(tenant)
        value = await body(request, CaseCreate)
        snapshot, item = resource(tenant, value.scan_id, value.resource_id)
        return call(repo.create, tenant, snapshot, item, value)

    @router.get("/cases/{case_id}")
    def detail(case_id: UUID, tenant=Depends(finance)):
        return required(call(repo.detail, tenant, str(case_id)))

    @router.post("/cases/{case_id}/actions")
    async def case_action(case_id: UUID, request: Request, tenant=Depends(finance)):
        value = await body(request, CaseAction)
        if value.action in ("assign", "review", "approve", "implement", "reopen"):
            admin(tenant)
        post = scan(tenant, value.scan_id) if value.scan_id else None
        return required(call(repo.act, tenant, str(case_id), value, post))

    @router.get("/cases/{case_id}/billing-evidence")
    def billing(
        case_id: UUID,
        baseline_start: date,
        baseline_end: date,
        post_start: date,
        post_end: date,
        currency: str = Query("USD", pattern=r"^[A-Z]{3}$"),
        tenant=Depends(finance),
    ):
        raw = dict(
            baseline_start=str(baseline_start),
            baseline_end=str(baseline_end),
            post_start=str(post_start),
            post_end=str(post_end),
            currency=currency,
        )
        return required(call(repo.billing_preview, tenant, str(case_id), raw))

    @router.post("/evidence/receipts", status_code=201)
    async def receipt(
        request: Request,
        x_evidence_signature: str = Header(default=""),
        tenant=Depends(finance),
    ):
        return call(
            repo.save_receipt, tenant, await bounded_json(request), x_evidence_signature
        )

    @router.get("/ownership")
    def ownership(tenant=Depends(finance)):
        return dict(
            items=call(anomalies.ownership, tenant),
            basis="current_direct_resource_mapping",
        )

    @router.put("/ownership")
    async def ownership_write(request: Request, tenant=Depends(finance)):
        admin(tenant)
        value = await body(request, Ownership)
        _, item = resource(tenant, value.scan_id, value.resource_id)
        return call(anomalies.save_ownership, tenant, item, value)

    @router.get("/ownership/history")
    def ownership_history(
        provider: str, scope_id: str, resource_id: str, tenant=Depends(finance)
    ):
        return dict(
            items=call(anomalies.history, tenant, provider, scope_id, resource_id)
        )

    @router.get("/anomalies")
    def investigations_list(tenant=Depends(finance)):
        return dict(items=call(anomalies.anomalies, tenant))

    @router.post("/anomalies/detect")
    async def detect(request: Request, tenant=Depends(finance)):
        return call(anomalies.detect, tenant, await body(request, Detection))

    @router.get("/anomalies/metrics")
    def metrics(tenant=Depends(finance)):
        return call(anomalies.metrics, tenant)

    @router.get("/anomalies/{anomaly_id}")
    def investigation(anomaly_id: UUID, tenant=Depends(finance)):
        return required(call(anomalies.detail, tenant, str(anomaly_id)))

    @router.post("/anomalies/{anomaly_id}/actions")
    async def investigation_action(
        anomaly_id: UUID, request: Request, tenant=Depends(finance)
    ):
        return required(
            call(
                anomalies.act,
                tenant,
                str(anomaly_id),
                await body(request, AnomalyAction),
            )
        )

    @router.post("/suppressions", status_code=201)
    async def suppress(request: Request, tenant=Depends(finance)):
        admin(tenant)
        if not human(tenant):
            raise HTTPException(
                403, "A verified human TenantAdmin must approve a planned exception"
            )
        return call(anomalies.suppress, tenant, await body(request, Suppression))

    return router
