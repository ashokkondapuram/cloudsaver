"""Database boundaries tested through the real runtime role, independently of HTTP."""
from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

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
    legacy = {'scan_id': str(legacy_id), 'findings': [], 'mode': 'demo'}
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
    _, app, _ = database
    a, b = workspace(), workspace()
    keys = ('integration-workspace-a-key', 'integration-workspace-b-key')
    for tenant, key in zip((a, b), keys):
        tenant['api_key_sha256'] = hashlib.sha256(key.encode()).hexdigest()
    settings = Settings('demo', '', (a, b), app)
    headers = {'Authorization': 'Bearer ' + keys[0], 'X-Tenant-ID': b['tenant_id']}
    with TestClient(create_app(settings)) as client:
        assert client.get('/api/v1/me', headers={'X-Tenant-ID': a['tenant_id']}).status_code == 401
        assert client.get('/api/v1/me', headers=headers).json()['tenant_id'] == a['tenant_id']
        response = client.post('/api/v1/scans', headers=headers)
        assert response.status_code == 201
        result = response.json()
        assert client.get('/api/v1/scans/' + result['scan_id'], headers={'Authorization': 'Bearer ' + keys[1]}).status_code == 404
    with TestClient(create_app(settings)) as client:
        assert client.get('/api/v1/scans/' + result['scan_id'], headers=headers).json() == result


def test_billing_event_changes_persisted_entitlements(database):
    from database.billing_store import BillingStore
    from app.auth import with_plan
    owner, app, store = database
    a = workspace()
    store.save(a['tenant_id'], scan(a), workspace=a)
    customer, subscription = 'cus_'+uuid4().hex, 'sub_'+uuid4().hex
    with psycopg.connect(owner) as db:
        context(db,a['tenant_id'])
        organization = db.execute('UPDATE organizations SET stripe_customer_id=%s WHERE tenant_id=%s RETURNING id',
                                  (customer,a['tenant_id'])).fetchone()[0]
    event = dict(id='evt_'+uuid4().hex,type='customer.subscription.updated',created=100,
                 data={'object':dict(id=subscription,customer=customer,created=90,status='active',
                      items={'data':[dict(price={'id':'price_growth'},quantity=1)]})})
    route = dict(tenant_id=a['tenant_id'],organization_id=str(organization))
    billing = BillingStore(app)
    assert billing.apply_event(route,customer,event,{'price_growth':'GROWTH'}) == 'subscription_updated'
    assert billing.apply_event(route,customer,event,{'price_growth':'GROWTH'}) == 'duplicate'
    settings = Settings('demo','',(a,),app)
    assert with_plan(settings,dict(a,plan_tier='ENTERPRISE'))['plan_tier'] == 'GROWTH'
    event['id'] = 'evt_'+uuid4().hex
    event['created'] = 101
    event['type'] = 'customer.subscription.deleted'
    billing.apply_event(route,customer,event,{'price_growth':'GROWTH'})
    assert with_plan(settings,a)['plan_tier'] == 'STARTER'


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
        assert db.execute('SELECT version_num FROM alembic_version').fetchall() == [('0005_cloud_findings',)]


def test_scheduler_reservation_throttles_concurrent_publishers(database):
    from workers.storage import JobRepository
    _,app,store = database
    a = workspace()
    store.save(a['tenant_id'],scan(a),workspace=a)
    repository = JobRepository(app)
    assert repository.reserve_scheduled_job(a['tenant_id'],str(uuid4()),86400)
    assert not repository.reserve_scheduled_job(a['tenant_id'],str(uuid4()),86400)


def test_multi_cloud_findings_are_atomic_and_rls_isolated(database):
    from app.multi_cloud import demo_cloud_findings
    _, app, store = database
    a, b = workspace(), workspace()
    payload = scan(a)
    payload.update(mode='demo', cloud_providers=['aws','gcp','kubernetes'])
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


@pytest.mark.parametrize('starting_revision',['0002_scan_findings','0003_scan_jobs','0004_merge_hardening'])
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
        payload = {'scan_id':id,'mode':'demo','findings':[]}
        with psycopg.connect(owner_url) as db:
            context(db,tenant)
            db.execute('INSERT INTO scans VALUES (%s,%s,now(),%s)',(id,tenant,Jsonb(payload)))
        migrate(owner_url,'head')
        assert PostgresStore(app_url).get(tenant,id) == payload
    finally:
        with psycopg.connect(privileged,autocommit=True) as admin:
            admin.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(name)))
