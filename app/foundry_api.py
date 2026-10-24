"""Tenant-bound AI preferences and non-invoking diagnostics exposed through the scanner."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field

from app.ai_advisory import AIError
from app.auth import Role, require_workspace_role
from app.foundry_config import Strict, FoundrySettings


class Update(Strict):
    version: int = Field(ge=1)
    ai_foundry: FoundrySettings
    acknowledge_external_processing: bool = False


class Probe(Strict):
    provider: Literal['azure', 'aws', 'gcp']
    target_id: str = Field(pattern=r'^[a-z0-9-]{1,40}$')


def create_router(controller, current_tenant):
    router = APIRouter(prefix='/api/v1/settings/ai')

    def call(function, *args):
        try:
            return function(*args)
        except AIError as error:
            raise HTTPException(error.status, str(error)) from None

    @router.get('')
    def view(tenant=Depends(current_tenant)):
        return call(controller.view, tenant)

    @router.put('')
    def update(body: Update, tenant=Depends(current_tenant)):
        require_workspace_role(tenant, Role.TENANT_ADMIN)
        return call(controller.save, tenant, body.version, body.ai_foundry.model_dump(), body.acknowledge_external_processing)

    @router.post('/test-connection')
    def diagnostic(body: Probe, tenant=Depends(current_tenant)):
        require_workspace_role(tenant, Role.TENANT_ADMIN)
        return call(controller.diagnose, tenant, body.provider, body.target_id)

    return router
