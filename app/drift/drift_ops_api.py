"""Drift subscription provisioning and semantic embedding vector backfill APIs."""
from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException
from starlette.concurrency import run_in_threadpool

from app.auth import Role, require_workspace_role


def create_drift_subscriptions_router(settings, current_tenant):
    router = APIRouter(prefix="/api/v1/drift/cloud-events", tags=["Drift subscriptions"])

    def admin(tenant=Depends(current_tenant)):
        require_workspace_role(tenant, Role.TENANT_ADMIN)
        return tenant

    @router.post("/subscriptions/ensure", status_code=202)
    async def ensure_subscriptions(tenant=Depends(admin)):
        if os.getenv("CLOUDSAVER_DRIFT_SUBSCRIPTION_WIRING", "false").lower() != "true":
            raise HTTPException(503, "Drift subscription wiring is disabled in this environment")

        def run():
            from app.drift.cloud_event_subscriptions import ensure_workspace_subscriptions

            azure_token = None
            if tenant.get("subscription_ids"):
                from app.cloud_identity import managed_identity_token

                azure_token = lambda: managed_identity_token(
                    "https://management.azure.com",
                    settings=settings,
                    tenant=tenant,
                )
            return ensure_workspace_subscriptions(tenant, azure_token=azure_token)

        try:
            return await run_in_threadpool(run)
        except ValueError as error:
            raise HTTPException(422, str(error)) from None

    return router


def create_semantic_router(settings, evidence_store, current_tenant):
    router = APIRouter(prefix="/api/v1/semantic", tags=["Semantic embeddings"])

    def admin(tenant=Depends(current_tenant)):
        require_workspace_role(tenant, Role.TENANT_ADMIN)
        return tenant

    @router.post("/embeddings/backfill-vectors", status_code=202)
    async def backfill_vectors(tenant=Depends(admin)):
        if os.getenv("CLOUDSAVER_SEMANTIC_EMBEDDINGS_PIPELINE", "false").lower() != "true":
            raise HTTPException(503, "Semantic embeddings pipeline is disabled in this environment")

        def run():
            from app.semantic_embeddings_pipeline import backfill_embedding_vectors

            return backfill_embedding_vectors(evidence_store, tenant["tenant_id"])

        try:
            return await run_in_threadpool(run)
        except ValueError as error:
            raise HTTPException(422, str(error)) from None

    return router
