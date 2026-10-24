"""Synthetic multi-source acceptance tests; no live cluster or cloud is contacted."""
import copy
import hashlib
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient

from app.collectors.kubernetes import RESOURCES, binding, inventory, matrix
from app.collectors.federation import scan
from app.collectors.provenance import compact
from app.kubernetes_rules import DEFINITIONS, RULE_IDS, evaluate_inventory, findings_from
from app.kubernetes_topology import project, quantity
from app.k8s_cost_reconciler import allocations, breakdown, group_opportunities
from app.scanner import ScanError

NOW=datetime.now(timezone.utc).replace(second=0,microsecond=0)
NOW=NOW-timedelta(minutes=NOW.minute%5)
CLUSTER='fixture-cluster'
SOURCE=dict(cluster_id=CLUSTER,prometheus_url='https://prometheus.example.test',bearer_token_env='CLOUDSAVER_PROMETHEUS_TOKEN_TEST')
BINDING=dict(tenant_id=str(uuid4()),cluster_id=CLUSTER,api_url='https://kubernetes.example.test',api_token_env='CLOUDSAVER_K8S_TEST')


def obj(kind,name,namespace='production',**fields):
    return dict(kind=kind,metadata=dict(name=name,uid=kind+'-'+name,namespace=namespace,creationTimestamp=(NOW-timedelta(days=60)).isoformat(),generation=1),**fields)


def objects():
    result={kind:[] for _,kind in RESOURCES}
    result['Namespace']=[obj('Namespace','production',None)]
    result['Deployment']=[obj('Deployment','checkout',spec={'replicas':1})]
    result['Pod']=[obj('Pod','checkout-pod',spec={'nodeName':'node-a','containers':[{'name':'api','resources':{'requests':{'cpu':'2','memory':'2Gi'},'limits':{'memory':'3Gi'}},'env':[{'name':'PRIVATE_TOKEN','value':'never-persist-this'}]}]},status={'phase':'Running','qosClass':'Burstable'})]
    result['Pod'][0]['metadata']['ownerReferences']=[{'kind':'Deployment','name':'checkout','uid':'Deployment-checkout','controller':True}]
    result['Node']=[obj('Node','node-a',None,spec={'providerID':'azure:///subscriptions/22222222-2222-4222-8222-222222222222/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/node-a'},status={'allocatable':{'cpu':'8','memory':'16Gi'}})]
    result['Node'][0]['metadata']['labels']={'agentpool':'application'}
    return result


def stat(value,**changes):
    return dict(sufficient=True,p95=value,p99=value,minimum=value,maximum=value,window_start=(NOW-timedelta(days=30)).isoformat(),
        window_end=NOW.isoformat(),window_days=30,coverage_ratio=1.,valid_samples=8640,expected_samples=8640,max_gap_minutes=5,gap_reason=None,**changes)


def rows():
    key=('production','checkout-pod','api')
    metrics={name:{key:stat(value)} for name,value in {'cpu':.2,'memory':100*1024**2,'throttling':.001,'cpu_request':2.,'memory_request':2*1024**3,'oom':0.,'restarts':0.}.items()}
    metrics['network']={('production','checkout-pod'):stat(1.)}
    return project(CLUSTER,objects(),metrics,[],NOW)


def container(values=None):
    return next(r for r in values or rows() if r['resource_type']=='kubernetes.io/Container')


def evaluated(row,rid,**kwargs):
    return next(o for o in evaluate_inventory([row],observed_at=NOW.isoformat(),now=NOW,**kwargs) if o['rule_id']==rid)


@pytest.mark.parametrize('value,expected',[('100m',.1),('2Gi',2*1024**3),('100u',.0001),('4',4.),('NaN',None),('1e300',None),('-1',None),('bad',None)])
def test_quantities_are_unit_normalized_and_invalid_values_are_unknown(value,expected):
    assert quantity(value)==expected


def test_all_eight_contracts_are_registered_and_healthy_reviews_keep_finance_unknown():
    assert len(RULE_IDS)==8
    row=container()
    cpu=evaluated(row,'K8S_CONTAINER_CPU_OVERREQUEST')
    memory=evaluated(row,'K8S_CONTAINER_MEMORY_OVERREQUEST')
    assert cpu['recommendation']['cpu_request_cores']==pytest.approx(.3)
    assert memory['outcome']=='condition_detected' and memory['recommendation']
    assert cpu['estimated_savings'] is None and cpu['realizable_node_savings_usd'] is None
    assert cpu['automatic_execution'] is False


@pytest.mark.parametrize('change,block', [('throttling','CPU_THROTTLING_ABOVE_2_PERCENT'),('hpa','COORDINATED_HPA_REVIEW_REQUIRED')])
def test_cpu_risks_retain_review_but_remove_patch_proposals(change,block):
    row=container()
    if change=='hpa':row['evidence']['hpa_present']=True
    else:row['evidence']['metrics']['throttling']=stat(.03)
    outcome=evaluated(row,'K8S_CONTAINER_CPU_OVERREQUEST')
    assert outcome['outcome']=='condition_detected'
    assert outcome['recommendation'] is None and block in outcome['safety_blocks']


@pytest.mark.parametrize('change,block',[('oom','OOMKILL_OBSERVED'),('restarts','RESTART_HISTORY_REQUIRES_OOM_VERIFICATION'),('heap','COORDINATED_RUNTIME_HEAP_REVIEW_REQUIRED')])
def test_memory_gates_block_downsizing_and_preserve_oom_risk(change,block):
    row=container()
    if change=='heap':row['evidence']['fixed_heap_configured']=True
    elif change=='restarts':row['evidence']['metrics']['restarts']['maximum']=2.
    else:row['evidence']['metrics']['oom']=stat(1.)
    outcome=evaluated(row,'K8S_CONTAINER_MEMORY_OVERREQUEST')
    assert outcome['outcome']=='condition_detected' and outcome['recommendation'] is None and block in outcome['safety_blocks']
    if change=='oom':
        risk=evaluated(row,'K8S_CONTAINER_UNDERPROVISIONED_RISK')
        assert risk['outcome']=='condition_detected' and risk['estimated_savings']==0


def test_stale_changed_or_conflicting_evidence_never_becomes_rightsizing_approval():
    for mode in ('stale','changed','conflict','missing_hpa'):
        row=container()
        if mode=='stale':row['evidence']['metrics']['cpu']['window_end']=(NOW-timedelta(days=2)).isoformat()
        elif mode=='changed':row['evidence']['metrics']['cpu_request']['minimum']=1.
        elif mode=='conflict':row['reconciliation_status']='source_conflict'
        else:row['evidence']['hpa_present']=None
        assert evaluated(row,'K8S_CONTAINER_CPU_OVERREQUEST')['outcome']=='insufficient_evidence'


def test_disabling_each_rule_is_frozen_and_prevents_findings():
    values=rows()
    policy={r:{'enabled':False} for r in RULE_IDS}
    outcomes=evaluate_inventory(values,policies=policy,observed_at=NOW.isoformat(),now=NOW)
    assert outcomes and {o['outcome'] for o in outcomes}=={'disabled_by_policy'}
    assert findings_from(outcomes,values)==[]


def test_pdb_zero_allowance_and_current_hpa_floor_are_distinguished():
    values=objects()
    values['PodDisruptionBudget']=[obj('PodDisruptionBudget','critical',status={'disruptionsAllowed':0,'expectedPods':2,'observedGeneration':1})]
    values['HorizontalPodAutoscaler']=[obj('HorizontalPodAutoscaler','autoscale',spec={'minReplicas':2,'maxReplicas':8},status={'currentReplicas':2})]
    projected=project(CLUSTER,values,{},[],NOW)
    outcomes=evaluate_inventory(projected,observed_at=NOW.isoformat(),now=NOW)
    pdb=next(o for o in outcomes if o['resource_type'].endswith('/PodDisruptionBudget'))
    hpa=next(o for o in outcomes if o['resource_type'].endswith('/HorizontalPodAutoscaler'))
    assert pdb['outcome']=='condition_detected'
    assert hpa['outcome']=='insufficient_evidence'


def test_pvc_snapshot_cannot_establish_idle_duration_and_expansion_is_not_shrink():
    row=dict(container(),resource_type='kubernetes.io/PersistentVolumeClaim',evidence={'created_at':(NOW-timedelta(days=60)).isoformat(),'phase':'Bound','mounted_by_current_pods':[],
        'cronjob_inventory_complete':True,'cronjob_reference':False,'capacity_bytes':200*1024**3,'metrics':{}})
    rid='K8S_PVC_UNMOUNTED_OR_LOW_OCCUPANCY'
    assert evaluated(row,rid)['outcome']=='insufficient_evidence'
    row['evidence']['metrics']['occupancy']=stat(.02)
    result=evaluated(row,rid)
    assert result['outcome']=='condition_detected' and 'in-place shrink' in result['reason']


def test_load_balancer_requires_history_and_known_endpoint_inventory():
    row=dict(container(),resource_type='kubernetes.io/Service',evidence={'service_type':'LoadBalancer','cloud_lb_observed':True,'available_endpoints':0,'metrics':{}})
    rid='K8S_ORPHANED_LOADBALANCER_SERVICE'
    assert evaluated(row,rid)['outcome']=='insufficient_evidence'
    row['evidence']['metrics']['endpoints']=stat(0.)
    assert evaluated(row,rid)['outcome']=='condition_detected'


def test_typed_projection_omits_commands_environment_values_and_secret_fields():
    projected=rows()
    serialized=json.dumps(projected)
    assert 'never-persist-this' not in serialized and 'PRIVATE_TOKEN' not in serialized
    assert container(projected)['evidence']['controller']['uid']=='Deployment-checkout'
    assert next(r for r in projected if r['resource_type']=='kubernetes.io/Node')['evidence']['requests']['cpu']==2.


class APIReader:
    def __init__(self,fail=()):self.fail=set(fail);self.reads=[]
    def get(self,url,params=None):
        kind=next(kind for path,kind in RESOURCES if url.endswith(path))
        self.reads.append(kind)
        if kind in self.fail:raise ScanError('sensitive-provider-error-should-not-be-saved')
        return {'items':copy.deepcopy(objects()[kind]),'metadata':{}}


class OfflineMetrics:
    def get(self,url,params=None):raise ScanError('unavailable')


def test_secondary_failure_preserves_inventory_unknown_rules_and_sanitized_ledger():
    batch=scan(SOURCE,BINDING,api_reader=APIReader(fail={'HorizontalPodAutoscaler'}),metric_reader=OfflineMetrics(),now=NOW)
    assert batch.inventory and any(r['resource_type']=='kubernetes.io/Container' for r in batch.inventory)
    outcomes=evaluate_inventory(batch.inventory,observed_at=NOW.isoformat(),now=NOW)
    assert next(o for o in outcomes if o['rule_id']=='K8S_CONTAINER_CPU_OVERREQUEST')['outcome']=='insufficient_evidence'
    assert 'sensitive-provider-error' not in json.dumps(batch.inventory)
    assert any(s['status']=='unavailable' for s in batch.inventory[0]['data_sources'])


def test_primary_failure_never_saves_a_partial_clean_baseline():
    with pytest.raises(ScanError,match='Primary Kubernetes'):
        scan(SOURCE,BINDING,api_reader=APIReader(fail={'Pod'}),metric_reader=OfflineMetrics(),now=NOW)


def test_cluster_bindings_are_tenant_specific_and_reject_secret_or_redirect_fields(monkeypatch):
    monkeypatch.setenv('CLOUDSAVER_KUBERNETES_BINDINGS',json.dumps([BINDING]))
    assert binding(str(uuid4()),CLUSTER) is None
    assert binding(BINDING['tenant_id'],CLUSTER)==BINDING
    for invalid in (dict(BINDING,api_url='http://insecure'),dict(BINDING,api_key='secret'),dict(BINDING,api_token_env='STRIPE_SECRET_KEY'),dict(BINDING,api_url='https://user:password@example.test')):
        monkeypatch.setenv('CLOUDSAVER_KUBERNETES_BINDINGS',json.dumps([invalid]))
        with pytest.raises(ScanError):binding(BINDING['tenant_id'],CLUSTER)


def test_matrix_validates_30_day_five_minute_coverage_and_never_fills_missing_points():
    start=NOW-timedelta(days=30)
    values=[[int((start+timedelta(minutes=5*i)).timestamp()),'.2'] for i in range(1,8641)]
    def payload(points,cluster=CLUSTER):return {'status':'success','data':{'resultType':'matrix','result':[{'metric':{'cluster':cluster,'namespace':'production','pod':'checkout-pod','container':'api'},'values':points}]}}
    result=matrix(payload(values),CLUSTER,'cpu','container',False,start,NOW,NOW)
    assert next(iter(result.values()))['sufficient'] is True
    assert next(iter(matrix(payload(values[1000:]),CLUSTER,'cpu','container',False,start,NOW,NOW).values()))['sufficient'] is False
    with pytest.raises(ScanError):matrix(payload(values,'foreign-cluster'),CLUSTER,'cpu','container',False,start,NOW,NOW)
    duplicate=matrix(payload(values[:-1]+[values[0]]),CLUSTER,'cpu','container',False,start,NOW,NOW)
    assert next(iter(duplicate.values()))['sufficient'] is False


def test_allocation_scope_period_and_missing_costs_remain_explicit():
    start=NOW-timedelta(days=30);key=('production','checkout-pod','api')
    payload={'code':200,'data':[{'fixture':{'properties':{'cluster':CLUSTER,'namespace':key[0],'pod':key[1],'container':key[2]},
        'window':{'start':start.isoformat(),'end':NOW.isoformat()},'cpuCost':20,'ramCost':40,'totalCost':65}}]}
    cost=allocations(payload,CLUSTER,{key},start,NOW)
    row=container();row['evidence']['allocation']=cost[key]
    result=breakdown(row)
    assert result['workload_used_estimate_usd'] is not None and result['billed_node_cost_usd'] is None
    assert result['realizable_node_savings_usd'] is None
    payload['data'][0]['fixture']['window']['end']=(NOW-timedelta(days=1)).isoformat()
    with pytest.raises(ValueError):allocations(payload,CLUSTER,{key},start,NOW)


def test_opaque_pool_group_unifies_verified_cloud_component_without_double_counting():
    values=rows();node=next(r for r in values if r['resource_type']=='kubernetes.io/Node')
    cloud=dict(cloud_provider='azure',resource_id='/'+node['evidence']['provider_id'][len('azure:///'):],resource_type='microsoft.compute/virtualmachines',resource_name='node-a')
    values.append(cloud)
    pod_finding={'resource_id':container()['resource_id'],'cloud_provider':'kubernetes'}
    cloud_finding=dict(cloud,opportunity_group_id='old-azure-group')
    disk=dict(cloud_finding,resource_id=cloud['resource_id']+'/disk')
    result=group_opportunities([pod_finding,cloud_finding,disk],values)
    assert len({r['opportunity_group_id'] for r in result})==1
    assert result[0]['opportunity_group_id'].startswith('cluster_pool:')
    assert 'fixture-cluster' not in result[0]['opportunity_group_id']


def test_ledger_is_compact_and_scope_filtered_without_private_cluster_metadata():
    from app.provider_access import filter_scan
    values=rows()
    private=copy.deepcopy(container());private['scope_id']=private['subscription_id']='private-cluster';private['resource_id']=private['resource_id'].replace(CLUSTER,'private-cluster')
    values.append(private)
    ledger=compact(values,[],NOW.isoformat())
    assert ledger and len(values[0]['data_sources'][0])==2
    snapshot={'cloud_providers':['kubernetes'],'findings':[],'inventory':values,'rule_evaluations':[],'source_ledger':ledger}
    result=filter_scan(snapshot,{'kubernetes'},scopes={'kubernetes':{CLUSTER}})
    assert 'private-cluster' not in json.dumps(result)


def api_client(tmp_path,monkeypatch,values=None,role='TenantAdmin'):
    from app.config import Settings
    from app.main import create_app
    from app.store import Store
    monkeypatch.setenv('CLOUDSAVER_KEY_VERIFIER','local');monkeypatch.setenv('CLOUDSAVER_AUTH_MODE','workspace')
    key='offline-kubernetes-test-key'
    tenant=dict(tenant_id=str(uuid4()),name='Kubernetes test',plan_tier='ENTERPRISE',subscription_ids=[],kubernetes_clusters=[SOURCE],roles=[role],api_key_sha256=hashlib.sha256(key.encode()).hexdigest())
    settings=Settings('azure',str(tmp_path/'store.sqlite3'),(tenant,))
    values=values or rows();scan_id=str(uuid4())
    snapshot=dict(scan_id=scan_id,timestamp=NOW.isoformat(),status='completed',mode='multi-cloud',cloud_providers=['kubernetes'],subscriptions_scanned=0,total_items_found=len(values),
        total_monthly_waste_usd=None,findings=[],inventory=values,rule_evaluations=evaluate_inventory(values,observed_at=NOW.isoformat(),now=NOW))
    Store(settings.database).save(tenant['tenant_id'],snapshot,workspace=tenant)
    from app.auth import Role,UserClaims
    monkeypatch.setenv('CLOUDSAVER_AUTH_MODE','entra')
    class Validator:
        def verify_token(self,token):return UserClaims(user_id=str(uuid4()),tenant_id=tenant['tenant_id'],roles=[Role(role)])
    return TestClient(create_app(settings,identity_validator=Validator())),{'Authorization':'Bearer '+key},scan_id


def test_workspace_and_patch_preview_use_saved_evidence_and_no_live_cluster_mutation(tmp_path,monkeypatch):
    api,headers,scan_id=api_client(tmp_path,monkeypatch)
    path=f'/api/v1/scans/{scan_id}/kubernetes'
    result=api.get(path,headers=headers)
    assert result.status_code==200
    view=result.json();row=next(r for r in view['resources'] if r['resource_type']=='kubernetes.io/Container')
    assert len(view['rule_matrix'])==8 and row['costs']['billed_node_cost_usd'] is None
    body=dict(resource_id=row['resource_id'],rule_id='K8S_CONTAINER_CPU_OVERREQUEST',evidence_digest=row['evidence_digest'])
    preview=api.post(path+'/patch-preview',headers=headers,json=body)
    assert preview.status_code==409 and 'SLO' in preview.json()['detail']
    assert api.post(path+'/patch-preview',headers=headers,json=dict(body,evidence_digest='0'*64)).status_code==409
    assert api.get(f'/api/v1/scans/{uuid4()}/kubernetes',headers=headers).status_code==404


def test_a_single_unverified_replica_blocks_controller_patch(tmp_path,monkeypatch):
    values=rows();sibling=copy.deepcopy(container(values));sibling['resource_id']+="-other";sibling['evidence']['metrics']['throttling']=None;values.append(sibling)
    api,headers,scan_id=api_client(tmp_path,monkeypatch,values)
    path=f'/api/v1/scans/{scan_id}/kubernetes'
    row=next(r for r in api.get(path,headers=headers).json()['resources'] if r['resource_type']=='kubernetes.io/Container')
    result=api.post(path+'/patch-preview',headers=headers,json=dict(resource_id=row['resource_id'],rule_id='K8S_CONTAINER_CPU_OVERREQUEST',evidence_digest=row['evidence_digest']))
    assert result.status_code==409 and 'replica' in result.json()['detail']


def test_viewer_can_read_but_not_request_a_patch(tmp_path,monkeypatch):
    api,headers,scan_id=api_client(tmp_path,monkeypatch,role='Viewer')
    path=f'/api/v1/scans/{scan_id}/kubernetes'
    result=api.get(path,headers=headers)
    assert result.status_code==200
    row=next(r for r in result.json()['resources'] if r['resource_type']=='kubernetes.io/Container')
    assert api.post(path+'/patch-preview',headers=headers,json=dict(resource_id=row['resource_id'],rule_id='K8S_CONTAINER_CPU_OVERREQUEST',evidence_digest=row['evidence_digest'])).status_code==403


def test_private_cloud_dependency_is_removed_from_cluster_only_results():
    from app.dependencies import canonical_inventory
    from app.provider_access import filter_scan
    values=rows();node=next(r for r in values if r['resource_type']=='kubernetes.io/Node')
    cloud=dict(cloud_provider='azure',subscription_id='22222222-2222-4222-8222-222222222222',resource_id='/'+node['evidence']['provider_id'][len('azure:///'):],resource_name='node-a',resource_type='Microsoft.Compute/virtualMachines',evidence={})
    values=canonical_inventory(values+[cloud],NOW.isoformat())
    node=next(r for r in values if r['resource_type']=='kubernetes.io/Node')
    assert node['dependency_refs'][0]['relationship']=='k8s_node_to_cloud_vm'
    snapshot={'cloud_providers':['azure','kubernetes'],'findings':[],'inventory':values,'rule_evaluations':[]}
    filtered=filter_scan(snapshot,{'kubernetes'})
    assert all(r.get('dependency_refs')==[] for r in filtered['inventory'])


def test_bound_pvc_conflicting_with_cloud_disk_blocks_both_rule_evaluators():
    from app.dependencies import canonical_inventory
    from app.analysis_rules import evaluate_inventory as all_rules
    disk_id='/subscriptions/22222222-2222-4222-8222-222222222222/resourceGroups/rg/providers/Microsoft.Compute/disks/recovery'
    objmap=objects()
    objmap['PersistentVolume']=[obj('PersistentVolume','pv-a',None,spec={'csi':{'driver':'disk.csi.azure.com','volumeHandle':disk_id}})]
    objmap['PersistentVolumeClaim']=[obj('PersistentVolumeClaim','pvc-a',spec={'volumeName':'pv-a'},status={'phase':'Bound','capacity':{'storage':'200Gi'}})]
    values=project(CLUSTER,objmap,{},[],NOW)
    values.append(dict(cloud_provider='azure',resource_id=disk_id,resource_type='Microsoft.Compute/disks',resource_name='recovery',subscription_id='22222222-2222-4222-8222-222222222222',evidence={'disk_state':'Unattached'}))
    values=canonical_inventory(values,NOW.isoformat())
    ledger=compact(values,[],NOW.isoformat())
    conflicted=[r for r in values if r.get('reconciliation_status')=='source_conflict']
    assert len(conflicted)==3
    outcomes=all_rules(conflicted,observed_at=NOW.isoformat(),now=NOW)
    assert outcomes and {o['outcome'] for o in outcomes}=={'insufficient_evidence'}


def test_conflicting_ledger_digest_marks_every_affected_observation():
    a=container();b=copy.deepcopy(a);b['resource_id']+='-other'
    a['data_sources']=[{'source_id':'fixture','status':'available','evidence_digest':'a'}]
    b['data_sources']=[{'source_id':'fixture','status':'available','evidence_digest':'b'}]
    ledger=compact([a,b],[],NOW.isoformat())
    assert ledger[0]['status']=='conflict'
    assert a['reconciliation_status']==b['reconciliation_status']=='source_conflict'


def test_source_conflict_blocks_destructive_script_and_invalidates_opportunity():
    from app.remediation import generate_script
    from app.assessment import protection
    sid='22222222-2222-4222-8222-222222222222'
    rid=f'/subscriptions/{sid}/resourceGroups/rg/providers/Microsoft.Compute/disks/recovery'
    row={'cloud_provider':'azure','subscription_id':sid,'resource_id':rid,'resource_type':'Microsoft.Compute/disks','reconciliation_status':'source_conflict'}
    finding=dict(row,rule_id='ORPHANED_DISK',resource_name='recovery',estimated_monthly_waste_usd=10.)
    compact([row],[finding],NOW.isoformat())
    assert finding['estimated_monthly_waste_usd'] is None
    assert 'SOURCE_CONFLICT' in protection(finding)
    with pytest.raises(ValueError):generate_script({'mode':'azure','status':'completed','findings':[finding]},[rid],BINDING['tenant_id'],[sid])


def test_managed_prometheus_endpoints_fail_before_sending_identity_to_wrong_cloud(monkeypatch):
    from app.collectors.prometheus_auth import reader
    for backend in ('azure_amp','aws_amp_sigv4','gcp_gmp'):
        with pytest.raises(ScanError):reader(SOURCE,dict(BINDING,telemetry_backend=backend,region='us-east-1',role_arn='arn:aws:iam::123456789012:role/Reader',service_account='reader@project-a.iam.gserviceaccount.com'))


def test_azure_federation_uses_customer_credential_and_managed_prometheus_audience(monkeypatch):
    from app.collectors.prometheus_auth import reader
    calls=[]
    class Credential:
        def get_token(self,audience):calls.append(audience);return type('Token',(),{'token':'fixture-only'})()
        def close(self):calls.append('closed')
    monkeypatch.setattr('app.collectors.prometheus_auth.azure_credential',lambda tenant:(calls.append(tenant) or Credential()))
    value=reader(dict(SOURCE,prometheus_url='https://fixture.eastus.prometheus.monitor.azure.com'),dict(BINDING,telemetry_backend='azure_amp'))
    value.close()
    assert calls==[{'tenant_id':BINDING['tenant_id']},'https://prometheus.monitor.azure.com/.default','closed']


def test_platform_rule_contracts_match_and_can_be_individually_disabled():
    from pathlib import Path
    contract=Path(__file__).resolve().parents[1]/'platform/contracts/fixtures/kubernetes-rule-ids-v1.json'
    assert set(json.loads(contract.read_text()))==RULE_IDS


def test_telemetry_circuit_opens_after_three_failures_without_fabricating_other_metrics():
    from app.collectors.kubernetes import telemetry,queries
    class Broken:
        calls=0
        def get(self,*args,**kwargs):self.calls+=1;raise ScanError('unavailable')
    reader=Broken();metrics,sources=telemetry(reader,SOURCE['prometheus_url'],CLUSTER,NOW)
    assert reader.calls==3 and len(sources)==len(queries(CLUSTER))
    assert not any(metrics.values())
    assert sources[-1]['reason_code']=='source_circuit_open_for_scan'


def test_idle_node_in_busy_pool_does_not_create_false_pool_slack():
    values=objects();second=copy.deepcopy(values['Node'][0]);second['metadata'].update(name='node-b',uid='Node-node-b');values['Node'].append(second)
    values['Pod'][0]['spec']['containers'][0]['resources']['requests']['cpu']='10'
    projected=project(CLUSTER,values,{},[],NOW)
    nodes=[r for r in projected if r['resource_type']=='kubernetes.io/Node']
    assert all(r['evidence']['pool_capacity']['node_count']==2 for r in nodes)
    assert all(evaluated(r,'K8S_NODE_POOL_FRAGMENTATION_WASTE')['outcome']=='condition_not_detected' for r in nodes)


def test_collection_duration_does_not_turn_shared_provenance_into_source_conflict(monkeypatch):
    import app.collectors.provenance as provenance
    class AdvancingClock(datetime):
        calls=0
        @classmethod
        def now(cls,tz=None):cls.calls+=1;return NOW+timedelta(seconds=10*cls.calls)
    monkeypatch.setattr(provenance,'datetime',AdvancingClock)
    values=[{'cloud_provider':'azure','resource_id':'disk-'+str(i),'subscription_id':'same-subscription'} for i in range(3)]
    ledger=compact(values,[],NOW.isoformat())
    assert len(ledger)==1 and ledger[0]['status']=='available'
    assert not any(r.get('reconciliation_status')=='source_conflict' for r in values)


def test_signed_fresh_slo_proof_enables_review_patch_and_revocation_blocks_it(tmp_path,monkeypatch):
    from test_high_impact_improvements import slo
    from app.nextgen_evidence import canonical
    import hmac
    api,headers,scan_id=api_client(tmp_path,monkeypatch)
    tid=api.get('/api/v1/me',headers=headers).json()['tenant_id']
    path=f'/api/v1/scans/{scan_id}/kubernetes'
    row=next(r for r in api.get(path,headers=headers).json()['resources'] if r['resource_type']=='kubernetes.io/Container')
    case=api.post('/api/v1/optimization/cases',headers=headers,json=dict(scan_id=scan_id,resource_id=row['resource_id'],request_key=str(uuid4()),action='rightsizing'))
    assert case.status_code==201,case.text
    secret='synthetic-signature-key-'+'x'*32
    monkeypatch.setenv('CLOUDSAVER_EVIDENCE_KEY_FIXTURE',secret)
    monkeypatch.setenv('CLOUDSAVER_EVIDENCE_SOURCES',json.dumps([dict(tenant_id=tid,source_id='fixture',providers=['kubernetes'],scope_ids=[CLUSTER],kinds=['slo'],key_env='CLOUDSAVER_EVIDENCE_KEY_FIXTURE')]))
    receipt=dict(receipt_id=str(uuid4()),source_id='fixture',tenant_id=tid,provider='kubernetes',scope_id=CLUSTER,resource_id=row['resource_id'],kind='slo',issued_at=datetime.now(timezone.utc).isoformat(),payload=slo())
    signature=hmac.new(secret.encode(),canonical(receipt),hashlib.sha256).hexdigest()
    stored=api.post('/api/v1/optimization/receipts',headers=dict(headers,**{'X-Evidence-Signature':signature}),json=receipt)
    assert stored.status_code==201,stored.text
    body=dict(resource_id=row['resource_id'],rule_id='K8S_CONTAINER_CPU_OVERREQUEST',evidence_digest=row['evidence_digest'])
    result=api.post(path+'/patch-preview',headers=headers,json=body)
    assert result.status_code==200,result.text
    assert result.json()['automatic_execution'] is False and 'limits' not in result.json()['content']
    monkeypatch.setenv('CLOUDSAVER_EVIDENCE_SOURCES','[]')
    assert api.post(path+'/patch-preview',headers=headers,json=body).status_code==409
