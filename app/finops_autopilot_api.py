"""FinOps autopilot: deterministic resize plans and optional hands-free agent execution."""
from __future__ import annotations

import os
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from app.auth import Role, require_workspace_role


class AutopilotResizeRequest(BaseModel):
    scan_id: UUID
    resource_id: str = Field(min_length=1, max_length=2048)
    connector_id: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9-]{0,59}$")
    target_size: str | None = Field(default=None, max_length=80)
    finops_action: str | None = Field(default=None, max_length=64)
    request_key: UUID
    target_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,59}$")
    auto_execute: bool = False
    sync_iac: bool = False
    gitops_target_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,59}$")
    model_config = ConfigDict(extra="forbid")


def create_router(settings, scan_store, evidence_store, current_tenant):
    router = APIRouter(prefix="/api/v1/finops/autopilot", tags=["FinOps autopilot"])

    def admin(tenant=Depends(current_tenant)):
        require_workspace_role(tenant, Role.TENANT_ADMIN)
        return tenant

    @router.get("/playbooks")
    def playbooks(tenant=Depends(admin)):
        from app.finops_resize_playbooks import list_playbooks

        return dict(items=list_playbooks())

    @router.post("/resize", status_code=202)
    async def autopilot_resize(request_body: AutopilotResizeRequest, tenant=Depends(admin)):
        if os.getenv("CLOUDSAVER_FINOPS_AUTOPILOT", "false").lower() != "true":
            raise HTTPException(503, "FinOps autopilot is disabled in this environment")
        if request_body.auto_execute and os.getenv("CLOUDSAVER_AGENT_ENABLED", "false").lower() != "true":
            raise HTTPException(503, "Agent execution must be enabled for auto_execute")

        def run():
            from app.agent_contract import connectors, supports_resource
            from app.agent_store import AgentRepository
            from app.finops_autopilot_planner import build_resize_agent_plan
            from app.finops_resize_playbooks import candidate_size_from_resource, pick_gitops_connector, pick_resize_connector, resolve_playbook
            from app.data_governance import DataGovernor, sanitize

            snapshot = scan_store.get(tenant["tenant_id"], str(request_body.scan_id))
            if not snapshot or snapshot.get("status") != "completed":
                raise ValueError("Completed scan required")
            resource = next(
                (row for row in snapshot.get("inventory", []) if row.get("resource_id") == request_body.resource_id),
                None,
            )
            if resource is None:
                raise ValueError("Resource not found in scan")
            book = resolve_playbook(
                cloud_provider=resource.get("cloud_provider", "azure"),
                resource_type=resource.get("resource_type", ""),
                finops_action=request_body.finops_action,
            )
            target_size = request_body.target_size or candidate_size_from_resource(resource, book)
            if not target_size:
                raise ValueError("Provide target_size or ensure scan evidence includes a recommended size")
            catalog = connectors()
            if request_body.connector_id:
                connector = next((c for c in catalog if c.id == request_body.connector_id), None)
                if connector is None or connector.tenant_id != tenant["tenant_id"]:
                    raise ValueError("Connector not found for workspace")
            else:
                connector = pick_resize_connector(catalog, tenant["tenant_id"], book, resource["resource_id"])
            if connector.kind != book["connector_kind"]:
                raise ValueError("Connector kind does not match resize playbook")
            if book["resize_operation"] not in connector.operations:
                raise ValueError("Connector must allow compute.resize for autopilot execution")
            if not supports_resource(connector, resource["resource_id"]):
                raise ValueError("Connector does not support this resource")
            gitops_connector = None
            connector_ids = [connector.id]
            if request_body.sync_iac:
                if not request_body.gitops_target_id:
                    raise ValueError("gitops_target_id is required when sync_iac is true")
                gitops_connector = pick_gitops_connector(catalog, tenant["tenant_id"], request_body.gitops_target_id)
                connector_ids.append(gitops_connector.id)
            plan = build_resize_agent_plan(
                resource=resource,
                connector_id=connector.id,
                target_size=target_size,
                finops_action=book["finops_action"],
                gitops_connector_id=gitops_connector.id if gitops_connector else None,
                gitops_target_id=request_body.gitops_target_id if gitops_connector else None,
            )
            sanitize({"instruction": plan["summary"]}, purpose="agent_planning")
            governor = DataGovernor(evidence_store)
            _, policy, _ = governor.policy()
            repo = AgentRepository(evidence_store)
            task = repo.create(
                tenant,
                snapshot,
                resource,
                dict(
                    scan_id=str(request_body.scan_id),
                    resource_id=request_body.resource_id,
                    request_key=str(request_body.request_key),
                    intent=plan["summary"],
                    target_id=request_body.target_id,
                    connector_ids=connector_ids,
                    _retention_days=policy["response_retention_days"],
                ),
            )
            installed = repo.install_finops_plan(
                tenant,
                task["id"],
                plan,
                catalog,
                auto_approve=request_body.auto_execute
                and os.getenv("CLOUDSAVER_FINOPS_AUTOPILOT_AUTO_APPROVE", "false").lower() == "true",
            )
            plan_hash = installed["payload"]["plan_hash"]
            return dict(
                task_id=installed["id"],
                plan_hash=plan_hash,
                connector_id=connector.id,
                finops_action=plan["finops_action"],
                target_size=plan["target_size"],
                state=installed["state"],
                steps=len(plan["steps"]),
                auto_execute=request_body.auto_execute,
                sync_iac=request_body.sync_iac,
                requires_human_approval=installed["state"] == "awaiting_approval",
            )

        try:
            return await run_in_threadpool(run)
        except ValueError as error:
            raise HTTPException(422, str(error)) from None

    return router
