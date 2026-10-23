"""Durable interactive Azure submission: API never executes a background scan."""
import os
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field

from app.auth import Role, require_workspace_role


class ScanSubmission(BaseModel):
    model_config = ConfigDict(extra='forbid')
    subscription_ids: list[UUID] = Field(min_length=1, max_length=100)
    idempotency_key: UUID


def create_router(settings, current_tenant, *, repository=None):
    from workers.storage import JobRepository, SubmissionConflict
    router = APIRouter(prefix='/api/v1/scan-jobs', tags=['Scan jobs'])
    repository = repository or (JobRepository(settings.database_url) if settings.database_url else None)

    def available():
        if repository is None:
            raise HTTPException(503, 'Durable scan jobs require PostgreSQL')

    def public(row):
        return dict(row, poll_url='/api/v1/scan-jobs/' + row['job_id'],
                    result_url='/api/v1/scans/' + row['scan_id'] if row['scan_id'] else None)

    @router.post('', status_code=202)
    def submit(payload: ScanSubmission, response: Response, tenant=Depends(current_tenant)):
        require_workspace_role(tenant, Role.TENANT_ADMIN)
        available()
        if (os.getenv('CLOUDSAVER_INTERACTIVE_JOBS', '').lower() != 'true'
                or os.getenv('CLOUDSAVER_DELIVERY_ENABLED', '').lower() != 'true'):
            raise HTTPException(503, 'Interactive jobs and the delivery dispatcher must be enabled')
        requested = sorted(str(s) for s in payload.subscription_ids)
        if len(set(requested)) != len(requested) or not set(requested) <= set(tenant['subscription_ids']):
            raise HTTPException(422, 'Select unique authorized Azure subscriptions')
        from app.entitlements import enforce_subscription_quota
        enforce_subscription_quota(tenant['plan_tier'], len(requested), adding_count=0)
        try:
            row = repository.submit(tenant['tenant_id'], str(payload.idempotency_key), requested)
        except SubmissionConflict as exc:
            raise HTTPException(409, str(exc)) from None
        result = public(row)
        response.headers['Location'] = result['poll_url']
        response.headers['Retry-After'] = '3'
        return result

    @router.get('')
    def history(limit: int = Query(50, ge=1, le=100), tenant=Depends(current_tenant)):
        available()
        return [public(row) for row in repository.list_jobs(tenant['tenant_id'], limit)]

    @router.get('/{job_id}')
    def status(job_id: UUID, response: Response, tenant=Depends(current_tenant)):
        available()
        row = repository.job_status(tenant['tenant_id'], str(job_id))
        if row is None:
            raise HTTPException(404, 'Scan job not found')
        if row['status'] in ('queued', 'running'):
            response.headers['Retry-After'] = '3'
        return public(row)

    return router
