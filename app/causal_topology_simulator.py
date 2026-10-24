"""Deterministic counterfactuals with explicit missing evidence and no provider writes."""
from datetime import datetime,timezone
from decimal import Decimal,localcontext
import math
from pydantic import BaseModel,ConfigDict,Field,model_validator
from typing import Literal
from app.commitment_arbitrage import parse_strict_monetary_decimal as money,decimal_text as text
from app.telemetry_contract import TimeSeriesEvidenceContract,evaluate_series,moment


class Strict(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True,allow_inf_nan=False)


class CostNode(Strict):
    node_id:str=Field(pattern=r'^[a-zA-Z0-9_-]{1,80}$')
    component_id:str=Field(pattern=r'^[a-zA-Z0-9_-]{1,80}$')
    label:str=Field(min_length=1,max_length=120)
    monthly_savings_usd:str|None=None
    opportunity_group_id:str|None=Field(None,max_length=120)


class Dependency(Strict):
    parent:str=Field(max_length=80)
    child:str=Field(max_length=80)
    verification_state:Literal['verified','inferred','stale','unavailable']='unavailable'


class TopologyScenario(Strict):
    nodes:list[CostNode]=Field(min_length=1,max_length=200)
    edges:list[Dependency]=Field(default_factory=list,max_length=500)
    selected_roots:list[str]=Field(min_length=1,max_length=50)
    one_time_transition_cost_usd:str|None=None
    recurring_new_overhead_usd:str|None=None


def simulate_cascading_topology_savings(value):
    scenario=value if isinstance(value,TopologyScenario) else TopologyScenario.model_validate(value)
    nodes={node.node_id:node for node in scenario.nodes}
    if len(nodes)!=len(scenario.nodes) or len(set(scenario.selected_roots))!=len(scenario.selected_roots) or not set(scenario.selected_roots)<=nodes.keys():
        raise ValueError('Node and root identities must be unique and refer to known nodes.')
    graph={key:[] for key in nodes};parents={key:[] for key in nodes};indegree={key:0 for key in nodes};edge_ids=set()
    for edge in scenario.edges:
        key=(edge.parent,edge.child)
        if edge.parent not in nodes or edge.child not in nodes or key in edge_ids:raise ValueError('Invalid or duplicate dependency edge.')
        edge_ids.add(key);graph[edge.parent].append(edge);parents[edge.child].append(edge);indegree[edge.child]+=1
    # Validate the whole supplied graph; stale/inferred cycles are still invalid topology.
    pending=[key for key,count in indegree.items() if count==0];ordered=[]
    while pending:
        key=pending.pop();ordered.append(key)
        for edge in graph[key]:
            indegree[edge.child]-=1
            if indegree[edge.child]==0:pending.append(edge.child)
    if len(ordered)!=len(nodes):raise ValueError('Causal topology must be acyclic.')
    if any(parents[key] for key in scenario.selected_roots):raise ValueError('Selected actions must be graph roots; prerequisite actions cannot be skipped.')
    selected=set(scenario.selected_roots);blocked=[]
    for key in ordered:
        incoming=parents[key]
        if not incoming or not any(edge.parent in selected for edge in incoming):continue
        if all(edge.parent in selected and edge.verification_state=='verified' for edge in incoming):selected.add(key)
        else:
            blocked.extend(dict(parent=edge.parent,child=key,reason='ALL_PREREQUISITES_MUST_BE_VERIFIED_AND_SELECTED') for edge in incoming if edge.parent not in selected or edge.verification_state!='verified')
    groups={}
    for key in selected:
        group=nodes[key].opportunity_group_id
        if group:
            if group in groups:raise ValueError('Select one compatible alternative per opportunity group; overlapping alternatives cannot be added.')
            groups[group]=key
    components={};unknown=[]
    for key in sorted(selected):
        node=nodes[key]
        if node.monthly_savings_usd is None:unknown.append(key);continue
        amount=money(node.monthly_savings_usd)
        prior=components.get(node.component_id)
        if prior and prior['amount']!=amount:raise ValueError('Conflicting costs for one billed component cannot be reconciled.')
        if not prior:components[node.component_id]={'node_id':key,'amount':amount,'direct':key in scenario.selected_roots}
        elif key in scenario.selected_roots:prior['direct']=True
    # Validate even unreachable monetary fields; malformed numbers never disappear behind graph selection.
    for node in scenario.nodes:
        if node.monthly_savings_usd is not None:money(node.monthly_savings_usd)
    transition=money(scenario.one_time_transition_cost_usd) if scenario.one_time_transition_cost_usd is not None else None
    overhead=money(scenario.recurring_new_overhead_usd) if scenario.recurring_new_overhead_usd is not None else None
    with localcontext() as context:
        context.prec=50
        direct=sum((v['amount'] for v in components.values() if v['direct']),Decimal(0))
        cascade=sum((v['amount'] for v in components.values() if not v['direct']),Decimal(0))
        complete=not unknown and not blocked and overhead is not None and transition is not None
        net=direct+cascade-overhead if complete else None
        payback=transition/(net/Decimal(30)) if net is not None and net>0 else None
    return dict(status='modeled' if complete else 'insufficient_evidence',basis='user_supplied_counterfactual',currency='USD',
        direct_monthly_savings_usd=text(direct) if not unknown else None,cascading_downstream_savings_usd=text(cascade) if not unknown else None,
        known_gross_subtotal_usd=text(direct+cascade),one_time_transition_cost_usd=text(transition) if transition is not None else None,
        recurring_new_overhead_usd=text(overhead) if overhead is not None else None,net_monthly_savings_usd=text(net) if net is not None else None,
        payback_days=text(payback.quantize(Decimal('.0001'))) if payback is not None else None,
        selected_nodes=sorted(selected),unique_billed_components=len(components),unknown_nodes=unknown,blocked_dependencies=blocked,
        verified_realized_savings_usd=None,automatic_execution=False,
        warning='Scenario results are not billing proof. Thirty days/month is a stated payback convention; confirm attachment releases, commitments, transition and retention costs.')


class SLOEvidence(Strict):
    cpu_series:dict|None=None
    latency_p99_series:dict|None=None
    error_budget_burn_rate_30d:float|int|None=Field(None,ge=0,le=1000000)
    slo_latency_target_ms:float|int|None=Field(None,gt=0,le=10000000)
    observed_at:str|None=None
    oom_kill_count_30d:int|None=Field(None,ge=0,le=10000000)
    p95_cfs_throttled_ratio:float|int|None=Field(None,ge=0,le=1)
    fixed_heap_configured:bool|None=None
    hpa_coordination_required:bool|None=None


def evaluate_slo_bounded_rightsizing(value,*,now=None):
    evidence=value if isinstance(value,SLOEvidence) else SLOEvidence.model_validate(value)
    now=now or datetime.now(timezone.utc)
    reasons=[];unknown=[]
    observed=moment(evidence.observed_at)
    if not observed or not 0<=(now-observed).total_seconds()<86400:unknown.append('SLO_OBSERVATION_STALE_OR_MISSING')
    if evidence.error_budget_burn_rate_30d is None:unknown.append('SLO_BURN_RATE_MISSING')
    elif evidence.error_budget_burn_rate_30d>1:reasons.append('BLOCKED_BY_SLO_BURN_RATE')
    if evidence.oom_kill_count_30d is None:unknown.append('OOM_HISTORY_MISSING')
    elif evidence.oom_kill_count_30d>0:reasons.append('BLOCKED_BY_OOM_HISTORY')
    if evidence.p95_cfs_throttled_ratio is None:unknown.append('THROTTLING_HISTORY_MISSING')
    elif evidence.p95_cfs_throttled_ratio>.02:reasons.append('BLOCKED_BY_CPU_THROTTLING')
    for field,code in (('fixed_heap_configured','COORDINATED_HEAP_REVIEW_REQUIRED'),('hpa_coordination_required','COORDINATED_HPA_REVIEW_REQUIRED')):
        value=getattr(evidence,field)
        if value is None:unknown.append(code+'_UNKNOWN')
        elif value:reasons.append(code)
    cpu=evaluate_series(evidence.cpu_series,TimeSeriesEvidenceContract('cpu','P95'),now=now,require_resource_age=False)
    latency=evaluate_series(evidence.latency_p99_series,TimeSeriesEvidenceContract('interval_p99_latency_ms','MAX'),now=now,require_resource_age=False)
    correlation=None;paired_count=0;paired_ratio=None
    if not cpu.is_sufficient:unknown.append('CPU_'+str(cpu.gap_reason).upper())
    if not latency.is_sufficient:unknown.append('LATENCY_'+str(latency.gap_reason).upper())
    if evidence.slo_latency_target_ms is None:unknown.append('SLO_LATENCY_TARGET_MISSING')
    elif latency.is_sufficient and latency.observed_value>=evidence.slo_latency_target_ms*.9:reasons.append('BLOCKED_BY_TAIL_LATENCY_PROXIMITY')
    if cpu.is_sufficient and latency.is_sufficient:
        if cpu.window_start!=latency.window_start or cpu.window_end!=latency.window_end:
            unknown.append('TELEMETRY_WINDOWS_DO_NOT_MATCH')
        else:
            a={p['at']:p['value'] for p in evidence.cpu_series['points']};b={p['at']:p['value'] for p in evidence.latency_p99_series['points']}
            # Canonical timestamps make equivalent UTC offsets pair identically.
            a={moment(k):v for k,v in a.items()};b={moment(k):v for k,v in b.items()}
            paired=sorted(a.keys()&b.keys());paired_count=len(paired);paired_ratio=paired_count/cpu.expected_samples
            times=[cpu.window_start,*paired,cpu.window_end]
            if paired_ratio<.95 or max((y-x).total_seconds() for x,y in zip(times,times[1:]))>3600:
                unknown.append('PAIRED_TELEMETRY_COVERAGE_INSUFFICIENT')
            else:
                from statistics import correlation as pearson
                try:
                    scale_a=max(a[t] for t in paired);scale_b=max(b[t] for t in paired)
                    correlation=pearson([a[t]/scale_a for t in paired],[b[t]/scale_b for t in paired])
                    if correlation>.60:reasons.append('BLOCKED_BY_LATENCY_SENSITIVITY')
                except (ValueError,ZeroDivisionError):unknown.append('CORRELATION_UNDEFINED')
    status='blocked' if reasons else 'insufficient_evidence' if unknown else 'review_eligible'
    return dict(status=status,capacity_reduction_allowed=status=='review_eligible',blocks=reasons,evidence_gaps=unknown,
        observation_window_start=cpu.window_start.isoformat() if cpu.window_start else None,
        observation_window_end=cpu.window_end.isoformat() if cpu.window_end else None,
        pearson_r=round(correlation,6) if correlation is not None else None,paired_samples=paired_count,paired_coverage_ratio=paired_ratio,
        max_observed_interval_p99_ms=latency.observed_value,automatic_execution=False,
        alternative='Review a same-core generational upgrade with verified binary/ISA, disk/network compatibility, benchmark and regional pricing.' if 'BLOCKED_BY_LATENCY_SENSITIVITY' in reasons else None,
        warning='Statistical screening is not an SLO guarantee or change approval. No architecture discount or target compatibility is assumed.')


class NetworkScenario(Strict):
    provider:Literal['azure','aws','gcp']
    eligible_service:Literal['s3','dynamodb','blob','registry']
    endpoint_mode:Literal['gateway','interface','azure_service_endpoint']
    nat_processed_gib:str
    endpoint_eligible_gib:str
    cross_az_billable_gib:str
    nat_cost_per_gib:str
    cross_az_cost_per_gib:str
    endpoint_cost_per_gib:str
    endpoint_fixed_monthly_usd:str
    flow_log_coverage_ratio:float|int=Field(ge=0,le=1)
    routing_verified:bool
    region:str|None=Field(None,pattern=r'^[a-z]+(?:-[a-z]+)+-?[0-9]+$')
    vpc_id:str|None=Field(None,pattern=r'^vpc-[0-9a-f]{8,17}$')
    route_table_ids:list[str]=Field(default_factory=list,max_length=50)


def analyze_cross_az_and_nat_hairpin_waste(value):
    import json
    scenario=value if isinstance(value,NetworkScenario) else NetworkScenario.model_validate(value)
    native_services={'aws':{'s3','dynamodb','registry'},'azure':{'blob','registry'},'gcp':{'registry'}}
    if scenario.eligible_service not in native_services[scenario.provider]:raise ValueError('Destination service does not match the selected cloud endpoint model.')
    processed,eligible,cross,nat_rate,cross_rate,endpoint_rate,fixed=map(money,(scenario.nat_processed_gib,scenario.endpoint_eligible_gib,
        scenario.cross_az_billable_gib,scenario.nat_cost_per_gib,scenario.cross_az_cost_per_gib,scenario.endpoint_cost_per_gib,scenario.endpoint_fixed_monthly_usd))
    if eligible>processed:raise ValueError('Endpoint-eligible traffic cannot exceed measured NAT traffic.')
    if scenario.endpoint_mode=='gateway' and (scenario.provider!='aws' or scenario.eligible_service not in ('s3','dynamodb')):
        raise ValueError('AWS Gateway Endpoints support S3/DynamoDB; registry traffic requires a priced and reviewed alternative.')
    if scenario.endpoint_mode=='azure_service_endpoint' and scenario.provider!='azure':raise ValueError('Azure service endpoints require Azure.')
    if len(set(scenario.route_table_ids))!=len(scenario.route_table_ids) or any(not __import__('re').fullmatch(r'rtb-[0-9a-f]{8,17}',x) for x in scenario.route_table_ids):
        raise ValueError('Supply unique AWS route table IDs.')
    complete=scenario.routing_verified and scenario.flow_log_coverage_ratio>=.95
    with localcontext() as context:
        context.prec=50
        nat=eligible*nat_rate
        # These two costs are alternatives unless non-overlapping traffic meters are independently proved.
        cross_cost=cross*cross_rate
        overhead=eligible*endpoint_rate+fixed
        net=nat-overhead if complete else None
    terraform=None
    if complete and scenario.provider=='aws' and scenario.endpoint_mode=='gateway' and scenario.region and scenario.vpc_id and scenario.route_table_ids:
        terraform=('variable "endpoint_policy_json" {\n  type = string\n  description = "Independently reviewed least-privilege endpoint policy; no default."\n}\n\n'
            'resource "aws_vpc_endpoint" "review_gateway" {\n'
            f'  vpc_id = {json.dumps(scenario.vpc_id)}\n  service_name = {json.dumps("com.amazonaws."+scenario.region+"."+scenario.eligible_service)}\n'
            '  vpc_endpoint_type = "Gateway"\n'
            f'  route_table_ids = {json.dumps(scenario.route_table_ids)}\n  policy = var.endpoint_policy_json\n}}\n')
    return dict(status='modeled' if complete else 'insufficient_evidence',basis='user_supplied_flow_scenario',currency='USD',volume_unit='GiB',
        nat_bypass_gross_monthly_usd=text(nat) if complete else None,endpoint_monthly_overhead_usd=text(overhead) if complete else None,
        nat_bypass_net_monthly_usd=text(net) if net is not None else None,cross_az_separate_opportunity_usd=text(cross_cost) if complete else None,
        combined_savings_usd=None,terraform_review=terraform,automatic_execution=False,
        warning='NAT and cross-zone opportunities are not added because traffic can overlap. Rates and flow provenance require independent validation. PreferClose is a routing preference, not guaranteed locality or preserved failover; no live routing change was made.')


class BatchJob(Strict):
    job_id:str=Field(pattern=r'^[a-zA-Z0-9_-]{1,80}$')
    duration_minutes:float|int=Field(gt=0,le=43200)
    active_compute_minutes:float|int=Field(ge=0,le=43200)
    billed_cost_usd:str


def analyze_ephemeral_batch_waste(jobs):
    if not isinstance(jobs,list) or not 1<=len(jobs)<=500:raise ValueError('Supply 1–500 completed batch records.')
    parsed=[BatchJob.model_validate(j) for j in jobs]
    if len({j.job_id for j in parsed})!=len(parsed):raise ValueError('Batch charge identities must be unique.')
    items=[]
    with localcontext() as context:
        context.prec=50
        for job in parsed:
            if job.active_compute_minutes>job.duration_minutes:raise ValueError('Active duration cannot exceed billed duration.')
            billed=money(job.billed_cost_usd)
            slack=billed*(1-Decimal(str(job.active_compute_minutes))/Decimal(str(job.duration_minutes)))
            items.append(dict(job_id=job.job_id,billed_cost_usd=text(billed),modeled_idle_allocation_usd=text(slack)))
    return dict(status='scenario_only',items=items,modeled_idle_allocation_usd=text(sum((Decimal(i['modeled_idle_allocation_usd']) for i in items),Decimal(0))),
        verified_realized_savings_usd=None,warning='Allocation review only. Warm-up, data transfer, minimum billing, reservations and critical-path timing can make this capacity non-removable.')
