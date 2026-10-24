"""Tenant-owned governance visibility, bounded legal holds and audited content erasure."""
from datetime import datetime,timezone
from uuid import UUID
from fastapi import APIRouter,Depends,HTTPException
from pydantic import Field,field_validator
from app.agent_contract import Strict
from app.auth import Role,require_workspace_role
from app.data_governance import DataGovernor
from app.data_retention import DataRetention,RetentionConflict


class PrivacyRequest(Strict):
    review_reference:str=Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9._/-]{2,119}$')


class HoldRequest(PrivacyRequest):
    hold_until:datetime

    @field_validator('hold_until',mode='before')
    @classmethod
    def aware(cls,value):
        if isinstance(value,str):value=datetime.fromisoformat(value.replace('Z','+00:00'))
        if not isinstance(value,datetime):raise ValueError('Use an ISO timestamp')
        if value.tzinfo is None:raise ValueError('A timezone is required')
        return value.astimezone(timezone.utc)


def create_router(store,current_tenant,governor=None):
    router=APIRouter(prefix='/api/v1/ai/governance');retention=DataRetention(store);governor=governor or DataGovernor(store)
    def owner(tenant):
        require_workspace_role(tenant,Role.TENANT_ADMIN)
        if tenant.get('subject_type')=='service_account':raise HTTPException(403,'A human data owner must authorize privacy and legal-hold requests.')
    def call(fn,*args):
        try:return fn(*args)
        except RetentionConflict as error:raise HTTPException(409,str(error)) from None

    @router.get('')
    def view(tenant=Depends(current_tenant)):
        retention.purge(tenant['tenant_id'])
        return dict(policy=governor.view(tenant),**retention.view(tenant))

    @router.post('/records/{attempt_id}/erase')
    def erase(attempt_id:UUID,body:PrivacyRequest,tenant=Depends(current_tenant)):
        owner(tenant)
        return call(retention.erase,tenant,str(attempt_id),body.review_reference)

    @router.post('/records/{attempt_id}/hold',status_code=201)
    def hold(attempt_id:UUID,body:HoldRequest,tenant=Depends(current_tenant)):
        owner(tenant)
        return call(retention.hold,tenant,str(attempt_id),body.hold_until,body.review_reference)

    return router
