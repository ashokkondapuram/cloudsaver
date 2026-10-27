from datetime import date,datetime,timedelta,timezone
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from app.billing_jobs import BillingJobs
from app.collectors import billing_sync,commitments
from app.main import create_app
from tests.test_billing_jobs import config,reader
from tests.test_enterprise import evidence,workspace,TID,SUB,AUTH

START,END=date(2026,10,1),date(2026,10,3)


class Credential:
    token='placeholder-token'
    def get_token(self,*_):return self
    def refresh(self,*_):pass
    def close(self):pass


def test_azure_merges_actual_and_amortized_cost_across_pages(monkeypatch):
    calls=[]
    def post(url,token,body,scope_id=None):
        calls.append((url,body['type']))
        rows={'ActualCost':[[20261001,'/sub/r1','USD','12.5']],'AmortizedCost':[[20261001,'/sub/r1','USD','8.25']]}[body['type']]
        nxt='https://management.azure.com/next' if url.endswith('2023-11-01') else None
        return {'properties':{'columns':[{'name':'UsageDate'},{'name':'ResourceId'},{'name':'Currency'},{'name':'PreTaxCost'}],'rows':rows,'nextLink':nxt}}
    monkeypatch.setattr(billing_sync,'_post',post)
    monkeypatch.setattr('app.cloud_identity.azure_credential',lambda tenant:Credential())
    rows,granularity,_=billing_sync.azure_rows(dict(provider='azure',scope_id=SUB),workspace(),START,END)
    assert granularity=='resource' and len(calls)==4
    assert rows==[dict(day=date(2026,10,1),resource_id='/sub/r1',currency='USD',billed='25.0',effective='16.50',category='Usage')]


def test_azure_pagination_rejects_foreign_hosts(monkeypatch):
    monkeypatch.setattr(billing_sync,'_post',lambda *_:{'properties':{'columns':[],'rows':[],'nextLink':'https://attacker.example/next'}})
    with pytest.raises(ValueError,match='pagination host'):billing_sync._azure_query('https://management.azure.com/q',Credential(),'ActualCost',START,END,SUB)


class Athena:
    def __init__(self,states):self.states,self.stopped,self.started=list(states),False,None
    def start_query_execution(self,**args):self.started=args;return {'QueryExecutionId':'q1'}
    def get_query_execution(self,**_):return {'QueryExecution':{'Status':{'State':self.states.pop(0) if self.states else 'RUNNING'}}}
    def stop_query_execution(self,**_):self.stopped=True
    def get_query_results(self,**args):
        cell=lambda *values:{'Data':[{'VarCharValue':v} for v in values]}
        if 'NextToken' not in args:return {'ResultSet':{'Rows':[cell('day','id','cur','type','b','e'),cell('2026-10-01','i-1','USD','DiscountedUsage','0','3.5')]},'NextToken':'n'}
        return {'ResultSet':{'Rows':[cell('2026-10-02','','USD','RIFee','40','1.2'),cell('2026-10-02','i-2','USD','Usage','0','0')]}}


class Session:
    def __init__(self,client):self.athena=client
    def client(self,name,**_):return self.athena


ATHENA=dict(provider='aws',scope_id='123456789012',athena_region='us-east-1',athena_workgroup='primary',athena_database='cur',athena_table='data')


def test_athena_reads_cur_per_resource_with_bound_parameters():
    pytest.importorskip('botocore')
    client=Athena(['RUNNING','SUCCEEDED'])
    rows=billing_sync.athena_rows(Session(client),ATHENA,START,END,sleep=lambda _:None)
    assert client.started['ExecutionParameters'][0]=="'123456789012'" and '123456789012' not in client.started['QueryString']
    assert [(r['resource_id'],r['billed'],r['effective'],r['category']) for r in rows]==[('i-1','0','3.5','Usage'),(None,'40','1.2','Purchase')]


def test_athena_stops_queries_that_exceed_the_bounded_wait():
    pytest.importorskip('botocore')
    client=Athena([])
    with pytest.raises(ValueError,match='bounded wait'):billing_sync.athena_rows(Session(client),ATHENA,START,END,sleep=lambda _:None,max_wait_seconds=3)
    assert client.stopped


def test_connector_validation_rejects_partial_athena_and_misapplied_export_type(monkeypatch):
    tenant=dict(workspace(),aws_accounts=[{'account_id':'123456789012'}])
    for binding in (dict(tenant_id=TID,provider='aws',scope_id='123456789012',athena_table='data'),
                    dict(tenant_id=TID,provider='azure',scope_id=SUB,export_type='detailed')):
        monkeypatch.setenv('CLOUDSAVER_BILLING_CONNECTORS',__import__('json').dumps([binding]))
        with pytest.raises(Exception):billing_sync.bindings(tenant)


def test_gcp_detailed_export_returns_resource_rows(monkeypatch):
    seen={}
    def post(url,token,body,scope_id=None):
        seen.update(body)
        return {'jobComplete':True,'totalRows':'1','rows':[{'f':[{'v':'2026-10-01'},{'v':'USD'},{'v':'regular'},{'v':'//compute/vm-1'},{'v':'4'},{'v':'3'}]}]}
    monkeypatch.setattr(billing_sync,'_post',post)
    monkeypatch.setattr('app.cloud_identity.gcp_credentials',lambda *a,**k:Credential())
    tenant=dict(workspace(),gcp_projects=[{'project_id':'proj-1'}])
    rows,granularity,_=billing_sync.gcp_rows(dict(provider='gcp',scope_id='proj-1',billing_project='bp',dataset='ds',table='t',export_type='detailed'),tenant,START,END)
    assert granularity=='resource' and rows[0]['resource_id']=='//compute/vm-1' and 'resource.global_name' in seen['query']


def test_commitment_normalization_and_summary():
    soon=(datetime.now(timezone.utc)+timedelta(days=30)).isoformat()
    items=[commitments.commitment(provider='aws',kind='reservation',utilization_percent=80,unused_amount='10.5',currency='USD',end=soon,status='active'),
           commitments.commitment(provider='aws',kind='savings_plan',utilization_percent='60',unused_amount='4.5',currency='USD',end='2030-01-01T00:00:00Z'),
           commitments.commitment(provider='azure',kind='reservation',status='Expired',utilization_percent='5')]
    assert items[0]['utilization_percent']=='80'
    assert commitments.summarize(items)==dict(active=2,total=3,expiring_90_days=1,average_utilization_percent='70.0',unused_commitment_cost={'USD':'15.0'})
    with pytest.raises(ValueError):commitments.commitment(unused_amount='NaN')


class CostExplorer:
    def get_reservation_utilization(self,**args):
        assert args['Filter']['Dimensions']['Values']==['123456789012']
        return {'UtilizationsByTime':[{'Groups':[{'Value':'ri-1','Attributes':{'instanceType':'m5.large','region':'us-east-1'},
            'Utilization':{'UtilizationPercentage':'75','UnusedHours':'25','PurchasedHours':'100','TotalAmortizedFee':'40','NetRISavings':'12'}}]}]}
    def get_savings_plans_utilization_details(self,**_):
        return {'SavingsPlansUtilizationDetails':[{'SavingsPlanArn':'arn:sp','Attributes':{'SavingsPlansType':'ComputeSavingsPlans'},
            'Utilization':{'UtilizationPercentage':'90','TotalCommitment':'100','UnusedCommitment':'10'},'Savings':{'NetSavings':'20'}}]}
    def get_reservation_coverage(self,**_):return {'Total':{'CoverageHours':{'CoverageHoursPercentage':'55'}}}
    def get_savings_plans_coverage(self,**_):return {'SavingsPlansCoverages':[{'Coverage':{'SpendCoveredBySavingsPlans':'30','TotalCost':'120'}}]}


def test_aws_commitments_read_utilization_unused_cost_and_coverage():
    items,coverage,warnings=commitments.aws_commitments(dict(provider='aws',scope_id='123456789012'),workspace(),START,END,client=CostExplorer())
    assert [(i['kind'],i['utilization_percent'],i['unused_amount']) for i in items]==[('reservation','75','10.00'),('savings_plan','90','10')]
    assert coverage=={'reservation_hours_percent':'55','savings_plan_spend_percent':'25.00'} and warnings==[]


def test_azure_commitments_filter_to_the_bound_subscription(monkeypatch):
    other=str(uuid4())
    pages={'Microsoft.Capacity':{'value':[
        {'id':'r1','sku':{'name':'Standard_D2s_v5'},'location':'eastus','properties':{'appliedScopeType':'Single','appliedScopes':[f'/subscriptions/{SUB}'],'term':'P1Y',
            'utilization':{'aggregates':[{'grain':'1','grainUnit':'days','value':50},{'grain':'30','grainUnit':'days','value':88}]}}},
        {'id':'r2','properties':{'appliedScopeType':'Single','appliedScopes':[f'/subscriptions/{other}']}}]}}
    def get(url,token,params=None):
        if 'BillingBenefits' in url:
            import httpx
            raise httpx.HTTPStatusError('forbidden',request=httpx.Request('GET',url),response=httpx.Response(403))
        return pages['Microsoft.Capacity']
    monkeypatch.setattr(commitments,'_get',get)
    monkeypatch.setattr('app.cloud_identity.azure_credential',lambda tenant:Credential())
    items,_,warnings=commitments.azure_commitments(dict(provider='azure',scope_id=SUB),workspace(),START,END)
    assert [(i['commitment_id'],i['utilization_percent'],i['utilization_window_days']) for i in items]==[('r1','88',30)]
    assert any('Savings plan Reader' in w for w in warnings)


def test_worker_stores_commitments_and_api_requires_finance_access(evidence,monkeypatch):
    settings,store,_=evidence;config(monkeypatch)
    item=commitments.commitment(provider='azure',scope_id=SUB,commitment_id='r1',kind='reservation',utilization_percent='70',unused_amount='3',currency='USD')
    jobs=BillingJobs(store);jobs.submit(workspace(),str(uuid4()))
    jobs.execute_scope(workspace(),jobs.claim(TID),readers={'azure':reader},commitment_readers={'azure':lambda *_:([item],{},['Shared scope'])})
    body=TestClient(create_app(settings)).get('/api/v1/finops/commitments',headers=AUTH).json()
    assert body['items'][0]['commitment_id']=='r1' and body['summary']['average_utilization_percent']=='70.0'
    assert body['scopes'][0]['status']=='completed' and body['scopes'][0]['warnings']==['Shared scope']
    # A failing commitment source never fails the billed-cost import and never stores provider error text.
    jobs.submit(workspace(),str(uuid4()))
    def broken(*_):raise RuntimeError('secret response body')
    jobs.execute_scope(workspace(),jobs.claim(TID),readers={'azure':reader},commitment_readers={'azure':broken})
    body=TestClient(create_app(settings)).get('/api/v1/finops/commitments',headers=AUTH).json()
    assert body['scopes'][0]['status']=='failed' and 'secret' not in str(body) and body['items']==[]


def test_injected_billing_readers_skip_live_commitment_reads(evidence,monkeypatch):
    _,store,_=evidence;config(monkeypatch)
    monkeypatch.setattr(commitments,'READERS',{'azure':lambda *_:pytest.fail('Tests must not call providers')})
    jobs=BillingJobs(store);jobs.submit(workspace(),str(uuid4()))
    jobs.execute_scope(workspace(),jobs.claim(TID),readers={'azure':reader})


def test_viewer_cannot_read_commitments(evidence,monkeypatch):
    from app.auth import Role,UserClaims
    settings,_,_=evidence
    monkeypatch.setenv('CLOUDSAVER_AUTH_MODE','entra')
    class Validator:
        def verify_token(self,token):return UserClaims(user_id=str(uuid4()),tenant_id=TID,roles=[Role.VIEWER])
    with TestClient(create_app(settings,identity_validator=Validator())) as client:
        assert client.get('/api/v1/finops/commitments',headers=AUTH).status_code==403
