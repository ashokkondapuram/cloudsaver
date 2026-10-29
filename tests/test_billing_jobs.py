from datetime import datetime,timedelta,timezone
from decimal import Decimal
from uuid import uuid4
import json
import pytest
from fastapi.testclient import TestClient
from app.billing_jobs import BillingJobs
from app.collectors.billing_sync import _import_snapshot
from app.focus import FocusRepository
from app.main import create_app
from app.v150_store import WorkflowConflict
from tests.test_enterprise import evidence,workspace,TID,SUB,AUTH


def config(monkeypatch):
    monkeypatch.setenv('CLOUDSAVER_BILLING_CONNECTORS',json.dumps([dict(tenant_id=TID,provider='azure',scope_id=SUB)]))
    monkeypatch.setenv('CLOUDSAVER_AUTO_BILLING_SYNC','true')


def reader(binding,tenant,start,end):return [dict(day=start,resource_id=None,currency='USD',category='Usage',billed='10',effective='10')],'account',[]


def total(store):
    with store.transaction(TID) as db:return sum((Decimal(str(r[0])) for r in db.execute('SELECT billed_cost FROM focus_charges WHERE tenant_id=%s',(TID,)).fetchall()),Decimal(0))


def test_provider_cooldown_defers_same_scope_without_saving_partial_lines(evidence,monkeypatch):
    from app.provider_retry import ProviderDeferred
    _,store,_=evidence;config(monkeypatch);jobs=BillingJobs(store)
    job=jobs.submit(workspace(),str(uuid4()));claim=jobs.claim(TID)
    def throttled(*args):raise ProviderDeferred(120)
    jobs.execute_scope(workspace(),claim,readers={'azure':throttled})
    saved=jobs.get(TID,job['id'])
    assert saved['status']=='queued' and saved['payload']['scope_index']==0
    assert saved['payload']['last_error_code']=='BILLING_PROVIDER_THROTTLED'
    assert jobs.claim(TID) is None and total(store)==0
    assert jobs.cancel(TID,job['id'])['status']=='cancelled'
    assert jobs.claim(TID,now=datetime.now(timezone.utc)+timedelta(minutes=3)) is None


def test_recovery_preserves_requested_cancellation(evidence,monkeypatch):
    from workers.billing_sync import _recover_orphaned_jobs
    settings,store,_=evidence;config(monkeypatch);jobs=BillingJobs(store)
    job=jobs.submit(workspace(),str(uuid4()));jobs.claim(TID);jobs.cancel(TID,job['id'])
    _recover_orphaned_jobs(settings)
    assert jobs.get(TID,job['id'])['status']=='cancelled' and jobs.claim(TID) is None


def test_api_enqueue_returns_202_reuses_key_and_never_calls_provider(evidence,monkeypatch):
    settings,store,_=evidence;config(monkeypatch)
    monkeypatch.setattr('app.collectors.billing_sync.READERS',{'azure':lambda *_:pytest.fail('The HTTP request must not call a provider')})
    api=TestClient(create_app(settings));key=str(uuid4())
    a=api.post('/api/v1/finops/sync',headers=AUTH,json={'idempotency_key':key})
    b=api.post('/api/v1/finops/sync',headers=AUTH,json={'idempotency_key':key})
    assert a.status_code==b.status_code==202 and a.json()['id']==b.json()['id']
    assert a.headers['location']==a.json()['poll_url'] and total(store)==0
    jobs=BillingJobs(store)
    with pytest.raises(WorkflowConflict):jobs.submit(workspace(),str(uuid4()))
    claim=jobs.claim(TID);jobs.execute_scope(workspace(),claim,readers={'azure':reader})
    assert BillingJobs(store).get(TID,a.json()['id'])['status']=='completed' and total(store)==10
    assert jobs.claim(TID) is None
    assert api.get(a.headers['location'],headers=AUTH).json()['status']=='completed'
    assert jobs.get(str(uuid4()),a.json()['id']) is None


def test_worker_crash_and_lost_lease_never_duplicate_or_commit_stale_reads(evidence,monkeypatch):
    _,store,_=evidence;config(monkeypatch);jobs=BillingJobs(store);job=jobs.submit(workspace(),str(uuid4()))
    first=jobs.claim(TID)
    def crash(*a):raise SystemExit('synthetic process loss before import')
    with pytest.raises(SystemExit):jobs.execute_scope(workspace(),first,readers={'azure':crash})
    with store.transaction(TID,write=True) as db:db.execute('UPDATE billing_sync_jobs SET lease_until=%s WHERE tenant_id=%s AND id=%s',((datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat(),TID,job['id']))
    second=BillingJobs(store).claim(TID)
    assert first['token']!=second['token']
    with pytest.raises(WorkflowConflict):jobs.execute_scope(workspace(),first,readers={'azure':reader})
    assert total(store)==0
    jobs.execute_scope(workspace(),second,readers={'azure':reader})
    assert total(store)==10
    assert BillingJobs(store).submit(workspace(),str(uuid4()))['status']=='queued'
    # Re-observing the same provider amounts in a fresh explicit job adds no delta.
    jobs.execute_scope(workspace(),jobs.claim(TID),readers={'azure':reader})
    assert total(store)==10


def test_cancel_and_midflight_scope_revocation_stop_imports(evidence,monkeypatch):
    _,store,_=evidence;config(monkeypatch);jobs=BillingJobs(store)
    job=jobs.submit(workspace(),str(uuid4()));assert jobs.cancel(TID,job['id'])['status']=='cancelled';assert jobs.claim(TID) is None
    job=jobs.submit(workspace(),str(uuid4()));claim=jobs.claim(TID)
    jobs.execute_scope(workspace(),claim,readers={'azure':reader},refresh=lambda:dict(workspace(),subscription_ids=[]))
    assert total(store)==0 and jobs.get(TID,job['id'])['status']=='failed'


def test_missing_groups_need_completeness_and_source_watermark(evidence):
    _,store,_=evidence;repo=FocusRepository(store);binding=dict(provider='azure',scope_id=SUB)
    start=datetime.now(timezone.utc).date()-timedelta(days=20);end=start+timedelta(days=1)
    def snapshot(rows,**kw):return _import_snapshot(repo,workspace(),binding,rows,start,end,'USD',**kw)
    row=dict(day=start,resource_id=None,currency='USD',category='Usage',billed='10',effective='10')
    snapshot([row]);assert total(store)==10
    incomplete=snapshot([]);assert incomplete['unresolved_absent_groups']==1 and total(store)==10
    with pytest.raises(ValueError):snapshot([],authoritative=True)
    result=snapshot([],authoritative=True,watermark='export:1')
    assert total(store)==0 and result['unresolved_absent_groups']==0
    assert snapshot([],authoritative=True,watermark='export:1')['inserted']==0
    # Category reclassification plus late credit must reconcile the union, rather
    # than keep both the former and replacement categories.
    snapshot([row]);replacement=dict(row,category='Purchase');credit=dict(row,category='Credit',billed='-2',effective='-2')
    result=snapshot([replacement,credit]);assert result['unresolved_absent_groups']==1 and total(store)==18
    snapshot([replacement,credit],authoritative=True,watermark='export:2');assert total(store)==8
