from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from threading import Event
from uuid import uuid4
import hashlib
import json

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.ai_advisory import AIError, AIGateway
from app.config import Settings
from app.enterprise_store import EnterpriseStore
from app.focus import Charge, FocusError, FocusRepository, ImportRequest
from app.inference_ledger import InferenceLedger
from app.main import create_app
from app.store import Store
from tests.support import stub_scanner
from tests.test_ai_advisory import advice,target,TID,SUB

KEY='test-enterprise-credential-more-than-32-characters'
AUTH={'Authorization':'Bearer '+KEY}


def workspace():
    return dict(tenant_id=TID,name='Enterprise evidence',subscription_ids=[SUB],plan_tier='ENTERPRISE',api_key_sha256=hashlib.sha256(KEY.encode()).hexdigest())


def charge(day=1,value='10',**changes):
    start=datetime(2026,10,day,tzinfo=timezone.utc)
    return dict(dict(x_ChargeId='charge-'+str(day),ProviderName='Azure',BillingAccountId='billing-account',SubAccountId=SUB,
        BillingCurrency='USD',ChargePeriodStart=start.isoformat(),ChargePeriodEnd=(start+timedelta(days=1)).isoformat(),
        ResourceId=None,ChargeCategory='Usage',BilledCost=value,EffectiveCost=value,ListCost='20'),**changes)


def batch(records=None,**changes):
    return dict(dict(source_id='export-2026-10',provider='azure',sub_account_id=SUB,billing_currency='USD',
        period_start='2026-10-01',period_end='2026-10-22',complete=True,records=records if records is not None else [charge(i) for i in range(1,22)]),**changes)


@pytest.fixture
def evidence(tmp_path):
    settings=Settings('azure',str(tmp_path/'evidence.db'),(workspace(),))
    store=Store(settings.database)
    scan=dict(scan_id=str(uuid4()),timestamp=datetime.now(timezone.utc).isoformat(),status='completed',mode='azure',subscriptions_scanned=1,
              total_items_found=1,total_monthly_waste_usd=None,findings=stub_scanner(workspace()))
    store.save(TID,scan,workspace=workspace())
    repository=EnterpriseStore(settings)
    return settings,repository,scan


def metadata(scan):
    return dict(scan_id=scan['scan_id'],provider='azure',model='test-model',target_id='test',resource_reference='a'*64)


def result():
    return dict(advice=advice(),usage=dict(input_tokens=100,output_tokens=20,billed_cost_usd=None))


def test_ledger_persists_cache_usage_and_exactly_one_attempt_across_instances(evidence):
    settings,repo,scan=evidence
    ledger=InferenceLedger(repo);key=str(uuid4());calls=[]
    def invoke(): calls.append(1);return result()
    first=ledger.run(TID,key,'a'*64,10,invoke,metadata=metadata(scan))
    restarted=InferenceLedger(EnterpriseStore(settings))
    second=restarted.run(TID,key,'a'*64,10,invoke,metadata=metadata(scan))
    assert first['assessment_id']==second['assessment_id'] and second['cached'] and len(calls)==1
    records=restarted.page(TID)
    assert len(records['items'])==1 and records['items'][0]['status']=='completed'
    detail=restarted.get(TID,first['assessment_id'])
    assert [e['action'] for e in detail['events']]==['claimed','completed']
    usage=restarted.usage(TID)['groups'][0]
    assert usage['attempts']==usage['completed']==1 and usage['input_tokens']==100 and usage['billed_cost_usd'] is None
    other=str(uuid4())
    assert restarted.page(other)['items']==[] and restarted.get(other,first['assessment_id']) is None
    with pytest.raises(AIError) as error: restarted.page(other,before=first['assessment_id'])
    assert error.value.status==422
    with pytest.raises(AIError) as error: restarted.run(TID,key,'b'*64,10,invoke,metadata=metadata(scan))
    assert error.value.status==409


def test_inflight_and_uncertain_attempts_cannot_repeat_or_consume_extra_slots(evidence):
    _,repo,scan=evidence;ledger=InferenceLedger(repo)
    ready,release=Event(),Event();key=str(uuid4());calls=[]
    def invoke():
        calls.append(1);ready.set();assert release.wait(5);raise AIError('provider test failure',502)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first=executor.submit(ledger.run,TID,key,'f'*64,1,invoke,metadata=metadata(scan))
        assert ready.wait(5)
        with pytest.raises(AIError) as error: ledger.run(TID,key,'f'*64,1,invoke,metadata=metadata(scan))
        assert error.value.status==409
        release.set()
        with pytest.raises(AIError): first.result()
    with pytest.raises(AIError) as error: ledger.run(TID,key,'f'*64,1,invoke,metadata=metadata(scan))
    assert error.value.status==409 and len(calls)==1
    with pytest.raises(AIError) as error: ledger.run(TID,str(uuid4()),'f'*64,1,lambda:result(),metadata=metadata(scan))
    assert error.value.status==429
    usage=ledger.usage(TID)['groups'][0]
    assert usage['incomplete_outcomes']==1 and usage['input_tokens'] is None


def test_completion_failure_leaves_fence_and_never_exposes_uncommitted_advice(evidence,monkeypatch):
    _,repo,scan=evidence;ledger=InferenceLedger(repo);key=str(uuid4());calls=[]
    original=ledger.event
    def fail(db,tid,attempt,action,now):
        if action=='completed': raise RuntimeError('private internal test failure')
        return original(db,tid,attempt,action,now)
    monkeypatch.setattr(ledger,'event',fail)
    with pytest.raises(AIError) as error:
        ledger.run(TID,key,'a'*64,10,lambda:(calls.append(1) or result()),metadata=metadata(scan))
    assert 'private' not in str(error.value)
    assert ledger.page(TID)['items'][0]['status']=='uncertain'
    assert ledger.get(TID,ledger.page(TID)['items'][0]['id'])['response'] is None
    with pytest.raises(AIError): ledger.run(TID,key,'a'*64,10,lambda:result(),metadata=metadata(scan))
    assert len(calls)==1


def test_ledger_failure_before_reservation_never_invokes_provider(evidence,monkeypatch):
    _,repo,scan=evidence;ledger=InferenceLedger(repo)
    def unavailable(*args,**kwargs): raise RuntimeError('private database endpoint')
    monkeypatch.setattr(repo,'transaction',unavailable)
    with pytest.raises(AIError) as error:
        ledger.run(TID,str(uuid4()),'a'*64,10,lambda:pytest.fail('Provider must not be called'),metadata=metadata(scan))
    assert error.value.status==503 and 'private' not in str(error.value)


def test_normalized_billing_is_atomic_deduplicated_and_decimal_exact(evidence):
    _,store,_=evidence;repo=FocusRepository(store);tenant=workspace()
    payload=ImportRequest.model_validate(batch([charge(1,'0.1'),charge(2,'0.2'),charge(3,'-0.05',ChargeCategory='Credit',ListCost=None)]))
    first=repo.import_records(tenant,payload)
    assert first['inserted']==3
    repeat=repo.import_records(tenant,payload)
    assert repeat['cached'] and repeat['import_id']==first['import_id']
    overlap=repo.import_records(tenant,ImportRequest.model_validate(batch(payload.model_dump(mode='json')['records'],source_id='second-export')))
    assert overlap['inserted']==0
    conflict=batch([charge(4),charge(1,'999')],source_id='conflicting-export')
    with pytest.raises(FocusError) as error: repo.import_records(tenant,ImportRequest.model_validate(conflict))
    assert error.value.status==409
    data=repo.summary(tenant,date(2026,10,1),date(2026,10,22),'USD')
    assert data['records']==3 and data['billed_cost']=='0.25000000'
    assert data['list_cost'] is data['effective_savings_rate_pct'] is None
    assert data['realized_savings'] is None and data['billing_reconciled'] is False
    assert repo.summary(dict(tenant,tenant_id=str(uuid4())),date(2026,10,1),date(2026,10,22),'USD')['records']==0


@pytest.mark.parametrize('value',[0,True,0.1,'NaN','Infinity','1e4','-1e2','1.000000001','9999999999999999'])
def test_malformed_money_is_rejected_without_guessing(value):
    with pytest.raises(ValidationError): Charge.model_validate(charge(BilledCost=value))


@pytest.mark.parametrize('changes',[dict(complete='true'),dict(records=[charge(),charge()]),dict(period_end='2026-09-30'),
    dict(records=[charge(BillingCurrency='EUR')]),dict(records=[charge(ChargePeriodStart='2026-10-01T00:00:00')]),
    dict(records=[charge(ChargePeriodEnd='2026-09-30T00:00:00Z')])])
def test_import_schema_rejects_ambiguous_or_inconsistent_evidence(changes):
    with pytest.raises(ValidationError): ImportRequest.model_validate(batch(**changes))


def test_billing_scope_and_resource_binding_are_current_and_exact(evidence):
    _,store,_=evidence;repo=FocusRepository(store);tenant=workspace()
    for changes in [dict(sub_account_id=str(uuid4()),records=[]),dict(records=[charge(ResourceId='/subscriptions/'+str(uuid4())+'/disks/foreign')])]:
        with pytest.raises(FocusError) as error: repo.import_records(tenant,ImportRequest.model_validate(batch(**changes)))
        assert error.value.status==403
    repo.import_records(tenant,ImportRequest.model_validate(batch()))
    changed=dict(tenant,subscription_ids=[str(uuid4())])
    assert repo.imports(changed)==[] and repo.summary(changed,date(2026,10,1),date(2026,10,22),'USD')['records']==0


def test_forecasts_require_declared_complete_closed_days_and_currency(evidence):
    _,store,_=evidence;repo=FocusRepository(store);tenant=workspace()
    repo.import_records(tenant,ImportRequest.model_validate(batch()))
    summary=repo.summary(tenant,date(2026,10,1),date(2026,10,22),'USD','300')
    assert summary['billed_cost']=='210.00000000' and summary['effective_savings_rate_pct']=='50.0000'
    assert summary['forecast']['month_end_billed_cost']=='310.00000000'
    assert summary['forecast']['projected_budget_overrun'] is True
    assert repo.summary(tenant,date(2026,10,1),date(2026,10,22),'EUR')['forecast'] is None
    # A newer partial declaration invalidates forecast coverage, without changing actual charges.
    repo.import_records(tenant,ImportRequest.model_validate(batch([],source_id='partial-update',complete=False)))
    partial=repo.summary(tenant,date(2026,10,1),date(2026,10,22),'USD')
    assert partial['forecast'] is None and partial['daily'][0]['billed_cost'] is None


def test_long_charge_intervals_are_not_spread_into_fabricated_daily_metrics(evidence):
    _,store,_=evidence;repo=FocusRepository(store);tenant=workspace()
    repo.import_records(tenant,ImportRequest.model_validate(batch([charge(1,'200',ChargePeriodEnd='2026-10-21T00:00:00Z')])) )
    summary=repo.summary(tenant,date(2026,10,1),date(2026,10,22),'USD')
    assert summary['billed_cost']=='200.00000000' and summary['forecast'] is None
    assert summary['daily'][0]['billed_cost'] is None
    narrow=repo.summary(tenant,date(2026,10,2),date(2026,10,10),'USD')
    assert narrow['records']==0 and narrow['excluded_overlapping_records']==1
    assert all(not point['complete'] for point in narrow['daily']) and narrow['forecast'] is None


def test_empty_complete_import_establishes_observed_zero_without_invented_spend(evidence):
    _,store,_=evidence;repo=FocusRepository(store);tenant=workspace()
    repo.import_records(tenant,ImportRequest.model_validate(batch([])))
    summary=repo.summary(tenant,date(2026,10,1),date(2026,10,22),'USD')
    assert summary['billed_cost']=='0' and summary['forecast']['month_end_billed_cost']=='0.00000000'


def test_finance_routes_and_durable_history_through_real_api(evidence):
    settings,store,_=evidence
    ledger=InferenceLedger(store)
    gateway=AIGateway(enabled=True,targets=[target()],budget=ledger,adapter=lambda *args:advice())
    with TestClient(create_app(settings,scanner=stub_scanner,ai_gateway=gateway)) as client:
        imported=client.post('/api/v1/finops/imports',headers=AUTH,json=batch())
        assert imported.status_code==201,imported.text
        summary=client.get('/api/v1/finops/summary?start=2026-10-01&end=2026-10-22&currency=USD',headers=AUTH)
        assert summary.status_code==200 and summary.json()['billed_cost']=='210.00000000'
        assert client.get('/api/v1/finops/summary?budget=nan',headers=AUTH).status_code==422
        scan=client.post('/api/v1/scans',headers=AUTH).json();base='/api/v1/scans/'+scan['scan_id']
        selection={k:scan['findings'][0][k] for k in ('resource_id','rule_id')}
        preview=client.post(base+'/analysis/resource',headers=AUTH,json=selection).json()
        request=dict(selection,target_id='review',evidence_digest=preview['assessment']['evidence_digest'],idempotency_key=str(uuid4()),acknowledge_external_processing=True)
        response=client.post(base+'/ai-risk-evaluation',headers=AUTH,json=request)
        assert response.status_code==200,response.text
        second=client.post(base+'/ai-risk-evaluation',headers=AUTH,json=request)
        assert second.json()['cached'] and second.json()['assessment_id']==response.json()['assessment_id']
        history=client.get('/api/v1/ai/assessments',headers=AUTH).json()
        assert len(history['items'])==1
        detail=client.get('/api/v1/ai/assessments/'+response.json()['assessment_id'],headers=AUTH).json()
        assert detail['response']['evidence_digest']==request['evidence_digest']
        assert client.get('/api/v1/ai/usage',headers=AUTH).json()['groups'][0]['attempts']==1


def test_viewer_cannot_import_or_read_billing_while_history_is_tenant_scoped(evidence,monkeypatch):
    from app.auth import Role,UserClaims
    settings,_,_=evidence
    monkeypatch.setenv('CLOUDSAVER_AUTH_MODE','entra')
    class Validator:
        def verify_token(self,token): return UserClaims(user_id=str(uuid4()),tenant_id=TID,roles=[Role.VIEWER])
    with TestClient(create_app(settings,identity_validator=Validator())) as client:
        assert client.post('/api/v1/finops/imports',headers=AUTH,json=batch()).status_code==403
        assert client.get('/api/v1/finops/summary',headers=AUTH).status_code==403
        assert client.get('/api/v1/ai/assessments',headers=AUTH).json()['items']==[]


def test_cost_center_attribution_is_structured_and_never_forwarded_to_models(evidence):
    from app.assessment import assess,ai_context
    from app.inference_ledger import attribution
    from tests.support import azure_disk_finding
    _,store,scan=evidence;ledger=InferenceLedger(store)
    item=dict(azure_disk_finding(SUB),evidence={'tags':{'CostCenter':'CC-7801','ApplicationId':'Checkout'}})
    assessment=assess(item);context=ai_context(item,assessment);sent=[]
    gateway=AIGateway(enabled=True,targets=[target()],budget=ledger,adapter=lambda t,w,c:(sent.append(c) or advice()))
    gateway.evaluate(workspace(),'review',uuid4(),scan['scan_id'],context,assessment,attribution=attribution(item))
    usage=ledger.usage(TID)['groups'][0]
    assert usage['cost_center']=='CC-7801' and usage['application_id']=='Checkout'
    assert 'CC-7801' not in json.dumps(sent) and 'Checkout' not in json.dumps(sent)
    assert attribution(dict(item,evidence={'tags':{'CostCenter':'person@example.invalid','ApplicationId':'x'*81}}))==dict(cost_center='unassigned',application_id='unassigned')


def test_zscore_requires_complete_nonconstant_thirty_day_baseline(evidence):
    _,store,_=evidence;repo=FocusRepository(store);tenant=workspace()
    start=datetime(2026,9,21,tzinfo=timezone.utc);rows=[]
    for i in range(31):
        day=start+timedelta(days=i)
        rows.append(charge(1,'100' if i==30 else '10' if i%2 else '11',x_ChargeId='baseline-'+str(i),
            ChargePeriodStart=day.isoformat(),ChargePeriodEnd=(day+timedelta(days=1)).isoformat()))
    repo.import_records(tenant,ImportRequest.model_validate(batch(rows,period_start='2026-09-21',period_end='2026-10-22')))
    summary=repo.summary(tenant,date(2026,9,21),date(2026,10,22),'USD')
    assert summary['anomaly']['baseline_days']==30 and summary['anomaly']['spike']
    assert summary['forecast'] is None # Not a month-to-date projection window.


def test_enterprise_gateway_forwards_only_fixed_authenticated_routes(tmp_path):
    import httpx
    from services.gateway import create_app as gateway_app
    requests=[]
    class Limiter:
        async def check(self,tenant_id): assert tenant_id==TID
    def upstream(request):
        requests.append(request)
        assert request.url.host=='scanner-service'
        assert request.headers['authorization']==AUTH['Authorization']
        return httpx.Response(200,json={'items':[]})
    settings=Settings('azure',str(tmp_path/'gateway.db'),(workspace(),))
    with TestClient(gateway_app(settings,limiter=Limiter(),transport=httpx.MockTransport(upstream))) as client:
        for route in ['/finops/imports','/finops/summary?currency=EUR&start=2026-10-01&end=2026-10-22&endpoint=https://evil.invalid',
                      '/ai/assessments?limit=10&resource_reference='+'a'*64,'/ai/usage?days=7','/ai/assessments/'+str(uuid4())]:
            assert client.get('/api/v1'+route,headers=AUTH).status_code==200
        assert all('endpoint' not in request.url.params for request in requests)
        before=len(requests)
        assert client.get('/api/v1/ai/assessments/not-a-uuid',headers=AUTH).status_code==422
        assert client.get('/api/v1/finops/arbitrary',headers=AUTH).status_code==404
        assert len(requests)==before
        assert client.post('/api/v1/finops/imports',headers=AUTH,json=batch()).status_code==201
        assert json.loads(requests[-1].content)['records'][0]['BilledCost']=='10'


def test_same_month_in_another_year_is_not_a_month_to_date_projection(evidence):
    _,store,_=evidence;repo=FocusRepository(store);tenant=workspace()
    repo.import_records(tenant,ImportRequest.model_validate(batch([],period_start='2025-10-01',period_end='2026-10-02')))
    summary=repo.summary(tenant,date(2025,10,1),date(2026,10,2),'USD')
    assert summary['forecast'] is None


def test_extreme_permitted_decimal_ratios_and_projections_remain_exact(evidence):
    _,store,_=evidence;repo=FocusRepository(store);tenant=workspace()
    maximum='999999999999999.99999999'
    rows=[charge(day,maximum,ListCost='0.00000001') for day in range(1,8)]
    repo.import_records(tenant,ImportRequest.model_validate(batch(rows,period_end='2026-10-08')))
    summary=repo.summary(tenant,date(2026,10,1),date(2026,10,8),'USD')
    expected=str((1-int(maximum.replace('.','')))*100)+'.0000'
    assert summary['effective_savings_rate_pct']==expected
    assert summary['forecast']['month_end_billed_cost']=='30999999999999999.99999969'
