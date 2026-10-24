"""Signed, tenant-bound collector receipts; workspace users cannot self-attest verification."""
from datetime import datetime,timezone
import hashlib,hmac,json,os,re
from typing import Literal
from pydantic import Field,field_validator
from app.causal_topology_simulator import Strict,SLOEvidence,evaluate_slo_bounded_rightsizing
from app.telemetry_contract import moment
from app.commitment_arbitrage import parse_strict_monetary_decimal as money


class Receipt(Strict):
    receipt_id:str=Field(pattern=r'^[a-fA-F0-9-]{36}$')
    source_id:str=Field(pattern=r'^[a-z0-9-]{1,60}$')
    tenant_id:str=Field(pattern=r'^[a-fA-F0-9-]{36}$')
    provider:Literal['azure','aws','gcp','kubernetes']
    scope_id:str=Field(min_length=1,max_length=128)
    resource_id:str=Field(min_length=1,max_length=2048)
    kind:Literal['audit','billing','slo']
    issued_at:str
    payload:dict

    @field_validator('receipt_id','tenant_id')
    @classmethod
    def identifiers(cls,value):
        from uuid import UUID
        return str(UUID(value))


class CollectorSource(Strict):
    tenant_id:str=Field(pattern=r'^[a-fA-F0-9-]{36}$')
    source_id:str=Field(pattern=r'^[a-z0-9-]{1,60}$')
    providers:list[Literal['azure','aws','gcp','kubernetes']]=Field(min_length=1,max_length=4)
    kinds:list[Literal['audit','billing','slo']]=Field(min_length=1,max_length=3)
    scope_ids:list[str]=Field(min_length=1,max_length=100)
    key_env:str=Field(pattern=r'^CLOUDSAVER_EVIDENCE_KEY_[A-Z0-9_]{1,80}$')


def current_sources():
    values=json.loads(os.getenv('CLOUDSAVER_EVIDENCE_SOURCES','[]'))
    if not isinstance(values,list) or len(values)>100:raise ValueError('Collector source configuration is invalid.')
    result=[CollectorSource.model_validate(v).model_dump() for v in values]
    if len({(v['tenant_id'],v['source_id']) for v in result})!=len(result):raise ValueError('Duplicate collector source identity.')
    return result


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()


class AuditProof(Strict):
    event_id:str=Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9_:/+=.-]{0,199}$')
    occurred_at:str
    operation:Literal['delete','resize']
    status:Literal['Succeeded']

    @field_validator('event_id')
    @classmethod
    def event_identifier(cls,value):
        from uuid import UUID
        try:return str(UUID(value))
        except ValueError:return value


class BillingProof(Strict):
    currency:Literal['USD']
    baseline_start:str
    baseline_end:str
    observation_start:str
    observation_end:str
    baseline_monthly_cost_usd:str
    post_resource_cost_usd:str
    new_backup_or_snapshot_overhead_usd:str
    one_time_transition_cost_usd:str
    provider_reconciled:bool
    coverage_complete:bool
    overhead_inventory_complete:bool
    workload_normalized:bool=False
    normalization_method:str|None=Field(None,max_length=200)


def validate_receipt(raw,signature,tenant,*,sources=None,now=None):
    from uuid import UUID
    receipt=Receipt.model_validate(raw)
    now=now or datetime.now(timezone.utc)
    if str(UUID(receipt.tenant_id))!=tenant['tenant_id']:raise ValueError('Receipt tenant does not match the workspace.')
    str(UUID(receipt.receipt_id))
    issued=moment(receipt.issued_at)
    if not issued or not -60<=(now-issued).total_seconds()<=300:raise ValueError('Receipt must be freshly issued within five minutes.')
    configured=current_sources() if sources is None else [CollectorSource.model_validate(s).model_dump() for s in sources]
    if not isinstance(configured,list) or len(configured)>100:raise ValueError('Collector source configuration is invalid.')
    matches=[s for s in configured if isinstance(s,dict) and s.get('tenant_id')==tenant['tenant_id'] and s.get('source_id')==receipt.source_id]
    if len(matches)!=1:raise ValueError('An operator-approved collector source is required.')
    source=matches[0]
    if receipt.provider not in source.get('providers',[]) or receipt.kind not in source.get('kinds',[]) or receipt.scope_id not in source.get('scope_ids',[]):
        raise ValueError('Collector grant does not cover this receipt.')
    key_env=source.get('key_env','')
    if not isinstance(key_env,str) or not re.fullmatch(r'CLOUDSAVER_EVIDENCE_KEY_[A-Z0-9_]{1,80}',key_env):raise ValueError('Collector signing-key binding is invalid.')
    secret=os.getenv(key_env,'')
    if len(secret)<32 or not isinstance(signature,str) or not re.fullmatch(r'[a-f0-9]{64}',signature):raise ValueError('Collector signature is unavailable or invalid.')
    if not hmac.compare_digest(hmac.new(secret.encode(),canonical(raw),hashlib.sha256).hexdigest(),signature):raise ValueError('Collector signature is invalid.')
    if receipt.kind=='slo':
        value=SLOEvidence.model_validate(receipt.payload)
        normalized={'gate':evaluate_slo_bounded_rightsizing(value,now=now),'observed_at':value.observed_at,'raw_evidence_sha256':hashlib.sha256(canonical(receipt.payload)).hexdigest()}
    elif receipt.kind=='audit':
        normalized=AuditProof.model_validate(receipt.payload).model_dump()
        if not moment(normalized['occurred_at']):raise ValueError('Deletion event timestamp must include a timezone.')
    else:
        normalized=BillingProof.model_validate(receipt.payload).model_dump()
        for field in ('baseline_monthly_cost_usd','post_resource_cost_usd','new_backup_or_snapshot_overhead_usd','one_time_transition_cost_usd'):money(normalized[field])
        from datetime import date
        for field in ('baseline_start','baseline_end','observation_start','observation_end'):date.fromisoformat(normalized[field])
    return receipt,normalized,hashlib.sha256(canonical(raw)).hexdigest()
