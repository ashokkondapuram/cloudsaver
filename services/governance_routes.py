"""Fixed governance forwarding contracts; no visitor-provided upstream destinations."""

from uuid import UUID
from fastapi import Depends, Header, Request
from fastapi.responses import JSONResponse
from app.gitops_api import bounded_json
from services.common import upstream


def register(app, allowed, targets, transport):
    @app.get("/api/v1/governance/capabilities", status_code=200)
    async def governance_capabilities(
        request: Request, row=Depends(allowed), authorization: str = Header()
    ):
        value = await upstream(
            "GET",
            targets["scanner"],
            "/api/v1/governance/capabilities",
            authorization,
            transport=transport,
        )
        return value

    @app.get("/api/v1/governance/access", status_code=200)
    async def governance_access(
        request: Request, row=Depends(allowed), authorization: str = Header()
    ):
        value = await upstream(
            "GET",
            targets["scanner"],
            "/api/v1/governance/access",
            authorization,
            transport=transport,
        )
        return value

    @app.put("/api/v1/governance/access", status_code=200)
    async def governance_update_access(
        request: Request, row=Depends(allowed), authorization: str = Header()
    ):
        value = await upstream(
            "PUT",
            targets["scanner"],
            "/api/v1/governance/access",
            authorization,
            transport=transport,
            json=await bounded_json(request),
        )
        return value

    @app.get("/api/v1/governance/directory", status_code=200)
    async def governance_directory(
        request: Request, row=Depends(allowed), authorization: str = Header()
    ):
        value = await upstream(
            "GET",
            targets["scanner"],
            "/api/v1/governance/directory",
            authorization,
            transport=transport,
        )
        return value

    @app.get("/api/v1/governance/controls", status_code=200)
    async def governance_controls(
        request: Request, row=Depends(allowed), authorization: str = Header()
    ):
        value = await upstream(
            "GET",
            targets["scanner"],
            "/api/v1/governance/controls",
            authorization,
            transport=transport,
        )
        return value

    @app.post("/api/v1/governance/controls", status_code=201)
    async def governance_review_control(
        request: Request, row=Depends(allowed), authorization: str = Header()
    ):
        value = await upstream(
            "POST",
            targets["scanner"],
            "/api/v1/governance/controls",
            authorization,
            transport=transport,
            json=await bounded_json(request),
        )
        return value

    @app.post("/api/v1/governance/assessments", status_code=201)
    async def governance_assess_control(
        request: Request, row=Depends(allowed), authorization: str = Header()
    ):
        value = await upstream(
            "POST",
            targets["scanner"],
            "/api/v1/governance/assessments",
            authorization,
            transport=transport,
            json=await bounded_json(request),
        )
        return value

    @app.get("/api/v1/governance/summary", status_code=200)
    async def governance_summary(
        request: Request, row=Depends(allowed), authorization: str = Header()
    ):
        value = await upstream(
            "GET",
            targets["scanner"],
            "/api/v1/governance/summary",
            authorization,
            transport=transport,
        )
        return value

    @app.get("/api/v1/governance/findings", status_code=200)
    async def governance_findings(
        request: Request, row=Depends(allowed), authorization: str = Header()
    ):
        value = await upstream(
            "GET",
            targets["scanner"],
            "/api/v1/governance/findings",
            authorization,
            transport=transport,
        )
        return value

    @app.get("/api/v1/governance/findings/{finding_id}", status_code=200)
    async def governance_finding(
        finding_id: UUID,
        request: Request,
        row=Depends(allowed),
        authorization: str = Header(),
    ):
        value = await upstream(
            "GET",
            targets["scanner"],
            f"/api/v1/governance/findings/{finding_id}",
            authorization,
            transport=transport,
        )
        return value

    @app.post("/api/v1/governance/findings/{finding_id}/actions", status_code=200)
    async def governance_finding_action(
        finding_id: UUID,
        request: Request,
        row=Depends(allowed),
        authorization: str = Header(),
    ):
        value = await upstream(
            "POST",
            targets["scanner"],
            f"/api/v1/governance/findings/{finding_id}/actions",
            authorization,
            transport=transport,
            json=await bounded_json(request),
        )
        return value

    @app.get("/api/v1/governance/findings/{finding_id}/export", status_code=200)
    async def governance_audit_export(
        finding_id: UUID,
        request: Request,
        row=Depends(allowed),
        authorization: str = Header(),
    ):
        value = await upstream(
            "GET",
            targets["scanner"],
            f"/api/v1/governance/findings/{finding_id}/export",
            authorization,
            transport=transport,
        )
        return JSONResponse(
            value,
            headers={
                "Cache-Control": "no-store",
                "Content-Disposition": f'attachment; filename="cloudsaver-governance-{finding_id}.json"',
            },
        )

    @app.get("/api/v1/governance/risks", status_code=200)
    async def governance_risks(
        request: Request, row=Depends(allowed), authorization: str = Header()
    ):
        value = await upstream(
            "GET",
            targets["scanner"],
            "/api/v1/governance/risks",
            authorization,
            transport=transport,
        )
        return value

    @app.post("/api/v1/governance/risks", status_code=201)
    async def governance_create_risk(
        request: Request, row=Depends(allowed), authorization: str = Header()
    ):
        value = await upstream(
            "POST",
            targets["scanner"],
            "/api/v1/governance/risks",
            authorization,
            transport=transport,
            json=await bounded_json(request),
        )
        return value

    @app.post("/api/v1/governance/risks/{risk_id}/actions", status_code=200)
    async def governance_risk_action(
        risk_id: UUID,
        request: Request,
        row=Depends(allowed),
        authorization: str = Header(),
    ):
        value = await upstream(
            "POST",
            targets["scanner"],
            f"/api/v1/governance/risks/{risk_id}/actions",
            authorization,
            transport=transport,
            json=await bounded_json(request),
        )
        return value

    @app.get("/api/v1/governance/exceptions", status_code=200)
    async def governance_exceptions(
        request: Request, row=Depends(allowed), authorization: str = Header()
    ):
        value = await upstream(
            "GET",
            targets["scanner"],
            "/api/v1/governance/exceptions",
            authorization,
            transport=transport,
        )
        return value

    @app.post("/api/v1/governance/exceptions", status_code=201)
    async def governance_request_exception(
        request: Request, row=Depends(allowed), authorization: str = Header()
    ):
        value = await upstream(
            "POST",
            targets["scanner"],
            "/api/v1/governance/exceptions",
            authorization,
            transport=transport,
            json=await bounded_json(request),
        )
        return value

    @app.post("/api/v1/governance/exceptions/{exception_id}/actions", status_code=200)
    async def governance_exception_action(
        exception_id: UUID,
        request: Request,
        row=Depends(allowed),
        authorization: str = Header(),
    ):
        value = await upstream(
            "POST",
            targets["scanner"],
            f"/api/v1/governance/exceptions/{exception_id}/actions",
            authorization,
            transport=transport,
            json=await bounded_json(request),
        )
        return value

    @app.post("/api/v1/governance/evidence/receipts", status_code=201)
    async def governance_evidence_receipt(
        request: Request, row=Depends(allowed), authorization: str = Header()
    ):
        value = await upstream(
            "POST",
            targets["scanner"],
            "/api/v1/governance/evidence/receipts",
            authorization,
            transport=transport,
            json=await bounded_json(request),
            evidence_signature=request.headers.get("X-Evidence-Signature"),
        )
        return value

    @app.post("/api/v1/governance/monitor", status_code=200)
    async def governance_monitor(
        request: Request, row=Depends(allowed), authorization: str = Header()
    ):
        value = await upstream(
            "POST",
            targets["scanner"],
            "/api/v1/governance/monitor",
            authorization,
            transport=transport,
        )
        return value
