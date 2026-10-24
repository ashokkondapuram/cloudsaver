"""Category differentiator contracts with synthetic evidence; no cloud or model calls."""
from datetime import datetime,timedelta,timezone
from decimal import Decimal
import copy
import pytest
from app.commitment_arbitrage import parse_strict_monetary_decimal,calculate_clean_commitment_baseline,hourly_p10
from app.causal_topology_simulator import simulate_cascading_topology_savings,evaluate_slo_bounded_rightsizing,analyze_cross_az_and_nat_hairpin_waste,analyze_ephemeral_batch_waste

NOW=datetime.now(timezone.utc).replace(second=0,microsecond=0)
NOW-=timedelta(minutes=NOW.minute%5)


@pytest.mark.parametrize('value',[True,False,1.2,float('nan'),float('inf'),'1e3','1.00001','-1','01',' 1','1.','NaN','Infinity'])
def test_strict_money_rejects_lossy_or_ambiguous_inputs(value):
    with pytest.raises(ValueError):parse_strict_monetary_decimal(value)


def test_commitments_only_use_the_clean_remaining_floor():
    result=calculate_clean_commitment_baseline('10.1000','3.2000','4.3000')
    assert Decimal(result['recommended_new_commitment_hr'])==Decimal('2.6000')
    assert calculate_clean_commitment_baseline('1','2','3')['recommended_new_commitment_hr']=='0'
    assert result['purchase_authorized'] is False
    assert hourly_p10(['1']*72+['9']*648)=='1'


def topology():
    return {'nodes':[{'node_id':'compute','component_id':'compute-charge','label':'Compute','monthly_savings_usd':'560'},
        {'node_id':'disks','component_id':'disk-charge','label':'Disks','monthly_savings_usd':'64'},
        {'node_id':'ip','component_id':'ip-charge','label':'IP','monthly_savings_usd':'7.30'},
        {'node_id':'traffic','component_id':'traffic-charge','label':'Traffic','monthly_savings_usd':'42'}],
        'edges':[{'parent':'compute','child':child,'verification_state':'verified'} for child in ('disks','ip','traffic')],
        'selected_roots':['compute'],'one_time_transition_cost_usd':'3.20','recurring_new_overhead_usd':'0'}


def test_causal_math_includes_transition_retention_and_deduplicates_one_billed_component():
    model=topology();result=simulate_cascading_topology_savings(model)
    assert Decimal(result['net_monthly_savings_usd'])==Decimal('673.30')
    assert result['payback_days']=='0.1426'
    model['nodes'].append(dict(model['nodes'][1],node_id='disk-alternative'))
    model['edges'].append({'parent':'compute','child':'disk-alternative','verification_state':'verified'})
    assert simulate_cascading_topology_savings(model)['unique_billed_components']==4
    model['recurring_new_overhead_usd']='1000'
    assert Decimal(simulate_cascading_topology_savings(model)['net_monthly_savings_usd'])<0


def test_shared_child_requires_all_parent_actions_and_verified_dependencies():
    model=topology();model['nodes'].append({'node_id':'other','component_id':'other-charge','label':'Other','monthly_savings_usd':'10'})
    model['edges'].append({'parent':'other','child':'disks','verification_state':'verified'})
    result=simulate_cascading_topology_savings(model)
    assert 'disks' not in result['selected_nodes'] and result['net_monthly_savings_usd'] is None
    model['selected_roots'].append('other')
    assert 'disks' in simulate_cascading_topology_savings(model)['selected_nodes']
    model['edges'][0]['verification_state']='inferred'
    assert simulate_cascading_topology_savings(model)['status']=='insufficient_evidence'


def test_cycles_alternative_groups_and_conflicting_bills_are_rejected():
    model=topology();model['edges'].append({'parent':'disks','child':'compute','verification_state':'verified'})
    with pytest.raises(ValueError):simulate_cascading_topology_savings(model)
    model=topology();model['nodes'][0]['opportunity_group_id']=model['nodes'][1]['opportunity_group_id']='exclusive'
    with pytest.raises(ValueError):simulate_cascading_topology_savings(model)
    model=topology();model['nodes'][1]['component_id']='compute-charge'
    with pytest.raises(ValueError):simulate_cascading_topology_savings(model)


def series(values):
    start=NOW-timedelta(days=30)
    return {'window_start':start.isoformat(),'window_end':NOW.isoformat(),'points':[{'at':(start+timedelta(minutes=5*(i+1))).isoformat(),'value':value} for i,value in enumerate(values)]}


def slo(correlated=False):
    cpu=[float(i%4+1) for i in range(8640)]
    latency=[x*10 if correlated else float((i//4)%4+10) for i,x in enumerate(cpu)]
    return dict(cpu_series=series(cpu),latency_p99_series=series(latency),error_budget_burn_rate_30d=.5,slo_latency_target_ms=100.,
        observed_at=NOW.isoformat(),oom_kill_count_30d=0,p95_cfs_throttled_ratio=.001,fixed_heap_configured=False,hpa_coordination_required=False)


def test_slo_solver_uses_aligned_30_day_tail_evidence_and_blocks_cpu_sensitive_latency():
    result=evaluate_slo_bounded_rightsizing(slo(),now=NOW)
    assert result['status']=='review_eligible' and result['paired_samples']==8640
    result=evaluate_slo_bounded_rightsizing(slo(True),now=NOW)
    assert 'BLOCKED_BY_LATENCY_SENSITIVITY' in result['blocks'] and result['capacity_reduction_allowed'] is False
    assert 'discount' not in result['alternative']


@pytest.mark.parametrize('change,code',[({'error_budget_burn_rate_30d':1.01},'BLOCKED_BY_SLO_BURN_RATE'),
    ({'slo_latency_target_ms':14.},'BLOCKED_BY_TAIL_LATENCY_PROXIMITY'),({'oom_kill_count_30d':1},'BLOCKED_BY_OOM_HISTORY'),
    ({'p95_cfs_throttled_ratio':.03},'BLOCKED_BY_CPU_THROTTLING'),({'fixed_heap_configured':True},'COORDINATED_HEAP_REVIEW_REQUIRED')])
def test_each_slo_safety_gate_is_independent(change,code):
    result=evaluate_slo_bounded_rightsizing(dict(slo(),**change),now=NOW)
    assert code in result['blocks'] and result['automatic_execution'] is False


def test_individually_complete_series_with_disjoint_gaps_cannot_prove_paired_coverage():
    value=slo();value['cpu_series']['points']=[p for i,p in enumerate(value['cpu_series']['points']) if i%20!=0]
    value['latency_p99_series']['points']=[p for i,p in enumerate(value['latency_p99_series']['points']) if i%20!=1]
    result=evaluate_slo_bounded_rightsizing(value,now=NOW)
    assert 'PAIRED_TELEMETRY_COVERAGE_INSUFFICIENT' in result['evidence_gaps']
    assert result['capacity_reduction_allowed'] is False


def network(**changes):
    return dict(provider='aws',eligible_service='s3',endpoint_mode='gateway',nat_processed_gib='1000',endpoint_eligible_gib='800',cross_az_billable_gib='100',nat_cost_per_gib='.045'.replace('.','0.',1),
        cross_az_cost_per_gib='0.02',endpoint_cost_per_gib='0',endpoint_fixed_monthly_usd='0',flow_log_coverage_ratio=1.,routing_verified=True,
        region='us-east-1',vpc_id='vpc-12345678',route_table_ids=['rtb-12345678'],**changes)


def test_network_does_not_double_count_traffic_or_call_private_registry_endpoints_free():
    result=analyze_cross_az_and_nat_hairpin_waste(network())
    assert Decimal(result['nat_bypass_net_monthly_usd'])==36 and result['combined_savings_usd'] is None
    assert 'endpoint_policy_json' in result['terraform_review'] and 'default' not in result['terraform_review'].split('variable')[0]
    value=network();value['eligible_service']='registry'
    with pytest.raises(ValueError):analyze_cross_az_and_nat_hairpin_waste(value)
    value=network();value['flow_log_coverage_ratio']=.8
    assert analyze_cross_az_and_nat_hairpin_waste(value)['nat_bypass_net_monthly_usd'] is None


def test_ephemeral_batch_slack_is_not_realized_cash():
    result=analyze_ephemeral_batch_waste([dict(job_id='batch-a',duration_minutes=20,active_compute_minutes=5,billed_cost_usd='4')])
    assert Decimal(result['modeled_idle_allocation_usd'])==3 and result['verified_realized_savings_usd'] is None
    with pytest.raises(ValueError):analyze_ephemeral_batch_waste([dict(job_id='batch-a',duration_minutes=20,active_compute_minutes=21,billed_cost_usd='4')])


















if __name__=='__main__':
    raise SystemExit(pytest.main([__file__,'-q']))
