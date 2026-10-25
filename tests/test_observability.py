from datetime import datetime,timedelta,timezone
from uuid import uuid4
import json
import httpx
import pytest
from fastapi.testclient import TestClient
from app.collectors import observability as obs
from app.main import create_app
from app.observability_store import ObservabilityStore,attach_signals,_derive
from app.v150_store import WorkflowConflict
from tests.test_enterprise import evidence,workspace,TID,AUTH

NOW=datetime(2026,10,25,12,0,tzinfo=timezone.utc)
HOST='metrics.example.com'
RID='/subscriptions/22222222-2222-4222-8222-222222222222/resourcegroups/rg/providers/microsoft.web/sites/checkout'


@pytest.fixture(autouse=True)
def allow(monkeypatch):
    monkeypatch.setenv('CLOUDSAVER_OBSERVABILITY_ALLOWED_HOSTS',HOST)
    monkeypatch.setenv('CLOUDSAVER_OBSERVABILITY_SECRET_PRIMARY','placeholder-token-value')


def prometheus_config(**extra):
    return obs.validate(dict(dict(name='Primary Prometheus',kind='prometheus',base_url=f'https://{HOST}',auth_kind='bearer_env',
        secret_ref='CLOUDSAVER_OBSERVABILITY_SECRET_PRIMARY',mappings={'resource_label':'azure_resource_id'},
        queries=[{'id':'requests','metric':'requests_per_second','unit':'req/s','promql':'sum by (azure_resource_id) (rate(http_requests_total[5m]))'}]),**extra),workspace())


def transport(handler):
    return httpx.MockTransport(handler)


@pytest.mark.parametrize('url',['http://metrics.example.com/','https://user:pw@metrics.example.com/','https://metrics.example.com/?x=1'])
def test_url_rejects_insecure_or_credentialed_forms(url):
    with pytest.raises(ValueError):obs.check_url(url)


@pytest.mark.parametrize('address',['10.0.0.5','127.0.0.1','169.254.169.254','100.64.0.1'])
def test_url_rejects_private_and_metadata_addresses(monkeypatch,address):
    monkeypatch.setattr(obs.socket,'getaddrinfo',lambda *a,**k:[(None,None,None,None,(address,443))])
    with pytest.raises(ValueError,match='private or reserved'):obs.check_url('https://internal.example.net/')
    assert obs.check_url(f'https://{HOST}/')==HOST


def test_validation_requires_mappings_named_secrets_and_relative_paths():
    with pytest.raises(ValueError,match='resource label'):obs.validate(dict(name='x',kind='prometheus',base_url=f'https://{HOST}',queries=[{'id':'a','promql':'up'}]),workspace())
    with pytest.raises(ValueError,match='Secret reference'):prometheus_config(secret_ref='AWS_SECRET_ACCESS_KEY')
    with pytest.raises(ValueError,match='Azure Monitor'):prometheus_config(auth_kind='azure_managed')
    with pytest.raises(ValueError,match='AWS account'):prometheus_config(auth_kind='aws_sigv4',aws_account_id='123456789012')
    with pytest.raises(ValueError,match='relative'):obs.validate(dict(name='r',kind='rest_metrics',base_url=f'https://{HOST}',mappings={'resource_label':'id'},
        queries=[{'id':'a','path':'../admin','resource_field':'id','points_path':'p'}]),workspace())
    with pytest.raises(ValueError,match='unsupported'):obs.validate(dict(name='x',kind='jaeger',base_url=f'https://{HOST}',services=['a'],password='x'),workspace())
    assert prometheus_config()['thresholds']=={'latency_p95_ms':500,'error_rate_pct':1}


def test_prometheus_reader_summarizes_series_with_secret_header_only_on_the_wire():
    seen={}
    def handler(request):
        seen['auth']=request.headers['authorization'];seen['url']=str(request.url)
        values=[[NOW.timestamp()-i*300,str(10+i%3)] for i in range(2016)]
        return httpx.Response(200,json={'status':'success','data':{'resultType':'matrix','result':[
            {'metric':{'azure_resource_id':RID},'values':values},{'metric':{},'values':[[NOW.timestamp(),'NaN']]}]}})
    result=obs.collect(prometheus_config(),workspace(),now=NOW,transport=transport(handler))
    assert seen['auth']=='Bearer placeholder-token-value' and 'api/v1/query_range' in seen['url']
    assert result['mapping_coverage']=={'series':2,'labeled':1,'services':0,'mapped_services':0}
    summary=result['series'][0]['summary']
    assert summary['coverage_pct']==100.0 and summary['max']==12 and summary['p50']==11
    assert result['series'][1]['summary'] is None and 'placeholder-token-value' not in json.dumps(result)


@pytest.mark.parametrize('status,code',[(302,'OBSERVABILITY_QUERY_REJECTED'),(401,'OBSERVABILITY_AUTH_REJECTED'),(500,'OBSERVABILITY_QUERY_REJECTED')])
def test_redirects_and_rejections_map_to_fixed_codes(status,code):
    handler=lambda request:httpx.Response(status,headers={'location':'https://attacker.example/'},text='secret upstream detail')
    with pytest.raises(obs.SourceError) as error:obs.collect(prometheus_config(),workspace(),now=NOW,transport=transport(handler))
    assert error.value.code==code and 'secret' not in str(error.value)


def test_missing_secret_reference_fails_before_any_request(monkeypatch):
    monkeypatch.delenv('CLOUDSAVER_OBSERVABILITY_SECRET_PRIMARY')
    with pytest.raises(obs.SourceError) as error:obs.collect(prometheus_config(),workspace(),now=NOW,transport=transport(lambda r:pytest.fail('No request expected')))
    assert error.value.code=='OBSERVABILITY_SECRET_UNAVAILABLE'


def test_rest_reader_maps_constrained_fields_and_substitutes_only_known_placeholders():
    config=obs.validate(dict(name='REST',kind='rest_metrics',base_url=f'https://{HOST}/api',auth_kind='none',mappings={'resource_label':'id'},
        queries=[{'id':'cpu','metric':'cpu_percent','path':'v1/cpu','params':{'from':'{start_epoch}','other':'{unknown}'},
                  'series_path':'data.items','resource_field':'meta.id','points_path':'points'}]),workspace())
    def handler(request):
        assert request.url.path=='/api/v1/cpu' and request.url.params['other']=='{unknown}' and request.url.params['from'].isdigit()
        return httpx.Response(200,json={'data':{'items':[{'meta':{'id':RID},'points':[{'timestamp':'2026-10-25T11:55:00Z','value':40},[NOW.timestamp(),60]]}]}})
    result=obs.collect(config,workspace(),now=NOW,transport=transport(handler))
    assert result['series'][0]['resource_id']==RID and result['series'][0]['summary']['max']==60


def test_tempo_reader_builds_rate_error_and_latency_aggregates():
    def handler(request):
        q=request.url.params['q']
        value=0.5 if 'quantile_over_time(duration, .95)' in q else 0.1 if 'quantile' in q else 2 if 'status=error' in q else 100
        return httpx.Response(200,json={'series':[{'samples':[{'timestampMs':str(int((NOW.timestamp()-60*i)*1000)),'value':value} for i in range(60)]}]})
    config=obs.validate(dict(name='Tempo',kind='tempo',base_url=f'https://{HOST}',mappings={'service_resources':{'checkout':RID}}),workspace())
    service=obs.collect(config,workspace(),now=NOW,transport=transport(handler))['services'][0]
    assert service==dict(service='checkout',requests_per_second=100.0,error_rate_pct=2.0,latency_p50_ms=100.0,latency_p95_ms=500.0,coverage_pct=100.0,sampled=False,dependencies=[])


def test_jaeger_reader_uses_entry_spans_and_keeps_no_trace_ids():
    def trace(i,error=False):
        return {'traceID':f'trace-{i}','processes':{'p1':{'serviceName':'checkout'},'p2':{'serviceName':'db'}},'spans':[
            {'spanID':f'a{i}','duration':(i+1)*1000,'processID':'p1','references':[],'tags':[{'key':'error','value':error}]},
            {'spanID':f'b{i}','duration':10,'processID':'p2','references':[{'spanID':f'a{i}'}],'tags':[]}]}
    def handler(request):
        if request.url.path.endswith('dependencies'):return httpx.Response(200,json={'data':[{'parent':'checkout','child':'db','callCount':40}]})
        return httpx.Response(200,json={'data':[trace(i,error=i==0) for i in range(10)]})
    config=obs.validate(dict(name='Jaeger',kind='jaeger',base_url=f'https://{HOST}',services=['checkout']),workspace())
    result=obs.collect(config,workspace(),now=NOW,transport=transport(handler))
    service=result['services'][0]
    assert service['traces_sampled']==10 and service['error_rate_pct']==10.0 and service['latency_p95_ms']==10.0
    assert service['dependencies']==[{'service':'db','calls':40}] and 'trace-' not in json.dumps(result)


def test_jobs_fence_commits_and_store_only_error_codes(evidence):
    _,store,_=evidence
    repo=ObservabilityStore(store);tenant=dict(workspace(),roles=['TenantAdmin'])
    connector=repo.create(tenant,prometheus_config())
    with pytest.raises(WorkflowConflict):repo.create(tenant,prometheus_config())
    repo.submit(tenant,str(uuid4()))
    claim=repo.claim(TID)
    with store.transaction(TID,write=True) as db:
        db.execute('UPDATE observability_jobs SET lease_token=%s WHERE tenant_id=%s AND id=%s',(str(uuid4()),TID,claim['id']))
    with pytest.raises(WorkflowConflict):repo.execute(tenant,claim,collect=lambda *a:dict(series=[],services=[],warnings=[]))
    assert repo.latest_snapshots(TID)=={}
    with store.transaction(TID,write=True) as db:db.execute("UPDATE observability_jobs SET state='failed' WHERE tenant_id=%s AND id=%s",(TID,claim['id']))
    repo.submit(tenant,str(uuid4()))
    def broken(*_):raise RuntimeError('response body with placeholder-token-value')
    result=repo.execute(tenant,repo.claim(TID),collect=broken)
    snap=repo.latest_snapshots(TID)[connector['id']]
    assert result['status']=='failed' and snap['error_code']=='OBSERVABILITY_SOURCE_UNAVAILABLE' and 'placeholder' not in json.dumps(snap)
    assert repo.due(TID,now=datetime.now(timezone.utc)+timedelta(hours=2))==[connector['id']]


def test_correlation_links_exact_ids_flags_latency_and_computes_cost_per_request(evidence):
    _,store,_=evidence
    repo=ObservabilityStore(store);tenant=dict(workspace(),roles=['TenantAdmin'])
    metrics=repo.create(tenant,prometheus_config())
    traces=repo.create(tenant,obs.validate(dict(name='Traces',kind='tempo',base_url=f'https://{HOST}',mappings={'service_resources':{'checkout':RID.upper()}},
                                                 thresholds={'latency_p95_ms':300,'error_rate_pct':5}),workspace()))
    summary=dict(samples=2016,coverage_pct=99.0,p50=10,p95=12,max=15,avg=10.0)
    data={metrics['id']:dict(series=[dict(query_id='requests',metric='requests_per_second',unit='req/s',resource_id=RID,summary=summary),
                                     dict(query_id='requests',metric='requests_per_second',unit='req/s',resource_id='/other',summary=summary)],services=[],warnings=[]),
          traces['id']:dict(series=[],services=[dict(service='checkout',requests_per_second=10,error_rate_pct=0.5,latency_p50_ms=80,latency_p95_ms=450,coverage_pct=100,sampled=False,dependencies=[])],warnings=[])}
    repo.submit(tenant,str(uuid4()))
    for _ in range(2):repo.execute(tenant,repo.claim(TID),collect=lambda c,t:data[c['id']])
    rows=[dict(resource_id=RID,evidence=dict(billed_cost_usd=2592.0,billing_coverage=True)),dict(resource_id='/unrelated',evidence={})]
    attach_signals(store,tenant,rows)
    e=rows[0]['evidence'];signals=e['observed_signals']
    assert e['latency_sensitive'] is True and e['observed_latency_p95_ms']==450 and len(signals['metrics'])==1
    assert signals['cost_per_1000_requests_usd']==pytest.approx(2592/30/(10*86400)*1000)
    assert 'observed_signals' not in rows[1]['evidence']


def test_cost_per_request_needs_complete_billing_and_request_coverage():
    found=dict(metrics=[dict(metric='requests_per_second',coverage_pct=80,avg=5,p95=6)],services=[],thresholds=[{'latency_p95_ms':500,'error_rate_pct':1}])
    assert 'below 95%' in _derive(found,{'billed_cost_usd':10,'billing_coverage':True})['observed_signals']['cost_per_1000_requests_reason']
    found['metrics'][0]['coverage_pct']=99
    result=_derive(found,{'billed_cost_usd':10,'billing_coverage':False})
    assert result['observed_signals']['cost_per_1000_requests_usd'] is None and 'latency_sensitive' not in result


def test_latency_sensitivity_blocks_unreviewed_capacity_reduction():
    from app.pillar_checks import checks
    added=[]
    checks('compute',dict(latency_sensitive=True,observed_latency_p95_ms=900),lambda *a:added.append(a))
    assert ('performance','OBSERVED_LATENCY_SENSITIVITY','risk') in [a[:3] for a in added]
    added.clear();checks('compute',{},lambda *a:added.append(a))
    assert 'OBSERVED_LATENCY_SENSITIVITY' not in [a[1] for a in added]


def connector_body():
    return dict(name='Primary Prometheus',kind='prometheus',base_url=f'https://{HOST}',auth_kind='bearer_env',
                secret_ref='CLOUDSAVER_OBSERVABILITY_SECRET_PRIMARY',mappings={'resource_label':'azure_resource_id'},
                queries=[{'id':'cpu','metric':'cpu_percent','promql':'avg by (azure_resource_id) (cpu)'}])


def test_api_manages_connectors_without_exposing_secret_values(evidence,monkeypatch):
    settings,_,_=evidence
    api=TestClient(create_app(settings))
    created=api.post('/api/v1/observability/connectors',headers=AUTH,json=connector_body())
    assert created.status_code==201 and created.json()['secret_ref']=='CLOUDSAVER_OBSERVABILITY_SECRET_PRIMARY'
    listed=api.get('/api/v1/observability/connectors',headers=AUTH)
    assert 'placeholder-token-value' not in listed.text and len(listed.json()['items'])==1
    id,version=created.json()['id'],created.json()['version']
    updated=api.post(f'/api/v1/observability/connectors/{id}',headers=AUTH,json={'connector':dict(connector_body(),schedule='daily'),'version':version})
    assert updated.status_code==200 and updated.json()['schedule']=='daily'
    assert api.post(f'/api/v1/observability/connectors/{id}',headers=AUTH,json={'connector':connector_body(),'version':version}).status_code==409
    assert api.post('/api/v1/observability/connectors',headers=AUTH,json=dict(connector_body(),base_url='http://x')).status_code==422
    monkeypatch.setattr('app.collectors.observability.collect',lambda *a,**k:(_ for _ in ()).throw(obs.SourceError('OBSERVABILITY_AUTH_REJECTED')))
    probe=api.post(f'/api/v1/observability/connectors/{id}/test',headers=AUTH,json={}).json()
    assert probe['ok'] is False and 'rejected the credentials' in probe['message']
    job=api.post('/api/v1/observability/sync',headers=AUTH,json={'idempotency_key':str(uuid4())})
    assert job.status_code==202 and job.headers['location']==job.json()['poll_url']
    assert api.post(f'/api/v1/observability/connectors/{id}/disable',headers=AUTH,json={}).json()['enabled'] is False
    summary=api.get('/api/v1/observability/summary',headers=AUTH).json()['items'][0]
    assert summary['status']=='not_collected' and 'base_url' not in summary


def test_viewer_reads_summary_but_cannot_manage_connectors(evidence,monkeypatch):
    from app.auth import Role,UserClaims
    settings,_,_=evidence
    monkeypatch.setenv('CLOUDSAVER_AUTH_MODE','entra')
    class Validator:
        def verify_token(self,token):return UserClaims(user_id=str(uuid4()),tenant_id=TID,roles=[Role.VIEWER])
    with TestClient(create_app(settings,identity_validator=Validator())) as client:
        assert client.post('/api/v1/observability/connectors',headers=AUTH,json=connector_body()).status_code==403
        assert client.get('/api/v1/observability/connectors',headers=AUTH).status_code==403
        assert client.post('/api/v1/observability/sync',headers=AUTH,json={'idempotency_key':str(uuid4())}).status_code==403
        assert client.get('/api/v1/observability/summary',headers=AUTH).status_code==200
