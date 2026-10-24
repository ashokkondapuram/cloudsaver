"""Explicit normalized billing ingestion; tenant-owned, finance-authorized access."""
from datetime import date, datetime, timezone
import json
from fastapi import APIRouter, Depends, HTTPException, Query, Request
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
    return router
