"""Review workflow contracts, concurrency and isolation without a cloud connection."""
import copy
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.enterprise_store import EnterpriseStore
from app.store import Store, PostgresStore
from app.engineering.api import create_router
from app.engineering.contracts import WorkloadCreate, WorkloadUpdate
from app.engineering.repository import Engineering, EngineeringError
from app.engineering.readiness import metric_gate
from app.resource_assessment import resource_key
from tests.test_outcomes import financial_postgres  # noqa: F401

SUB='33333333-3333-4333-8333-333333333333'


@pytest.fixture(params=['sqlite','postgres'])
def engineering(tmp_path,request):
    url=request.getfixturevalue('financial_postgres') if request.param=='postgres' else None
    tenant=dict(tenant_id=str(uuid4()),name='Engineering test',subscription_ids=[SUB],user_id=str(uuid4()),roles=['TenantAdmin'])
    settings=SimpleNamespace(database_url=url,database=str(tmp_path/'engineering.db'))
    store=PostgresStore(url) if url else Store(settings.database)
    db=EnterpriseStore(settings)
    repo=Engineering(db)
    resource=dict(cloud_provider='azure',scope_id=SUB,subscription_id=SUB,resource_name='pilot-vm',
                  resource_id=f'/subscriptions/{SUB}/resourceGroups/qa/providers/Microsoft.Compute/virtualMachines/pilot',
                  resource_type='Microsoft.Compute/virtualMachines',region='eastus',evidence={'vm_size':'Standard_D4s_v5'})
    scan=dict(scan_id=str(uuid4()),timestamp=datetime.now(timezone.utc).isoformat(),mode='azure',status='completed',
              cloud_providers=['azure'],subscriptions_scanned=1,total_items_found=1,total_monthly_waste_usd=None,
              inventory=[resource],findings=[])
    store.save(tenant['tenant_id'],scan,workspace=tenant)
    app=FastAPI();app.include_router(create_router(db,lambda:tenant))
    return SimpleNamespace(tenant=tenant,db=db,repo=repo,api=TestClient(app),scan=scan,resource=resource,store=store)


def command(s,path,body,version=None,key=None,method='POST',status=201):
    headers={'Idempotency-Key':key or str(uuid4())}
    if version is not None:headers['If-Match']=f'"{version}"'
    response=s.api.request(method,'/api/v1/engineering'+path,json=body,headers=headers)
    assert response.status_code==status,response.text
    return response


def workload(s,key=None):
    return command(s,'/workloads',dict(name='Payments',environment='nonproduction',owner='Test owner',team='Engineering',scope_id=SUB),key=key).json()


def prepare(s):
    w=workload(s)
    member=command(s,f'/workloads/{w["id"]}/members',dict(scan_id=s.scan['scan_id'],resource_key=resource_key(s.resource)),1).json()
    plan=dict(member_id=member['id'],objective='Review a smaller compatible VM candidate',action='azure.vm.rightsize',candidate_sku='Standard_D2s_v5')
    return w,member,plan


def test_complete_review_and_version_history(engineering):
    s=engineering;w,member,body=prepare(s)
    key=str(uuid4());path=f'/workloads/{w["id"]}/plans'
    plan=command(s,path,body,2,key).json()
    assert command(s,path,body,2,key).json()==plan
    assert plan['state']=='evidence_required' and plan['execution_enabled'] is False
    readiness=plan['parameters']['readiness']
    assert readiness['financial_outcome']['reconciled_benefit'] is None
    assert next(c for c in readiness['checks'] if c['code']=='MEMORY_PERCENT_HISTORY')['status']=='unknown'
    with s.db.transaction(s.tenant['tenant_id']) as db:
        assert db.execute('SELECT count(*) FROM engineering_outbox').fetchone()[0]==3
        assert str(db.execute('SELECT scan_id FROM engineering_plan_targets').fetchone()[0])==s.scan['scan_id']
    command(s,f'/workloads/{w["id"]}',{'owner':'New owner'},2,method='PATCH',status=200)
    plans=s.api.get('/api/v1/engineering'+path).json()['items']
    assert plans[0]['latest']['context_changed'] is True
    revision=command(s,path+f'/{plan["plan_id"]}/versions',dict(body,parent_version=1,candidate_sku='Standard_D2as_v5'),3).json()
    assert revision['version']==2 and revision['identity_digest']!=plan['identity_digest']
    assert revision['context_changed'] is False
    versions=s.api.get('/api/v1/engineering/plans/'+plan['plan_id']+'/versions').json()['items']
    assert sorted(v['version'] for v in versions)==[1,2]
    assert next(v for v in versions if v['version']==1)['parameters']==plan['parameters']
    command(s,path+f'/{plan["plan_id"]}/versions',dict(body,parent_version=1),3,status=409)


def test_idempotency_is_principal_operation_and_scope_bound(engineering):
    s=engineering;key=str(uuid4());w=workload(s,key)
    assert workload(s,key)==w
    command(s,'/workloads',dict(name='Different',environment='dev',owner='Owner',team='Team',scope_id=SUB),key=key,status=409)
    original=s.tenant['user_id'];s.tenant['user_id']=str(uuid4())
    assert workload(s,key)['id']!=w['id']
    s.tenant['user_id']=original
    s.tenant['subscription_ids']=[]
    command(s,'/workloads',dict(name='Payments',environment='nonproduction',owner='Test owner',team='Engineering',scope_id=SUB),key=key,status=404)


def test_tenant_scope_and_role_checks(engineering):
    s=engineering;w=workload(s)
    for change in ({'tenant_id':str(uuid4())},{'allowed_providers':['aws']},{'scope_restrictions':{'azure':[]}}, {'subscription_ids':[], 'scope_restrictions':{'azure':[SUB]}}):
        restricted=dict(s.tenant,**change)
        assert s.repo.workloads(restricted)['items']==[]
        with pytest.raises(EngineeringError,match='not found'):
            s.repo.detail(restricted,w['id'])
    s.tenant['roles']=['Viewer']
    assert s.api.get('/api/v1/engineering/workloads').status_code==200
    command(s,f'/workloads/{w["id"]}',{'owner':'Different'},1,method='PATCH',status=403)


def test_cursor_tampering_and_authorization_change(engineering):
    s=engineering
    for _ in range(3):workload(s)
    first=s.repo.workloads(s.tenant,1)
    second=s.repo.workloads(s.tenant,1,first['next_cursor'])
    assert first['items'][0]['id']!=second['items'][0]['id']
    for cursor,tenant,limit in ((first['next_cursor']+'x',s.tenant,1),(first['next_cursor'],dict(s.tenant,user_id=str(uuid4())),1),(first['next_cursor'],s.tenant,2)):
        with pytest.raises(EngineeringError,match='Cursor'):
            s.repo.workloads(tenant,limit,cursor)


def test_preconditions_and_untrusted_fields(engineering):
    s=engineering;w=workload(s)
    command(s,f'/workloads/{w["id"]}',{'owner':'Changed'},method='PATCH',status=428)
    command(s,f'/workloads/{w["id"]}',{'owner':'Changed'},9,method='PATCH',status=412)
    command(s,f'/workloads/{w["id"]}',{'verified_human':True},1,method='PATCH',status=422)
    assert s.api.post('/api/v1/engineering/workloads',json={}).status_code==422
    assert s.api.get('/api/v1/engineering/workloads?limit=201').status_code==422
    assert s.api.post('/api/v1/engineering/executions',json={}).status_code==404


def test_concurrent_update_and_atomic_rollback(engineering,monkeypatch):
    s=engineering;w=workload(s)
    def update(_):
        try:return s.repo.update(s.tenant,w['id'],WorkloadUpdate(owner='Changed'),str(uuid4()),1)['version']
        except EngineeringError as e:return e.status
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(update,range(2)))==[2,412]
    def fail(*args,**kwargs):raise RuntimeError('transaction rollback probe')
    monkeypatch.setattr(s.repo,'_event',fail)
    with pytest.raises(RuntimeError):
        s.repo.update(s.tenant,w['id'],WorkloadUpdate(owner='Must roll back'),str(uuid4()),2)
    assert s.repo.detail(s.tenant,w['id'])['owner']=='Changed'


def test_new_observation_revision_is_fk_bound(engineering):
    s=engineering;w,m,body=prepare(s)
    path=f'/workloads/{w["id"]}/plans'
    before=command(s,path,body,2).json()
    scan=copy.deepcopy(s.scan);scan['scan_id']=str(uuid4());scan['inventory'][0]['evidence']['management_locks']=['test-lock']
    s.store.save(s.tenant['tenant_id'],scan,workspace=s.tenant)
    after=command(s,path+f'/{before["plan_id"]}/versions',dict(body,parent_version=1,scan_id=scan['scan_id']),2).json()
    assert after['parameters']['readiness']['decision']=='blocked'
    assert after['parameters']['readiness']['evidence_digest']!=before['parameters']['readiness']['evidence_digest']
    command(s,path,dict(body,scan_id=str(uuid4())),2,status=404)


def test_metric_evidence_uses_samples_and_preserves_gaps():
    now=datetime.now(timezone.utc);start=now-timedelta(days=14)
    points=[dict(at=(start+timedelta(minutes=5*i)).isoformat(),value=20) for i in range(1,4033)]
    series=dict(window_start=start.isoformat(),window_end=now.isoformat(),points=points)
    evidence={'metrics':{'memory_percent':series},'metric_summaries':{'memory_percent':{'coverage_ratio':1,'p95':1}}}
    assert metric_gate(evidence,'memory_percent',now)['status']=='pass'
    series['points']=[]
    assert metric_gate(evidence,'memory_percent',now)['status']=='unknown'
    for malformed in ([],None,'invalid',{'points':None}):
        assert metric_gate({'metrics':{'memory_percent':malformed}},'memory_percent',now)['status']=='unknown'


def test_foreign_tenant_links_are_rejected_by_database(engineering):
    s=engineering;w,m,body=prepare(s)
    foreign=str(uuid4())
    with pytest.raises(Exception) as caught:
        with s.db.transaction(foreign,write=True) as db:
            db.execute('INSERT INTO engineering_members(tenant_id,id,workload_id,scan_id,resource_key,resource_id,resource_type,resource_name,evidence_digest,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                       (foreign,str(uuid4()),w['id'],s.scan['scan_id'],'a'*64,'id','type','name','b'*64,datetime.now(timezone.utc).isoformat()))
    assert 'foreign key' in str(caught.value).lower()


def test_postgres_rls_and_immutable_history(engineering):
    s=engineering
    if not s.db.url:pytest.skip('PostgreSQL runtime privilege check')
    import psycopg
    from app.engineering.schema import TABLES
    w=workload(s)
    with s.db.transaction(s.tenant['tenant_id']) as db:
        for table in TABLES:
            assert db.execute('SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid=to_regclass(%s)',(table,)).fetchone()==(True,True)
    with psycopg.connect(s.db.url) as db:
        assert db.execute('SELECT count(*) FROM engineering_workloads').fetchone()[0]==0
        with db.transaction():
            db.execute("SELECT set_config('app.current_tenant_id',%s,true)",(s.tenant['tenant_id'],))
            assert db.execute('SELECT count(*) FROM engineering_workloads').fetchone()[0]==1
        # psycopg's outer implicit transaction above keeps a nested transaction
        # local setting until commit; explicitly finish before pool reuse.
        db.commit()
        assert db.execute('SELECT count(*) FROM engineering_workloads').fetchone()[0]==0
        db.commit()
        with db.transaction():
            db.execute("SELECT set_config('app.current_tenant_id',%s,true)",(str(uuid4()),))
            assert db.execute('SELECT count(*) FROM engineering_workloads').fetchone()[0]==0
    for table in ('engineering_events','engineering_members','engineering_commands','engineering_plan_targets'):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with s.db.transaction(s.tenant['tenant_id']) as db:
                db.execute(f'DELETE FROM {table} WHERE false')


def test_gateway_preserves_preconditions_status_and_response_headers(engineering):
    import asyncio
    import httpx
    from services.engineering_routes import register
    s=engineering
    core=FastAPI();core.include_router(create_router(s.db,lambda:s.tenant))
    app=FastAPI();register(app,lambda:s.tenant,{'scanner':'http://core'},httpx.ASGITransport(app=core))
    gateway=TestClient(app)
    body=dict(name='Gateway workload',environment='dev',owner='Owner',team='Team',scope_id=SUB)
    response=gateway.post('/api/v1/engineering/workloads',json=body,headers={'Authorization':'Bearer test','Idempotency-Key':str(uuid4())})
    assert response.status_code==201,response.text
    assert response.headers['etag']=='"1"'
    path=response.headers['location']
    response=gateway.patch(path,json={'owner':'Other'},headers={'Authorization':'Bearer test','Idempotency-Key':str(uuid4())})
    assert response.status_code==428
    response=gateway.patch(path,json={'owner':'Other'},headers={'Authorization':'Bearer test','Idempotency-Key':str(uuid4()),'If-Match':'"2"'})
    assert response.status_code==412


def test_openapi_describes_strict_commands_and_responses(engineering):
    schema=engineering.api.get('/openapi.json').json()
    op=schema['paths']['/api/v1/engineering/workloads']['post']
    assert op['requestBody']['content']['application/json']['schema']['additionalProperties'] is False
    assert op['responses']['201']['content']['application/json']['schema']['$ref'].endswith('/Workload')
