"""Bounded connector programs. Model output is data; authority comes from saved approval."""
import hashlib
import json
import os
import re
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)

ALLOWED_OPERATIONS_BY_KIND={
    'azure_arm':{'resource.inspect','tags.merge','snapshot.create'},'aws_sdk':{'resource.inspect','tags.merge','ebs.snapshot.create'},
    'gcp_rest':{'resource.inspect','labels.merge','disk.snapshot.create'},'k8s_api':{'workload.inspect','annotations.merge'},
    'gitops_terraform':{'gitops.terraform.sync'},'http_json':{'action.submit'}}
READ_OPERATIONS={'resource.inspect','workload.inspect'}
WRITE_OPERATIONS=set().union(*ALLOWED_OPERATIONS_BY_KIND.values())-READ_OPERATIONS


EXPECTED_STATE_FIELDS={
    'azure_arm':{'diskState':str,'powerState':str,'numberOfSites':int},
    'aws_sdk':{'State':str,'DBInstanceStatus':str},'gcp_rest':{'status':str,'state':str},
    'k8s_api':{'generation':int,'replicas':int}}

def expected_state(resource):
    e=resource.get('evidence') or {};provider=resource.get('cloud_provider','azure');kind=resource.get('resource_type','').lower()
    pairs=[]
    if provider=='azure':pairs=[('diskState','disk_state'),('powerState','power_state'),('numberOfSites','hosted_app_count')]
    elif provider=='aws':pairs=[('DBInstanceStatus','power_state')] if ':rds:' in kind else [('State','disk_state' if kind.endswith(':volume') else 'power_state')]
    elif provider=='gcp':pairs=[('status','disk_state' if kind.endswith('/disk') else 'state')]
    elif provider=='kubernetes':pairs=[('generation','generation'),('replicas','desired_replicas')]
    return {target:e[source] for target,source in pairs if type(e.get(source)) in (str,int) and not isinstance(e.get(source),bool)}

class Connector(Strict):
    id: str = Field(pattern=r'^[a-z][a-z0-9-]{0,59}$')
    tenant_id: str
    provider: Literal['azure', 'aws', 'gcp', 'kubernetes']
    scope_id: str = Field(min_length=1, max_length=128)
    kind: Literal['azure_arm', 'aws_sdk', 'gcp_rest', 'k8s_api', 'gitops_terraform', 'http_json']
    target_id: str | None = None
    target_binding: dict | None = None
    operations: list[str] = Field(min_length=1, max_length=8)
    endpoint: str | None = Field(default=None,max_length=2048)
    token_env: str | None = Field(default=None,max_length=100)
    region: str | None = Field(default=None,max_length=40)
    role_arn: str | None = Field(default=None,max_length=512)
    service_account: str | None = Field(default=None,max_length=160)

    @field_validator('tenant_id')
    @classmethod
    def tenant(cls, value): return str(UUID(value))


def connectors():
    raw = json.loads(os.getenv('CLOUDSAVER_AGENT_CONNECTORS', '[]'))
    if not isinstance(raw, list) or len(raw) > 100: raise ValueError('Invalid connector catalog')
    result = [Connector.model_validate(item) for item in raw]
    if len({c.id for c in result}) != len(result): raise ValueError('Duplicate connector IDs')
    for c in result:
        if c.kind != 'gitops_terraform' and (c.target_id is not None or c.target_binding is not None):
            raise ValueError('Repository bindings belong only to GitOps connectors')
        if c.kind == 'gitops_terraform':
            from app.gitops import GitOpsConfig
            if c.operations!=['gitops.terraform.sync'] or any((c.endpoint,c.token_env,c.role_arn,c.service_account,c.region)):
                raise ValueError('GitOps connectors use only an approved server-side repository binding')
            target=GitOpsConfig.load().target(c.tenant_id,c.target_id)
            if c.target_binding is not None and c.target_binding!=target:raise ValueError('Repository grant differs from operator configuration')
            c.target_binding=target
        elif c.kind == 'azure_arm':
            if c.provider != 'azure' or not set(c.operations) <= ALLOWED_OPERATIONS_BY_KIND[c.kind] or any((c.endpoint,c.token_env,c.role_arn,c.service_account,c.region)):
                raise ValueError('Invalid Azure connector')
            UUID(c.scope_id)
        elif c.kind=='aws_sdk':
            if c.provider!='aws' or not re.fullmatch(r'[0-9]{12}',c.scope_id) or not re.fullmatch(r'[a-z]{2}-[a-z0-9-]{2,24}-[0-9]',c.region or '') or not re.fullmatch(r'arn:aws:iam::'+c.scope_id+r':role/[A-Za-z0-9+=,.@_/-]{1,512}',c.role_arn or '') or any((c.endpoint,c.token_env,c.service_account)):
                raise ValueError('AWS connectors require an exact account, region and keyless role binding')
        elif c.kind=='gcp_rest':
            if c.provider!='gcp' or not re.fullmatch(r'[a-z][a-z0-9-]{4,28}[a-z0-9]',c.scope_id) or not re.fullmatch(r'[a-z0-9-]{6,30}@'+re.escape(c.scope_id)+r'\.iam\.gserviceaccount\.com',c.service_account or '') or any((c.endpoint,c.token_env,c.role_arn,c.region)):
                raise ValueError('GCP connectors require an exact project and impersonated service account')
        elif c.kind=='k8s_api':
            u=urlsplit(c.endpoint or '')
            if c.provider!='kubernetes' or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,62}',c.scope_id) or u.scheme!='https' or not u.hostname or u.path not in ('','/') or u.username or u.password or u.query or u.fragment or not re.fullmatch(r'CLOUDSAVER_AGENT_K8S_TOKEN_[A-Z0-9_]{1,60}',c.token_env or '') or any((c.role_arn,c.service_account,c.region)):
                raise ValueError('Kubernetes connectors require a fixed HTTPS API origin and service-account token reference')
        else:
            u = urlsplit(c.endpoint or '')
            if (c.operations != ['action.submit'] or u.scheme != 'https' or not u.hostname or u.username or u.password
                    or u.query or u.fragment or not re.fullmatch(r'CLOUDSAVER_AGENT_CONNECTOR_[A-Z0-9_]{1,60}', c.token_env or '')):
                raise ValueError('HTTP connectors require a fixed HTTPS endpoint and secret reference')
        if not set(c.operations)<=ALLOWED_OPERATIONS_BY_KIND[c.kind]:raise ValueError('Unsupported connector operation')
    return result


class Step(Strict):
    connector_id: str = Field(pattern=r'^[a-z][a-z0-9-]{0,59}$')
    operation: Literal['resource.inspect', 'workload.inspect', 'tags.merge', 'labels.merge', 'annotations.merge', 'snapshot.create', 'ebs.snapshot.create', 'disk.snapshot.create', 'gitops.terraform.sync', 'action.submit']
    arguments: dict = Field(default_factory=dict)
    purpose: str = Field(min_length=1, max_length=500)
    verification: str = Field(min_length=1, max_length=500)
    rollback: str = Field(min_length=1, max_length=500)


class Plan(Strict):
    summary: str = Field(min_length=1, max_length=1000)
    steps: list[Step] = Field(min_length=1, max_length=8)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False)


def digest(value): return hashlib.sha256(canonical(value).encode()).hexdigest()

def supports_resource(c,resource_id):
    """Assignment and approval reject unsupported typed adapter targets early."""
    if c.kind=='http_json':return False
    if c.kind=='gitops_terraform':return True  # The paired cloud adapter validates the actual resource grammar.
    if c.kind=='azure_arm':
        valid=bool(re.fullmatch(r'/subscriptions/'+re.escape(c.scope_id)+r'/resourceGroups/[A-Za-z0-9_.()-]+/providers/[A-Za-z0-9.]+(?:/[A-Za-z0-9_.()-]+){2,}',resource_id,re.I))
        return valid and ('snapshot.create' not in c.operations or bool(re.fullmatch(r'/subscriptions/'+re.escape(c.scope_id)+r'/resourceGroups/[A-Za-z0-9_.()-]+/providers/Microsoft.Compute/disks/[A-Za-z0-9_.()-]+',resource_id,re.I)))
    if c.kind=='aws_sdk':return bool(re.fullmatch(r'arn:aws:(?:ec2:'+re.escape(c.region or '')+':'+re.escape(c.scope_id)+r':(?:volume/vol-[0-9a-f]{8,17}|instance/i-[0-9a-f]{8,17})|rds:'+re.escape(c.region or '')+':'+re.escape(c.scope_id)+r':db:[A-Za-z][A-Za-z0-9-]{0,62})',resource_id))
    if c.kind=='gcp_rest':return bool(re.fullmatch(r'//(?:compute\.googleapis\.com/projects/'+re.escape(c.scope_id)+r'/(?:zones|regions)/[a-z0-9-]+/(?:disks|instances)/[a-z0-9-]+|sqladmin\.googleapis\.com/projects/'+re.escape(c.scope_id)+r'/instances/[a-z0-9-]+)',resource_id))
    if c.kind=='k8s_api':return bool(re.fullmatch(r'k8s://'+re.escape(c.scope_id)+r'/namespaces/[a-z0-9-]+/(?:deployments|statefulsets|daemonsets|cronjobs|persistentvolumeclaims|services)/[a-z0-9.-]+',resource_id))
    return False


def render_code(plan):
    # No free-form model string is inserted into executable source.
    lines = ["type AgentContext = { call(index: number): Promise<unknown> };",
             "export async function run(ctx: AgentContext): Promise<unknown[]> {", "  const results: unknown[] = [];"]
    lines += [f"  results.push(await ctx.call({i}));" for i in range(len(plan['steps']))]
    return '\n'.join(lines + ['  return results;', '}', ''])


def validate_plan(value, task, catalog):
    plan = Plan.model_validate(value).model_dump()
    selected = {c.id: c for c in catalog if c.id in task['payload']['connector_ids']}
    paired=[c for c in selected.values() if c.kind=='gitops_terraform']
    if len(paired)>1:raise ValueError('A task can bind only one repository target')
    if paired:
        from app.agent_gitops_sync import TERRAFORM_RESOURCE_MAP
        if task['payload'].get('resource_type','').lower() not in TERRAFORM_RESOURCE_MAP:raise ValueError('No reviewed Terraform mapping for this resource type')
    metadata=[s for s in plan['steps'] if s['operation'] in ('tags.merge','labels.merge','annotations.merge')]
    if paired and not any(s['operation']=='gitops.terraform.sync' for s in plan['steps']):
        if len(metadata)!=1 or len(plan['steps'])>=8:raise ValueError('Paired synchronization requires exactly one bounded metadata mutation')
        c=paired[0]
        plan['steps'].append(dict(connector_id=c.id,operation='gitops.terraform.sync',
            arguments=dict(target_id=c.target_id,patch_mode='tags_sync',attributes=metadata[0]['arguments']),
            purpose='Prepare a repository review for the exact approved metadata merge',
            verification='Verify recorded cloud evidence and the linked draft PR; CI and repository review still required',
            rollback='Do not replay cloud writes; reconcile an uncertain repository outcome independently'))
    inspected = set()
    writes = 0
    cloud_change=None
    sync_count=0
    for step in plan['steps']:
        c = selected.get(step['connector_id'])
        if not c or c.tenant_id != task['tenant_id'] or c.provider != task['provider'] or c.scope_id != task['scope_id']:
            raise ValueError('Connector is outside the task grant')
        if step['operation'] not in c.operations: raise ValueError('Operation is disabled')
        if step['operation'] not in ALLOWED_OPERATIONS_BY_KIND[c.kind]:raise ValueError('Operation does not belong to this connector kind')
        if c.kind=='http_json':raise ValueError('Data governance prohibits exporting task/resource data through generic HTTP actions.')
        if not supports_resource(c,task.get('resource_id','')):raise ValueError('This typed connector does not support the task resource. Use a tag-only Azure binding for non-disk targets.')
        from app.data_governance import safe_action_data
        safe_action_data(step['arguments'])
        args = step['arguments']
        if step['operation']=='gitops.terraform.sync':
            from app.gitops import GitOpsConfig
            if not GitOpsConfig.load().enabled:raise ValueError('Paired execution requires publishing to be configured before cloud execution')
            if (sync_count or cloud_change is None or writes!=1 or step is not plan['steps'][-1]
                    or args!=dict(target_id=c.target_id,patch_mode='tags_sync',attributes=cloud_change)):
                raise ValueError('Repository synchronization must follow and match the one approved metadata merge')
            sync_count+=1
        elif step['operation'] in READ_OPERATIONS:
            if set(args)-{'expected_state'}:raise ValueError('Inspection accepts only bounded expected state')
            expected=args.get('expected_state',{})
            bounds=EXPECTED_STATE_FIELDS[c.kind]
            if not isinstance(expected,dict) or not 0<=len(expected)<=3 or any(key not in bounds or type(value) is not bounds[key] or isinstance(value,str) and not re.fullmatch(r'[A-Za-z0-9/_-]{1,80}',value) or type(value) is int and not 0<=value<=1000000 for key,value in expected.items()):raise ValueError('Unsupported expected live state')
            saved=task.get('payload',{}).get('expected_state') or {}
            if saved and expected and expected!=saved:raise ValueError('Expected state must match the saved observation')
            if saved:args['expected_state']=saved
            inspected.add(c.id)
        elif step['operation'] in ('tags.merge','labels.merge','annotations.merge'):
            field=step['operation'].split('.')[0]
            tags = args.get(field)
            if set(args) != {field} or not isinstance(tags, dict) or not 1 <= len(tags) <= 10 or c.id not in inspected:
                raise ValueError('Tag changes require prior inspection and explicit tags')
            for key, val in tags.items():
                if (not isinstance(key,str) or not re.fullmatch(r'[A-Za-z0-9._:/-]{1,64}', key) or key.lower().startswith(('hidden', 'microsoft', 'azure','aws:'))
                        or not isinstance(val, str) or not 1 <= len(val) <= 128 or any(ord(ch) < 32 for ch in val)):
                    raise ValueError('Unsupported tag key/value')
                if field=='labels' and (not re.fullmatch(r'[a-z][a-z0-9_-]{0,62}',key) or not re.fullmatch(r'[a-z0-9_-]{0,63}',val)):raise ValueError('GCP label syntax is invalid')
                if field=='annotations' and not re.fullmatch(r'cloudsaver\.io/recommended-[A-Za-z0-9_.-]{1,38}',key):raise ValueError('Only CloudSaver recommendation annotations may be changed')
            writes += 1
            cloud_change=args
        elif step['operation'] in ('snapshot.create','ebs.snapshot.create','disk.snapshot.create'):
            if (step['operation']=='ebs.snapshot.create' and ':volume/vol-' not in task['resource_id'] or step['operation']=='disk.snapshot.create' and '/disks/' not in task['resource_id']):raise ValueError('Safety snapshots require a managed/persistent disk or EBS volume target')
            if c.id not in inspected or set(args)!={'snapshot_name_prefix','retention_days'} or not isinstance(args['snapshot_name_prefix'],str) or not re.fullmatch(r'[a-z][a-z0-9-]{0,39}',args['snapshot_name_prefix']) or type(args['retention_days']) is not int or not 7<=args['retention_days']<=90:
                raise ValueError('Safety snapshots require prior inspection, a bounded prefix and 7–90 day retention')
            writes+=1
        else:
            if set(args) != {'body'} or not isinstance(args['body'], dict) or len(canonical(args).encode()) > 4000:
                raise ValueError('HTTP action requires a bounded explicit JSON body')
            writes += 1
    if writes > 1: raise ValueError('Split independent changes into separately approved tasks')
    if len(canonical(plan).encode()) > 16000: raise ValueError('Plan exceeds review limit')
    return plan


def binding(c):
    # Secret names, endpoint, operations and ownership are approval-bound; secret values are never returned.
    return c.model_dump(exclude={'target_id','target_binding'} if c.kind!='gitops_terraform' else set())


def program_hash(task, plan, catalog):
    selected = {s['connector_id'] for s in plan['steps']}
    paired=any(s['operation']=='gitops.terraform.sync' for s in plan['steps'])
    return digest(dict(schema=5 if paired else 4,data_governance_contract=2, task_id=task['id'], tenant_id=task['tenant_id'], provider=task['provider'],
        scope_id=task['scope_id'], resource_id=task['resource_id'], plan=plan, code=render_code(plan),
        connectors=[binding(c) for c in sorted(catalog, key=lambda c: c.id) if c.id in selected]))
