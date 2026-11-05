"""Tenant Code Mode API — human-gated sandbox execution via Cloudflare worker bridge."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from app.auth import Role, require_workspace_role
from app.code_mode_config import code_mode_enabled, public_status
from app.code_mode_store import CodeModeConflict, CodeModeRepository, RunRequest


def create_router(evidence_store, current_tenant):
    router = APIRouter()
    repo = CodeModeRepository(evidence_store)

    def enabled():
        if not code_mode_enabled():
            raise HTTPException(503, 'Code Mode is disabled by the deployment operator.')

    def human(row):
        require_workspace_role(row, Role.TENANT_ADMIN)
        if row.get('key_id') or row.get('subject_type') == 'service_account':
            raise HTTPException(403, 'A verified human workspace administrator must run Code Mode.')

    @router.get('/api/v1/code-mode/status')
    def status(_tenant=Depends(current_tenant)):
        return public_status()

    @router.get('/api/v1/code-mode/runs')
    def runs(tenant=Depends(current_tenant)):
        return {'items': repo.list_runs(tenant)}

    @router.get('/api/v1/code-mode/runs/{run_id}')
    def run_detail(run_id: UUID, tenant=Depends(current_tenant)):
        run = repo.get(tenant, str(run_id))
        if run is None:
            raise HTTPException(404, 'Code Mode run not found')
        events = repo.events(tenant, str(run_id))
        return dict(run, events=events)

    @router.post('/api/v1/code-mode/runs', status_code=201)
    def submit(body: RunRequest, tenant=Depends(current_tenant)):
        enabled()
        human(tenant)
        try:
            return repo.create_and_execute(tenant, body)
        except CodeModeConflict as error:
            raise HTTPException(409, str(error)) from None
        except ValueError as error:
            raise HTTPException(422, str(error)) from None
        except RuntimeError as error:
            raise HTTPException(503, str(error)) from None

    return router
