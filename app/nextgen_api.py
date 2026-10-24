"""Authenticated counterfactual planning and signed-evidence savings lifecycle."""
from datetime import datetime,timezone
import hashlib,json
from typing import Literal
from uuid import UUID
from fastapi import APIRouter,Depends,Header,HTTPException,Request
from pydantic import Field,ValidationError,field_validator
from app.auth import Role,require_workspace_role
from app.gitops_api import bounded_json
from app.causal_topology_simulator import Strict,TopologyScenario,SLOEvidence,NetworkScenario,simulate_cascading_topology_savings,evaluate_slo_bounded_rightsizing,analyze_cross_az_and_nat_hairpin_waste,analyze_ephemeral_batch_waste
from app.commitment_arbitrage import calculate_clean_commitment_baseline
from app.nextgen_evidence import validate_receipt
from app.savings_store import SavingsConflict,visible


class CaseRequest(Strict):
    scan_id:str=Field(pattern=r'^[a-fA-F0-9-]{36}$')
    resource_id:str=Field(min_length=1,max_length=2048)
    request_key:str=Field(pattern=r'^[a-fA-F0-9-]{36}$')
    action:Literal['retirement','rightsizing']
    note:str=Field('',max_length=1000)

    @field_validator('scan_id','request_key')
    @classmethod
    def identifiers(cls,value):return str(UUID(value))


class Transition(Strict):
    version:int=Field(ge=1)
    state:Literal['reviewed','accepted_for_investigation','scheduled','rejected','deferred']
    note:str=Field('',max_length=1000)


class VerifyRequest(Strict):
    version:int=Field(ge=1)
    scan_id:str=Field(pattern=r'^[a-fA-F0-9-]{36}$')

    @field_validator('scan_id')
    @classmethod
    def identifier(cls,value):return str(UUID(value))


class Commitment(Strict):
    raw_spend_p10_hr:str
    open_rightsizing_and_waste_hr:str
    existing_commitments_hr:str


def public_case(case,tenant):
    if case is None:return None
    if {'TenantAdmin','BillingAdmin'}&set(tenant.get('roles',[])):return case
    def redact(value):
        if isinstance(value,dict):return {k:(None if k.endswith('_usd') else redact(v)) for k,v in value.items()}
        if isinstance(value,list):return [redact(v) for v in value]
        return value
    return redact(case)


def create_router(scan_store,repository,current_tenant):
    router=APIRouter(prefix='/api/v1/optimization')
    def owned(scan_id,tenant):
        try:scan_id=str(UUID(scan_id))
        except ValueError:raise HTTPException(422,'Invalid scan identifier') from None
        scan=scan_store.get(tenant['tenant_id'],scan_id)
        if scan is None:raise HTTPException(404,'Scan not found')
        if scan['status']!='completed' or scan.get('data_origin')=='legacy_synthetic':raise HTTPException(409,'Select a completed live scan.')
        return scan
    def require(value):
        if value is None:raise HTTPException(404,'Savings case not found')
        return value
    def call(fn,*args,**kwargs):
        try:return fn(*args,**kwargs)
        except SavingsConflict as error:raise HTTPException(409,str(error)) from None
        except (ValidationError,ValueError,TypeError,KeyError):raise HTTPException(422,'Invalid planning input; check decimal strings, graph structure, evidence windows and required fields.') from None

    @router.get('/scans/{scan_id}')
    def overview(scan_id:UUID,tenant=Depends(current_tenant)):
        scan=owned(str(scan_id),tenant)
        from app.observed_topology import key_for
        return dict(scan_id=scan['scan_id'],observed_at=scan['timestamp'],resource_count=len(scan.get('inventory',[])),
            resources=[dict({k:r.get(k) for k in ('resource_id','resource_name','resource_type','cloud_provider','scope_id','subscription_id')},resource_key=key_for(r)) for r in scan.get('inventory',[])[:1000]],
            signed_evidence_required=True,verified_realized_savings_usd=None,
            warning='Planning outputs are counterfactuals. Only trusted evidence can complete a savings case.')

    @router.get('/scans/{scan_id}/topology/{root_key}')
    def topology(scan_id:UUID,root_key:str,tenant=Depends(current_tenant)):
        from app.observed_topology import graph
        import re
        if not re.fullmatch(r'[a-f0-9]{64}',root_key):raise HTTPException(422,'Invalid topology root')
        return require(call(graph,owned(str(scan_id),tenant),root_key))

    @router.post('/simulate/{engine}')
    async def simulate(engine:Literal['topology','slo','network','commitments','batch'],request:Request,tenant=Depends(current_tenant)):
        body=await bounded_json(request)
        functions={'topology':simulate_cascading_topology_savings,'slo':evaluate_slo_bounded_rightsizing,'network':analyze_cross_az_and_nat_hairpin_waste,
            'commitments':lambda v:calculate_clean_commitment_baseline(**Commitment.model_validate(v).model_dump()),'batch':analyze_ephemeral_batch_waste}
        from starlette.concurrency import run_in_threadpool
        return await run_in_threadpool(call,functions[engine],body)

    @router.get('/cases')
    def cases(tenant=Depends(current_tenant)):
        return dict(items=[public_case(case,tenant) for case in repository.list(tenant)])

    @router.post('/cases',status_code=201)
    def create(body:CaseRequest,tenant=Depends(current_tenant)):
        require_workspace_role(tenant,Role.TENANT_ADMIN)
        scan=owned(body.scan_id,tenant)
        resource=next((r for r in scan.get('inventory',[]) if r['resource_id']==body.resource_id),None)
        if resource is None:raise HTTPException(404,'Resource not found in the owned scan')
        return call(repository.create,tenant,scan,resource,str(UUID(body.request_key)),body.action,body.note)

    @router.get('/cases/{case_id}')
    def detail(case_id:UUID,tenant=Depends(current_tenant)):
        return public_case(require(repository.get(tenant,str(case_id))),tenant)

    @router.patch('/cases/{case_id}')
    def transition(case_id:UUID,body:Transition,tenant=Depends(current_tenant)):
        require_workspace_role(tenant,Role.TENANT_ADMIN)
        return require(call(repository.transition,tenant,str(case_id),body.version,body.state,body.note))

    @router.post('/cases/{case_id}/verify')
    def verify(case_id:UUID,body:VerifyRequest,tenant=Depends(current_tenant)):
        require_workspace_role(tenant,Role.BILLING_ADMIN)
        return require(call(repository.verify,tenant,str(case_id),owned(body.scan_id,tenant),body.version))

    @router.post('/receipts',status_code=201)
    async def receipt(request:Request,x_evidence_signature:str=Header(default=''),tenant=Depends(current_tenant)):
        require_workspace_role(tenant,Role.TENANT_ADMIN)
        raw=await bounded_json(request)
        try:
            receipt,value,fingerprint=validate_receipt(raw,x_evidence_signature,tenant)
        except (ValueError,KeyError,TypeError):raise HTTPException(422,'Collector receipt, source grant or signature is invalid.') from None
        if not visible({'provider':receipt.provider,'scope_id':receipt.scope_id},tenant):raise HTTPException(403,'Receipt is outside this key’s grant.')
        return call(repository.save_receipt,tenant,receipt,value,fingerprint)

    return router
