"""Governance routes use owned observations, explicit grants and bounded JSON."""

import json
from datetime import datetime, timezone
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Request, Header
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from app.gitops_api import bounded_json
from app.cloud_scope import validate_finding_scope
from app.telemetry_contract import moment
from app.governance_store import Governance, GovernanceConflict, GovernanceForbidden
from app.governance_contracts import (
    Grant,
    Policy,
    Evaluation,
    RiskCreate,
    FindingAction,
    ExceptionCreate,
    Decision,
    Envelope,
)
from app.data_scope import scan_visible


def latest_observation(store, t, f, requested=None):
    """Select the latest relevant completed scope scan, including explicit absence."""
    p = f["payload"]
    candidates = []
    for scan in store.list(t["tenant_id"], 1000):
        if (
            scan.get("status") != "completed"
            or scan.get("data_origin") == "legacy_synthetic"
            or not scan_visible(store, t, scan["scan_id"])
        ):
            continue
        resources = [*scan.get("inventory", []), *scan.get("findings", [])]
        resource = next(
            (
                r
                for r in resources
                if r.get("cloud_provider", "azure") == p["provider"]
                and str(r.get("resource_id", "")).lower() == p["resource_id"]
            ),
            None,
        )
        covered = any(
            s.get("provider") == p["provider"] and s.get("scope_id") == p["scope_id"]
            for s in scan.get("scope_results", [])
        )
        if resource or covered:
            candidates.append((scan, resource))
    if not candidates:
        return None
    scan, resource = max(
        candidates,
        key=lambda v: moment(v[0].get("timestamp"))
        or datetime.min.replace(tzinfo=timezone.utc),
    )
    if requested and str(requested) != scan["scan_id"]:
        raise GovernanceConflict(
            "Select the latest relevant owned scan; an older passing observation cannot hide newer evidence"
        )
    return resource, scan


def create_router(store, evidence_store, current_tenant, *, repository=None):
    repo = repository or Governance(evidence_store)
    router = APIRouter(prefix="/api/v1/governance", tags=["Risk and governance"])

    def call(fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except GovernanceForbidden as e:
            raise HTTPException(403, str(e)) from None
        except GovernanceConflict as e:
            raise HTTPException(409, str(e)) from None
        except KeyError:
            raise HTTPException(404, "Owned governance record not found") from None
        except (ValueError, TypeError):
            raise HTTPException(
                422, "Governance evidence or policy fields are invalid or incomplete"
            ) from None

    async def body(request, model):
        raw = await bounded_json(request)
        try:
            return model.model_validate_json(json.dumps(raw, allow_nan=False))
        except (ValueError, ValidationError):
            raise HTTPException(
                422,
                "Invalid governance request; review required evidence and policy fields",
            ) from None

    def observation(t, id, selected=None):
        f = call(repo.detail, t, "finding", str(id))
        return call(latest_observation, store, t, f, selected)

    @router.get("/capabilities")
    def capabilities(t=Depends(current_tenant)):
        return call(repo.capabilities, t)

    @router.get("/access")
    def access(t=Depends(current_tenant)):
        return dict(items=call(repo.grants, t))

    @router.put("/access")
    async def access_write(request: Request, t=Depends(current_tenant)):
        return call(repo.grant, t, await body(request, Grant))

    @router.get("/directory")
    def directory(t=Depends(current_tenant)):
        return dict(items=call(repo.directory, t))

    @router.get("/controls")
    def controls(t=Depends(current_tenant)):
        return dict(
            policy=call(repo.policy, t),
            supported_control="AZ-STORAGE-PUBLIC-BLOB-ACCESS",
            framework_compliance_certified=False,
        )

    @router.post("/controls", status_code=201)
    async def control_write(request: Request, t=Depends(current_tenant)):
        return call(repo.save_policy, t, await body(request, Policy))

    @router.post("/assessments", status_code=201)
    async def assess(request: Request, t=Depends(current_tenant)):
        value = await body(request, Evaluation)
        scan = store.get(t["tenant_id"], str(value.scan_id))
        if scan is None:
            raise HTTPException(404, "Owned scan not found")
        resource = next(
            (
                r
                for r in [*scan.get("inventory", []), *scan.get("findings", [])]
                if r.get("resource_id") == value.resource_id
            ),
            None,
        )
        if resource is None:
            raise HTTPException(404, "Resource not in the owned scan")
        try:
            validate_finding_scope(resource, t)
        except (KeyError, ValueError):
            raise HTTPException(
                403, "Resource is outside the authorized scope"
            ) from None
        return call(repo.assess, t, resource, scan, value)

    @router.get("/summary")
    def summary(t=Depends(current_tenant)):
        return call(repo.summary, t)

    @router.get("/findings")
    def findings(t=Depends(current_tenant)):
        return dict(items=call(repo.list, t, "finding"))

    @router.get("/findings/{finding_id}")
    def finding(finding_id: UUID, t=Depends(current_tenant)):
        return call(repo.detail, t, "finding", str(finding_id))

    @router.post("/findings/{finding_id}/actions")
    async def finding_action(
        finding_id: UUID, request: Request, t=Depends(current_tenant)
    ):
        value = await body(request, FindingAction)
        current = (
            observation(t, finding_id, value.scan_id)
            if value.action in ("propose", "approve", "verify", "close", "dismiss")
            else None
        )
        return call(repo.act, t, str(finding_id), value, current)

    @router.get("/findings/{finding_id}/export")
    def export(finding_id: UUID, t=Depends(current_tenant)):
        value = call(repo.export, t, str(finding_id), observation(t, finding_id))
        return JSONResponse(
            value,
            headers={
                "Content-Disposition": f'attachment; filename="cloudsaver-governance-{finding_id}.json"',
                "Cache-Control": "no-store",
            },
        )

    @router.get("/risks")
    def risks(t=Depends(current_tenant)):
        return dict(items=call(repo.list, t, "risk"))

    @router.post("/risks", status_code=201)
    async def risk_create(request: Request, t=Depends(current_tenant)):
        return call(repo.create_risk, t, await body(request, RiskCreate))

    @router.post("/risks/{risk_id}/actions")
    async def risk_action(risk_id: UUID, request: Request, t=Depends(current_tenant)):
        return call(repo.decide_risk, t, str(risk_id), await body(request, Decision))

    @router.get("/exceptions")
    def exceptions(t=Depends(current_tenant)):
        return dict(items=call(repo.list, t, "exception"))

    @router.post("/exceptions", status_code=201)
    async def exception_create(request: Request, t=Depends(current_tenant)):
        return call(repo.request_exception, t, await body(request, ExceptionCreate))

    @router.post("/exceptions/{exception_id}/actions")
    async def exception_action(
        exception_id: UUID, request: Request, t=Depends(current_tenant)
    ):
        return call(
            repo.decide_exception, t, str(exception_id), await body(request, Decision)
        )

    @router.post("/evidence/receipts", status_code=201)
    async def receipt(
        request: Request,
        x_evidence_signature: str = Header(default=""),
        t=Depends(current_tenant),
    ):
        raw = await bounded_json(request)
        try:
            Envelope.model_validate(raw)
        except ValueError:
            raise HTTPException(422, "Invalid governance evidence envelope") from None
        return call(repo.submit_receipt, t, raw, x_evidence_signature)

    @router.post("/monitor")
    def monitor(t=Depends(current_tenant)):
        findings = call(repo.list, t, "finding")
        observations = {
            f["id"]: call(latest_observation, store, t, f) for f in findings
        }
        return call(repo.monitor, t, observations)

    return router
