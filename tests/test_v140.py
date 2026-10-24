"""v1.4 evidence, financial, connector and data-boundary regression gates."""
import copy,json
from datetime import datetime,timedelta,timezone
from pathlib import Path
from uuid import uuid4
import pytest
from fastapi import FastAPI,Header
from fastapi.testclient import TestClient
from tests.test_data_governance import governed
from app.ai_advisory import Target
from app.data_governance import DataDenied
from app.data_policy import validate_data_governance
from app.data_retention import DataRetention,RetentionConflict
from app.inference_ledger import InferenceLedger
from app.resource_catalog import FAMILIES,definitions
from app.multicloud_rules import evaluate_inventory,slo_gate
from app.collectors.live_common import series,summary,window

NOW=datetime.now(timezone.utc).replace(second=0,microsecond=0)
NOW-=timedelta(minutes=NOW.minute%5)

def telemetry(value=0):
    start,end=window(NOW)
    return dict(window_start=start.isoformat(),window_end=end.isoformat(),points=[dict(at=(start+timedelta(minutes=5*(i+1))).isoformat(),value=value) for i in range(8640)])

def hourly(value='10'):
    end=NOW.replace(minute=0);start=end-timedelta(days=30)
    return dict(unit='USD/hour',currency='USD',window_start=start.isoformat(),window_end=end.isoformat(),points=[dict(at=(start+timedelta(hours=i+1)).isoformat(),value=value) for i in range(720)])

def test_catalog_has_exact_36_families_and_independent_control_plane_contract():
    assert {p:sum(f[0]==p for f in FAMILIES) for p in ('azure','aws','gcp','kubernetes')}=={'azure':10,'aws':10,'gcp':8,'kubernetes':8}
    assert len({r[0] for r in definitions()})==len(definitions())
    root=Path(__file__).resolve().parents[1]
    assert (root/'app/resource_catalog.py').read_bytes()==(root/'platform/identity/analysis/multicloud.py').read_bytes()

@pytest.mark.parametrize('f',[f for f in FAMILIES if f[0] in ('aws','gcp')],ids=lambda f:f[0]+'-'+f[1])
def test_new_cloud_rules_never_invent_conditions_or_prices_without_evidence(f):
    resource=dict(resource_id='synthetic',resource_type=f[3][0],cloud_provider=f[0],subscription_id='synthetic',scope_id='synthetic',evidence={})
    rows=evaluate_inventory([resource],observed_at=NOW.isoformat(),now=NOW)
    assert rows and all(r['outcome']=='insufficient_evidence' and r['estimated_savings'] is None and r['automatic_execution'] is False for r in rows)
    rows=evaluate_inventory([resource],observed_at=NOW.isoformat(),now=NOW,policies={rid:{'enabled':False} for rid in f[4]})
    assert all(r['outcome']=='disabled_by_policy' for r in rows)

def test_snapshot_recency_history_and_complete_series_are_required_for_ebs():
    resource=dict(resource_id='synthetic',resource_type='aws:ec2:volume',cloud_provider='aws',scope_id='123456789012',evidence=dict(disk_state='available'))
    evaluate=lambda:next(r for r in evaluate_inventory([resource],observed_at=NOW.isoformat(),now=NOW) if r['rule_id']=='AWS_UNATTACHED_EBS')
    e=resource['evidence'];assert evaluate()['outcome']=='insufficient_evidence'
    e.update(state_history=[dict(state='Unattached',start=(NOW-timedelta(days=20)).isoformat(),end=NOW.isoformat(),complete=True)],recent_snapshot_verified=True,snapshot_age_hours=1)
    assert evaluate()['outcome']=='condition_detected'
    e['snapshot_age_hours']=24;assert evaluate()['outcome']=='condition_not_detected'
    e['state_history']=None;assert evaluate()['outcome']=='insufficient_evidence'

def test_live_evidence_does_not_zero_fill_and_rejects_duplicate_or_invalid_points():
    t=telemetry(3);assert summary(t,'cpu',NOW)['sufficient'] is True
    missing=dict(t,points=t['points'][1000:]);assert summary(missing,'cpu',NOW)['sufficient'] is False
    start,end=window(NOW)
    with pytest.raises(ValueError):series([(end,-1)],NOW)
    with pytest.raises(ValueError):series([(end,0),(end,0)],NOW)
    assert series([],NOW)['points']==[]

def test_activity_log_without_transition_is_not_90_days_of_proven_idle_state():
    from app.collectors.azure_live import fetch_azure_state_history
    class Reader:
        def get(self,*args):return {'value':[]}
    r=dict(resource_id='/subscriptions/33333333-3333-4333-8333-333333333333/resourceGroups/rg/providers/Microsoft.Compute/disks/demo',subscription_id='33333333-3333-4333-8333-333333333333',evidence={'disk_state':'Unattached','created_at':'2020-01-01T00:00:00Z'})
    assert fetch_azure_state_history(Reader(),r,NOW) is None

def test_cloudwatch_and_gcp_readers_reject_partial_or_cross_project_data():
    from app.collectors.aws_live import fetch_cloudwatch_series
    from app.collectors.gcp_live import gcp_monitoring_series
    class CW:
        def get_metric_data(self,**kwargs):return {'MetricDataResults':[{'Id':'metric','StatusCode':'PartialData','Timestamps':[],'Values':[]}]}
    with pytest.raises(ValueError):fetch_cloudwatch_series(CW(),'AWS/EC2','CPUUtilization',[],NOW)
    class GCP:
        def get(self,*args):return {'timeSeries':[{'metric':{'type':'metric'},'resource':{'labels':{'project_id':'other-project'}},'points':[]}]}
    with pytest.raises(ValueError):gcp_monitoring_series(GCP(),'example-project','metric','resource.type="gce_instance"',NOW)

def test_slo_and_target_proof_cannot_be_replaced_by_low_average_cpu():
    r=dict(resource_id='synthetic',resource_type='aws:ec2:instance',cloud_provider='aws',evidence=dict(metrics={'cpu_percent':telemetry(2),'memory_percent':telemetry(20)},target_compatible=True))
    run=lambda:next(v for v in evaluate_inventory([r],observed_at=NOW.isoformat(),now=NOW) if v['rule_id']=='AWS_EC2_GRAVITON_AND_SLO_RIGHTSIZING')
    assert run()['outcome']=='insufficient_evidence'
    r['evidence'].update(slo_observed_at=NOW.isoformat(),slo_burn_rate=.8,cpu_latency_correlation_r=.4)
    assert run()['outcome']=='condition_detected'
    r['evidence']['slo_burn_rate']=1.01;assert run()['outcome']=='condition_not_detected'
    r['evidence']['slo_burn_rate']=.8;r['evidence']['cpu_latency_correlation_r']=.61;assert run()['outcome']=='condition_not_detected'

def test_clean_portfolio_deduplicates_each_hour_and_preserves_decimal_math():
    from app.nextgen_engines import compute_clean_before_commit_plan
    base=dict(resource_key='a'*64,provider='aws',scope_id='123456789012',opportunity_group_id='ec2-envelope:synthetic',outcome='condition_detected',disposition='requires_review',commitment_lock_conflict=False)
    terms=[dict(term_years=1,discount_percent='20',existing_commitment_hr='4',review_reference='TERM-42')]
    rows=[dict(base,hourly_waste_profile=hourly('2')),dict(base,resource_key='b'*64,hourly_waste_profile=hourly('3'))]
    result=compute_clean_before_commit_plan(hourly('10'),rows,terms)
    assert result['cleaned_commitment_floor_hr']=='7' and result['opportunity_group_count']==1
    option=result['options'][0];assert option['recommended_additional_commitment_hr']=='3'
    assert option['modeled_clean_plus_commit_annual_savings_usd']=='31536.0'
    assert option['verified_physical_cleanup_savings_usd'] is None and result['purchase_authorized'] is False
    rows[0].pop('hourly_waste_profile');assert compute_clean_before_commit_plan(hourly('10'),rows,terms)['cleaned_commitment_floor_hr'] is None
    with pytest.raises(ValueError):compute_clean_before_commit_plan(dict(hourly(),points=hourly()['points'][:-1]),[],terms)
    with pytest.raises(ValueError):compute_clean_before_commit_plan(dict(hourly(),unit='vCPU-hours'),[],terms)

def test_blast_radius_requires_complete_histories_and_verified_dependency_coverage():
    from app.nextgen_engines import simulate_topology_blast_radius
    r=dict(resource_id='root',resource_type='aws:elbv2:loadbalancer',cloud_provider='aws',evidence={'dependencies_verified':True,'metrics':{'requests':telemetry(),'healthy_targets':telemetry()}})
    run=lambda:simulate_topology_blast_radius('root','retirement',[],resources=[r],observed_at=NOW.isoformat(),now=NOW)
    assert run()['status']=='review_eligible' and run()['change_approved'] is False
    r['evidence']['metrics']['requests']=telemetry(1);assert run()['status']=='blocked'
    r['evidence']['metrics']['requests']=telemetry();r['evidence']['dependencies_verified']=False;assert 'DEPENDENCY_COMPLETENESS_UNVERIFIED' in run()['evidence_gaps']

def processor(s,provider):
    common={k:v for k,v in s.policy['processors'][0].items() if k in ('workspace_id','target_id','purposes','review_reference','review_expires_at','provider_controls_reviewed')}
    if provider=='aws':
        role='arn:aws:iam::123456789012:role/AIGoverned'
        approval=dict(common,provider='aws',aws_account_id='123456789012',aws_region='us-east-1',aws_role_arn=role,model_id='anthropic.claude-fixture-v1:0',guardrail_id='guardrail123',guardrail_version='1')
        target=Target(target_id=common['target_id'],tenant_id=s.tenant['tenant_id'],provider='aws',model=approval['model_id'],region='us-east-1',role_arn=role,guardrail_id='guardrail123',guardrail_version='1')
    else:
        approval=dict(common,provider='gcp',gcp_project_id='example-project',gcp_location='us-central1',gcp_service_account='review-worker@example-project.iam.gserviceaccount.com',model_id='gemini-2.5-pro',vpc_sc_enforced=True)
        target=Target(target_id=common['target_id'],tenant_id=s.tenant['tenant_id'],provider='gcp',model=approval['model_id'],project=approval['gcp_project_id'],region=approval['gcp_location'],service_account=approval['gcp_service_account'])
    return approval,target

@pytest.mark.parametrize('provider',['aws','gcp'])
def test_keyless_multicloud_processor_grants_bind_exact_owner_region_model_and_controls(governed,provider):
    s=governed;approval,target=processor(s,provider);s.policy['processors']=[approval]
    validate_data_governance(s.policy)
    cleaned,grant=s.governor.prepare(s.tenant,target,'assessment',{'facts':{'size_gb':10}},source_provider=provider,scope_id='owned-scope')
    assert grant.metadata['source_provider']==provider and cleaned['facts']=={'size_gb':10}
    with pytest.raises(DataDenied):s.governor.prepare(s.tenant,target.model_copy(update={'region':'other-region'}),'assessment',{})
    if provider=='aws':approval['guardrail_version']='DRAFT'
    else:approval['vpc_sc_enforced']=False
    with pytest.raises(ValueError):validate_data_governance(s.policy)

def test_governance_views_filter_events_records_counts_and_processors_before_limiting(governed):
    s=governed;sid=s.tenant['subscription_ids'][0]
    s.governor.event(s.tenant,'assessment','allowed','APPROVED',source_provider='azure',scope_id=sid)
    s.governor.event(s.tenant,'assessment','blocked','DENIED',source_provider='azure',scope_id=str(uuid4()))
    s.governor.event(s.tenant,'assessment','allowed','OTHER_PROVIDER',source_provider='aws',scope_id='123456789012')
    s.governor.event(s.tenant,'assessment','blocked','UNLABELLED_LEGACY')
    limited=dict(s.tenant,allowed_providers=['azure'],scope_restrictions={'azure':[sid]})
    result=DataRetention(s.store).view(limited)
    assert result['counts']=={'allowed':1} and len(result['events'])==1 and result['events'][0]['scope_id']==sid
    assert s.governor.view(limited)['processors']==[]
    assert len(DataRetention(s.store).view(s.tenant)['events'])==4

def test_legal_hold_release_requires_human_session_and_is_irreversible_audited(governed):
    from app.data_governance_api import create_router
    s=governed;ledger=InferenceLedger(s.store);result=ledger.run(s.tenant['tenant_id'],str(uuid4()),'c'*64,10,lambda:dict(advice={'summary':'Preserved text'},usage={}),metadata={'scan_id':s.scan['scan_id'],'provider':'azure','model':'approved','target_id':s.target.target_id})
    retention=DataRetention(s.store);hold=retention.hold(s.tenant,result['assessment_id'],NOW+timedelta(days=2),'LEGAL-42')
    def principal(authorization:str=Header(default='')):
        return dict(s.tenant,user_id='human-reviewer',key_id='delegated-key' if authorization=='key' else None,subject_type='service_account' if authorization=='machine' else 'user')
    app=FastAPI();app.include_router(create_router(s.store,principal,s.governor));client=TestClient(app);path='/api/v1/ai/governance/holds/'+hold['id']+'/release';body={'release_reason':'Preservation review completed','review_ticket':'LEGAL-RELEASE-42'}
    assert client.post(path,headers={'Authorization':'key'},json=body).status_code==403
    assert client.post(path,headers={'Authorization':'machine'},json=body).status_code==403
    assert client.post(path,json=body).json()['released'] is True
    assert client.post(path,json=body).status_code==409
    assert retention.erase(s.tenant,result['assessment_id'],'PRIVACY-42')['content_erased']
    events=retention.view(s.tenant)['events'];assert any(e['reason']=='LEGAL_HOLD_RELEASED' for e in events)
    assert 'Preservation review completed' not in json.dumps(events)
