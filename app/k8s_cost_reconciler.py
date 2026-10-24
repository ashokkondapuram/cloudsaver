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
        cluster_unallocated_slack_usd=None,billed_node_cost_usd=e.get('billed_node_cost_usd'),realizable_node_savings_usd=e.get('realizable_node_savings_usd'),
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
        if link and link[0]=='aws':
            resolved=resolve_eks_node(node,inventory)
            if resolved:mapped_cloud.setdefault(('aws',resolved['resource_id']),set()).add(group)
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


def resolve_eks_node(node, inventory):
    """An accountless providerID is useful only if one scoped inventory instance matches."""
    provider_id=(node.get('evidence') or {}).get('provider_id','')
    match=re.fullmatch(r'aws:///([a-z]{2}-[a-z]+-\d)[a-z]/(i-[0-9a-f]{8,17})',provider_id)
    if not match:return None
    candidates=[]
    for row in inventory:
        arn=re.fullmatch(r'arn:aws:ec2:([a-z0-9-]+):([0-9]{12}):instance/(i-[0-9a-f]{8,17})',row['resource_id'])
        if row.get('cloud_provider')=='aws' and arn and (arn[1],arn[3])==(match[1],match[2]) and row.get('scope_id',row.get('subscription_id'))==arn[2]:
            candidates.append(row)
    return candidates[0] if len(candidates)==1 else None


def attach_node_costs(inventory):
    """Attach complete imported node costs and conservative, explicitly gated pool models."""
    index={(r.get('cloud_provider','azure'),r['resource_id'].lower() if r.get('cloud_provider','azure')=='azure' else r['resource_id']):r for r in inventory}
    pools={}
    for node in inventory:
        if node.get('cloud_provider')!='kubernetes' or node['resource_type']!='kubernetes.io/Node':continue
        e=node.setdefault('evidence',{});link=cloud_identity(e.get('provider_id'))
        cloud=resolve_eks_node(node,inventory) if link and link[0]=='aws' else index.get(link) if link else None
        e['billed_node_cost_usd']=None;e['realizable_node_savings_usd']=None
        if cloud:
            billing=cloud.get('evidence') or {}
            cost=money(billing.get('billed_cost_usd'))
            if billing.get('billing_coverage') is True and cost is not None:
                e['billed_node_cost_usd']=cost
                e['backing_cloud_resource_id']=cloud['resource_id']
                e['node_billing_commitment_locked']=billing.get('commitment_locked') is True
        if e.get('node_pool'):pools.setdefault((node['scope_id'],e['node_pool']),[]).append(node)
    for members in pools.values():
        valid=all(r['evidence'].get('requests',{}).get('complete') is True and all(type(r['evidence'].get('allocatable_'+d)) in (int,float) and r['evidence']['allocatable_'+d]>0 for d in ('cpu','memory')) for r in members)
        # A uniform pool gives a lower bound on required nodes, not scheduler proof.
        uniform=valid and all(len({r['evidence']['allocatable_'+d] for r in members})==1 for d in ('cpu','memory'))
        count=0
        if uniform:
            required=max(math.ceil(sum(r['evidence']['requests'][d] for r in members)/members[0]['evidence']['allocatable_'+d]) for d in ('cpu','memory'))
            count=max(0,len(members)-max(1,required))
        safe=uniform and count>0 and all(e.get('pdb_blocked') is False and e.get('scale_down_disabled') is False and e.get('scheduling_constraints_verified') is True and e.get('node_billing_commitment_locked') is False for e in (r['evidence'] for r in members))
        costs=[r['evidence'].get('billed_node_cost_usd') for r in members]
        known=all(c is not None for c in costs)
        savings=sum(sorted(costs)[:count]) if safe and known else None
        for r in members:
            r['evidence'].update(pool_billed_node_cost_usd=sum(costs) if known else None,consolidatable_node_count=count if uniform else None,
                realizable_node_savings_usd=savings,node_savings_basis='modeled_complete_imported_billing_and_verified_scheduling' if savings is not None else 'unverified_scheduling_or_billing')
