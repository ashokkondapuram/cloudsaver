"""Real API approval/lease boundaries with synthetic AI and no provider mutation."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
from uuid import uuid4
import hashlib,json,sqlite3

import pytest
from fastapi.testclient import TestClient
from fastapi import HTTPException
from app.agent_contract import connectors,program_hash,render_code,validate_plan
from app.agent_store import AgentConflict,AgentRepository
from app.auth import Role,UserClaims
from app.config import Settings
from app.enterprise_store import EnterpriseStore
from app.store import Store
from services.agent_gateway import create_app


@pytest.fixture
def setup(tmp_path,monkeypatch):
    monkeypatch.setenv('CLOUDSAVER_AUTH_MODE','entra');monkeypatch.setenv('CLOUDSAVER_KEY_VERIFIER','local')
    monkeypatch.setenv('CLOUDSAVER_AGENT_ENABLED','true')
    from pathlib import Path
    monkeypatch.setenv('CLOUDSAVER_AI_PLATFORM_POLICY',(Path(__file__).resolve().parents[1]/'platform/contracts/fixtures/ai-policy-v1.json').read_text())
    tid,sid=str(uuid4()),str(uuid4());now=[datetime.now(timezone.utc)]
    tenant=dict(tenant_id=tid,subscription_ids=[sid],name='Agent QA',plan_tier='ENTERPRISE')
    settings=Settings('azure',str(tmp_path/'agents.sqlite3'),(tenant,));store=Store(settings.database)
    resource=dict(cloud_provider='azure',subscription_id=sid,scope_id=sid,resource_id=f'/subscriptions/{sid}/resourceGroups/rg/providers/Microsoft.Compute/disks/qa',resource_name='qa',resource_type='Microsoft.Compute/disks')
    scan=dict(scan_id=str(uuid4()),timestamp=now[0].isoformat(),status='completed',mode='azure',cloud_providers=['azure'],subscriptions_scanned=1,total_items_found=1,total_monthly_waste_usd=None,inventory=[resource],findings=[])
    store.save(tid,scan,workspace=tenant)
    connector=dict(id='azure-tags',tenant_id=tid,scope_id=sid,provider='azure',kind='azure_arm',operations=['resource.inspect','tags.merge'])
    monkeypatch.setenv('CLOUDSAVER_AGENT_CONNECTORS',json.dumps([connector]))
    token='synthetic-worker-token-'+('x'*32)
    worker=dict(id='worker-a',token_sha256=hashlib.sha256(token.encode()).hexdigest(),tenant_ids=[tid],connector_ids=['azure-tags'])
    monkeypatch.setenv('CLOUDSAVER_AGENT_WORKERS',json.dumps([worker]))
    plan=dict(summary='Inspect tags, then apply the explicitly requested cost center.',steps=[
        dict(connector_id='azure-tags',operation='resource.inspect',arguments={},purpose='Read current tags',verification='Provider returns current tags',rollback='Read-only'),
        dict(connector_id='azure-tags',operation='tags.merge',arguments={'tags':{'CostCenter':'FINOPS-42'}},purpose='Apply cost allocation tag',verification='Read back the exact value',rollback='Review previous value before an independently approved reversal')])
    class Validator:
        def verify_token(self,value):
            if value not in {'admin','viewer'}: raise HTTPException(401,'Invalid human credential')
            return UserClaims(user_id=str(uuid4()),tenant_id=tid,roles=[Role.VIEWER if value=='viewer' else Role.TENANT_ADMIN])
    repo=AgentRepository(EnterpriseStore(settings),lambda:now[0])
    app=TestClient(create_app(settings,Validator(),planner=lambda *_:plan,repository=repo))
    return SimpleNamespace(api=app,repo=repo,tenant=tenant,scan=scan,resource=resource,connector=connector,worker=worker,plan=plan,
        headers={'Authorization':'Bearer admin'},worker_headers={'Authorization':'Bearer '+token},now=now,settings=settings)


def create(s,**changes):
    body=dict(scan_id=s.scan['scan_id'],resource_id=s.resource['resource_id'],request_key=str(uuid4()),intent='Set CostCenter to FINOPS-42 after inspecting tags.',target_id='approved-model',connector_ids=['azure-tags'])
    body.update(changes)
    return s.api.post('/api/v1/agents/tasks',headers=s.headers,json=body)


def claim(s):
    r=s.api.post('/internal/v1/agent/claim',headers=s.worker_headers,json={'tenant_id':s.tenant['tenant_id']})
    assert r.status_code==200,r.text
    return r.json()['assignment']


def worker(s,a,path,**extra):
    return s.api.post('/internal/v1/agent/tasks/'+a['task']['id']+'/'+path,headers=s.worker_headers,
        json=dict(tenant_id=s.tenant['tenant_id'],lease_token=a['lease_token'],**extra))


def drafted(s):
    r=create(s);assert r.status_code==201,r.text
    a=claim(s);assert a['phase']=='draft'
    result=worker(s,a,'draft');assert result.status_code==200,result.text
    return result.json()


def approve(s,task,**changes):
    return s.api.post('/api/v1/agents/tasks/'+task['id']+'/review',headers=s.headers,
        json={**dict(version=task['version'],decision='approve',plan_hash=task['payload']['plan_hash']),**changes})


def executing(s):
    task=drafted(s);r=approve(s,task);assert r.status_code==200,r.text
    a=claim(s);assert a['phase']=='execute';return a


def test_worker_cannot_execute_or_approve_an_ai_draft(setup):
    s=setup;task=drafted(s)
    assert task['state']=='awaiting_approval' and task['payload']['approval'] is None
    assert 'lease' not in task['payload'] and claim(s) is None
    assert s.api.post('/api/v1/agents/tasks/'+task['id']+'/review',headers=s.worker_headers,json=dict(version=task['version'],decision='approve',plan_hash=task['payload']['plan_hash'])).status_code==401
    # Even a retained drafting lease cannot start a connector action.
    with s.repo.store.transaction(s.tenant['tenant_id']) as db:
        raw=s.repo._row(db,s.tenant['tenant_id'],task['id'])
    assert raw['payload']['lease']['token_hash'] and 'token' not in raw['payload']['lease']


def test_version_and_hash_are_required_and_viewers_cannot_review(setup):
    s=setup;task=drafted(s)
    assert approve(s,task,plan_hash='0'*64).status_code==409
    viewer={'Authorization':'Bearer viewer'}
    assert s.api.get('/api/v1/agents/tasks',headers=viewer).status_code==200
    assert s.api.post('/api/v1/agents/tasks/'+task['id']+'/review',headers=viewer,json={'version':task['version'],'decision':'approve','plan_hash':task['payload']['plan_hash']}).status_code==403
    assert approve(s,task).status_code==200
    assert approve(s,task).status_code==409


def test_ordered_single_use_steps_and_verified_tag_completion(setup):
    s=setup;a=executing(s);ph=a['task']['payload']['plan_hash']
    assert a['code']==render_code(s.plan)
    assert worker(s,a,'steps/1/start',plan_hash=ph).status_code==409
    for index in range(2):
        assert worker(s,a,f'steps/{index}/start',plan_hash=ph).json()['permitted'] is True
        assert worker(s,a,f'steps/{index}/start',plan_hash=ph).status_code==409
        r=worker(s,a,f'steps/{index}/complete',plan_hash=ph,outcome={'status':'succeeded','code':'TAGS_VERIFIED'})
        assert r.status_code==200,r.text
    assert r.json()['state']=='succeeded'
    assert worker(s,a,'steps/1/complete',plan_hash=ph,outcome={'status':'succeeded','code':'DUPLICATE'}).status_code==409


def test_uncertain_write_is_never_requeued_or_redrafted(setup):
    s=setup;a=executing(s);ph=a['task']['payload']['plan_hash']
    for i in range(2):
        assert worker(s,a,f'steps/{i}/start',plan_hash=ph).status_code==200
        r=worker(s,a,f'steps/{i}/complete',plan_hash=ph,outcome={'status':'succeeded' if i==0 else 'uncertain','code':'SYNTHETIC_RESULT'})
    assert r.json()['state']=='needs_reconciliation' and claim(s) is None
    task=r.json()
    assert s.api.post('/api/v1/agents/tasks/'+task['id']+'/review',headers=s.headers,json={'version':task['version'],'decision':'redraft'}).status_code==409


def test_crash_after_permit_and_approval_expiration_fence_execution(setup):
    s=setup;a=executing(s);ph=a['task']['payload']['plan_hash']
    assert worker(s,a,'steps/0/start',plan_hash=ph).status_code==200
    s.now[0]+=timedelta(seconds=121)
    assert claim(s) is None
    assert s.repo.get(s.tenant,a['task']['id'])['state']=='needs_reconciliation'


def test_approval_ttl_and_connector_grant_changes_block_dispatch(setup,monkeypatch):
    s=setup;task=drafted(s);assert approve(s,task,expires_in_minutes=1).status_code==200
    s.now[0]+=timedelta(minutes=2)
    assert claim(s) is None
    assert s.repo.get(s.tenant,task['id'])['state']=='approval_expired'
    task=drafted(s);assert approve(s,task).status_code==200
    monkeypatch.setenv('CLOUDSAVER_AGENT_CONNECTORS',json.dumps([dict(s.connector,operations=['resource.inspect'])]))
    assert claim(s) is None and s.repo.get(s.tenant,task['id'])['state']=='approval_expired'


def test_cancellation_stops_new_permits_and_preserves_inflight_outcome(setup):
    s=setup;a=executing(s);ph=a['task']['payload']['plan_hash']
    assert worker(s,a,'steps/0/start',plan_hash=ph).status_code==200
    task=s.repo.get(s.tenant,a['task']['id'])
    r=s.api.post('/api/v1/agents/tasks/'+task['id']+'/review',headers=s.headers,json={'version':task['version'],'decision':'cancel'})
    assert r.json()['state']=='cancel_requested'
    assert worker(s,a,'steps/1/start',plan_hash=ph).status_code==409
    r=worker(s,a,'steps/0/complete',plan_hash=ph,outcome={'status':'succeeded','code':'READ_COMPLETE'})
    assert r.json()['state']=='cancelled'


def test_connector_scope_tenant_and_worker_auth_are_isolated(setup):
    s=setup;task=create(s).json()
    assert create(s,connector_ids=['other-tenant']).status_code==403
    assert s.api.post('/internal/v1/agent/claim',headers=s.headers,json={'tenant_id':s.tenant['tenant_id']}).status_code==401
    assert s.api.post('/internal/v1/agent/claim',headers=s.worker_headers,json={'tenant_id':str(uuid4())}).status_code==403
    assert s.repo.get(dict(s.tenant,tenant_id=str(uuid4())),task['id']) is None
    assert s.repo.get(dict(s.tenant,scope_restrictions={'azure':[str(uuid4())]}),task['id']) is None
    assert s.repo.get(dict(s.tenant,subscription_ids=[]),task['id']) is None


def test_plan_validation_disallows_code_urls_extra_arguments_and_multiple_writes(setup):
    s=setup;task=create(s).json();catalog=connectors()
    with pytest.raises(ValueError):validate_plan(dict(s.plan,code='process.env'),task,catalog)
    bad=json.loads(json.dumps(s.plan));bad['steps'][1]['arguments']['url']='https://attacker.invalid'
    with pytest.raises(ValueError):validate_plan(bad,task,catalog)
    with pytest.raises(ValueError):validate_plan(dict(s.plan,steps=s.plan['steps']*2),task,catalog)
    assert program_hash(task,s.plan,catalog)==program_hash(task,s.plan,catalog)


def test_idempotency_concurrent_claims_and_immutable_audit(setup):
    s=setup;key=str(uuid4());first=create(s,request_key=key)
    assert create(s,request_key=key).json()['id']==first.json()['id']
    assert create(s,request_key=key,intent='A different task instruction').status_code==409
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:s.repo.claim(s.tenant,s.worker,connectors()),range(2)))
    assert sum(r is not None for r in results)==1
    with sqlite3.connect(s.settings.database) as db:
        with pytest.raises(sqlite3.IntegrityError):db.execute('DELETE FROM agent_task_events')


def test_disabled_execution_never_issues_worker_assignment(setup,monkeypatch):
    s=setup;create(s);monkeypatch.setenv('CLOUDSAVER_AGENT_ENABLED','false')
    assert s.api.post('/internal/v1/agent/claim',headers=s.worker_headers,json={'tenant_id':s.tenant['tenant_id']}).status_code==503
    assert create(s).status_code==503
    assert s.api.get('/api/v1/agents/catalog',headers=s.headers).json()['enabled'] is False


def test_expired_inflight_assignment_is_visible_as_uncertain_without_another_worker(setup):
    s=setup;a=executing(s)
    assert worker(s,a,'steps/0/start',plan_hash=a['task']['payload']['plan_hash']).status_code==200
    s.now[0]+=timedelta(seconds=121)
    result=s.api.get('/api/v1/agents/tasks/'+a['task']['id'],headers=s.headers)
    assert result.json()['state']=='needs_reconciliation'
    assert result.json()['events'][-1]['action']=='lease_expired'


def test_typescript_program_consumes_real_gateway_step_permits(setup):
    """Cross-language execution: Python approval/queue -> real Node runCode -> durable API results."""
    import http.server,shutil,subprocess,threading
    from pathlib import Path
    node=shutil.which('node')
    if not node: pytest.skip('Node 24 is required for the TypeScript cross-language acceptance test')
    s=setup;a=executing(s)
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self,*_args): pass
        def do_POST(self):
            size=int(self.headers.get('Content-Length','0'))
            assert 0<size<32000
            response=s.api.post(self.path,headers={'Authorization':self.headers.get('Authorization','')},json=json.loads(self.rfile.read(size)))
            self.send_response(response.status_code);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(response.content)
    server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    code='''import {runCode} from './src/runtime.ts';
let input='';for await(const chunk of process.stdin)input+=chunk;
const x=JSON.parse(input);let calls=0;
await runCode(x.assignment,x.assignment.connectors,async(path,body)=>{
  const r=await fetch(x.origin+path,{method:'POST',headers:{'Content-Type':'application/json',Authorization:x.authorization},body:JSON.stringify(body)});
  if(!r.ok)throw new Error('Gateway rejected step '+r.status);return r.json();
},async()=>{calls++;return {status:'succeeded',code:'SYNTHETIC_CONNECTOR_VERIFIED'};});
console.log(JSON.stringify({calls}));'''
    try:
        result=subprocess.run([node,'--input-type=module','-e',code],cwd=Path(__file__).resolve().parents[1]/'agent-worker',
            input=json.dumps(dict(assignment=a,origin='http://127.0.0.1:'+str(server.server_port),authorization=s.worker_headers['Authorization'])),text=True,capture_output=True,timeout=20)
        assert result.returncode==0,result.stderr
        assert json.loads(result.stdout)['calls']==2
    finally:server.shutdown();server.server_close();thread.join(timeout=2)
    assert s.repo.get(s.tenant,a['task']['id'])['state']=='succeeded'


def test_agent_planner_uses_existing_token_budget_and_excludes_resource_identifiers(setup):
    from app.agent_planner import AgentPlanner
    from app.ai_advisory import InferenceResult
    s=setup;task=create(s).json();seen={}
    class Target:
        max_context_bytes=16000;provider='azure';model='approved';target_id='approved-model'
        def model_dump(self,**_kwargs):return {'target_id':self.target_id}
    class Budget:
        durable=True
        def run(self,*args,**kwargs):seen['budget_args']=args;seen['budget_options']=kwargs;return args[4]()
    class Gateway:
        budget=Budget()
        def _selection(self,*_args):return Target(),{'hourly':10,'monthly':10000}
        def _budget_options(self,*_args):return {'monthly_token_limit':10000,'token_reservation':6000}
        def adapter(self,_target,_tenant,context,**kwargs):
            seen['context']=context
            return InferenceResult(kwargs['parse'](json.dumps(s.plan),context),{'input_tokens':200,'output_tokens':300})
    assert AgentPlanner(Gateway())(s.tenant,task,connectors())==s.plan
    assert seen['budget_options']['monthly_token_limit']==10000 and seen['budget_options']['token_reservation']==6000
    assert s.resource['resource_id'] not in json.dumps(seen['context'])
    assert s.tenant['tenant_id'] not in json.dumps(seen['context'])


def test_planning_is_metered_without_polluting_the_advisory_response_contract(setup):
    from app.inference_ledger import InferenceLedger
    s=setup;ledger=InferenceLedger(EnterpriseStore(s.settings))
    result=ledger.run(s.tenant['tenant_id'],str(uuid4()),'a'*64,10,
        lambda:dict(plan=s.plan,usage={'input_tokens':100,'output_tokens':200}),
        metadata=dict(scan_id=s.scan['scan_id'],kind='agent_plan',provider='azure',model='approved',target_id='approved-model'))
    assert ledger.page(s.tenant['tenant_id'])['items']==[]
    assert ledger.get(s.tenant['tenant_id'],result['assessment_id']) is None
    usage=ledger.usage(s.tenant['tenant_id'])['groups']
    assert usage[0]['attempts']==1 and usage[0]['input_tokens']==100 and usage[0]['output_tokens']==200


def test_stale_production_directory_blocks_private_worker_claims(setup,monkeypatch):
    s=setup
    # The fixture constructs a development store; switching the runtime policy
    # demonstrates that internal worker endpoints also refuse missing freshness.
    monkeypatch.setenv('CLOUDSAVER_ENVIRONMENT','production')
    r=s.api.post('/internal/v1/agent/claim',headers=s.worker_headers,json={'tenant_id':s.tenant['tenant_id']})
    assert r.status_code==503 and 'fresh' in r.json()['detail']
