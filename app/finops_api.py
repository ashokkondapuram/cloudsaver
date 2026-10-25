"""Explicit normalized billing ingestion; tenant-owned, finance-authorized access."""
from datetime import date, datetime, timezone
import json
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from uuid import UUID
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool
from app.auth import Role, require_workspace_role
from app.focus import FocusError, FocusRepository, ImportRequest, money
from app.schemas import bounded_json


def create_router(repository, current_tenant):
    router=APIRouter(prefix='/api/v1/finops',tags=['Billing evidence'])

    def finance(tenant=Depends(current_tenant)):
        require_workspace_role(tenant,Role.BILLING_ADMIN)
        return tenant

    @router.post('/sync',status_code=202)
    async def sync(request:Request,response:Response,currency:str=Query('USD',pattern=r'^[A-Z]{3}$'),tenant=Depends(finance)):
        from app.billing_jobs import BillingJobs
        from app.v150_store import WorkflowConflict
        raw=await bounded_json(request)
        try:
            if not isinstance(raw,dict) or set(raw)!={'idempotency_key'}:raise ValueError()
            key=str(UUID(raw['idempotency_key']))
        except (ValueError,TypeError,KeyError):raise HTTPException(422,'Provide a UUID idempotency_key') from None
        try:result=await run_in_threadpool(BillingJobs(repository.store).submit,tenant,key,currency)
        except FocusError as error:raise HTTPException(error.status,str(error)) from None
        except WorkflowConflict as error:raise HTTPException(409,str(error)) from None
        response.headers['Location']=result['poll_url'];response.headers['Retry-After']='3'
        return result

    @router.get('/sync-jobs/{job_id}')
    def sync_job(job_id:UUID,response:Response,tenant=Depends(finance)):
        from app.billing_jobs import BillingJobs
        result=BillingJobs(repository.store).get(tenant['tenant_id'],str(job_id))
        if result is None:raise HTTPException(404,'Billing job not found')
        if result['status'] in ('queued','running','cancel_requested'):response.headers['Retry-After']='3'
        return result

    @router.post('/sync-jobs/{job_id}/cancel')
    def cancel_sync(job_id:UUID,tenant=Depends(finance)):
        from app.billing_jobs import BillingJobs
        result=BillingJobs(repository.store).cancel(tenant['tenant_id'],str(job_id))
        if result is None:raise HTTPException(404,'Billing job not found')
        return result

    @router.get('/sync-status')
    def billing_sync_status(tenant=Depends(finance)):
        from app.collectors.billing_sync import sync_status
        try:return sync_status(tenant,repository)
        except (ValueError,KeyError,TypeError):
            raise HTTPException(503,'Billing connector configuration is unavailable') from None

    @router.post('/imports',status_code=201)
    async def import_evidence(request:Request,tenant=Depends(finance)):
        try:
            payload=ImportRequest.model_validate(await bounded_json(request))
        except (ValidationError,ValueError):
            raise HTTPException(422,'Invalid normalized billing import; check schema, decimal strings, scope and charge periods') from None
        try:
            return await run_in_threadpool(repository.import_records,tenant,payload)
        except FocusError as error:
            raise HTTPException(error.status,str(error)) from None

    @router.get('/imports')
    def import_history(limit:int=Query(25,ge=1,le=100),tenant=Depends(finance)):
        return dict(items=repository.imports(tenant,limit))

    @router.get('/summary')
    def summary(start:date|None=None,end:date|None=None,currency:str=Query('USD',pattern=r'^[A-Z]{3}$'),
                budget:str|None=None,tenant=Depends(finance)):
        today=datetime.now(timezone.utc).date()
        start,end=start or today.replace(day=1),end or today
        if not 0<(end-start).days<=366:
            raise HTTPException(422,'Select a billing window from 1 to 366 UTC days')
        try:
            if budget is not None:
                budget=money(budget)
                if budget.startswith('-'): raise ValueError('Budget cannot be negative')
            return repository.summary(tenant,start,end,currency,budget)
        except (FocusError,ValueError) as error:
            raise HTTPException(error.status if isinstance(error,FocusError) else 422,
                                str(error) if isinstance(error,FocusError) else 'Budget must be a nonnegative decimal string') from None

    @router.get('/unit-economics/preview')
    def unit_economics_preview(
        prior_cost: str = Query(..., min_length=1, max_length=32),
        current_cost: str = Query(..., min_length=1, max_length=32),
        prior_volume: str = Query(..., min_length=1, max_length=32),
        current_volume: str = Query(..., min_length=1, max_length=32),
        tenant=Depends(finance),
    ):
        from app.unit_economics import compute_elasticity_ratio
        try:
            return compute_elasticity_ratio(prior_cost, current_cost, prior_volume, current_volume)
        except ValueError as error:
            raise HTTPException(422, str(error)) from None

    return router
