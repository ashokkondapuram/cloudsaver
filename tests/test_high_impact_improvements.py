"""Category differentiator contracts with synthetic evidence; no cloud or model calls."""
from datetime import datetime,timedelta,timezone
from decimal import Decimal
import copy
import pytest
from app.commitment_arbitrage import parse_strict_monetary_decimal,calculate_clean_commitment_baseline,hourly_p10
from app.causal_topology_simulator import simulate_cascading_topology_savings,evaluate_slo_bounded_rightsizing,analyze_cross_az_and_nat_hairpin_waste,analyze_ephemeral_batch_waste
from app.realized_savings_verifier import evaluate_realized_savings

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


def verification():
    action=NOW-timedelta(days=61)
    case=dict(provider='azure',scope_id='scope',resource_id='disk',resource_type='disk',state='scheduled',action='retirement',scheduled_at=action.isoformat(),baseline_rule_ids=['ORPHANED_DISK'])
    scan=dict(scan_id='latest',timestamp=NOW.isoformat(),status='completed',inventory=[],findings=[],scope_results=[dict(provider='azure',scope_id='scope',status='completed',supported_inventory_complete=True,supported_resource_types=['disk'])])
    audit=dict(trusted=True,operation='delete',status='Succeeded',occurred_at=(action+timedelta(hours=1)).isoformat())
    billing=dict(trusted=True,provider_reconciled=True,coverage_complete=True,overhead_inventory_complete=True,currency='USD',
        baseline_start=(action-timedelta(days=30)).date().isoformat(),baseline_end=action.date().isoformat(),
        observation_start=(action+timedelta(days=1)).date().isoformat(),observation_end=(action+timedelta(days=31)).date().isoformat(),
        baseline_monthly_cost_usd='100',post_resource_cost_usd='0',new_backup_or_snapshot_overhead_usd='15',one_time_transition_cost_usd='0')
    return case,scan,audit,billing


def test_verified_retirement_needs_complete_scope_audit_and_net_reconciled_billing():
    case,scan,audit,billing=verification()
    assert evaluate_realized_savings(case,scan,audit=audit,billing=billing,now=NOW)['verified_realized_savings_usd']=='85'
    for changed in (dict(billing,trusted=False),dict(billing,overhead_inventory_complete=False),dict(billing,provider_reconciled=False)):
        assert evaluate_realized_savings(case,scan,audit=audit,billing=changed,now=NOW)['state']=='scheduled'
    scan['scope_results']=[]
    result=evaluate_realized_savings(case,scan,audit=audit,billing=billing,now=NOW)
    assert result['reasons']==['unverified_scope_missing'] and result['verified_realized_savings_usd'] is None


def test_post_change_regression_reopens_and_never_reuses_the_prior_savings_claim():
    case,scan,audit,billing=verification();case.update(state='verified_completed',previous_verified_savings='85')
    scan['inventory']=[{'cloud_provider':'azure','resource_id':'disk','evidence':{}}]
    result=evaluate_realized_savings(case,scan,now=NOW)
    assert result['state']=='reopened_on_regression' and Decimal(result['verified_realized_savings_usd'])==0


def test_cost_increase_is_not_hidden_by_zero_clamping():
    case,scan,audit,billing=verification();billing['new_backup_or_snapshot_overhead_usd']='120'
    assert Decimal(evaluate_realized_savings(case,scan,audit=audit,billing=billing,now=NOW)['verified_realized_savings_usd'])==-20


def test_privacy_scrubbing_never_enables_client_derived_publication():
    from app.knowledge_pipeline import scrub_and_validate_knowledge_candidate
    value='Account 123456789012 disk /subscriptions/11111111-1111-4111-8111-111111111111/disks/secret contact owner@client.internal address 10.1.2.3'
    result=scrub_and_validate_knowledge_candidate(value,origin='synthetic')
    assert '123456789012' not in result['scrubbed_text'] and 'owner@' not in result['scrubbed_text'] and '10.1.2.3' not in result['scrubbed_text']
    assert result['publication_eligible'] is False and result['dual_review_required'] is True
    with pytest.raises(ValueError):scrub_and_validate_knowledge_candidate(value,origin='tenant_observation')
    with pytest.raises(ValueError):scrub_and_validate_knowledge_candidate('private-client-code',origin='synthetic',tenant_tokens=['private-client-code'])


@pytest.mark.parametrize('kind,values',[('google_compute_region_commitment',{}),('aws_savingsplans_savings_plan',{}),
    ('azurerm_cognitive_deployment',{'sku':[{'name':'ProvisionedManaged'}]}),('azurerm_cognitive_deployment',{})])
def test_commitment_firewall_requires_independent_baseline_approval(kind,values):
    from test_plan_policy import resource,plan
    from app.plan_policy import evaluate_plan
    result=evaluate_plan(plan(resource(kind+'.review',kind,values=values)))
    assert result['decision']=='fail' and 'CLEAN_BASELINE_APPROVAL_REQUIRED' in {r['code'] for r in result['issues']}


def test_known_payg_deployment_and_cost_category_are_not_commitment_purchases():
    from test_plan_policy import resource,plan
    from app.plan_policy import evaluate_plan
    for kind,values in [('azurerm_cognitive_deployment',{'sku':[{'name':'Standard'}]}),('aws_ce_cost_category',{})]:
        assert evaluate_plan(plan(resource(kind+'.review',kind,values=values)))['decision']=='pass'


def test_account_scan_in_another_region_cannot_verify_missing_resource():
    from app.realized_savings_verifier import scope_is_complete
    case,scan,_,_=verification();case.update(provider='aws',region='us-west-2',resource_type='aws:ec2:volume')
    scan['scope_results']=[dict(provider='aws',scope_id=case['scope_id'],status='completed',supported_inventory_complete=True,supported_resource_types=['aws:ec2:volume'],regions=['us-east-1'])]
    assert scope_is_complete(case,scan) is False
    scan['scope_results'][0]['regions'].append('us-west-2')
    assert scope_is_complete(case,scan) is True


if __name__=='__main__':
    raise SystemExit(pytest.main([__file__,'-q']))
