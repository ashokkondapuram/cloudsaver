"""Consolidated product contracts, exact billing joins and safe worker integration."""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from decimal import Decimal
import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from app.assessment import assess
from app.resource_assessment import assessments,lifecycle,decision_state,planning_summary
from app.focus import FocusRepository,ImportRequest
from app.k8s_cost_reconciler import resolve_eks_node,group_opportunities,attach_node_costs
from app.scan_selection import select,restrict,normalize
from app.pricing import AzurePricingClient,regional_attribution
from tests.test_enterprise import evidence,workspace,charge,batch,AUTH
from tests.support import azure_disk_finding
from tests.test_ai_advisory import SUB
from tests.test_v140 import hourly,NOW


def check(result,code):
    return next(c for p in result['pillars'] for c in p['checks'] if c['code']==code)


def test_billed_cost_exposure_and_dependencies_use_explicit_evidence():
    r=azure_disk_finding(SUB);r.update(resource_type='Microsoft.Compute/virtualMachines',evidence=dict(billed_cost_usd=20,effective_cost_usd=30,commitment_locked=True,public_admin_ingress=False,imds_v2_required=True,
        verified_dependencies=[],dependency_inventory_complete=True,state_history=[dict(start=(NOW-timedelta(days=30)).isoformat(),end=NOW.isoformat(),complete=True,state='stopped')]))
    a=assess(r,observed_at=NOW.isoformat(),now=NOW)
    assert check(a,'BILLED_COST')['status']=='risk'
    assert check(a,'ACCESS_AND_EXPOSURE')['status']=='observed'
    assert check(a,'DEPENDENCY_GRAPH')['status']=='observed'
    r['evidence']['state_history'][0]['complete']=False
    assert check(assess(r,observed_at=NOW.isoformat(),now=NOW),'DEPENDENCY_GRAPH')['status']=='unknown'
    r['evidence']['verified_dependencies']=['attached-resource']
    assert check(assess(r,observed_at=NOW.isoformat(),now=NOW),'DEPENDENCY_GRAPH')['status']=='risk'


def test_resource_billing_join_is_exact_in_scope_and_currency(evidence):
    _,store,_=evidence;repo=FocusRepository(store);tenant=workspace();rid=azure_disk_finding(SUB)['resource_id'];end=NOW.replace(hour=0,minute=0,second=0,microsecond=0);start=end-timedelta(days=30)
    record=charge(1,'12.50',ResourceId=rid.upper(),ChargePeriodStart=start.isoformat(),ChargePeriodEnd=(start+timedelta(days=1)).isoformat(),EffectiveCost='15')
    payload=batch([record],source_id='exact',period_start=start.date().isoformat(),period_end=end.date().isoformat())
    repo.import_records(tenant,ImportRequest.model_validate(payload))
    costs=repo.resource_costs(tenant,[rid],as_of=NOW)
    value=costs[('azure',rid.lower())]
    assert value['billed_cost_usd']==12.5 and value['effective_cost_usd']==15
    assert value['commitment_locked'] and value['billing_coverage']
    assert repo.resource_costs(dict(tenant,subscription_ids=[]),[rid],as_of=NOW)=={}
    assert repo.resource_costs(tenant,[rid+'-different'],as_of=NOW)=={}
    other=deepcopy(payload);other['source_id']='eur';other['billing_currency']='EUR';other['records'][0].update(BillingCurrency='EUR',x_ChargeId='eur')
    repo.import_records(tenant,ImportRequest.model_validate(other))
    assert repo.resource_costs(tenant,[rid],as_of=NOW)[('azure',rid.lower())]['billed_cost_usd']==12.5


def test_inventory_only_resource_displays_billing_and_security(evidence):
    _,store,_=evidence;repo=FocusRepository(store);tenant=workspace();r=azure_disk_finding(SUB)
    end=NOW.replace(hour=0,minute=0,second=0,microsecond=0);start=end-timedelta(days=30)
    repo.import_records(tenant,ImportRequest.model_validate(batch([charge(1,'7',ResourceId=r['resource_id'],ChargePeriodStart=start.isoformat(),ChargePeriodEnd=(start+timedelta(days=1)).isoformat())],source_id='inventory-cost',period_start=start.date().isoformat(),period_end=end.date().isoformat())))
    scan=dict(scan_id=str(uuid4()),timestamp=NOW.isoformat(),findings=[],inventory=[dict(r,evidence={'encrypted':True})])
    a=next(iter(assessments(repo.attach(tenant,scan),now=NOW).values()))[0]
    assert a['finding_count']==0 and a['disposition']=='inventory_only' and a['billed_cost_usd']==7
    assert check(a,'BILLED_COST')['status']=='observed' and check(a,'ENCRYPTION_AT_REST')['status']=='observed'
    assert a['retail_estimate_usd'] is None


def test_expired_defer_reopens_without_rewriting_audit_history():
    a={'evidence_digest':'a'};decision=dict(decision='defer',defer_until=(NOW-timedelta(days=1)).date().isoformat(),evidence_digest='a')
    value=decision_state(a,decision,now=NOW)
    assert value['decision']=='none' and value['reopened'] and value['previous_decision']=='defer'
    assert decision['decision']=='defer'


def test_scan_delta_distinguishes_regressions_and_resolved_signals():
    r=azure_disk_finding(SUB);scan=dict(scan_id=str(uuid4()),timestamp=NOW.isoformat(),findings=[r],inventory=[])
    older=assessments(scan,now=NOW)
    healthy=dict(scan,findings=[],inventory=[r])
    deltas,summary=lifecycle(assessments(healthy,now=NOW),scan)
    assert list(deltas.values())==['persisting'] and summary['resolved_count']==1
    deltas,_=lifecycle(older,healthy)
    assert list(deltas.values())==['regressed']


def test_clean_baseline_runs_only_over_complete_saved_hourly_inputs():
    assert planning_summary({})['recommended_new_commitment_hr'] is None
    scan={'commitment_evidence':dict(source_verified=True,commitment_coverage_verified=True,usage_series=hourly('10'),cleanup_series=hourly('2'),existing_commitments_hr='3')}
    result=planning_summary(scan)
    assert result['recommended_new_commitment_hr']=='5' and not result['purchase_authorized']
    scan['commitment_evidence']['cleanup_series']['points'].pop()
    assert planning_summary(scan)['recommended_new_commitment_hr'] is None


def test_accountless_eks_identity_requires_one_regional_inventory_match():
    node=dict(cloud_provider='kubernetes',scope_id='cluster',resource_id='k8s://cluster/nodes/node',resource_type='kubernetes.io/Node',resource_name='node',evidence={'provider_id':'aws:///us-east-1a/i-0123456789abcdef0','node_pool':'pool'})
    cloud=dict(cloud_provider='aws',scope_id='123456789012',resource_id='arn:aws:ec2:us-east-1:123456789012:instance/i-0123456789abcdef0')
    assert resolve_eks_node(node,[cloud])==cloud
    duplicate=dict(cloud,scope_id='999999999999',resource_id=cloud['resource_id'].replace('123456789012','999999999999'))
    assert resolve_eks_node(node,[cloud,duplicate]) is None
    result=group_opportunities([dict(node,rule_id='K8S_NODE_POOL_FRAGMENTATION_WASTE'),dict(cloud,rule_id='AWS_EC2_RIGHTSIZING')],[node,cloud])
    assert result[0]['opportunity_group_id']==result[1]['opportunity_group_id']


def test_node_financials_require_complete_billing_and_verified_scheduling():
    inventory=[]
    for index in range(2):
        iid='i-'+str(index).zfill(17);rid='arn:aws:ec2:us-east-1:123456789012:instance/'+iid
        inventory += [dict(cloud_provider='aws',scope_id='123456789012',resource_id=rid,evidence=dict(billed_cost_usd=100,billing_coverage=True,commitment_locked=False)),
          dict(cloud_provider='kubernetes',scope_id='cluster',resource_id='node-'+str(index),resource_type='kubernetes.io/Node',resource_name='node-'+str(index),evidence=dict(provider_id='aws:///us-east-1a/'+iid,node_pool='pool',allocatable_cpu=8,allocatable_memory=16,requests=dict(complete=True,cpu=1,memory=2),pdb_blocked=False,scale_down_disabled=False,scheduling_constraints_verified=True))]
    attach_node_costs(inventory);e=inventory[1]['evidence']
    assert e['billed_node_cost_usd']==100 and e['pool_billed_node_cost_usd']==200 and e['realizable_node_savings_usd']==100
    inventory[3]['evidence']['pdb_blocked']=True;attach_node_costs(inventory)
    assert inventory[1]['evidence']['realizable_node_savings_usd'] is None


def test_multi_cloud_selection_contains_only_scope_ids_and_cannot_expand():
    tenant=dict(subscription_ids=[SUB],aws_accounts=[dict(account_id='123456789012',region='us-east-1',role_arn='private-role')],gcp_projects=[],kubernetes_clusters=[])
    selection=select(tenant,['azure','aws'])
    assert 'private-role' not in json.dumps(selection)
    assert restrict(tenant,selection)['aws_accounts']==tenant['aws_accounts']
    with pytest.raises(ValueError):restrict(dict(tenant,aws_accounts=[]),selection)
    with pytest.raises(ValueError):normalize(dict(providers=['aws'],scopes={'aws':['123456789012']},endpoint='https://attacker.invalid'))


def test_disk_composite_retail_estimate_deducts_snapshot_and_rejects_missing_meter():
    class Pricing(AzurePricingClient):
        def fetch_price(self,e):return None if e.get('meter_id')=='missing' else dict(unitPrice=e['rate'],unitOfMeasure=e['unit_of_measure'],meterId=e['meter_id'])
    def component(rate,quantity):return dict(rate=rate,quantity=quantity,unit_of_measure='1 GB/Month',meter_id='exact')
    r=azure_disk_finding(SUB);r['pricing_evidence']={'components':{'current':component('.15',100),'snapshot':component('.05',100)}}
    assert Pricing().attribute(r).monthly_waste_usd==10
    r['pricing_evidence']['components']['snapshot']['meter_id']='missing'
    assert Pricing().attribute(r).monthly_waste_usd is None


def test_regional_meter_review_is_exact_and_expires(monkeypatch):
    meter=dict(provider='aws',region='us-east-1',product='public-ip:unassociated',unit='hour',currency='USD',rate_usd='0.005',source='https://aws.amazon.com/vpc/pricing/',reviewed_at=(NOW-timedelta(days=1)).isoformat(),expires_at=(NOW+timedelta(days=1)).isoformat())
    monkeypatch.setenv('CLOUDSAVER_REGIONAL_PRICE_CATALOG',json.dumps([meter]))
    finding=dict(rule_id='AWS_UNASSOCIATED_EIP',cloud_provider='aws',region='us-east-1')
    assert regional_attribution(finding).monthly_waste_usd==3.65
    assert regional_attribution(dict(finding,region='us-west-2')).monthly_waste_usd is None
    meter['expires_at']=(NOW-timedelta(hours=1)).isoformat();monkeypatch.setenv('CLOUDSAVER_REGIONAL_PRICE_CATALOG',json.dumps([meter]))
    assert regional_attribution(finding).monthly_waste_usd is None


def test_multi_cloud_durable_job_scans_selected_scopes_and_never_widens(monkeypatch):
    from app.config import Settings
    from workers import tasks
    from tests.test_worker import Repository,Lease,TENANT
    tenant=dict(tenant_id=TENANT,name='Multi cloud',subscription_ids=[],aws_accounts=[dict(account_id='123456789012',region='us-east-1')],gcp_projects=[],kubernetes_clusters=[],plan_tier='ENTERPRISE')
    settings=Settings('multi-cloud','unused',(tenant,),'unused')
    selection=select(tenant,['aws'])
    resource=dict(cloud_provider='aws',scope_id='123456789012',subscription_id='123456789012',resource_id='arn:aws:ec2:us-east-1:123456789012:volume/vol-0123456789abcdef0',resource_type='aws:ec2:volume',resource_name='disk',resource_group='us-east-1',region='us-east-1',rule_id='AWS_UNATTACHED_EBS',severity='MEDIUM',details='Synthetic observation',estimated_monthly_waste_usd=None,evidence={})
    class Jobs(Repository):
        def complete_job(self,tid,jid,scan,scopes,**options):
            assert scopes==selection
            self.scans[scan['scan_id']]=deepcopy(scan)
            self.jobs[jid].update(status='completed',scan_id=scan['scan_id'])
    calls=[]
    def scan(workspace,providers,**options):
        calls.append((workspace,providers));return [resource],[]
    monkeypatch.setattr('app.multi_cloud.scan_multi_cloud',scan)
    jobs=Jobs(active=[]);result=tasks.run_scan_job(settings,TENANT,selection,str(uuid4()),jobs,Lease())
    saved=jobs.scans[result['scan_id']]
    assert saved['cloud_providers']==['aws'] and saved['subscriptions_scanned']==0 and len(calls)==1
    assert saved['scope_results'][0]['scope_id']=='123456789012'
    with pytest.raises(tasks.UnauthorizedJob):tasks.authorized_tenant(Settings('multi-cloud','unused',(dict(tenant,aws_accounts=[]),),'unused'),jobs,TENANT,selection)


def test_shared_json_parser_rejects_duplicate_keys_and_nonfinite_numbers():
    from app.schemas import load_json,InvalidJSON
    for value in ('{"x":1,"x":2}','{"x":NaN}','{"x":1e999}', '['*70+'0'+']'*70):
        with pytest.raises(InvalidJSON):load_json(value)


def test_platform_and_application_share_the_pruned_ai_policy_contract():
    from pathlib import Path
    from app.ai_platform_policy import validate
    policy=json.loads((Path(__file__).resolve().parents[1]/'platform/contracts/fixtures/ai-policy-v2.json').read_text())['policy']
    assert 'allow_knowledge_candidates' not in policy
    assert validate(policy)['enabled'] is False
    assert 'allow_knowledge_candidates' not in validate(dict(policy,allow_knowledge_candidates=True))
