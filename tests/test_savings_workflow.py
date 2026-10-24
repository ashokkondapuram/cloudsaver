"""Tenant isolation, versioning and signed collector proof for the savings lifecycle."""
from datetime import datetime,timedelta,timezone
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
import hashlib,hmac,json,sqlite3
import pytest
from fastapi.testclient import TestClient
from app.config import Settings
from app.main import create_app
from app.store import Store
from app.enterprise_store import EnterpriseStore
from app.savings_store import SavingsRepository,SavingsConflict
from app.nextgen_evidence import canonical
from app.auth import UserClaims,Role


@pytest.fixture
def setup(tmp_path,monkeypatch):
    monkeypatch.setenv('CLOUDSAVER_AUTH_MODE','entra');monkeypatch.setenv('CLOUDSAVER_KEY_VERIFIER','local')
    tid,sid=str(uuid4()),str(uuid4());token='synthetic-savings-workspace'
    tenant=dict(tenant_id=tid,subscription_ids=[sid],name='Savings test',plan_tier='ENTERPRISE',api_key_sha256=hashlib.sha256(token.encode()).hexdigest())
    settings=Settings('azure',str(tmp_path/'savings.sqlite3'),(tenant,));store=Store(settings.database)
    now=datetime.now(timezone.utc);action=now-timedelta(days=61)
    resource=dict(cloud_provider='azure',subscription_id=sid,scope_id=sid,resource_id=f'/subscriptions/{sid}/resourceGroups/rg/providers/Microsoft.Compute/disks/fixture',resource_name='fixture',resource_type='Microsoft.Compute/disks',evidence={'disk_state':'Unattached'})
    baseline=dict(scan_id=str(uuid4()),timestamp=(action-timedelta(days=1)).isoformat(),status='completed',mode='azure',cloud_providers=['azure'],subscriptions_scanned=1,total_items_found=1,
        total_monthly_waste_usd=None,findings=[],inventory=[resource])
    latest=dict(baseline,scan_id=str(uuid4()),timestamp=now.isoformat(),total_items_found=0,inventory=[],scope_results=[dict(provider='azure',scope_id=sid,status='completed',supported_inventory_complete=True,supported_resource_types=['Microsoft.Compute/disks'])])
    store.save(tid,baseline,workspace=tenant);store.save(tid,latest,workspace=tenant)
    class Validator:
        def verify_token(self,value):return UserClaims(user_id=str(uuid4()),tenant_id=tid,roles=[Role.VIEWER if value=='viewer' else Role.TENANT_ADMIN])
    monkeypatch.setattr('app.scanner.scan_live',lambda _,enabled_rule_ids=None:([],[resource]))
    api=TestClient(create_app(settings,identity_validator=Validator()))
    source=dict(tenant_id=tid,source_id='trusted-test',providers=['azure'],scope_ids=[sid],kinds=['audit','billing','slo'],key_env='CLOUDSAVER_EVIDENCE_KEY_TEST')
    secret='test-only-collector-key-'+('x'*32)
    monkeypatch.setenv('CLOUDSAVER_EVIDENCE_SOURCES',json.dumps([source]));monkeypatch.setenv(source['key_env'],secret)
    return SimpleNamespace(api=api,tenant=tenant,headers={'Authorization':'Bearer '+token},baseline=baseline,latest=latest,resource=resource,settings=settings,secret=secret,action=action,now=now,store=store)


def create(s,key=None,**updates):
    body=dict(scan_id=s.baseline['scan_id'],resource_id=s.resource['resource_id'],request_key=key or str(uuid4()),action='retirement',note='Reviewed retention and ownership.')
    body.update(updates)
    return s.api.post('/api/v1/optimization/cases',headers=s.headers,json=body)


def scheduled(s,monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None):return s.action
    monkeypatch.setattr('app.savings_store.datetime',Clock)
    response=create(s);assert response.status_code==201,response.text
    case=response.json()
    for state in ('accepted_for_investigation','scheduled'):
        response=s.api.patch('/api/v1/optimization/cases/'+case['id'],headers=s.headers,json={'version':case['version'],'state':state})
        assert response.status_code==200,response.text;case=response.json()
    return case


def receipt(s,kind,payload,**updates):
    raw=dict(receipt_id=str(uuid4()),source_id='trusted-test',tenant_id=s.tenant['tenant_id'],provider='azure',scope_id=s.tenant['subscription_ids'][0],resource_id=s.resource['resource_id'],kind=kind,issued_at=s.now.isoformat(),payload=payload)
    raw.update(updates);signature=hmac.new(s.secret.encode(),canonical(raw),hashlib.sha256).hexdigest()
    return raw,dict(s.headers,**{'X-Evidence-Signature':signature})


def proofs(s):
    audit={'event_id':'authoritative-test-event','occurred_at':(s.action+timedelta(hours=1)).isoformat(),'operation':'delete','status':'Succeeded'}
    billing=dict(currency='USD',baseline_start=(s.action-timedelta(days=30)).date().isoformat(),baseline_end=s.action.date().isoformat(),
        observation_start=(s.action+timedelta(days=1)).date().isoformat(),observation_end=(s.action+timedelta(days=31)).date().isoformat(),
        baseline_monthly_cost_usd='100',post_resource_cost_usd='0',new_backup_or_snapshot_overhead_usd='15',one_time_transition_cost_usd='0',provider_reconciled=True,coverage_complete=True,overhead_inventory_complete=True)
    return audit,billing


def test_case_creation_is_idempotent_and_cannot_be_self_marked_verified(setup):
    s=setup;key=str(uuid4());first=create(s,key);second=create(s,key)
    assert first.status_code==second.status_code==201 and first.json()['id']==second.json()['id']
    assert create(s,key,note='different').status_code==409
    assert s.api.patch('/api/v1/optimization/cases/'+first.json()['id'],headers=s.headers,json={'version':1,'state':'verified_completed'}).status_code==422
    assert create(s,resource_id='/foreign/resource').status_code==404


def test_stale_case_versions_cannot_overwrite_review_history(setup):
    s=setup;case=create(s).json();path='/api/v1/optimization/cases/'+case['id']
    assert s.api.patch(path,headers=s.headers,json={'version':1,'state':'accepted_for_investigation'}).status_code==200
    assert s.api.patch(path,headers=s.headers,json={'version':1,'state':'deferred'}).status_code==409
    history=s.api.get(path,headers=s.headers).json()['events']
    assert [event['version'] for event in history]==[1,2]


def test_racing_transitions_have_one_winner(setup):
    s=setup;case=create(s).json();repo=SavingsRepository(EnterpriseStore(s.settings));tenant=dict(s.tenant,roles=['TenantAdmin'])
    def change(state):
        try:return repo.transition(tenant,case['id'],1,state,'Concurrent review')['state']
        except SavingsConflict:return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(change,['accepted_for_investigation','deferred']))
    assert results.count('conflict')==1


def test_only_signed_bound_receipts_are_accepted_and_replays_are_immutable(setup):
    s=setup;create(s);audit,_=proofs(s);raw,headers=receipt(s,'audit',audit)
    path='/api/v1/optimization/receipts'
    assert s.api.post(path,headers=s.headers,json=raw).status_code==422
    response=s.api.post(path,headers=headers,json=raw)
    assert response.status_code==201,response.text
    assert s.api.post(path,headers=headers,json=raw).json()['cached'] is True
    altered=dict(raw,payload=dict(audit,event_id='changed'))
    assert s.api.post(path,headers=headers,json=altered).status_code==422
    altered,signature_headers=receipt(s,'audit',dict(audit,event_id='changed'),receipt_id=raw['receipt_id'])
    assert s.api.post(path,headers=signature_headers,json=altered).status_code==409


def test_verified_savings_require_audit_billing_and_complete_post_action_scope(setup,monkeypatch):
    s=setup;case=scheduled(s,monkeypatch);path='/api/v1/optimization/cases/'+case['id']+'/verify'
    result=s.api.post(path,headers=s.headers,json={'version':case['version'],'scan_id':s.latest['scan_id']})
    assert result.status_code==200 and result.json()['state']=='scheduled'
    assert result.json()['verification']['verified_realized_savings_usd'] is None
    case=result.json()
    for kind,payload in zip(('audit','billing'),proofs(s)):
        raw,headers=receipt(s,kind,payload)
        assert s.api.post('/api/v1/optimization/receipts',headers=headers,json=raw).status_code==201
    verified=s.api.post(path,headers=s.headers,json={'version':case['version'],'scan_id':s.latest['scan_id']})
    assert verified.status_code==200,verified.text
    assert verified.json()['state']=='verified_completed' and verified.json()['verification']['verified_realized_savings_usd']=='85'
    assert set(verified.json()['verification']['evidence_receipts'])=={'audit','billing'}
    # The regular successful scan path automatically reopens a retired resource that recurs.
    scanned=s.api.post('/api/v1/scans',headers=s.headers)
    assert scanned.status_code==201,scanned.text
    reopened=s.api.get('/api/v1/optimization/cases/'+case['id'],headers=s.headers).json()
    assert reopened['state']=='reopened_on_regression' and Decimal(reopened['verification']['verified_realized_savings_usd'])==0


def test_failed_or_unsupported_scope_never_converts_disappearance_to_savings(setup,monkeypatch):
    s=setup;case=scheduled(s,monkeypatch)
    missing=dict(s.latest,scan_id=str(uuid4()),scope_results=[])
    s.store.save(s.tenant['tenant_id'],missing,workspace=s.tenant)
    result=s.api.post('/api/v1/optimization/cases/'+case['id']+'/verify',headers=s.headers,json={'version':case['version'],'scan_id':missing['scan_id']})
    assert result.json()['verification']['reasons']==['unverified_scope_missing']


def test_viewer_can_plan_and_read_but_cannot_change_lifecycle_or_read_actual_billing(setup):
    s=setup;case=create(s).json();viewer={'Authorization':'Bearer viewer'}
    assert s.api.get('/api/v1/optimization/cases',headers=viewer).status_code==200
    assert s.api.post('/api/v1/optimization/cases',headers=viewer,json=dict(scan_id=s.baseline['scan_id'],resource_id=s.resource['resource_id'],request_key=str(uuid4()),action='retirement')).status_code==403
    assert s.api.patch('/api/v1/optimization/cases/'+case['id'],headers=viewer,json={'version':1,'state':'accepted_for_investigation'}).status_code==403
    response=s.api.post('/api/v1/optimization/simulate/commitments',headers=viewer,json=dict(raw_spend_p10_hr='10',open_rightsizing_and_waste_hr='2',existing_commitments_hr='3'))
    assert response.status_code==200
    from app.nextgen_api import public_case
    assert public_case({'verification':{'baseline_monthly_cost_usd':'100'}},{'roles':['Viewer']})['verification']['baseline_monthly_cost_usd'] is None


def test_foreign_cases_and_append_only_records_remain_protected(setup):
    s=setup;case=create(s).json();repo=SavingsRepository(EnterpriseStore(s.settings))
    assert repo.get(dict(s.tenant,tenant_id=str(uuid4())),case['id']) is None
    assert repo.get(dict(s.tenant,scope_restrictions={'azure':[str(uuid4())]}),case['id']) is None
    with sqlite3.connect(s.settings.database) as db:
        with pytest.raises(sqlite3.IntegrityError):db.execute('DELETE FROM savings_case_events')


def test_one_authoritative_action_cannot_credit_multiple_cases(setup,monkeypatch):
    s=setup;first=scheduled(s,monkeypatch);second=scheduled(s,monkeypatch)
    for kind,payload in zip(('audit','billing'),proofs(s)):
        raw,headers=receipt(s,kind,payload)
        assert s.api.post('/api/v1/optimization/receipts',headers=headers,json=raw).status_code==201
    body=lambda case:{'version':case['version'],'scan_id':s.latest['scan_id']}
    assert s.api.post('/api/v1/optimization/cases/'+first['id']+'/verify',headers=s.headers,json=body(first)).json()['state']=='verified_completed'
    duplicate=s.api.post('/api/v1/optimization/cases/'+second['id']+'/verify',headers=s.headers,json=body(second))
    assert duplicate.status_code==409 and 'credited' in duplicate.json()['detail']


def test_failed_followup_does_not_destroy_the_prior_verified_period(setup,monkeypatch):
    s=setup;case=scheduled(s,monkeypatch)
    for kind,payload in zip(('audit','billing'),proofs(s)):
        raw,headers=receipt(s,kind,payload);s.api.post('/api/v1/optimization/receipts',headers=headers,json=raw)
    path='/api/v1/optimization/cases/'+case['id']+'/verify'
    first=s.api.post(path,headers=s.headers,json={'version':case['version'],'scan_id':s.latest['scan_id']}).json()
    missing=dict(s.latest,scan_id=str(uuid4()),scope_results=[]);s.store.save(s.tenant['tenant_id'],missing,workspace=s.tenant)
    unknown=s.api.post(path,headers=s.headers,json={'version':first['version'],'scan_id':missing['scan_id']}).json()
    assert unknown['verification']['verified_realized_savings_usd'] is None
    assert unknown['payload']['last_verified_result']['verified_realized_savings_usd']=='85'
    checked=s.api.post(path,headers=s.headers,json={'version':unknown['version'],'scan_id':s.latest['scan_id']}).json()
    assert checked['verification']['verified_realized_savings_usd']=='85' and checked['verification']['verified_period_end']


def test_malformed_case_uuid_is_a_validation_error_not_a_server_failure(setup):
    s=setup
    assert create(s,key='-'*36).status_code==422


def test_observed_topology_uses_owned_snapshot_and_discards_unknown_endpoints(setup):
    s=setup
    inventory=s.api.get('/api/v1/optimization/scans/'+s.baseline['scan_id'],headers=s.headers).json()
    key=inventory['resources'][0]['resource_key']
    graph=s.api.get(f'/api/v1/optimization/scans/{s.baseline["scan_id"]}/topology/{key}',headers=s.headers)
    assert graph.status_code==200 and len(graph.json()['nodes'])==1
    assert graph.json()['verified_realized_savings_usd'] is None and graph.json()['nodes'][0]['avoidable_monthly_cost_usd'] is None
    assert s.api.get(f'/api/v1/optimization/scans/{uuid4()}/topology/{key}',headers=s.headers).status_code==404
    from app.observed_topology import graph as observed
    snapshot=dict(s.baseline,inventory=[dict(s.resource,dependency_refs=[dict(from_resource_id=s.resource['resource_id'],to_resource_id='private-unobserved-endpoint',relationship='vm_to_disk',verification_state='inferred')])])
    assert 'private-unobserved-endpoint' not in json.dumps(observed(snapshot,key))


from decimal import Decimal
