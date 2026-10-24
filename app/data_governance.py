"""Purpose-bound AI data use: no networking policy or network configuration."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime,timedelta,timezone
import hashlib,json,math,os,re
from uuid import UUID,uuid4

from app.data_policy import DEFAULT_DATA_GOVERNANCE,validate_data_governance

CONTRACT_VERSION=1
ACTIVE_GRANT=ContextVar('ai_data_processing_grant',default=None)
DROP_FIELDS={'resource_id','resource_name','tenant_id','subscription_id','account_id','project_id','customer_id',
    'billing_account','cost_center','application_id','tags','raw_tags','raw_telemetry','connection_string',
    'email','phone','private_ip','hostname','endpoint','url','billed_cost_usd','invoice','invoice_data'}
SECRET_FIELDS={'password','secret','client_secret','api_key','access_token','refresh_token','authorization','connection_string'}
SECRET_KEYS={re.sub(r'[^a-z0-9]','',v) for v in SECRET_FIELDS}
DROP_KEYS={re.sub(r'[^a-z0-9]','',v) for v in DROP_FIELDS}
SECRETS=re.compile(r'(?i)-----BEGIN (?:[A-Z ]*PRIVATE KEY|CERTIFICATE)-----|\bbearer\s+\S{8,}|\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]+|(?:AccountKey|SharedAccessSignature|client_secret|api[_ -]?key|password)\s*[:=]\s*\S+|[?&]sig=[A-Za-z0-9%+/=]{8,}|\b(?:sk-[A-Za-z0-9_-]{16,}|cs_(?:live|test)_[A-Za-z0-9_]{12,})')
IDENTIFIERS=[re.compile(p,re.I) for p in (
    r'/subscriptions/[^\s\"\],;]+',r'\barn:[^\s\"\],;]+',
    r'\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b',
    r'\b[\w.+-]+@[\w.-]+\.[a-z]{2,}\b',r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b',
    r'\b[0-9]{3}-[0-9]{2}-[0-9]{4}\b',r'\b(?:[a-z0-9-]+\.)+(?:internal|corp|local)\b')]
TOP_FIELDS={'assessment':{'resource_reference','provider','service_category','rule_id','facts','policy_version','observation','risk_floor','checks','protected','guardrails','observed_check_codes','knowledge'},
    'resource_assessment':{'resource_reference','provider','service_category','findings','policy_version','observation','risk_floor','checks','protected','guardrails','observed_check_codes','knowledge'},
    'followup':{'resource','question','prior_summary','prior_assessment'},'agent_planning':{'instruction','resource_type','connectors'}}
FACT_FIELDS={'encrypted','multi_az','publicly_accessible','deletion_protection','recent_snapshot_verified','imds_v2_required',
    'public_admin_ingress','monitoring_enabled','tls_required','engine_supported','auto_minor_upgrade','health_probes_enabled',
    'managed_secrets','flow_logs_enabled','public_snapshot','p95_usage','window_days','backup_retention_days','size_gb',
    'provisioned_iops','minimum_request','hosted_app_count','patch_age_days','unattached_days','snapshot_age_hours',
    'window_start','window_end','samples','step_seconds','percentile_method','dimension','unit'}


class DataDenied(ValueError):
    def __init__(self,code):self.code=code;super().__init__('AI data governance blocked processing: '+code)


def fingerprint(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def sanitize(value,*,purpose=None,output=False):
    counts={'removed_fields':0,'redacted_values':0}
    def visit(item,depth=0):
        if depth>16:raise DataDenied('PAYLOAD_DEPTH_EXCEEDED')
        if isinstance(item,dict):
            result={}
            for key,child in item.items():
                if not isinstance(key,str):raise DataDenied('INVALID_DATA_FIELD')
                normalized=re.sub(r'[^a-z0-9]','',key.casefold())
                if normalized in SECRET_KEYS:raise DataDenied('SECRET_FIELD_DETECTED')
                if not output and normalized in DROP_KEYS:counts['removed_fields']+=1;continue
                if SECRETS.search(key):raise DataDenied('SECRET_DETECTED')
                if key=='publication_id' and isinstance(child,str):
                    try:result[key]=str(UUID(child));continue
                    except ValueError:pass
                result[key]=visit(child,depth+1)
                if not output and key=='facts' and isinstance(result[key],dict):
                    counts['removed_fields']+=len(set(result[key])-FACT_FIELDS)
                    result[key]={k:v for k,v in result[key].items() if k in FACT_FIELDS}
            return result
        if isinstance(item,list):
            if len(item)>1000:raise DataDenied('PAYLOAD_ITEMS_EXCEEDED')
            return [visit(x,depth+1) for x in item]
        if isinstance(item,str):
            if len(item)>8000:raise DataDenied('DATA_VALUE_TOO_LARGE')
            if SECRETS.search(item):raise DataDenied('SECRET_DETECTED')
            for pattern in IDENTIFIERS:
                item,number=pattern.subn('[REDACTED]',item);counts['redacted_values']+=number
            return item
        if item is None or type(item) in (bool,int):return item
        if type(item) is float and math.isfinite(item):return item
        raise DataDenied('UNSUPPORTED_DATA_VALUE')
    if purpose:
        if purpose not in TOP_FIELDS or not isinstance(value,dict):raise DataDenied('UNSUPPORTED_PROCESSING_PURPOSE')
        selected={k:v for k,v in value.items() if k in TOP_FIELDS[purpose]}
        counts['removed_fields']+=len(value)-len(selected)
    else:selected=value
    cleaned=visit(selected)
    if purpose=='agent_planning' and counts['redacted_values']:
        # Replacing an action value could change its meaning. Request a generic instruction instead.
        raise DataDenied('IDENTIFYING_ACTION_INSTRUCTION')
    if len(json.dumps(cleaned,ensure_ascii=True).encode())>64000:raise DataDenied('PAYLOAD_SIZE_EXCEEDED')
    return cleaned,counts


def safe_action_data(value):
    """First-party changes retain exact approved arguments but cannot carry credentials."""
    def check(v):
        if isinstance(v,dict):
            for k,c in v.items():
                if re.sub(r'[^a-z0-9]','',k.casefold()) in SECRET_KEYS:raise DataDenied('SECRET_FIELD_DETECTED')
                check(c)
        elif isinstance(v,list):
            for c in v:check(c)
        elif isinstance(v,str) and SECRETS.search(v):raise DataDenied('SECRET_DETECTED')
    check(value)


@dataclass(frozen=True)
class ProcessingGrant:
    governor: object
    tenant_id: str
    target_id: str
    policy_digest: str
    payload_digest: str
    purpose: str
    expires_at: datetime
    retention_days: int
    metadata: dict

    @contextmanager
    def active(self):
        token=ACTIVE_GRANT.set(self)
        try:yield
        finally:ACTIVE_GRANT.reset(token)


def require_processing_grant(target,tenant,context):
    grant=ACTIVE_GRANT.get()
    if (not isinstance(grant,ProcessingGrant) or grant.tenant_id!=tenant['tenant_id'] or grant.target_id!=target.target_id
            or grant.payload_digest!=fingerprint(context) or grant.expires_at<=datetime.now(timezone.utc)):
        raise DataDenied('NO_VALID_DATA_USE_GRANT')
    grant.governor.check_processor(tenant,target,grant.purpose,expected_digest=grant.policy_digest)
    return grant


class DataGovernor:
    def __init__(self,store,policy_reader=None,clock=None):
        from app.ai_platform_policy import current
        self.store,self.reader,self.clock=store,policy_reader or current,clock or (lambda:datetime.now(timezone.utc))

    def policy(self):
        row=self.reader()
        policy=validate_data_governance(row['policy'].get('data_governance',DEFAULT_DATA_GOVERNANCE))
        return row['version'],policy,fingerprint(policy)

    def event(self,tenant,purpose,decision,reason,*,policy_digest=None,target_id=None,counts=None):
        if self.store is None:raise DataDenied('GOVERNANCE_AUDIT_UNAVAILABLE')
        from app.savings_store import actor
        with self.store.transaction(tenant['tenant_id'],write=True) as db:
            db.execute('INSERT INTO ai_data_events(id,tenant_id,purpose,decision,reason,policy_digest,target_id,metadata,actor,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                (str(uuid4()),tenant['tenant_id'],purpose,decision,reason,policy_digest or fingerprint('unavailable'),target_id,
                 db.json(counts or {}),actor(tenant),self.clock().isoformat()))

    def check_processor(self,tenant,target,purpose,expected_digest=None):
        revision,policy,digest=self.policy()
        if expected_digest is not None and expected_digest!=digest:raise DataDenied('DATA_POLICY_CHANGED')
        if (not policy['environment_id'] or policy['environment_id']!=os.getenv('CLOUDSAVER_DATA_ENVIRONMENT_ID')
                or not policy['azure_tenant_id'] or policy['azure_tenant_id']!=os.getenv('CLOUDSAVER_DATA_AZURE_TENANT_ID')):
            raise DataDenied('PROCESSING_ENVIRONMENT_NOT_REGISTERED')
        if target.provider!='azure' or target.auth!='managed_identity':raise DataDenied('PROCESSOR_OUTSIDE_ENVIRONMENT')
        if str(target.tenant_id)!=tenant['tenant_id']:raise DataDenied('PROCESSOR_WORKSPACE_MISMATCH')
        record=next((r for r in policy['processors'] if r['workspace_id']==tenant['tenant_id'] and r['target_id']==target.target_id),None)
        if not record or purpose not in record['purposes']:raise DataDenied('PROCESSOR_PURPOSE_NOT_APPROVED')
        if not target.azure_resource_id or record['azure_resource_id'].lower()!=target.azure_resource_id.lower():raise DataDenied('PROCESSOR_RESOURCE_MISMATCH')
        if not target.endpoint or record['endpoint_url'].rstrip('/')!=target.endpoint.rstrip('/') or record['deployment_name']!=target.model:raise DataDenied('PROCESSOR_DESTINATION_MISMATCH')
        expiry=datetime.fromisoformat(record['review_expires_at'].replace('Z','+00:00'))
        if expiry<=self.clock():raise DataDenied('PROCESSOR_REVIEW_EXPIRED')
        return revision,policy,digest,record

    def prepare(self,tenant,target,purpose,message):
        digest=None
        try:
            revision,policy,digest,record=self.check_processor(tenant,target,purpose)
            cleaned,counts=sanitize(message,purpose=purpose)
            metadata=dict(classification='sanitized_operational',purpose=purpose,policy_revision=revision,
                policy_digest=digest,processor_target_id=target.target_id,removed_fields=counts['removed_fields'],
                redacted_values=counts['redacted_values'],response_expires_at=(self.clock()+timedelta(days=policy['response_retention_days'])).isoformat())
            self.event(tenant,purpose,'allowed','MINIMIZED_DATA_APPROVED',policy_digest=digest,target_id=target.target_id,counts=counts)
            grant=ProcessingGrant(self,tenant['tenant_id'],target.target_id,digest,fingerprint(cleaned),purpose,
                self.clock()+timedelta(seconds=60),policy['response_retention_days'],metadata)
            return cleaned,grant
        except DataDenied as error:
            self.event(tenant,purpose,'blocked',error.code,policy_digest=digest,target_id=target.target_id)
            raise

    def clean_output(self,tenant,grant,value):
        try:return sanitize(value,output=True)[0]
        except DataDenied as error:
            self.event(tenant,grant.purpose,'blocked','MODEL_OUTPUT_'+error.code,policy_digest=grant.policy_digest,target_id=grant.target_id)
            raise

    def view(self,tenant):
        try:
            revision,policy,digest=self.policy()
            processors=[{k:v for k,v in r.items() if k!='workspace_id'} for r in policy['processors'] if r['workspace_id']==tenant['tenant_id']]
            configured=bool(policy['environment_id'] and policy['environment_id']==os.getenv('CLOUDSAVER_DATA_ENVIRONMENT_ID') and policy['azure_tenant_id']==os.getenv('CLOUDSAVER_DATA_AZURE_TENANT_ID'))
            return dict(status='enforced' if configured else 'processing_blocked',policy_revision=revision,policy_digest=digest,
                environment_id=policy['environment_id'],response_retention_days=policy['response_retention_days'],processors=processors,
                allowed_data_classes=['public','sanitized_operational'],raw_inventory_and_credentials_allowed=False,training_allowed=False,
                cross_tenant_reuse_allowed=False,external_action_data_allowed=False,
                provider_controls='Operator review attestation; provider retention/training behavior is not independently verified by CloudSaver.')
        except Exception:
            return dict(status='processing_blocked',processors=[],policy_revision=None,environment_id=None,
                response_retention_days=7,raw_inventory_and_credentials_allowed=False,training_allowed=False,cross_tenant_reuse_allowed=False,external_action_data_allowed=False)
