"""Data-use approvals, minimization, secret blocking, retention and tenant isolation."""
from contextlib import nullcontext
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
from uuid import uuid4
import copy,json,sqlite3

import pytest
from fastapi.testclient import TestClient
from app.ai_advisory import AIError,CloudAdapter,Target
from app.config import Settings
from app.data_governance import DataDenied,DataGovernor,require_processing_grant,sanitize,safe_action_data
from app.data_policy import DEFAULT_DATA_GOVERNANCE,validate_data_governance
from app.data_retention import DataRetention,RetentionConflict
from app.enterprise_store import EnterpriseStore
from app.inference_ledger import InferenceLedger
from app.store import Store


@pytest.fixture
def governed(tmp_path,monkeypatch):
    tid,sid,azure_tenant=str(uuid4()),str(uuid4()),str(uuid4())
    tenant=dict(tenant_id=tid,name='Governance QA',subscription_ids=[sid],roles=['TenantAdmin'])
    settings=Settings('azure',str(tmp_path/'data.sqlite3'),(tenant,));Store(settings.database)
    scan=dict(scan_id=str(uuid4()),timestamp=datetime.now(timezone.utc).isoformat(),status='completed',mode='azure',subscriptions_scanned=1,total_items_found=0,total_monthly_waste_usd=None,inventory=[],findings=[])
    Store(settings.database).save(tid,scan,workspace=tenant)
    target=Target(target_id='private-review',tenant_id=tid,provider='azure',auth='managed_identity',model='approved-model',region='eastus',endpoint='https://approved.openai.azure.com',
        azure_resource_id=f'/subscriptions/{sid}/resourceGroups/rg/providers/Microsoft.CognitiveServices/accounts/approved')
    policy=dict(copy.deepcopy(DEFAULT_DATA_GOVERNANCE),environment_id='prod-company',azure_tenant_id=azure_tenant,
        processors=[dict(workspace_id=tid,target_id=target.target_id,azure_resource_id=target.azure_resource_id,endpoint_url=target.endpoint,deployment_name=target.model,purposes=['assessment','resource_assessment','followup','agent_planning'],
            review_reference='GOV-APPROVAL-42',review_expires_at=(datetime.now(timezone.utc)+timedelta(days=20)).isoformat(),provider_controls_reviewed=True)])
    row={'version':1,'policy':{'data_governance':policy}}
    monkeypatch.setenv('CLOUDSAVER_DATA_ENVIRONMENT_ID',policy['environment_id']);monkeypatch.setenv('CLOUDSAVER_DATA_AZURE_TENANT_ID',azure_tenant)
    store=EnterpriseStore(settings);governor=DataGovernor(store,lambda:row)
    return SimpleNamespace(tenant=tenant,settings=settings,store=store,governor=governor,target=target,policy=policy,row=row,scan=scan)


def test_minimization_removes_raw_inventory_and_redacts_identifiers_without_storing_prompt(governed):
    s=governed
    context={'resource_reference':'a'*64,'provider':'azure','service_category':'storage','facts':{'size_gb':128,'business_name':'private-business-name','tags':{'owner':'private@example.com'}},
        'resource_id':'/subscriptions/private/resource','question':'not part of this purpose'}
    cleaned,grant=s.governor.prepare(s.tenant,s.target,'assessment',context)
    assert cleaned['facts']=={'size_gb':128} and 'resource_id' not in cleaned and 'question' not in cleaned
    with grant.active():assert require_processing_grant(s.target,s.tenant,cleaned)==grant
    view=DataRetention(s.store).view(s.tenant)
    assert view['counts']=={'allowed':1}
    assert 'private@example.com' not in json.dumps(view) and 'size_gb' not in json.dumps(view)


@pytest.mark.parametrize('value',[{'facts':{'clientSecret':'private'}},{'facts':{'note':'Bearer abcdefghijklmno'}},
    {'facts':{'note':'AccountKey=abcdefghijklmno'}},{'facts':{'note':'https://storage.blob.core.windows.net/a?sig=abcdefghijklmno'}}])
def test_credentials_block_before_processing_and_audit_contains_only_reason_codes(governed,value):
    s=governed
    with pytest.raises(DataDenied):s.governor.prepare(s.tenant,s.target,'assessment',value)
    view=DataRetention(s.store).view(s.tenant)
    assert view['counts']=={'blocked':1} and 'abcdefghijklmno' not in json.dumps(view)


def test_purpose_owner_environment_review_and_resource_bindings_cannot_be_replaced_by_consent(governed):
    s=governed;message={'facts':{'size_gb':128}}
    for alter in [lambda p:p.update(environment_id='different-env'),lambda p:p.update(azure_tenant_id=str(uuid4())),
        lambda p:p['processors'][0].update(workspace_id=str(uuid4())),lambda p:p['processors'][0].update(purposes=['followup']),
        lambda p:p['processors'][0].update(azure_resource_id=s.target.azure_resource_id+'-other'),
        lambda p:p['processors'][0].update(review_expires_at='2020-01-01T00:00:00Z')]:
        p=copy.deepcopy(s.policy);alter(p);s.row['policy']['data_governance']=p
        with pytest.raises(DataDenied):s.governor.prepare(s.tenant,s.target,'assessment',dict(message,consent=True))
    s.row['policy']['data_governance']=s.policy
    with pytest.raises(DataDenied):s.governor.prepare(s.tenant,s.target.model_copy(update={'auth':'customer_federated'}),'assessment',message)


def test_processing_grant_is_exact_payload_bound_expiring_and_revocable(governed):
    s=governed;cleaned,grant=s.governor.prepare(s.tenant,s.target,'assessment',{'facts':{'size_gb':128}})
    with grant.active():
        with pytest.raises(DataDenied):require_processing_grant(s.target,s.tenant,{'facts':{'size_gb':256}})
        s.row['policy']['data_governance']=dict(s.policy,response_retention_days=1)
        with pytest.raises(DataDenied):require_processing_grant(s.target,s.tenant,cleaned)
    with pytest.raises(DataDenied):require_processing_grant(s.target,s.tenant,cleaned)


def test_native_model_transport_refuses_calls_without_a_data_use_grant(governed,monkeypatch):
    monkeypatch.setattr('app.cloud_identity.platform_credential',lambda:pytest.fail('No credential/provider call is permitted'))
    with pytest.raises(AIError,match='NO_VALID_DATA_USE_GRANT'):CloudAdapter()(governed.target,governed.tenant,{})


def test_identifying_action_values_are_not_silently_rewritten_and_output_secrets_are_blocked(governed):
    s=governed
    with pytest.raises(DataDenied,match='IDENTIFYING_ACTION_INSTRUCTION'):
        s.governor.prepare(s.tenant,s.target,'agent_planning',{'instruction':'Set owner to alice@example.com','resource_type':'disk','connectors':[]})
    _,grant=s.governor.prepare(s.tenant,s.target,'assessment',{'facts':{}})
    with pytest.raises(DataDenied):s.governor.clean_output(s.tenant,grant,{'summary':'password=unsafe-value'})
    result,_=sanitize({'resource':{'facts':{}},'question':'Review /subscriptions/abc/resources/disk and owner alice@example.com'},purpose='followup')
    assert 'alice@example.com' not in json.dumps(result) and '/subscriptions/' not in json.dumps(result)


def test_policy_contract_matches_platform_and_cannot_enable_training_or_external_reuse(governed):
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    assert (root/'app/data_policy.py').read_bytes()==(root/'platform/identity/data_policy.py').read_bytes()
    assert validate_data_governance(governed.policy)==governed.policy
    for flag in ('allow_training','allow_cross_tenant_reuse','allow_external_action_data'):
        with pytest.raises(ValueError):validate_data_governance(dict(governed.policy,**{flag:True}))


def record(s,key=None):
    key=key or str(uuid4());ledger=InferenceLedger(s.store)
    result=ledger.run(s.tenant['tenant_id'],key,'a'*64,10,lambda:dict(usage={'input_tokens':100,'output_tokens':200},advice={'summary':'governed response'}),
        metadata={'scan_id':s.scan['scan_id'],'provider':'azure','model':'approved','target_id':'private-review'})
    return ledger,key,result


def test_privacy_erasure_preserves_usage_and_replay_fences_and_cannot_be_reversed(governed):
    s=governed;ledger,key,result=record(s);attempt=result['assessment_id']
    erased=DataRetention(s.store).erase(s.tenant,attempt,'PRIVACY-42')
    assert erased['content_erased'] and ledger.get(s.tenant['tenant_id'],attempt)['response'] is None
    assert ledger.usage(s.tenant['tenant_id'])['groups'][0]['input_tokens']==100
    with pytest.raises(AIError) as error:
        record(s,key)
    assert error.value.status==410
    with s.store.transaction(s.tenant['tenant_id'],write=True) as db:
        with pytest.raises(sqlite3.IntegrityError):db.execute("UPDATE ai_inference_attempts SET response='{}' WHERE id=%s",(attempt,))


def test_legal_holds_are_tenant_owned_time_bounded_and_block_content_erasure(governed):
    s=governed;_,_,result=record(s);attempt=result['assessment_id'];repo=DataRetention(s.store)
    repo.hold(s.tenant,attempt,datetime.now(timezone.utc)+timedelta(days=2),'LEGAL-42')
    with pytest.raises(RetentionConflict):repo.erase(s.tenant,attempt,'PRIVACY-42')
    with pytest.raises(RetentionConflict):repo.hold(s.tenant,attempt,datetime.now(timezone.utc)+timedelta(days=31),'LEGAL-42')
    with pytest.raises(RetentionConflict):repo.erase(dict(s.tenant,tenant_id=str(uuid4())),attempt,'PRIVACY-42')
    assert DataRetention(s.store).view(dict(s.tenant,tenant_id=str(uuid4())))['events']==[]
    with sqlite3.connect(s.settings.database) as db:
        with pytest.raises(sqlite3.IntegrityError):db.execute('DELETE FROM ai_data_events')


def test_first_party_actions_cannot_carry_secrets():
    safe_action_data({'tags':{'CostCenter':'FINOPS-42'}})
    with pytest.raises(DataDenied):safe_action_data({'tags':{'password':'private'}})


def test_privacy_erasure_clears_the_linked_agent_plan_and_instruction_copy(governed):
    from app.agent_store import AgentRepository
    from app.agent_contract import Connector
    s=governed;repo=AgentRepository(s.store);sid=s.tenant['subscription_ids'][0]
    resource={'cloud_provider':'azure','scope_id':sid,'subscription_id':sid,'resource_id':f'/subscriptions/{sid}/resourceGroups/rg/providers/Microsoft.Compute/disks/qa','resource_type':'Microsoft.Compute/disks'}
    task=repo.create(s.tenant,s.scan,resource,dict(request_key=str(uuid4()),intent='Inspect the allocation tags',connector_ids=['azure-tags'],target_id=s.target.target_id))
    connector=Connector(id='azure-tags',tenant_id=s.tenant['tenant_id'],provider='azure',scope_id=sid,kind='azure_arm',operations=['resource.inspect'])
    worker={'id':'worker','connector_ids':['azure-tags']};assignment=repo.claim(s.tenant,worker,[connector])
    plan={'summary':'Inspect tags','steps':[dict(connector_id='azure-tags',operation='resource.inspect',arguments={},purpose='Read tags',verification='Provider read succeeds',rollback='Read-only')]}
    task=repo.save_draft(s.tenant,task['id'],worker,assignment['lease_token'],plan,[connector])
    result=InferenceLedger(s.store).run(s.tenant['tenant_id'],task['payload']['draft_key'],'b'*64,10,lambda:dict(plan=plan,usage={}),
        metadata=dict(scan_id=s.scan['scan_id'],kind='agent_plan',provider='azure',model='approved',target_id=s.target.target_id))
    DataRetention(s.store).erase(s.tenant,result['assessment_id'],'PRIVACY-42')
    erased=repo.get(s.tenant,task['id'])
    assert erased['payload']['plan'] is None and erased['payload']['data_erased'] is True and erased['state']=='cancelled'
    assert 'Inspect the allocation tags' not in json.dumps(erased)
    assert not any('plan' in e['payload'] for e in erased['events'])


def test_legal_preservation_does_not_authorize_reading_or_replaying_expired_content(governed):
    s=governed;ledger=InferenceLedger(s.store);past=datetime.now(timezone.utc)-timedelta(days=8)
    ledger.now=lambda db:past
    key=str(uuid4());result=ledger.run(s.tenant['tenant_id'],key,'a'*64,10,lambda:dict(advice={'summary':'preserved evidence'},usage={}),
        metadata=dict(scan_id=s.scan['scan_id'],provider='azure',model='approved',target_id=s.target.target_id))
    DataRetention(s.store).hold(s.tenant,result['assessment_id'],datetime.now(timezone.utc)+timedelta(days=1),'LEGAL-42')
    ledger.now=lambda db:datetime.now(timezone.utc)
    assert ledger.get(s.tenant['tenant_id'],result['assessment_id'])['response'] is None
    with s.store.transaction(s.tenant['tenant_id']) as db:
        assert db.execute('SELECT response FROM ai_inference_attempts WHERE id=%s',(result['assessment_id'],)).fetchone()[0] is not None
    with pytest.raises(AIError) as error:ledger.run(s.tenant['tenant_id'],key,'a'*64,10,lambda:pytest.fail('No replay'),metadata={'scan_id':s.scan['scan_id']})
    assert error.value.status==410


def test_workspace_governance_api_enforces_owner_roles_and_tenant_owned_erasure(governed):
    from fastapi import FastAPI,Header
    from app.data_governance_api import create_router
    s=governed;_,_,result=record(s)
    def tenant(authorization:str=Header(default='')):
        return dict(s.tenant,roles=['Viewer'] if authorization=='viewer' else ['TenantAdmin'],
            tenant_id=str(uuid4()) if authorization=='foreign' else s.tenant['tenant_id'])
    app=FastAPI();app.include_router(create_router(s.store,tenant,s.governor));api=TestClient(app)
    assert api.get('/api/v1/ai/governance',headers={'Authorization':'viewer'}).status_code==200
    path='/api/v1/ai/governance/records/'+result['assessment_id']+'/erase'
    assert api.post(path,headers={'Authorization':'viewer'},json={'review_reference':'PRIVACY-42'}).status_code==403
    assert api.post(path,headers={'Authorization':'foreign'},json={'review_reference':'PRIVACY-42'}).status_code==409
    assert api.post(path,json={'review_reference':'PRIVACY-42'}).json()['content_erased'] is True
