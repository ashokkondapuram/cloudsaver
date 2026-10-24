"""Allocation estimates remain distinct from verified node billing and realizable savings."""
from decimal import Decimal, InvalidOperation
import hashlib
import math
import re
from app.telemetry_contract import moment


def money(value):
    try:
        if isinstance(value,bool): return None
        number=Decimal(str(value))
        return float(number) if number.is_finite() and 0<=number<=Decimal('1e12') else None
    except (ValueError,InvalidOperation,TypeError,OverflowError):
        return None


def allocations(payload, cluster, allowed, start, end):
    if payload.get('code')!=200 or payload.get('errors') or payload.get('warnings'):
        raise ValueError('Incomplete allocation response')
    data=payload.get('data')
    if not isinstance(data,list) or len(data)!=1 or not isinstance(data[0],dict) or len(data[0])>20000:
        raise ValueError('Ambiguous allocation window')
    result={}
    for row in data[0].values():
        props=row.get('properties') or {}
        key=(props.get('namespace'),props.get('pod'),props.get('container'))
        # Shared, idle and unknown containers are intentionally not reassigned to a workload.
        if props.get('cluster')!=cluster or key not in allowed:
            continue
        window=row.get('window') or {}
        if moment(window.get('start'))!=start or moment(window.get('end'))!=end or key in result:
            raise ValueError('Conflicting allocation identity or window')
        cpu,ram,total=(money(row.get(k)) for k in ('cpuCost','ramCost','totalCost'))
        # OpenCost values are model estimates. They are never relabelled as FOCUS billed costs.
        result[key]=dict(cpu_allocation_usd=cpu,memory_allocation_usd=ram,total_allocation_usd=total,
            billed_cost_usd=None,realizable_node_savings_usd=None,currency='USD',basis='opencost_allocation_estimate',
            window_start=start.isoformat(),window_end=end.isoformat())
    return result


def breakdown(row):
    e=row.get('evidence') or {};allocation=e.get('allocation') or {};metrics=e.get('metrics') or {}
    used=slack=0.
    complete=True
    for dimension,field in (('cpu','cpu_allocation_usd'),('memory','memory_allocation_usd')):
        metric=metrics.get(dimension) or {};request=e.get(dimension+'_request');cost=allocation.get(field)
        if metric.get('sufficient') is not True or type(request) not in (int,float) or request<=0 or cost is None:
            complete=False;continue
        ratio=min(1,metric['p95']/request)
        used+=cost*ratio;slack+=cost*(1-ratio)
    return dict(workload_used_estimate_usd=used if complete else None,workload_request_slack_estimate_usd=slack if complete else None,
        cluster_unallocated_slack_usd=None,billed_node_cost_usd=None,realizable_node_savings_usd=None,
        allocation_total_usd=allocation.get('total_allocation_usd'),currency='USD',
        explanation='P95 CPU/memory allocation estimates are not a bill or additive node savings. Storage/network allocation is not included in the split.')


def cloud_identity(provider_id):
    if not isinstance(provider_id,str):return None
    if provider_id.startswith('azure:///subscriptions/'):
        return 'azure','/'+provider_id[len('azure:///'):].lower()
    match=re.fullmatch(r'aws:///([a-z0-9-]+)/([a-z0-9-]+)',provider_id)
    if match:
        return 'aws',match[2]
    match=re.fullmatch(r'gce://([a-z0-9-]+)/([a-z0-9-]+)/([a-z0-9-]+)',provider_id)
    if match:
        return 'gcp','//compute.googleapis.com/projects/'+match[1]+'/zones/'+match[2]+'/instances/'+match[3]
    return None


def group_opportunities(findings, inventory):
    nodes={(r['scope_id'],r['resource_name']):r for r in inventory if r.get('cloud_provider')=='kubernetes' and r['resource_type']=='kubernetes.io/Node'}
    groups={}
    mapped_cloud={}
    for row in inventory:
        if row.get('cloud_provider')!='kubernetes':continue
        e=row.get('evidence') or {}
        node=row if row['resource_type']=='kubernetes.io/Node' else nodes.get((row['scope_id'],e.get('node')))
        pool=(node or {}).get('evidence',{}).get('node_pool')
        if not node or not pool:continue
        group='cluster_pool:'+hashlib.sha256((row['scope_id']+'|'+pool).encode()).hexdigest()
        groups[('kubernetes',row['resource_id'])]=group
        link=cloud_identity(node['evidence'].get('provider_id'))
        if link and link[0] in ('azure','gcp'):
            mapped_cloud.setdefault(link,set()).add(group)
        # AWS providerID omits the account ID; it cannot uniquely prove the billing resource.
    visible={(r.get('cloud_provider','azure'),r['resource_id'].lower() if r.get('cloud_provider','azure')=='azure' else r['resource_id']) for r in inventory}
    for cloud,values in mapped_cloud.items():
        if len(values)==1 and cloud in visible:
            groups[cloud]=next(iter(values))
    joined={}
    for row in findings:
        provider=row.get('cloud_provider','azure')
        identity=(provider,row['resource_id'].lower() if provider=='azure' else row['resource_id'])
        if row.get('opportunity_group_id') and identity in groups:
            joined.setdefault(row['opportunity_group_id'],set()).add(groups[identity])
    result=[]
    for row in findings:
        provider=row.get('cloud_provider','azure')
        key=(provider,row['resource_id'].lower() if provider=='azure' else row['resource_id'])
        group=groups.get(key)
        old=row.get('opportunity_group_id')
        if old in joined:
            group=next(iter(joined[old])) if len(joined[old])==1 else None
        result.append(dict(row,opportunity_group_id=group,opportunity_overlap_basis='observed_cluster_node_pool') if group else row)
    return result
