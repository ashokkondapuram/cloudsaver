"""Durable interactive multi-cloud submission: API never executes a background scan."""
import os
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field

from app.auth import Role, require_workspace_role


class ScanSubmission(BaseModel):
    model_config = ConfigDict(extra='forbid')
    subscription_ids: list[UUID] | None = Field(default=None,min_length=1, max_length=100)
    providers: list[str] | None = Field(default=None,min_length=1,max_length=4)
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
        from app.scan_selection import normalize,select,count
        from app.cloud_scope import configured_providers
        from app.entitlements import enforce_subscription_quota,enforce_providers
        try:
            if (payload.subscription_ids is None)==(payload.providers is None):
                raise ValueError('Select providers or Azure subscriptions, not both')
            if payload.providers is not None:
                if not set(payload.providers)<=set(configured_providers(tenant)):raise ValueError('Select configured providers')
                requested=select(tenant,payload.providers)
            else:
                requested=normalize([str(s) for s in payload.subscription_ids])
                if not set(requested)<=set(tenant['subscription_ids']):raise ValueError('Select authorized subscriptions')
        except (ValueError,KeyError,TypeError) as error:
            raise HTTPException(422,str(error)) from None
        enforce_providers(tenant,payload.providers or ['azure'])
        enforce_subscription_quota(tenant,count(requested),adding_count=0)
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
