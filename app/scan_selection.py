"""Credential-free durable scan selections; reauthorized at dispatch and execution."""
from uuid import UUID

SCOPE_KEYS={'azure':('subscription_ids',None),'aws':('aws_accounts','account_id'),'gcp':('gcp_projects','project_id'),'kubernetes':('kubernetes_clusters','cluster_id')}

def normalize(value):
    if isinstance(value,list):
        ids=[str(UUID(v)) for v in value]
        if not 1<=len(ids)<=100 or len(set(ids))!=len(ids):raise ValueError('Invalid Azure selection')
        return sorted(ids)
    if not isinstance(value,dict) or set(value)!={'providers','scopes'}:raise ValueError('Invalid scan selection')
    providers=value['providers'];scopes=value['scopes']
    if not isinstance(providers,list) or not providers or len(set(providers))!=len(providers) or not set(providers)<=set(SCOPE_KEYS) or not isinstance(scopes,dict) or set(scopes)!=set(providers):raise ValueError('Invalid selected providers')
    result={}
    for provider in sorted(providers):
        values=scopes[provider]
        if not isinstance(values,list) or not values or len(values)>100 or any(not isinstance(v,str) or not v or len(v)>128 for v in values) or len(set(values))!=len(values):raise ValueError('Invalid selected cloud scopes')
        result[provider]=sorted(str(UUID(v)) if provider=='azure' else v for v in values)
    if sum(map(len,result.values()))>100:raise ValueError('Select at most 100 cloud scopes')
    return dict(providers=sorted(providers),scopes=result)

def select(tenant,providers):
    return normalize(dict(providers=providers,scopes={p:[v if field is None else v[field] for v in tenant.get(key,[])] for p,(key,field) in SCOPE_KEYS.items() if p in providers}))

def restrict(tenant,selection):
    selection=normalize(selection)
    if isinstance(selection,list):
        if not set(selection)<=set(tenant.get('subscription_ids',[])):raise ValueError('Azure scope revoked')
        return dict(tenant,subscription_ids=selection)
    changes={key:[] for key,_ in SCOPE_KEYS.values()}
    for provider in selection['providers']:
        key,field=SCOPE_KEYS[provider];available={v if field is None else v[field]:v for v in tenant.get(key,[])}
        if not set(selection['scopes'][provider])<=set(available):raise ValueError('Cloud scope revoked')
        if tenant.get('allowed_providers') is not None and provider not in tenant['allowed_providers']:raise ValueError('Provider access revoked')
        changes[key]=[available[v] for v in selection['scopes'][provider]]
    return dict(tenant,**changes)

def providers(value):return value['providers'] if isinstance(value,dict) else ['azure']
def azure_ids(value):return value['scopes'].get('azure',[]) if isinstance(value,dict) else value
def count(value):return sum(map(len,value['scopes'].values())) if isinstance(value,dict) else len(value)
def payload(value):return {'selection':value} if isinstance(value,dict) else {'subscription_ids':value}
def from_payload(value):return value.get('selection',value.get('subscription_ids'))
