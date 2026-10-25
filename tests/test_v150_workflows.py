"""Provider effects are mocked; durable billing and human approvals use real stores."""
from copy import deepcopy
from datetime import datetime,timezone,timedelta
from decimal import Decimal
import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from app.agent_contract import connectors,program_hash,validate_plan
from app.agent_gitops_sync import build_synchronized_agent_gitops_bundle,generate_synchronized_terraform_patch
from app.collectors.billing_sync import bindings,sync_status,sync_workspace_billing
from app.focus import FocusError,FocusRepository
from app.gitops import GitOpsConfig,GitOpsFailure
from app.main import create_app
from app.v150_store import WorkflowConflict,WorkflowStore
from tests.test_enterprise import evidence,workspace,TID,SUB,AUTH
from tests.test_agent_execution import setup,create,claim,worker,approve


def configured(monkeypatch):
    monkeypatch.setenv('CLOUDSAVER_AUTO_BILLING_SYNC','true')
    monkeypatch.setenv('CLOUDSAVER_BILLING_CONNECTORS',json.dumps([dict(tenant_id=TID,provider='azure',scope_id=SUB)]))


def test_billing_status_is_honest_and_scope_revocation_fails_closed(evidence,monkeypatch):
    _,store,_=evidence;repo=FocusRepository(store)
    monkeypatch.delenv('CLOUDSAVER_BILLING_CONNECTORS',raising=False)
    assert sync_status(workspace(),repo)['automatic_sync_enabled'] is False
    with pytest.raises(FocusError):sync_workspace_billing(workspace(),repo)
    configured(monkeypatch)
    assert sync_status(workspace(),repo)['configured']
    assert bindings(dict(workspace(),subscription_ids=[]))==[]
    monkeypatch.setenv('CLOUDSAVER_AUTO_BILLING_SYNC','false')
    assert sync_status(workspace(),repo)['automatic_sync_enabled'] is False
    with pytest.raises(FocusError):sync_workspace_billing(workspace(),repo)


def test_billing_snapshots_append_corrections_without_double_counting(evidence,monkeypatch):
    _,store,_=evidence;repo=FocusRepository(store);configured(monkeypatch)
    amount=['10']
    def reader(binding,tenant,start,end):
        return [dict(day=end-timedelta(days=1),currency='USD',billed=amount[0],effective=amount[0],resource_id=None,category='Usage')],'account',[]
    def run():return sync_workspace_billing(workspace(),repo,readers={'azure':reader})
    assert run()['inserted_records']==1
    assert run()['inserted_records']==0
    amount[0]='12';assert run()['inserted_records']==1
    amount[0]='10';assert run()['inserted_records']==1
    with store.transaction(TID) as db:
        rows=db.execute('SELECT billed_cost FROM focus_charges WHERE tenant_id=%s',(TID,)).fetchall()
    assert len(rows)==3 and sum(Decimal(str(r[0])) for r in rows)==10
    status=sync_status(workspace(),FocusRepository(store))
    assert status['last_synced_at'] and len(status['recent_syncs'])==4
    assert all(not r['payload']['coverage_verified'] for r in status['recent_syncs'])


def test_provider_errors_do_not_leak_or_claim_synced(evidence,monkeypatch):
    _,store,_=evidence;repo=FocusRepository(store);configured(monkeypatch)
    def fail(*args):raise RuntimeError('secret-token client-record')
    result=sync_workspace_billing(workspace(),repo,readers={'azure':fail})
    assert result['status']=='failed' and 'secret' not in json.dumps(result)
    assert sync_status(workspace(),repo)['last_synced_at'] is None
    with pytest.raises(FocusError):
        monkeypatch.setenv('CLOUDSAVER_BILLING_CONNECTORS','not-json');bindings(workspace())


def test_workflow_lease_and_tenant_history_are_durable(evidence):
    _,store,_=evidence;flows=WorkflowStore(store)
    run=flows.begin(TID,'agent_gitops_syncs','one',{})
    with pytest.raises(WorkflowConflict):flows.begin(TID,'agent_gitops_syncs','one',{},once=True)
    flows.finish(TID,'agent_gitops_syncs',run,'needs_reconciliation',{})
    with pytest.raises(WorkflowConflict):WorkflowStore(store).begin(TID,'agent_gitops_syncs','one',{},once=True)
    assert flows.rows(str(uuid4()),'agent_gitops_syncs')==[]


def paired(s,monkeypatch):
    target=dict(tenant_id=s.tenant['tenant_id'],target_id='infra',repository='example/infra',repository_id=123,base_branch='main',installation_id=456)
    monkeypatch.setenv('CLOUDSAVER_GITOPS_TARGETS',json.dumps([target]))
    monkeypatch.setenv('CLOUDSAVER_GITOPS_PUBLISH','true');monkeypatch.setenv('CLOUDSAVER_GITHUB_APP_ID','789')
    monkeypatch.setenv('CLOUDSAVER_GITHUB_APP_PRIVATE_KEY','test-key')
    git=dict(id='repo-sync',tenant_id=s.tenant['tenant_id'],scope_id=s.connector['scope_id'],provider='azure',kind='gitops_terraform',target_id='infra',operations=['gitops.terraform.sync'])
    monkeypatch.setenv('CLOUDSAVER_AGENT_CONNECTORS',json.dumps([s.connector,git]))
    s.worker['connector_ids'].append('repo-sync')
    monkeypatch.setenv('CLOUDSAVER_AGENT_WORKERS',json.dumps([s.worker]))
    response=create(s,connector_ids=['azure-tags','repo-sync']);assert response.status_code==201,response.text
    a=claim(s);r=worker(s,a,'draft');assert r.status_code==200,r.text
    return r.json(),target


def test_paired_plan_binds_target_and_rejects_fabricated_evidence(setup,monkeypatch):
    s=setup;task,target=paired(s,monkeypatch);catalog=connectors()
    assert task['payload']['plan']['steps'][-1]['operation']=='gitops.terraform.sync'
    preview=build_synchronized_agent_gitops_bundle(task,s.tenant,s.scan,GitOpsConfig.load(),catalog)
    assert preview['policy']['decision']=='review_required' and preview['parity_verified'] is False
    assert json.loads(preview['artifact']['hcl'])['resource']['azurerm_managed_disk']
    with pytest.raises(ValueError,match='approval'):
        build_synchronized_agent_gitops_bundle(task,s.tenant,s.scan,GitOpsConfig.load(),catalog,publish=True,store=s.repo.store)
    changed=deepcopy(target);changed['base_branch']='release'
    monkeypatch.setenv('CLOUDSAVER_GITOPS_TARGETS',json.dumps([changed]))
    assert program_hash(task,task['payload']['plan'],connectors())!=task['payload']['plan_hash']


def test_pair_publish_never_replays_uncertain_github_and_cancel_requires_reconciliation(setup,monkeypatch):
    s=setup;task,_=paired(s,monkeypatch);assert approve(s,task).status_code==200
    a=claim(s);ph=a['task']['payload']['plan_hash']
    for i in range(2):
        assert worker(s,a,f'steps/{i}/start',plan_hash=ph).status_code==200
        assert worker(s,a,f'steps/{i}/complete',plan_hash=ph,outcome=dict(status='succeeded',code='VERIFIED',evidence_digest=str(i+1)*64)).status_code==200
    task=s.repo.get(s.tenant,task['id'])
    cancelled=s.api.post('/api/v1/agents/tasks/'+task['id']+'/review',headers=s.headers,json=dict(version=task['version'],decision='cancel'))
    assert cancelled.status_code==200,cancelled.text
    assert cancelled.json()['state']=='needs_reconciliation'
    # Use a saved execution-shaped task to test the independent durable PR fence.
    task['state']='running';task['payload']['steps'][2]['state']='started'
    class BrokenGitHub:
        calls=0
        def publish(self,*args):self.calls+=1;raise RuntimeError('response lost')
    client=BrokenGitHub();kwargs=dict(publish=True,store=s.repo.store,client=client)
    task['payload']['steps'][0]['result']['evidence_digest']='f'*64
    with pytest.raises(ValueError,match='recorded'):
        build_synchronized_agent_gitops_bundle(task,s.tenant,s.scan,GitOpsConfig.load(),connectors(),**kwargs)
    assert client.calls==0
    task['payload']['steps'][0]['result']['evidence_digest']='1'*64
    with pytest.raises(GitOpsFailure):build_synchronized_agent_gitops_bundle(task,s.tenant,s.scan,GitOpsConfig.load(),connectors(),**kwargs)
    with pytest.raises(WorkflowConflict):build_synchronized_agent_gitops_bundle(task,s.tenant,s.scan,GitOpsConfig.load(),connectors(),**kwargs)
    assert client.calls==1
    journal=WorkflowStore(s.repo.store).rows(s.tenant['tenant_id'],'agent_gitops_syncs')[0]['payload']
    assert 'artifact' not in journal and 'CostCenter' not in json.dumps(journal)


def test_service_and_optimization_views_use_owned_observations(evidence):
    settings,_,scan=evidence;api=TestClient(create_app(settings,scanner=lambda *_:scan['findings']))
    response=api.get('/api/v1/services/disks',headers=AUTH)
    assert response.status_code==200,response.text
    assert response.json()['total']>0
    response=api.get('/api/v1/optimization/scans/'+scan['scan_id']+'/auto-scenarios',headers=AUTH)
    assert response.status_code==200,response.text
    assert response.json()['automatic_execution'] is False
    assert response.json()['engines']['topology']['status']=='insufficient_evidence'
    assert api.get('/api/v1/optimization/scans/'+str(uuid4())+'/auto-scenarios',headers=AUTH).status_code==404


def test_keyless_billing_readers_bind_exact_scopes_and_report_real_granularity(monkeypatch):
    from types import SimpleNamespace
    from datetime import date
    from app.collectors.billing_sync import azure_rows,aws_rows,gcp_rows
    from app import cloud_identity
    calls=[]
    class Credential:
        token='synthetic'
        def get_token(self,scope):assert scope=='https://management.azure.com/.default';return self
        def close(self):calls.append('closed')
        def refresh(self,request):pass
    monkeypatch.setattr(cloud_identity,'azure_credential',lambda tenant:Credential())
    def azure_post(url,token,body):
        assert '/subscriptions/'+SUB+'/' in url and token=='synthetic'
        return {'properties':{'columns':[{'name':n} for n in ('PreTaxCost','UsageDate','ResourceId','Currency')],'rows':[['2.50',20261001,None,'USD']]}}
    monkeypatch.setattr('app.collectors.billing_sync._post',azure_post)
    rows,grain,_=azure_rows(dict(scope_id=SUB),workspace(),date(2026,10,1),date(2026,10,2))
    assert rows[0]['billed']=='2.50' and grain=='resource' and calls==['closed']
    class CE:
        def get_cost_and_usage(self,**args):
            assert args['Filter']['Dimensions']['Values']==['123456789012']
            return {'ResultsByTime':[{'TimePeriod':{'Start':'2026-10-01'},'Groups':[{'Keys':['Usage'],'Metrics':{'UnblendedCost':{'Amount':'5','Unit':'USD'},'AmortizedCost':{'Amount':'4','Unit':'USD'}}}]}]}
        def close(self):calls.append('ce-closed')
    monkeypatch.setattr(cloud_identity,'aws_session',lambda *a,**kw:SimpleNamespace(client=lambda *a,**kw:CE()))
    tenant=dict(workspace(),aws_accounts=[dict(account_id='123456789012')])
    rows,grain,_=aws_rows(dict(scope_id='123456789012'),tenant,date(2026,10,1),date(2026,10,2))
    assert rows[0]['effective']=='4' and rows[0]['resource_id'] is None and grain=='account'
    monkeypatch.setattr(cloud_identity,'gcp_credentials',lambda *a,**kw:Credential())
    def bq_post(url,token,body):
        assert url.startswith('https://bigquery.googleapis.com/')
        assert 'project.id=@scope' in body['query'] and body['maximumBytesBilled']=='1000000000'
        return dict(jobComplete=True,totalRows='1',rows=[{'f':[{'v':v} for v in ['2026-10-01','USD','regular',None,'10','8']]}])
    monkeypatch.setattr('app.collectors.billing_sync._post',bq_post)
    tenant=dict(workspace(),gcp_projects=[dict(project_id='test-project')])
    rows,grain,_=gcp_rows(dict(scope_id='test-project',billing_project='billing-project',dataset='billing',table='export'),tenant,date(2026,10,1),date(2026,10,2))
    assert rows[0]['effective']=='8' and grain=='project' and rows[0]['resource_id'] is None
