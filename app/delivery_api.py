"""Tenant operational visibility and explicit, bounded integration replay."""
import hashlib
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, StrictBool, ValidationError

from app.auth import Role, require_workspace_role


class ReplayRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    acknowledge_duplicate_risk: StrictBool


async def replay_payload(request:Request):
    from app.plan_policy import InvalidPlan,load_json
    raw=bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw)>1024:
            raise HTTPException(413,'Replay request exceeds the 1 KB limit')
    try:
        return ReplayRequest.model_validate(load_json(bytes(raw)))
    except (InvalidPlan,ValidationError):
        raise HTTPException(422,'Invalid replay acknowledgment') from None


def create_router(settings,store,current_tenant,*,targets=None,repository=None):
    from app.delivery_config import enabled,load_targets
    from database.delivery import DeliveryConflict,DeliveryRepository
    router=APIRouter()
    # SQLite is deliberately unsupported: operational reliability requires PG.
    repository=repository or (DeliveryRepository(settings.database_url) if settings.database_url else None)
    fixed_targets=targets

    def current_targets(tenant_id):
        rows=load_targets(settings) if fixed_targets is None else fixed_targets
        return [t for t in rows if t.tenant_id==tenant_id]

    def available():
        if repository is None:
            raise HTTPException(503,'Durable delivery requires PostgreSQL')

    def own_scan(tenant,scan_id):
        scan=store.get(tenant['tenant_id'],str(scan_id))
        if not scan:
            raise HTTPException(404,'Scan not found')
        if scan.get('status')!='completed' or scan.get('data_origin')=='legacy_synthetic':
            raise HTTPException(409,'A completed live scan is required')
        return scan

    @router.get('/api/v1/operations/reliability')
    def reliability(tenant=Depends(current_tenant)):
        if repository is None:
            return {'available':False,'dispatcher_enabled':False,'targets':[],'counts':[],'oldest_due_seconds':None,'dispatcher':None}
        return {'available':True,'dispatcher_enabled':enabled(),
                'targets':[t.public() for t in current_targets(tenant['tenant_id'])],**repository.summary(tenant['tenant_id'])}

    @router.get('/api/v1/operations/deliveries')
    def deliveries(limit:int=Query(50,ge=1,le=100),status:str|None=Query(None,pattern='^(pending|leased|published|delivered|dead_letter)$'),before:UUID|None=None,tenant=Depends(current_tenant)):
        available()
        try:
            return repository.page(tenant['tenant_id'],limit,status,str(before) if before else None)
        except DeliveryConflict:
            raise HTTPException(422,'Invalid delivery cursor') from None

    @router.get('/api/v1/operations/deliveries/{event_id}/audit')
    def history(event_id:UUID,limit:int=Query(50,ge=1,le=100),before:UUID|None=None,tenant=Depends(current_tenant)):
        available()
        try:
            result=repository.history(tenant['tenant_id'],str(event_id),limit,str(before) if before else None)
        except DeliveryConflict:
            raise HTTPException(422,'Invalid audit cursor') from None
        if result is None:
            raise HTTPException(404,'Delivery not found')
        return result

    @router.post('/api/v1/operations/deliveries/{event_id}/retry',status_code=202)
    def replay(event_id:UUID,tenant=Depends(current_tenant),payload:ReplayRequest=Depends(replay_payload)):
        require_workspace_role(tenant,Role.TENANT_ADMIN)
        available()
        if not repository.get(tenant['tenant_id'],str(event_id)):
            raise HTTPException(404,'Delivery not found')
        if not enabled():
            raise HTTPException(503,'Delivery dispatcher is disabled')
        if not payload.acknowledge_duplicate_risk:
            raise HTTPException(422,'Acknowledge that the provider may already have accepted this message')
        # Actor is stable and pseudonymous; no access key, email or raw claims.
        actor='principal:'+hashlib.sha256((tenant.get('user_id') or 'workspace-key').encode()).hexdigest()
        try:
            return repository.replay(tenant['tenant_id'],str(event_id),actor)
        except DeliveryConflict as exc:
            raise HTTPException(409,str(exc)) from None

    @router.post('/api/v1/notifications/{scan_id}',status_code=202)
    def enqueue_notification(scan_id:UUID,tenant=Depends(current_tenant)):
        require_workspace_role(tenant,Role.TENANT_ADMIN)
        scan=own_scan(tenant,scan_id)
        available()
        chosen=current_targets(tenant['tenant_id'])
        if not enabled() or not chosen:
            raise HTTPException(503,'Workspace notification delivery is not configured or enabled')
        ids=repository.enqueue_notification(tenant['tenant_id'],scan,chosen)
        return {'status':'queued','scan_id':str(scan_id),'delivery_ids':ids}

    return router
