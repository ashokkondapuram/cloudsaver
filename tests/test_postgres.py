"""Database boundaries tested through the real runtime role, independently of HTTP."""
from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
import sys
from uuid import UUID, uuid4

import psycopg
from psycopg import errors, sql
from psycopg.types.json import Jsonb
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.store import PostgresStore

pytestmark = pytest.mark.postgres
TABLES = ('scans', 'organizations', 'tenants', 'subscriptions', 'waste_findings')
ROOT = Path(__file__).resolve().parents[1]


def migrate(owner, revision):
    env = os.environ.copy()
    env['CLOUDSAVER_MIGRATION_URL'] = owner
    subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', revision], cwd=ROOT, env=env,
                   check=True, capture_output=True, text=True)


@pytest.fixture(scope='module')
def database():
    owner = os.getenv('CLOUDSAVER_TEST_OWNER_URL')
    app = os.getenv('CLOUDSAVER_TEST_APP_URL')
    if not owner or not app:
        pytest.skip('Use python scripts/test_postgres.py for a disposable PostgreSQL database')
    # The runner supplies a fresh database. Never clean/drop an existing database.
    with psycopg.connect(owner) as db:
        assert db.execute("SELECT to_regclass('public.alembic_version')").fetchone()[0] is None, 'Requires an empty disposable database'
    migrate(owner, '0001_domain')
    legacy_tenant, legacy_id = uuid4(), uuid4()
    legacy = {'scan_id': str(legacy_id), 'findings': [], 'mode': 'azure'}
    with psycopg.connect(owner) as db:
        db.execute((ROOT / 'database/001_schema.sql').read_text())
        db.execute("SELECT set_config('app.current_tenant_id', %s, true)", (str(legacy_tenant),))
        db.execute('INSERT INTO scans VALUES (%s, %s, now(), %s)', (legacy_id, legacy_tenant, Jsonb(legacy)))
    migrate(owner, 'head')
    store = PostgresStore(app)
    assert store.get(str(legacy_tenant), str(legacy_id)) == legacy
    return owner, app, store


def workspace():
    return {'tenant_id': str(uuid4()), 'name': 'Integration workspace', 'subscription_ids': [str(uuid4())]}


def scan(tenant):
    sub = tenant['subscription_ids'][0]
    return {'scan_id': str(uuid4()), 'timestamp': datetime.now(timezone.utc).isoformat(),
            'status': 'completed', 'mode': 'azure', 'subscriptions_scanned': 1,
            'total_items_found': 1, 'total_monthly_waste_usd': None,
            'findings': [{'subscription_id': sub, 'resource_id': f'/subscriptions/{sub}/resourceGroups/test/providers/Microsoft.Compute/disks/archive',
                          'resource_name': 'archive', 'resource_type': 'Microsoft.Compute/disks',
                          'resource_group': 'test', 'rule_id': 'ORPHANED_DISK', 'severity': 'HIGH',
                          'details': 'Review retention', 'estimated_monthly_waste_usd': None}]}


@pytest.fixture
def tenants(database):
    _, app, store = database
    a, b = workspace(), workspace()
    sa, sb = scan(a), scan(b)
    store.save(a['tenant_id'], sa, workspace=a)
    store.save(b['tenant_id'], sb, workspace=b)
    return app, store, a, b, sa, sb


def context(db, tenant):
    db.execute("SELECT set_config('app.current_tenant_id', %s, true)", (tenant,))


def test_runtime_role_and_forced_policies(database):
    _, app, _ = database
    with psycopg.connect(app) as db:
        assert db.execute('SELECT rolsuper, rolbypassrls, rolcreatedb, rolcreaterole FROM pg_roles WHERE rolname=current_user').fetchone() == (False,) * 4
        for table in TABLES:
            assert db.execute('SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE oid=%s::regclass', (table,)).fetchone() == (True, True)
        with pytest.raises(errors.InsufficientPrivilege):
            db.execute('ALTER TABLE scans DISABLE ROW LEVEL SECURITY')


def test_no_context_and_unknown_context_cannot_read_or_insert(tenants):
    app, _, a, _, sa, _ = tenants
    with psycopg.connect(app) as db:
        for table in TABLES:
            assert db.execute(sql.SQL('SELECT count(*) FROM {}').format(sql.Identifier(table))).fetchone()[0] == 0
        with pytest.raises(errors.InsufficientPrivilege):
            db.execute('INSERT INTO scans VALUES (%s, %s, now(), %s)', (uuid4(), a['tenant_id'], Jsonb(sa)))
        db.rollback()
        context(db, str(uuid4()))
        assert db.execute('SELECT count(*) FROM scans').fetchone()[0] == 0


def test_cross_tenant_reads_inserts_and_updates_are_blocked(tenants):
    app, store, a, b, sa, sb = tenants
    assert store.get(a['tenant_id'], sb['scan_id']) is None
    assert [r['scan_id'] for r in store.list(a['tenant_id'])] == [sa['scan_id']]
    with psycopg.connect(app) as db:
        context(db, a['tenant_id'])
        for table in TABLES:
            assert {str(row[0]) for row in db.execute(sql.SQL('SELECT tenant_id FROM {}').format(sql.Identifier(table)))} == {a['tenant_id']}
        assert db.execute('UPDATE tenants SET display_name=%s WHERE tenant_id=%s', ('not allowed', b['tenant_id'])).rowcount == 0
        with pytest.raises(errors.InsufficientPrivilege):
            db.execute('INSERT INTO scans VALUES (%s, %s, now(), %s)', (uuid4(), b['tenant_id'], Jsonb(sb)))
        db.rollback()
        context(db, a['tenant_id'])
        with pytest.raises(errors.InsufficientPrivilege):
            db.execute('UPDATE tenants SET tenant_id=%s WHERE tenant_id=%s', (b['tenant_id'], a['tenant_id']))


@pytest.mark.parametrize('fail', [False, True])
def test_local_context_clears_on_commit_and_failed_transaction(tenants, fail):
    app, _, a, b, _, _ = tenants
    with psycopg.connect(app) as db:
        context(db, a['tenant_id'])
        assert db.execute('SELECT count(*) FROM scans').fetchone()[0] == 1
        if fail:
            with pytest.raises(errors.DivisionByZero):
                db.execute('SELECT 1/0')
            db.rollback()
        else:
            db.commit()
        assert db.execute('SELECT count(*) FROM scans').fetchone()[0] == 0
        context(db, b['tenant_id'])
        assert {str(r[0]) for r in db.execute('SELECT tenant_id FROM scans')} == {b['tenant_id']}


def test_findings_are_atomic_linked_and_not_duplicated(tenants):
    app, store, a, b, sa, sb = tenants
    with psycopg.connect(app) as db:
        context(db, a['tenant_id'])
        row = db.execute('SELECT scan_id, estimated_monthly_waste_usd, evidence FROM waste_findings').fetchone()
        assert str(row[0]) == sa['scan_id'] and row[1] is None and row[2] == {'mode': 'azure'}
        with pytest.raises(errors.ForeignKeyViolation):
            db.execute('UPDATE waste_findings SET scan_id=%s', (sb['scan_id'],))
    broken = scan(a)
    broken['findings'][0]['severity'] = 'INVALID'
    with pytest.raises(errors.CheckViolation):
        store.save(a['tenant_id'], broken, workspace=a)
    assert store.get(a['tenant_id'], broken['scan_id']) is None
    with pytest.raises(errors.UniqueViolation):
        store.save(a['tenant_id'], sa, workspace=a)
    assert len(store.list(a['tenant_id'])) == 1
    next_scan = scan(a)
    store.save(a['tenant_id'], next_scan, workspace=a)
    with psycopg.connect(app) as db:
        context(db, a['tenant_id'])
        assert db.execute('SELECT count(*) FROM waste_findings').fetchone()[0] == 2
        assert db.execute('SELECT count(*) FROM organizations').fetchone()[0] == 1


def test_scope_rejection_and_empty_scan(database):
    _, app, store = database
    a, b = workspace(), workspace()
    outside = scan(b)
    with pytest.raises(ValueError, match='scope'):
        store.save(a['tenant_id'], outside, workspace=a)
    empty = scan(a)
    empty.update(findings=[], total_items_found=0)
    store.save(a['tenant_id'], empty, workspace=a)
    assert store.get(a['tenant_id'], empty['scan_id']) == empty
    with psycopg.connect(app) as db:
        context(db, a['tenant_id'])
        assert db.execute('SELECT count(*) FROM waste_findings').fetchone()[0] == 0


def test_privileged_runtime_and_runtime_migration_are_rejected(database):
    owner, app, _ = database
    with pytest.raises(ValueError, match='own storage tables'):
        PostgresStore(owner)
    privileged = os.getenv('CLOUDSAVER_TEST_PRIVILEGED_URL')
    if privileged:
        with pytest.raises(ValueError, match='superuser'):
            PostgresStore(privileged)
    with pytest.raises(subprocess.CalledProcessError):
        migrate(app, 'head')


@pytest.mark.parametrize('table', ['organizations', 'tenants', 'subscriptions', 'waste_findings'])
def test_domain_cross_tenant_inserts_rejected(tenants, table):
    app, _, a, b, _, _ = tenants
    with psycopg.connect(app) as db:
        context(db, a['tenant_id'])
        with pytest.raises(errors.InsufficientPrivilege):
            # Copy an authorized row but claim the foreign tenant. RLS must reject
            # it before foreign-key or uniqueness checks can authorize ownership.
            columns = [r[0] for r in db.execute('SELECT column_name FROM information_schema.columns WHERE table_schema=\'public\' AND table_name=%s ORDER BY ordinal_position', (table,))]
            row = list(db.execute(sql.SQL('SELECT * FROM {} LIMIT 1').format(sql.Identifier(table))).fetchone())
            row[columns.index('tenant_id')] = b['tenant_id']
            if 'id' in columns:
                row[columns.index('id')] = uuid4()
            if 'evidence' in columns:
                row[columns.index('evidence')] = Jsonb(row[columns.index('evidence')])
            db.execute(sql.SQL('INSERT INTO {} ({}) VALUES ({})').format(
                sql.Identifier(table), sql.SQL(', ').join(map(sql.Identifier, columns)),
                sql.SQL(', ').join(sql.Placeholder() for _ in columns)), row)


def test_ingestion_failure_rolls_back_new_workspace(database):
    _, app, store = database
    a = workspace()
    broken = scan(a)
    broken['findings'][0]['resource_name'] = 'x' * 257
    with pytest.raises(errors.StringDataRightTruncation):
        store.save(a['tenant_id'], broken, workspace=a)
    with psycopg.connect(app) as db:
        context(db, a['tenant_id'])
        for table in TABLES:
            assert db.execute(sql.SQL('SELECT count(*) FROM {}').format(sql.Identifier(table))).fetchone()[0] == 0


def test_postgres_api_ownership_header_spoof_and_restart(database):
    import hashlib
    from tests.support import stub_scanner
    _, app, _ = database
    a, b = workspace(), workspace()
    keys = ('integration-workspace-a-key', 'integration-workspace-b-key')
    for tenant, key in zip((a, b), keys):
        tenant['api_key_sha256'] = hashlib.sha256(key.encode()).hexdigest()
    settings = Settings('azure', '', (a, b), app)
    headers = {'Authorization': 'Bearer ' + keys[0], 'X-Tenant-ID': b['tenant_id']}
    with TestClient(create_app(settings,scanner=stub_scanner)) as client:
        assert client.get('/api/v1/me', headers={'X-Tenant-ID': a['tenant_id']}).status_code == 401
        assert client.get('/api/v1/me', headers=headers).json()['tenant_id'] == a['tenant_id']
        response = client.post('/api/v1/scans', headers=headers)
        assert response.status_code == 201
        result = response.json()
        assert client.get('/api/v1/scans/' + result['scan_id'], headers={'Authorization': 'Bearer ' + keys[1]}).status_code == 404
    with TestClient(create_app(settings,scanner=stub_scanner)) as client:
        assert client.get('/api/v1/scans/' + result['scan_id'], headers=headers).json() == result


def test_local_billing_state_is_read_only_for_the_runtime_role(database):
    owner, app, store = database
    a = workspace()
    store.save(a['tenant_id'], scan(a), workspace=a)
    with psycopg.connect(owner) as db:
        context(db, a['tenant_id'])
        organization = db.execute("UPDATE organizations SET stripe_customer_id='cus_placeholder' WHERE tenant_id=%s "
                                  'RETURNING id', (a['tenant_id'],)).fetchone()[0]
    with psycopg.connect(app) as db:
        context(db, a['tenant_id'])
        db.execute("UPDATE organizations SET name='Renamed', plan_tier='PARTNER_2026' WHERE id=%s", (organization,))
        assert db.execute('SELECT stripe_customer_id FROM organizations WHERE id=%s', (organization,)).fetchone() == ('cus_placeholder',)
    for statement, params in (
            ('UPDATE organizations SET stripe_customer_id=NULL WHERE id=%s', (organization,)),
            ("INSERT INTO stripe_events (event_id, tenant_id, organization_id, event_type, event_created, outcome) "
             "VALUES ('evt_placeholder', %s, %s, 'invoice.paid', 1, 'applied')", (a['tenant_id'], organization)),
            ('DELETE FROM stripe_events', ())):
        with psycopg.connect(app) as db:
            context(db, a['tenant_id'])
            with pytest.raises(errors.InsufficientPrivilege):
                db.execute(statement, params)
    with psycopg.connect(app) as db:
        context(db, a['tenant_id'])
        with pytest.raises(errors.CheckViolation):
            db.execute("UPDATE organizations SET plan_tier='not a code' WHERE id=%s", (organization,))


def test_directory_projection_persists_the_plan_block(database):
    import json
    from app.entitlements import billing_summary
    from app.tenant_registry import PostgresRegistry
    _, app, _ = database
    fixtures = ROOT / 'platform/contracts/fixtures'
    snapshot = json.loads((fixtures / 'directory_snapshot.json').read_text())['workspaces'][0]
    tid = str(uuid4())
    snapshot.update(tenant_id=tid, customer_id=str(uuid4()))
    registry = PostgresRegistry(app, (), ttl=0)
    assert registry.apply_snapshot(snapshot)
    stored = registry.get(tid)
    assert stored['plan']['code'] == 'STARTER' and stored['plan']['billing_state'] == 'lapsed'
    assert stored['plan']['grace_ends_at'] == '2026-10-14T00:00:00Z' and stored['plan']['entitlements_version'] == 8
    summary = billing_summary(stored)
    assert summary['entitlements_source'] == 'platform' and summary['subscription_plan_name'] == 'Growth'
    custom = dict(snapshot, version=6, plan_tier='PARTNER', plan=dict(snapshot['plan'], code='PARTNER', name='Partner',
                  billing_state='active', manage_billing_url='https://billing.example.com/partner'))
    assert registry.apply_snapshot(custom)
    stored = registry.get(tid)
    assert stored['plan_tier'] == 'PARTNER' and stored['plan']['manage_billing_url'] == 'https://billing.example.com/partner'
    with psycopg.connect(app) as db:
        context(db, tid)
        assert db.execute('SELECT plan_tier FROM organizations').fetchall() == [('PARTNER',)]
    unplanned = dict(snapshot, version=7)
    unplanned.pop('plan')
    registry.apply_snapshot(unplanned)
    assert 'plan' not in registry.get(tid) or registry.get(tid)['plan'] is None


def test_worker_fencing_and_scan_links_use_real_postgres(database):
    from workers.storage import JobRepository
    _,app,store = database
    a = workspace()
    store.save(a['tenant_id'],scan(a),workspace=a)
    with store.connection(a['tenant_id']) as db:
        db.execute("UPDATE tenants SET connection_status='connected'")
        db.execute('UPDATE subscriptions SET active=true')
    repository = JobRepository(app)
    job_id,old,new = (str(uuid4()) for _ in range(3))
    repository.queue_job(a['tenant_id'],job_id)
    assert repository.start_job(a['tenant_id'],job_id,old)
    assert repository.start_job(a['tenant_id'],job_id,new)
    result = scan(a)
    with pytest.raises(ValueError,match='Stale'):
        repository.complete_job(a['tenant_id'],job_id,result,a['subscription_ids'],token=old)
    repository.fail_job(a['tenant_id'],job_id,'stale_failure',True,token=old)
    assert repository.get_job(a['tenant_id'],job_id)['status'] == 'running'
    assert store.get(a['tenant_id'],result['scan_id']) is None
    repository.complete_job(a['tenant_id'],job_id,result,a['subscription_ids'],token=new)
    assert repository.get_job(a['tenant_id'],job_id)['status'] == 'completed'
    with store.connection(a['tenant_id']) as db:
        assert db.execute('SELECT count(*) FROM waste_findings WHERE scan_id=%s',(result['scan_id'],)).fetchone()[0] == 1
    b = workspace()
    assert repository.get_job(b['tenant_id'],job_id) is None


def test_job_and_billing_tables_are_isolated_and_migrations_have_one_head(database):
    owner,app,_ = database
    with psycopg.connect(app) as db:
        for table in ('scan_jobs','stripe_events'):
            assert db.execute('SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid=%s::regclass',(table,)).fetchone() == (True,True)
            assert db.execute(sql.SQL('SELECT count(*) FROM {}').format(sql.Identifier(table))).fetchone()[0] == 0
    with psycopg.connect(owner) as db:
        assert db.execute('SELECT version_num FROM alembic_version').fetchall() == [('0013_billing_projection',)]


def test_scheduler_reservation_throttles_concurrent_publishers(database):
    from workers.storage import JobRepository
    _,app,store = database
    a = workspace()
    store.save(a['tenant_id'],scan(a),workspace=a)
    repository = JobRepository(app)
    assert repository.reserve_scheduled_job(a['tenant_id'],str(uuid4()),86400,a['subscription_ids'])
    assert not repository.reserve_scheduled_job(a['tenant_id'],str(uuid4()),86400,a['subscription_ids'])


@pytest.fixture
def delivery(database):
    from app.delivery_config import Target
    from database.delivery import DeliveryRepository
    _,url,store=database
    tenant=workspace()
    snapshot=scan(tenant)
    store.save(tenant['tenant_id'],snapshot,workspace=tenant)
    target=Target('finops',tenant['tenant_id'],'slack','https://hooks.slack.com/services/T/B/private-token')
    repository=DeliveryRepository(url)
    event=repository.enqueue_notification(tenant['tenant_id'],snapshot,(target,))[0]
    return repository,tenant,snapshot,target,event


def test_delivery_rls_fk_audit_append_only_and_public_redaction(delivery,database):
    repository,a,snapshot,target,event=delivery
    _,url,_=database
    other=workspace()
    assert repository.get(other['tenant_id'],event) is None
    assert repository.history(other['tenant_id'],event) is None
    assert repository.list(other['tenant_id'])==[]
    public=repository.get(a['tenant_id'],event)
    assert 'private-token' not in str(public) and 'payload' not in public and 'target_fingerprint' not in public
    with psycopg.connect(url) as db:
        for table in ('delivery_events','delivery_audit','delivery_dispatchers'):
            assert db.execute('SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid=%s::regclass',(table,)).fetchone()==(True,True)
            assert db.execute(sql.SQL('SELECT count(*) FROM {}').format(sql.Identifier(table))).fetchone()[0]==0
        context(db,a['tenant_id'])
        with pytest.raises(errors.InsufficientPrivilege):
            db.execute('UPDATE delivery_audit SET actor=%s WHERE tenant_id=%s',('forged',a['tenant_id']))
        db.rollback()
        context(db,a['tenant_id'])
        with pytest.raises(errors.InsufficientPrivilege):
            db.execute('DELETE FROM delivery_audit WHERE tenant_id=%s',(a['tenant_id'],))
        db.rollback()
        context(db,other['tenant_id'])
        from database.delivery import enqueue
        with pytest.raises(errors.ForeignKeyViolation):
            enqueue(db,other['tenant_id'],'notification',scan_id=snapshot['scan_id'],target=target,payload={})


def test_delivery_dedupe_survives_restart_and_stale_completion_is_fenced(delivery):
    from database.delivery import DeliveryRepository
    repository,a,snapshot,target,event_id=delivery
    restarted=DeliveryRepository(repository.url)
    assert restarted.enqueue_notification(a['tenant_id'],snapshot,(target,))==[event_id]
    assert len(restarted.history(a['tenant_id'],event_id)['items'])==1
    first=repository.claim(a['tenant_id'],['notification'])
    assert restarted.claim(a['tenant_id'],['notification']) is None
    with repository.transaction(a['tenant_id']) as db:
        db.execute("UPDATE delivery_events SET lease_until=clock_timestamp()-interval '1 second' WHERE id=%s",(event_id,))
    assert not repository.finish(a['tenant_id'],first,outcome='delivered')
    second=restarted.claim(a['tenant_id'],['notification'])
    assert second['lease_token']!=first['lease_token'] and second['attempts']==2
    assert not repository.finish(a['tenant_id'],first,outcome='delivered')
    assert restarted.finish(a['tenant_id'],second,outcome='delivered')
    assert repository.get(a['tenant_id'],event_id)['status']=='delivered'
    assert repository.claim(a['tenant_id'],['notification']) is None


def test_concurrent_dispatchers_claim_distinct_rows(delivery):
    from concurrent.futures import ThreadPoolExecutor
    from app.delivery_config import Target
    repository,a,snapshot,target,_=delivery
    another=Target('second',a['tenant_id'],'slack',target.url)
    repository.enqueue_notification(a['tenant_id'],snapshot,(another,))
    with ThreadPoolExecutor(max_workers=4) as pool:
        results=list(pool.map(lambda _:repository.claim(a['tenant_id'],['notification']),range(4)))
    claimed=[r for r in results if r]
    assert len(claimed)==len({r['id'] for r in claimed})==2


def test_dead_letter_budget_bounded_replay_and_audit_pagination(delivery):
    from database.delivery import DeliveryConflict
    repository,a,_,_,event_id=delivery
    for attempt in range(8):
        current=repository.claim(a['tenant_id'],['notification'])
        assert current['attempts']==attempt+1
        repository.finish(a['tenant_id'],current,outcome='retry',error_code='provider_unavailable',retry_after=30)
        with repository.transaction(a['tenant_id']) as db:
            db.execute('UPDATE delivery_events SET next_attempt_at=clock_timestamp() WHERE id=%s',(event_id,))
    assert repository.get(a['tenant_id'],event_id)['status']=='dead_letter'
    assert repository.claim(a['tenant_id'],['notification']) is None
    ids=[]
    cursor=None
    while True:
        page=repository.history(a['tenant_id'],event_id,3,cursor)
        ids.extend(r['id'] for r in page['items'])
        cursor=page['next_cursor']
        if not cursor:
            break
    assert len(ids)==len(set(ids))==17
    for count in range(1,4):
        replay=repository.replay(a['tenant_id'],event_id,'principal:test')
        assert replay['replay_count']==count and replay['attempts']==0
        claimed=repository.claim(a['tenant_id'],['notification'])
        repository.finish(a['tenant_id'],claimed,outcome='dead_letter',error_code='provider_rejected')
    with pytest.raises(DeliveryConflict):
        repository.replay(a['tenant_id'],event_id,'principal:test')


def test_scheduler_and_completion_outbox_are_atomic(database,monkeypatch):
    from workers.storage import JobRepository
    from database.delivery import DeliveryRepository
    from app.delivery_config import Target
    import database.delivery as outbox
    _,url,store=database
    a=workspace()
    store.save(a['tenant_id'],scan(a),workspace=a)
    jobs,deliveries=JobRepository(url),DeliveryRepository(url)
    job_id=str(uuid4())
    original=outbox.enqueue
    def failure(*args,**kwargs):
        raise RuntimeError('simulated transactional insertion failure')
    with monkeypatch.context() as patch:
        patch.setattr(outbox,'enqueue',failure)
        with pytest.raises(RuntimeError):
            jobs.reserve_scheduled_job(a['tenant_id'],job_id,3600,a['subscription_ids'])
    assert jobs.get_job(a['tenant_id'],job_id) is None
    assert deliveries.list(a['tenant_id'])==[]
    assert jobs.reserve_scheduled_job(a['tenant_id'],job_id,3600,a['subscription_ids'])
    assert jobs.verify_delivery(a['tenant_id'],job_id,a['subscription_ids'])
    assert not jobs.verify_delivery(a['tenant_id'],job_id,[str(uuid4())])
    assert not jobs.verify_delivery(str(uuid4()),job_id,a['subscription_ids'])
    assert not jobs.verify_delivery(a['tenant_id'],str(uuid4()),a['subscription_ids'])
    assert len(deliveries.list(a['tenant_id']))==1
    with store.connection(a['tenant_id']) as db:
        db.execute("UPDATE tenants SET connection_status='connected'")
        db.execute('UPDATE subscriptions SET active=true')
    token=str(uuid4())
    jobs.start_job(a['tenant_id'],job_id,token)
    result=scan(a)
    target=Target('finops',a['tenant_id'],'slack','https://hooks.slack.com/services/T/B/test')
    with monkeypatch.context() as patch:
        patch.setattr(outbox,'enqueue',failure)
        with pytest.raises(RuntimeError):
            jobs.complete_job(a['tenant_id'],job_id,result,a['subscription_ids'],token=token,notification_targets=(target,))
    assert store.get(a['tenant_id'],result['scan_id']) is None
    assert jobs.get_job(a['tenant_id'],job_id)['status']=='running'
    jobs.complete_job(a['tenant_id'],job_id,result,a['subscription_ids'],token=token,notification_targets=(target,))
    events=deliveries.list(a['tenant_id'])
    assert {(e['kind'],e['status']) for e in events}=={('scan','delivered'),('notification','pending')}
    assert jobs.get_job(a['tenant_id'],job_id)['status']=='completed'
    jobs.complete_job(a['tenant_id'],job_id,result,a['subscription_ids'],token=token,notification_targets=(target,))
    assert len(deliveries.list(a['tenant_id']))==2


def test_lost_broker_message_republished_with_same_task_id(database):
    import json
    import redis
    from celery import Celery
    from workers.storage import JobRepository
    from database.delivery import DeliveryRepository
    from workers.dispatcher import dispatch_one
    import httpx
    redis_url=os.getenv('CLOUDSAVER_TEST_REDIS_URL')
    if not redis_url:
        pytest.skip('Disposable Redis required')
    _,url,store=database
    a=workspace()
    store.save(a['tenant_id'],scan(a),workspace=a)
    jobs,deliveries=JobRepository(url),DeliveryRepository(url)
    job_id=str(uuid4())
    jobs.reserve_scheduled_job(a['tenant_id'],job_id,3600,a['subscription_ids'])
    queue='cloudsaver-fault-'+uuid4().hex
    app=Celery('delivery-fault-test',broker=redis_url)
    broker=redis.Redis.from_url(redis_url)
    def publish(tid,subscriptions,id):
        app.send_task('workers.tasks.execute_subscription_scan',args=[tid,subscriptions],task_id=id,queue=queue,retry=False)
    try:
        with httpx.Client() as client:
            dispatch_one(deliveries,a['tenant_id'],targets=(),publish_scan=publish,client=client,kinds=['scan'])
            assert json.loads(broker.lindex(queue,0))['headers']['id']==job_id
            # Simulate loss of the accepted broker message. DB retains intent.
            broker.delete(queue)
            assert jobs.get_job(a['tenant_id'],job_id)['status']=='queued'
            with deliveries.transaction(a['tenant_id']) as db:
                db.execute('UPDATE delivery_events SET next_attempt_at=clock_timestamp() WHERE tenant_id=%s',(a['tenant_id'],))
            assert deliveries.reconcile(a['tenant_id'])==1
            dispatch_one(deliveries,a['tenant_id'],targets=(),publish_scan=publish,client=client,kinds=['scan'])
            assert json.loads(broker.lindex(queue,0))['headers']['id']==job_id
            assert deliveries.list(a['tenant_id'])[0]['attempts']==2
    finally:
        broker.delete(queue,'_kombu.binding.'+queue)
        broker.close()
        app.close()


def test_reconcile_stale_worker_and_exhausted_dispatch_are_visible(database):
    from workers.storage import JobRepository
    from database.delivery import DeliveryRepository
    _,url,store=database
    a=workspace()
    store.save(a['tenant_id'],scan(a),workspace=a)
    jobs,deliveries=JobRepository(url),DeliveryRepository(url)
    job_id=str(uuid4())
    jobs.reserve_scheduled_job(a['tenant_id'],job_id,3600,a['subscription_ids'])
    event=deliveries.claim(a['tenant_id'],['scan'])
    deliveries.finish(a['tenant_id'],event,outcome='published')
    token=str(uuid4())
    jobs.start_job(a['tenant_id'],job_id,token)
    with deliveries.transaction(a['tenant_id']) as db:
        db.execute('UPDATE delivery_events SET next_attempt_at=clock_timestamp() WHERE id=%s',(event['id'],))
    deliveries.reconcile(a['tenant_id'])
    assert jobs.get_job(a['tenant_id'],job_id)['status']=='running'
    with deliveries.transaction(a['tenant_id']) as db:
        db.execute('UPDATE delivery_events SET next_attempt_at=clock_timestamp() WHERE id=%s',(event['id'],))
        db.execute("UPDATE scan_jobs SET updated_at=clock_timestamp()-interval '16 minutes' WHERE id=%s",(job_id,))
    deliveries.reconcile(a['tenant_id'])
    assert jobs.get_job(a['tenant_id'],job_id)['status']=='queued'
    assert deliveries.get(a['tenant_id'],event['id'])['status']=='pending'
    with pytest.raises(ValueError,match='Stale'):
        jobs.complete_job(a['tenant_id'],job_id,scan(a),a['subscription_ids'],token=token)


def test_delivery_api_owned_dedupe_and_explicit_retry(delivery,database,monkeypatch):
    import hashlib
    repository,a,snapshot,target,event=delivery
    _,url,_=database
    key='private-workspace-key'
    a.update(api_key_sha256=hashlib.sha256(key.encode()).hexdigest(),plan_tier='GROWTH')
    monkeypatch.setenv('CLOUDSAVER_DELIVERY_ENABLED','true')
    settings=Settings('azure','',(a,),url)
    with TestClient(create_app(settings,delivery_targets=(target,))) as client:
        headers={'Authorization':'Bearer '+key,'X-Tenant-ID':str(uuid4())}
        base='/api/v1/operations/deliveries/'+event
        assert client.get('/api/v1/operations/reliability').status_code==401
        summary=client.get('/api/v1/operations/reliability',headers=headers)
        assert summary.status_code==200 and 'private-token' not in summary.text
        assert client.post('/api/v1/notifications/'+snapshot['scan_id'],headers=headers).json()['delivery_ids']==[event]
        assert client.post('/api/v1/notifications/'+str(uuid4()),headers=headers).status_code==404
        assert client.get('/api/v1/operations/deliveries?limit=101',headers=headers).status_code==422
        assert client.get(base+'/audit',headers=headers).json()['items'][0]['action']=='enqueued'
        assert client.get('/api/v1/operations/deliveries/'+str(uuid4())+'/audit',headers=headers).status_code==404
        assert client.post(base+'/retry',json={'acknowledge_duplicate_risk':True},headers=headers).status_code==409
        current=repository.claim(a['tenant_id'],['notification'])
        repository.finish(a['tenant_id'],current,outcome='dead_letter',error_code='provider_rejected')
        assert client.post(base+'/retry',json={'acknowledge_duplicate_risk':False},headers=headers).status_code==422
        assert client.post(base+'/retry',json={'acknowledge_duplicate_risk':'true'},headers=headers).status_code==422
        assert client.post(base+'/retry',json={'acknowledge_duplicate_risk':True},headers=headers).status_code==202
        audit_result=client.get(base+'/audit',headers=headers)
        assert 'private-workspace-key' not in audit_result.text
        assert any(row['action']=='replay_requested' and row['actor'].startswith('principal:') for row in audit_result.json()['items'])
        monkeypatch.setenv('CLOUDSAVER_DELIVERY_ENABLED','false')
        assert client.post('/api/v1/notifications/'+snapshot['scan_id'],headers=headers).status_code==503


def test_dispatcher_heartbeat_is_tenant_scoped(delivery):
    repository,a,_,_,_=delivery
    assert repository.summary(a['tenant_id'])['dispatcher'] is None
    repository.heartbeat(a['tenant_id'],True)
    result=repository.summary(a['tenant_id'])['dispatcher']
    assert result['last_poll_at'] and result['last_success_at'] and not result['last_error_at']
    repository.heartbeat(a['tenant_id'],False)
    result=repository.summary(a['tenant_id'])['dispatcher']
    assert result['last_error_at'] and result['last_success_at']
    assert repository.summary(str(uuid4()))['dispatcher'] is None


def test_delivery_list_pagination_and_foreign_cursors(delivery):
    from app.delivery_config import Target
    from database.delivery import DeliveryConflict
    repository,a,snapshot,target,_=delivery
    for i in range(4):
        repository.enqueue_notification(a['tenant_id'],snapshot,(Target('target-'+str(i),a['tenant_id'],'slack',target.url),))
    page=repository.page(a['tenant_id'],2,'pending')
    assert len(page['items'])==2 and page['next_cursor']
    second=repository.page(a['tenant_id'],2,'pending',page['next_cursor'])
    third=repository.page(a['tenant_id'],2,'pending',second['next_cursor'])
    assert len({r['id'] for r in page['items']+second['items']+third['items']})==5
    assert third['next_cursor'] is None
    with pytest.raises(DeliveryConflict):
        repository.page(str(uuid4()),2,None,page['next_cursor'])


def test_gitops_requests_rls_foreign_keys_and_durable_fencing(database):
    from app.gitops_store import ReviewRepository,ReviewConflict
    owner,app,store=database
    a,b=workspace(),workspace()
    sa,sb=scan(a),scan(b)
    store.save(a['tenant_id'],sa,workspace=a)
    store.save(b['tenant_id'],sb,workspace=b)
    repository=ReviewRepository(store)
    package=dict(scan_id=sa['scan_id'],fingerprint='a'*64,target_id='infra',repository='example/infra',branch='cloudsaver/review-test')
    id=repository.reserve(a['tenant_id'],'test-key-12345678',package)
    assert repository.reserve(a['tenant_id'],'test-key-12345678',package)==id
    assert repository.get(b['tenant_id'],id) is None
    with psycopg.connect(app) as db:
        assert db.execute("SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid='gitops_requests'::regclass").fetchone()==(True,True)
        assert db.execute('SELECT count(*) FROM gitops_requests').fetchone()[0]==0
    with pytest.raises(errors.ForeignKeyViolation):
        repository.reserve(a['tenant_id'],'foreign-scan-key-12345678',dict(package,scan_id=sb['scan_id']))
    old,new=str(uuid4()),str(uuid4())
    assert repository.claim(a['tenant_id'],id,old)
    with pytest.raises(ReviewConflict):repository.claim(a['tenant_id'],id,new)
    with psycopg.connect(owner) as db:
        context(db,a['tenant_id'])
        db.execute('UPDATE gitops_requests SET lease_until=0 WHERE id=%s',(id,))
    assert repository.claim(a['tenant_id'],id,new)
    with pytest.raises(ReviewConflict):repository.finish(a['tenant_id'],id,old,{'pr_number':7})
    repository.finish(a['tenant_id'],id,new,{'pr_number':7})
    assert ReviewRepository(PostgresStore(app)).get(a['tenant_id'],id)['status']=='open'


def test_multi_cloud_findings_are_atomic_and_rls_isolated(database):
    from tests.fixtures.synthetic_findings import demo_cloud_findings,demo_workspace
    _, app, store = database
    a, b = demo_workspace(workspace()), workspace()
    payload = scan(a)
    payload.update(mode='multi-cloud', cloud_providers=['aws','gcp','kubernetes'])
    payload['findings'] = demo_cloud_findings(a, ['aws','gcp','kubernetes'])
    payload['total_items_found'] = len(payload['findings'])
    store.save(a['tenant_id'], payload, workspace=a)
    assert store.get(a['tenant_id'], payload['scan_id']) == payload
    assert store.get(b['tenant_id'], payload['scan_id']) is None
    with psycopg.connect(app) as db:
        assert db.execute('SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid=\'cloud_findings\'::regclass').fetchone() == (True,True)
        assert db.execute('SELECT count(*) FROM cloud_findings').fetchone()[0] == 0
        context(db, a['tenant_id'])
        assert db.execute('SELECT count(*) FROM cloud_findings').fetchone()[0] == 10
        with pytest.raises(errors.InsufficientPrivilege):
            db.execute('INSERT INTO cloud_findings SELECT %s,%s,scan_id,cloud_provider,scope_id,resource_id,rule_id,payload,observed_at FROM cloud_findings LIMIT 1', (uuid4(),b['tenant_id']))
    broken = dict(payload, scan_id=str(uuid4()))
    broken['findings'] = [dict(payload['findings'][0], rule_id='x'*65)]
    # Scope validation rejects malformed rules before any transaction writes.
    broken['total_items_found'] = 1
    with pytest.raises(ValueError):
        store.save(a['tenant_id'], broken, workspace=a)
    assert store.get(a['tenant_id'], broken['scan_id']) is None
    # A database error in the non-Azure write must also roll back the snapshot.
    broken['findings'] = [payload['findings'][0], payload['findings'][0]]
    broken['total_items_found'] = 2
    with pytest.raises(errors.UniqueViolation):
        store.save(a['tenant_id'], broken, workspace=a)
    assert store.get(a['tenant_id'], broken['scan_id']) is None


@pytest.mark.parametrize('starting_revision',['0002_scan_findings','0003_scan_jobs','0004_merge_hardening','0005_cloud_findings'])
def test_upgrade_each_release_lineage_preserves_history(database,starting_revision):
    from sqlalchemy.engine import make_url
    privileged = os.getenv('CLOUDSAVER_TEST_PRIVILEGED_URL')
    if not privileged:
        pytest.skip('Requires the disposable integration runner')
    owner,app,_ = database
    name = 'cloudsaver_upgrade_'+uuid4().hex
    owner_url = make_url(owner).set(database=name).render_as_string(hide_password=False)
    app_url = make_url(app).set(database=name).render_as_string(hide_password=False)
    with psycopg.connect(privileged,autocommit=True) as admin:
        admin.execute(sql.SQL('CREATE DATABASE {} OWNER cloudsaver_owner').format(sql.Identifier(name)))
    try:
        with psycopg.connect(owner_url) as db:
            db.execute((ROOT/'database/001_schema.sql').read_text())
        migrate(owner_url,starting_revision)
        tenant,id = str(uuid4()),str(uuid4())
        payload = {'scan_id':id,'mode':'azure','findings':[]}
        with psycopg.connect(owner_url) as db:
            context(db,tenant)
            db.execute('INSERT INTO scans VALUES (%s,%s,now(),%s)',(id,tenant,Jsonb(payload)))
        migrate(owner_url,'head')
        assert PostgresStore(app_url).get(tenant,id) == payload
    finally:
        from database.connection import dispose
        dispose()
        with psycopg.connect(privileged,autocommit=True) as admin:
            admin.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(name)))


def test_reconciliation_skips_locked_job_and_exhaustion_fences_lost_worker(database):
    from workers.storage import JobRepository
    from database.delivery import DeliveryRepository
    _,url,store=database
    a=workspace();store.save(a['tenant_id'],scan(a),workspace=a)
    jobs,deliveries=JobRepository(url),DeliveryRepository(url)
    job_id=str(uuid4());jobs.reserve_scheduled_job(a['tenant_id'],job_id,3600,a['subscription_ids'])
    event=deliveries.claim(a['tenant_id'],['scan']);deliveries.finish(a['tenant_id'],event,outcome='published')
    with deliveries.transaction(a['tenant_id']) as db:
        db.execute('UPDATE delivery_events SET attempts=8,next_attempt_at=clock_timestamp() WHERE id=%s',(event['id'],))
    with jobs.transaction(a['tenant_id']) as held:
        held.execute('SELECT 1 FROM scan_jobs WHERE id=%s FOR UPDATE',(job_id,))
        deliveries.reconcile(a['tenant_id'])
        assert deliveries.get(a['tenant_id'],event['id'])['status']=='published'
    deliveries.reconcile(a['tenant_id'])
    assert deliveries.get(a['tenant_id'],event['id'])['status']=='dead_letter'
    assert jobs.get_job(a['tenant_id'],job_id)['status']=='failed'


def test_multiple_notification_targets_project_queued_failed_and_sent_accurately(database):
    from workers.storage import JobRepository
    from database.delivery import DeliveryRepository
    from app.delivery_config import Target
    _,url,store=database
    a=workspace();store.save(a['tenant_id'],scan(a),workspace=a)
    with store.connection(a['tenant_id']) as db:
        db.execute("UPDATE tenants SET connection_status='connected'")
        db.execute('UPDATE subscriptions SET active=true')
    jobs,deliveries=JobRepository(url),DeliveryRepository(url)
    job_id,token=str(uuid4()),str(uuid4())
    jobs.queue_job(a['tenant_id'],job_id);jobs.start_job(a['tenant_id'],job_id,token)
    targets=tuple(Target(name,a['tenant_id'],'slack','https://hooks.slack.com/services/T/B/test') for name in ('first','second'))
    jobs.complete_job(a['tenant_id'],job_id,scan(a),a['subscription_ids'],token=token,notification_targets=targets)
    def state():
        with deliveries.transaction(a['tenant_id']) as db:
            return db.execute('SELECT notification_status FROM scan_jobs WHERE id=%s',(job_id,)).fetchone()[0]
    first=deliveries.claim(a['tenant_id'],['notification'])
    deliveries.finish(a['tenant_id'],first,outcome='delivered')
    assert state()=='queued'
    second=deliveries.claim(a['tenant_id'],['notification'])
    deliveries.finish(a['tenant_id'],second,outcome='dead_letter',error_code='provider_rejected')
    assert state()=='failed'
    deliveries.replay(a['tenant_id'],second['id'],'principal:test')
    assert state()=='queued'
    second=deliveries.claim(a['tenant_id'],['notification'])
    deliveries.finish(a['tenant_id'],second,outcome='delivered')
    assert state()=='sent'


def test_delivery_downgrade_upgrade_preserves_scans_and_restores_forced_rls(database):
    owner,url,store=database
    a=workspace();snapshot=scan(a);store.save(a['tenant_id'],snapshot,workspace=a)
    from workers.storage import JobRepository
    jobs=JobRepository(url);job_id=str(uuid4());jobs.queue_job(a['tenant_id'],job_id)
    with jobs.transaction(a['tenant_id']) as db:
        db.execute("UPDATE scan_jobs SET notification_status='queued' WHERE id=%s",(job_id,))
    env=os.environ.copy();env['CLOUDSAVER_MIGRATION_URL']=owner
    subprocess.run([sys.executable,'-m','alembic','downgrade','0006_gitops_requests'],cwd=ROOT,env=env,check=True,capture_output=True)
    with psycopg.connect(url) as db:
        context(db,a['tenant_id'])
        assert db.execute('SELECT notification_status FROM scan_jobs WHERE id=%s',(job_id,)).fetchone()[0]=='failed'
        assert db.execute("SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid='scan_jobs'::regclass").fetchone()==(True,True)
    migrate(owner,'head')
    assert store.get(a['tenant_id'],snapshot['scan_id'])==snapshot
    from database.delivery import DeliveryRepository
    assert DeliveryRepository(url).list(a['tenant_id'])==[]


def test_interactive_job_submission_is_atomic_idempotent_and_tenant_isolated(tenants, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from workers.storage import JobRepository, SubmissionConflict
    from database.delivery import DeliveryRepository
    url, _, a, b, _, _ = tenants
    jobs = JobRepository(url)
    with jobs.transaction(a['tenant_id']) as db:
        db.execute("UPDATE tenants SET connection_status='connected'")
        db.execute('UPDATE subscriptions SET active=true')
    key = str(uuid4())
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(lambda _: jobs.submit(a['tenant_id'], key, a['subscription_ids']), range(4)))
    job_id = rows[0]['job_id']
    assert {row['job_id'] for row in rows} == {job_id}
    assert rows[0]['status'] == 'queued'
    assert jobs.job_status(b['tenant_id'], job_id) is None
    assert jobs.list_jobs(b['tenant_id'], 50) == []
    assert jobs.job_origin(a['tenant_id'], job_id) == 'interactive'
    assert JobRepository(url).job_status(a['tenant_id'], job_id)['status'] == 'queued'
    assert len(DeliveryRepository(url).list(a['tenant_id'])) == 1
    with pytest.raises(SubmissionConflict, match='Idempotency'):
        jobs.submit(a['tenant_id'], key, [str(uuid4())])
    assert len(jobs.list_jobs(a['tenant_id'], 100)) == 1
    # A delivery insert failure must not leave an orphan queued job.
    monkeypatch.setattr('database.delivery.enqueue', lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError('insert failed')))
    with pytest.raises(RuntimeError):
        jobs.submit(a['tenant_id'], str(uuid4()), a['subscription_ids'])
    assert len(jobs.list_jobs(a['tenant_id'], 100)) == 1


def test_interactive_backlog_bound_and_revoked_scope(tenants):
    from workers.storage import JobRepository, SubmissionConflict
    url, _, a, _, _, _ = tenants
    jobs = JobRepository(url)
    with pytest.raises(SubmissionConflict, match='connected'):
        jobs.submit(a['tenant_id'], str(uuid4()), a['subscription_ids'])
    with jobs.transaction(a['tenant_id']) as db:
        db.execute("UPDATE tenants SET connection_status='connected'")
        db.execute('UPDATE subscriptions SET active=true')
    for _ in range(5):
        jobs.submit(a['tenant_id'], str(uuid4()), a['subscription_ids'])
    with pytest.raises(SubmissionConflict, match='five unfinished'):
        jobs.submit(a['tenant_id'], str(uuid4()), a['subscription_ids'])


def test_starter_interactive_worker_completes_without_scheduled_entitlement(tenants):
    from workers.storage import JobRepository
    from workers.tasks import run_scan_job
    from tests.test_worker import Lease
    from tests.support import stub_scanner
    url, store, a, b, _, _ = tenants
    jobs = JobRepository(url)
    with jobs.transaction(a['tenant_id']) as db:
        db.execute("UPDATE tenants SET connection_status='connected'")
        db.execute('UPDATE subscriptions SET active=true')
    row = jobs.submit(a['tenant_id'], str(uuid4()), a['subscription_ids'])
    class OwnedLease(Lease):
        def acquire(self, tenant_id, token):
            return True
    settings = Settings('azure', 'unused', (a,), url)
    result = run_scan_job(settings, a['tenant_id'], a['subscription_ids'], row['job_id'], jobs, OwnedLease(), scanner=stub_scanner)
    assert result['status'] == 'completed'
    snapshot = store.get(a['tenant_id'], result['scan_id'])
    assert snapshot['cloud_providers'] == ['azure'] and snapshot['scope_fingerprint']
    assert store.get(b['tenant_id'], result['scan_id']) is None
    assert jobs.job_status(a['tenant_id'], row['job_id'])['scan_id'] == result['scan_id']


def test_pooled_connections_clear_tenant_context_and_recover_after_rollback(tenants):
    from database.connection import connect
    from psycopg.rows import dict_row
    url, _, a, b, _, _ = tenants
    with connect(url) as db:
        context(db, a['tenant_id'])
        assert {str(row[0]) for row in db.execute('SELECT tenant_id FROM scans')} == {a['tenant_id']}
    with pytest.raises(errors.DivisionByZero):
        with connect(url, row_factory=dict_row) as db:
            context(db, b['tenant_id'])
            assert db.execute('SELECT tenant_id FROM scans').fetchone()['tenant_id'] == UUID(b['tenant_id'])
            db.execute('SELECT 1/0')
    with connect(url) as db:
        assert db.execute('SELECT count(*) FROM scans').fetchone() == (0,)
        context(db, b['tenant_id'])
        assert {str(row[0]) for row in db.execute('SELECT tenant_id FROM scans')} == {b['tenant_id']}


def test_interactive_http_accepts_without_scanning_and_survives_restart(tenants, monkeypatch, tmp_path):
    import hashlib
    from workers.storage import JobRepository
    url, _, a, b, _, _ = tenants
    jobs = JobRepository(url)
    with jobs.transaction(a['tenant_id']) as db:
        db.execute("UPDATE tenants SET connection_status='connected'")
        db.execute('UPDATE subscriptions SET active=true')
    configured = tuple(dict(t, api_key_sha256=hashlib.sha256(key.encode()).hexdigest()) for t, key in [(a, 'key-a'), (b, 'key-b')])
    settings = Settings('azure', str(tmp_path / 'unused'), configured, url)
    monkeypatch.setenv('CLOUDSAVER_INTERACTIVE_JOBS', 'true')
    monkeypatch.setenv('CLOUDSAVER_DELIVERY_ENABLED', 'true')
    def scanner(_):
        pytest.fail('HTTP submission must not execute a cloud scan')
    payload = {'subscription_ids': a['subscription_ids'], 'idempotency_key': str(uuid4())}
    auth = {'Authorization': 'Bearer key-a'}
    with TestClient(create_app(settings, scanner=scanner)) as client:
        assert client.post('/api/v1/scan-jobs', json=payload).status_code == 401
        response = client.post('/api/v1/scan-jobs', json=payload, headers=auth)
        assert response.status_code == 202 and response.headers['retry-after'] == '3'
        location = response.headers['location']
        assert response.json()['status'] == 'queued' and response.json()['result_url'] is None
        assert client.post('/api/v1/scan-jobs', json=payload, headers=auth).json()['job_id'] == response.json()['job_id']
        assert client.get(location, headers={'Authorization': 'Bearer key-b', 'X-Tenant-ID': a['tenant_id']}).status_code == 404
    with TestClient(create_app(settings, scanner=scanner)) as client:
        assert client.get(location, headers=auth).json()['status'] == 'queued'
        assert client.get('/api/v1/scan-jobs', headers=auth).json()[0]['poll_url'] == location
        monkeypatch.setenv('CLOUDSAVER_INTERACTIVE_JOBS', 'false')
        assert client.post('/api/v1/scan-jobs', json=payload, headers=auth).status_code == 503


def test_tenant_registry_seeds_once_syncs_domain_and_rejects_stale_writes(database):
    import hashlib
    from app.tenant_config import normalize_tenant
    from app.tenant_registry import PostgresRegistry, VersionConflict
    owner, app, _ = database
    tid, keep, drop = str(uuid4()), str(uuid4()), str(uuid4())
    seed = normalize_tenant(dict(tenant_id=tid, name='Registry workspace', plan_tier='GROWTH',
                                 subscription_ids=[keep, drop], api_key_sha256=hashlib.sha256(tid.encode()).hexdigest()))
    registry = PostgresRegistry(app, (seed,), ttl=0)
    assert registry.get(tid)['version'] == 1
    assert PostgresRegistry(app, (dict(seed, name='Ignored reseed'),), ttl=0).get(tid)['name'] == 'Registry workspace'
    updated = registry.update(tid, {'subscription_ids': [keep], 'plan_tier': 'ENTERPRISE'}, 1, 'test',
                              webhook='https://hooks.slack.com/services/T000/B000/abc')
    assert updated['version'] == 2 and updated['webhook_configured'] is True
    with pytest.raises(VersionConflict):
        registry.update(tid, {'name': 'Stale'}, 1, 'test')
    with psycopg.connect(app) as db:
        context(db, tid)
        active = dict(db.execute('SELECT subscription_id::text, active FROM subscriptions').fetchall())
        assert active == {keep: True, drop: False}
        assert db.execute('SELECT plan_tier FROM organizations').fetchall() == [('ENTERPRISE',)]
        assert db.execute('SELECT count(*) FROM settings_audit WHERE tenant_id=%s', (tid,)).fetchone() == (2,)
        with pytest.raises(errors.InsufficientPrivilege):
            db.execute('DELETE FROM settings_audit')


def test_architecture_analysis_reads_use_runtime_rls_and_preserve_saved_evidence(tenants):
    import hashlib
    from app.ai_advisory import AIGateway
    app, store, a, b, sa, sb = tenants
    key_a, key_b = 'architecture-a-key-at-least-32-characters', 'architecture-b-key-at-least-32-characters'
    for row, key in ((a,key_a),(b,key_b)):
        row['api_key_sha256'] = hashlib.sha256(key.encode()).hexdigest()
    settings = Settings('azure', ':memory:', (a,b), database_url=app)
    with TestClient(create_app(settings, ai_gateway=AIGateway(enabled=False))) as client:
        path = '/api/v1/scans/' + sa['scan_id']
        assert client.get(path+'/analysis', headers={'Authorization':'Bearer '+key_b}).status_code == 404
        result = client.post(path+'/analysis/resource', headers={'Authorization':'Bearer '+key_a},
                             json={'resource_id':sa['findings'][0]['resource_id'],'rule_id':'ORPHANED_DISK'})
        assert result.status_code == 200 and result.json()['assessment']['retail_estimate_usd'] is None
        assert store.get(a['tenant_id'],sa['scan_id']) == sa


def test_enterprise_ledger_and_billing_use_forced_rls_and_append_only_evidence(tenants):
    from app.enterprise_store import EnterpriseStore
    from app.inference_ledger import InferenceLedger
    from app.focus import FocusRepository,ImportRequest
    from tests.test_enterprise import batch,charge,result
    from datetime import date
    app,_,a,b,sa,_=tenants
    settings=Settings('azure','unused',(a,b),app)
    persistence=EnterpriseStore(settings);ledger=InferenceLedger(persistence)
    meta=dict(scan_id=sa['scan_id'],provider='azure',model='injected-test-model',target_id='review',resource_reference='a'*64)
    key=str(uuid4());calls=[]
    first=ledger.run(a['tenant_id'],key,'f'*64,10,lambda:(calls.append(1) or result()),metadata=meta)
    assert InferenceLedger(EnterpriseStore(settings)).run(a['tenant_id'],key,'f'*64,10,result,metadata=meta)['cached']
    assert len(calls)==1 and ledger.usage(a['tenant_id'])['groups'][0]['input_tokens']==100
    assert ledger.page(a['tenant_id'])['items'][0]['status']=='completed'
    assert ledger.get(b['tenant_id'],first['assessment_id']) is None
    assert ledger.page(b['tenant_id'])['items']==[]
    billing=FocusRepository(persistence)
    payload=ImportRequest.model_validate(batch([charge(1,SubAccountId=a['subscription_ids'][0])],sub_account_id=a['subscription_ids'][0]))
    billing.import_records(a,payload)
    assert billing.summary(a,date(2026,10,1),date(2026,10,22),'USD')['billed_cost']=='10.00000000'
    assert billing.summary(b,date(2026,10,1),date(2026,10,22),'USD')['records']==0
    tables=('ai_inference_attempts','ai_inference_events','focus_imports','focus_charges')
    with psycopg.connect(app) as db:
        for table in tables:
            assert db.execute('SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid=%s::regclass',(table,)).fetchone()==(True,True)
            assert db.execute(sql.SQL('SELECT count(*) FROM {}').format(sql.Identifier(table))).fetchone()[0]==0
        context(db,a['tenant_id'])
        assert db.execute('SELECT count(*) FROM ai_inference_attempts').fetchone()[0]==1
        with pytest.raises(errors.InsufficientPrivilege): db.execute('DELETE FROM focus_charges')
        db.rollback();context(db,a['tenant_id'])
        with pytest.raises(errors.InsufficientPrivilege): db.execute("UPDATE ai_inference_events SET action='uncertain'")
        db.rollback();context(db,a['tenant_id'])
        with pytest.raises(errors.CheckViolation): db.execute("UPDATE ai_inference_attempts SET status='uncertain' WHERE id=%s",(first['assessment_id'],))
        db.rollback();context(db,a['tenant_id'])
        with pytest.raises(errors.InsufficientPrivilege):
            db.execute("INSERT INTO ai_inference_events(id,tenant_id,attempt_id,action) VALUES (%s,%s,%s,'claimed')",(uuid4(),b['tenant_id'],first['assessment_id']))


def test_resource_batches_followups_and_decisions_use_forced_rls(tenants):
    import hashlib
    from app.ai_advisory import AIGateway
    from app.enterprise_store import EnterpriseStore
    from app.inference_ledger import InferenceLedger
    from app.resource_batches import process_batches
    from app.resource_store import ResourceConflict, ResourceStore
    from tests.test_resource_assessment import adapter_for
    app, store, a, b, sa, _ = tenants
    key_a, key_b = 'resource-rls-a-key-at-least-32-characters', 'resource-rls-b-key-at-least-32-characters'
    for row, key in ((a, key_a), (b, key_b)):
        row['api_key_sha256'] = hashlib.sha256(key.encode()).hexdigest()
    settings = Settings('azure', 'unused', (a, b), database_url=app)
    evidence, calls = EnterpriseStore(settings), []
    gateway = AIGateway(enabled=True, targets=[dict(target_id='review', tenant_id=a['tenant_id'], provider='azure', model='gpt-4o',
                                                    endpoint='https://hub.services.ai.azure.com', auth='managed_identity')],
                        budget=InferenceLedger(evidence), adapter=adapter_for(calls), limit=10)
    repo = ResourceStore(evidence)
    with TestClient(create_app(settings, ai_gateway=gateway)) as client:
        base = '/api/v1/scans/' + sa['scan_id']
        items = client.get(base + '/resources', headers={'Authorization': 'Bearer ' + key_a}).json()['items']
        assert items and client.get(base + '/resources', headers={'Authorization': 'Bearer ' + key_b}).status_code == 404
        batch = client.post(base + '/ai-batches', headers={'Authorization': 'Bearer ' + key_a}, json=dict(
            all=True, target_id='review', idempotency_key=str(uuid4()), acknowledge_external_processing=True))
        assert batch.status_code == 202, batch.text
        with pytest.raises(ResourceConflict):
            repo.create_batch(a['tenant_id'], scan_id=sa['scan_id'], target_id='review', request_key=str(uuid4()),
                              actor='0' * 64, items=[(items[0]['resource_key'], items[0]['evidence_digest'])])
        assert process_batches(settings.tenants, store, repo, gateway) == len(items) == len(calls)
        assert repo.batch(a['tenant_id'], batch.json()['id'])['status'] == 'completed'
        assert repo.batch(b['tenant_id'], batch.json()['id']) is None
        decided = client.post(f"/api/v1/resources/{items[0]['resource_key']}/decisions", headers={'Authorization': 'Bearer ' + key_a},
                              json=dict(scan_id=sa['scan_id'], decision='accept', evidence_digest=items[0]['evidence_digest']))
        assert decided.status_code == 201, decided.text
        assert repo.latest_decisions(b['tenant_id']) == {}
        listing = client.get(base + '/resources', headers={'Authorization': 'Bearer ' + key_a}).json()
        assert listing['items'][0]['ai']['status'] == 'completed'
        assert listing['items'][0]['decision'] is not None
    tables = ('ai_batches', 'ai_batch_items', 'ai_followups', 'resource_decisions')
    with psycopg.connect(app) as db:
        for table in tables:
            assert db.execute('SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid=%s::regclass', (table,)).fetchone() == (True, True)
            assert db.execute(sql.SQL('SELECT count(*) FROM {}').format(sql.Identifier(table))).fetchone()[0] == 0
        context(db, a['tenant_id'])
        assert db.execute('SELECT count(*) FROM resource_decisions').fetchone()[0] == 1
        with pytest.raises(errors.InsufficientPrivilege): db.execute("UPDATE resource_decisions SET decision='dismiss'")
        db.rollback(); context(db, a['tenant_id'])
        with pytest.raises(errors.InsufficientPrivilege): db.execute('DELETE FROM ai_batch_items')
        db.rollback(); context(db, a['tenant_id'])
        with pytest.raises(errors.InsufficientPrivilege):
            db.execute("""INSERT INTO resource_decisions(id,tenant_id,resource_key,scan_id,decision,evidence_digest,actor)
                VALUES (%s,%s,%s,%s,'accept',%s,%s)""", (uuid4(), b['tenant_id'], 'a' * 64, sa['scan_id'], 'b' * 64, 'c' * 64))
