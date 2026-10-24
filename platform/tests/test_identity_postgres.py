"""token-db boundaries through the real identity roles: forced RLS, append-only audit, digest-only storage."""
import hashlib
import os
import secrets
import subprocess
import sys
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg import errors, sql

from identity.domain import utcnow
from identity.events import MemoryEvents
from identity.importer import import_directory
from identity.keys import Peppers
from identity.service import IdentityService
from identity.store_postgres import PostgresStore
from identity.throttle import MemoryBackend, Throttle
from identity.usage import UsageRecorder

pytestmark = pytest.mark.postgres
ROOT = Path(__file__).resolve().parents[1]
TID = str(uuid4())
SID = str(uuid4())
OPERATOR = {'actor': 'operator-key', 'actor_type': 'operator'}
TABLES = ('directory.customers', 'directory.workspaces', 'directory.workspace_azure_subscriptions',
          'directory.workspace_aws_accounts', 'directory.workspace_gcp_projects', 'directory.workspace_kubernetes_clusters',
          'directory.platform_settings', 'directory.directory_changes', 'identity.api_keys', 'identity.key_events',
          'identity.key_usage_hourly', 'identity.verification_failures_minute', 'directory.access_checks',
          'identity.service_accounts', 'identity.cache_events', 'identity.customer_memberships',
          'identity.workspace_memberships', 'identity.users', 'directory.ai_foundry_policy')


def test_separate_knowledge_database_governance(token_db):
    """Real migrations, separate credentials, forced RLS and independent publication reviews."""
    from sqlalchemy.engine import make_url
    from identity.knowledge.store import PostgresKnowledgeStore
    from test_identity import build
    privileged = os.environ['CLOUDSAVER_TEST_PRIVILEGED_URL']
    name = 'knowledge_test_' + uuid4().hex
    password = secrets.token_urlsafe(24)
    base = make_url(privileged).set(database=name)
    owner = base.set(username='knowledge_owner', password=password).render_as_string(hide_password=False)
    runtime = base.set(username='knowledge_app', password=password).render_as_string(hide_password=False)
    with psycopg.connect(privileged, autocommit=True) as admin:
        for role in ('knowledge_owner', 'knowledge_app'):
            admin.execute(sql.SQL('CREATE ROLE {} LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE PASSWORD {}')
                          .format(sql.Identifier(role), sql.Literal(password)))
        admin.execute(sql.SQL('CREATE DATABASE {} OWNER knowledge_owner').format(sql.Identifier(name)))
        admin.execute(sql.SQL('REVOKE ALL ON DATABASE {} FROM PUBLIC').format(sql.Identifier(name)))
        admin.execute(sql.SQL('GRANT CONNECT ON DATABASE {} TO knowledge_app').format(sql.Identifier(name)))
    try:
        env = dict(os.environ, PLATFORM_KNOWLEDGE_MIGRATION_URL=owner, PLATFORM_IDENTITY_MIGRATION_URL=token_db[0])
        subprocess.run([sys.executable, '-m', 'alembic', '-c', 'knowledge_alembic.ini', 'upgrade', 'head'],
                       cwd=ROOT, env=env, check=True, capture_output=True)
        service = build()
        service.knowledge_store = PostgresKnowledgeStore(runtime, token_db[1])
        created = service.create_knowledge_publication({'title': 'Public storage guidance',
            'summary': 'Verify recovery before any storage change.', 'body': 'Independent synthetic guidance.'}, OPERATOR)
        for version, kind, role in ((1, 'technical', 'KnowledgeReviewer'), (2, 'privacy', 'PrivacyReviewer')):
            service.review_knowledge_publication(created['id'], {'version': version, 'review': kind},
                {'actor': kind, 'actor_type': 'operator', 'roles': [role]})
        service.update_knowledge_publication(created['id'], {'version': 3, 'status': 'published'}, OPERATOR)
        assert service.knowledge_metrics()['active_published'] == 1
        assert service.retrieve_knowledge('azure', 'storage')['items'][0]['publication_id'] == created['id']
        with psycopg.connect(runtime) as db:
            flags = db.execute("SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid='knowledge.publications'::regclass").fetchone()
            assert flags == (True, True)
            assert db.execute("SELECT to_regclass('directory.customers')").fetchone()[0] is None
    finally:
        with psycopg.connect(privileged, autocommit=True) as admin:
            admin.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))


@pytest.fixture(scope='module')
def token_db():
    from sqlalchemy.engine import make_url
    privileged = os.getenv('CLOUDSAVER_TEST_PRIVILEGED_URL')
    if not privileged:
        pytest.skip('Requires the disposable integration runner')
    name = 'identity_test_' + uuid4().hex
    passwords = {role: secrets.token_urlsafe(24) for role in ('identity_owner', 'identity_app')}
    with psycopg.connect(privileged, autocommit=True) as admin:
        for role, password in passwords.items():
            exists = admin.execute('SELECT 1 FROM pg_roles WHERE rolname=%s', (role,)).fetchone()
            verb = 'ALTER' if exists else 'CREATE'
            admin.execute(sql.SQL(verb + ' ROLE {} LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE PASSWORD {}')
                          .format(sql.Identifier(role), sql.Literal(password)))
        if not admin.execute("SELECT 1 FROM pg_roles WHERE rolname='identity_retention'").fetchone():
            admin.execute('CREATE ROLE identity_retention NOLOGIN NOSUPERUSER NOBYPASSRLS')
        admin.execute('GRANT identity_retention TO identity_owner')
        admin.execute(sql.SQL('CREATE DATABASE {} OWNER identity_owner').format(sql.Identifier(name)))
        admin.execute(sql.SQL('REVOKE ALL ON DATABASE {} FROM PUBLIC').format(sql.Identifier(name)))
        admin.execute(sql.SQL('GRANT CONNECT ON DATABASE {} TO identity_app').format(sql.Identifier(name)))
    base = make_url(privileged).set(database=name)
    owner = base.set(username='identity_owner', password=passwords['identity_owner']).render_as_string(hide_password=False)
    app = base.set(username='identity_app', password=passwords['identity_app']).render_as_string(hide_password=False)
    env = dict(os.environ, CLOUDSAVER_IDENTITY_MIGRATION_URL=owner)
    migration = subprocess.run([sys.executable, '-m', 'alembic', '-c', 'identity_alembic.ini', 'upgrade', 'head'], cwd=ROOT, env=env,
                              capture_output=True, text=True)
    assert migration.returncode == 0, migration.stderr
    yield owner, app
    with psycopg.connect(privileged, autocommit=True) as admin:
        admin.execute(sql.SQL('DROP DATABASE IF EXISTS {} WITH (FORCE)').format(sql.Identifier(name)))


@pytest.fixture(scope='module')
def service(token_db):
    return IdentityService(PostgresStore(token_db[1]), Peppers(1, secrets.token_bytes(32)), Throttle(MemoryBackend()),
                           MemoryEvents(), UsageRecorder(last_used_interval=0), environment='development',
                           cache_seconds=15, provider_scoped_keys=True)


def test_every_table_forces_row_level_security(token_db):
    with psycopg.connect(token_db[0]) as db:
        rows = db.execute('SELECT n.nspname || \'.\' || c.relname, c.relrowsecurity, c.relforcerowsecurity FROM pg_class c '
                          "JOIN pg_namespace n ON n.oid=c.relnamespace WHERE c.relkind='r' AND n.nspname IN ('directory','identity') "
                          "AND c.relname <> 'alembic_version'").fetchall()
    assert {r[0] for r in rows} == set(TABLES)
    assert all(r[1] and r[2] for r in rows)


def test_rule_parameter_revision_uses_real_jsonb_and_preserves_forced_rls(service, token_db):
    tid = str(uuid4())
    customer = service.create_customer({'name': 'Policy integration'}, OPERATOR)
    service.create_workspace({'tenant_id': tid, 'customer_id': customer['id'], 'name': 'Rules',
                              'plan_tier': 'ENTERPRISE'}, OPERATOR)
    policy = service.list_workspace_analysis_rules(tid)
    updated = service.update_workspace_analysis_rules(tid, {'version': policy['version'], 'rules': [
        {'rule_id': 'AZURE_DISK_UNATTACHED_RETENTION', 'enabled': True, 'parameters': {'minimum_days': 21}}]}, OPERATOR)
    assert updated['version'] == policy['version'] + 1
    rule = next(r for r in updated['items'] if r['id'] == 'AZURE_DISK_UNATTACHED_RETENTION')
    assert rule['parameters'] == {'minimum_days': 21}
    with psycopg.connect(token_db[1]) as db:
        assert db.execute("SELECT relforcerowsecurity FROM pg_class WHERE oid='analysis.rule_catalog'::regclass").fetchone() == (True,)


def test_global_ai_policy_persists_with_forced_rls_and_audit(service, token_db):
    row = service.get_ai_policy()
    policy = row['policy']
    policy['allowed_models']['azure'] = ['approved-test-model']
    policy['allowed_regions']['azure'] = ['eastus']
    changed = service.update_ai_policy({'version': row['version'], 'policy': policy}, OPERATOR)
    assert changed['version'] == row['version'] + 1
    assert service.get_ai_policy()['policy']['allowed_models']['azure'] == ['approved-test-model']
    with psycopg.connect(token_db[1]) as db:
        assert db.execute("SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid='directory.ai_foundry_policy'::regclass").fetchone() == (True,True)
        assert db.execute("SELECT details->>'version' FROM identity.key_events WHERE action='ai_policy_updated' ORDER BY occurred_at DESC LIMIT 1").fetchone()[0] == str(changed['version'])


def test_runtime_store_refuses_the_owner_role(token_db):
    with psycopg.connect(token_db[0]) as db:
        privileged = db.execute('SELECT rolcreaterole FROM pg_roles WHERE rolname=current_user').fetchone()[0]
    if privileged:
        with pytest.raises(ValueError):
            PostgresStore(token_db[0])


def test_directory_and_key_lifecycle_on_postgres(service, token_db):
    customer = service.create_customer({'name': 'Fabrikam'}, OPERATOR)
    service.create_workspace({'tenant_id': TID, 'customer_id': customer['id'], 'name': 'Fabrikam prod', 'plan_tier': 'GROWTH'},
                             OPERATOR, scopes={'subscription_ids': [SID]})
    issued = service.issue_key(TID, {'name': 'Dashboard', 'roles': ['Viewer'], 'all_providers': True,
                                     'expires_at': (utcnow() + timedelta(days=30)).isoformat()}, OPERATOR)
    grant = service.verify(issued['secret'], '203.0.113.9', 'gateway')
    assert grant['valid'] and grant['tenant_id'] == TID and grant['allowed_providers'] == ['azure']
    service.usage.flush(service.store)
    assert service.get_key(issued['key']['key_id'])['last_used_ip'] == '203.0.113.9'
    assert service.key_usage(issued['key']['key_id'])['items'][0]['success_count'] == 1
    service.revoke_key(issued['key']['key_id'], {'reason': 'Rotation'}, OPERATOR)
    assert service.verify(issued['secret'], '203.0.113.9', 'gateway')['reason'] == 'revoked'
    assert service.changes(0)['items'][-1]['tenant_id'] == TID
    with psycopg.connect(token_db[0]) as db:
        stored = db.execute('SELECT secret_digest, legacy_sha256 FROM identity.api_keys').fetchall()
        dump = repr(db.execute('SELECT * FROM identity.key_events').fetchall())
    assert all(issued['secret'].encode() not in bytes(row[0]) for row in stored)
    assert issued['secret'] not in dump


def test_legacy_import_upgrades_on_first_use(service):
    legacy = secrets.token_hex(32)
    tenant = {'tenant_id': str(uuid4()), 'name': 'Imported', 'plan_tier': 'STARTER', 'subscription_ids': [str(uuid4())],
              'api_key_sha256': hashlib.sha256(legacy.encode()).hexdigest(), 'active': True}
    assert import_directory(service, [tenant], 'registry_import')['keys'] == 1
    assert service.verify(legacy, '203.0.113.10', 'gateway')['valid']
    keys = service.list_keys(tenant['tenant_id'])['items']
    assert keys[0]['format'] == 'legacy' and keys[0]['source'] == 'registry_import'
    assert import_directory(service, [tenant], 'registry_import')['skipped_keys'] == 1
    assert service.verify(legacy, '203.0.113.10', 'gateway')['valid']


def test_audit_is_append_only_and_customers_cannot_be_deleted(service, token_db):
    with psycopg.connect(token_db[1]) as db:
        with pytest.raises(errors.InsufficientPrivilege):
            db.execute("UPDATE identity.key_events SET action='edited'")
    with psycopg.connect(token_db[1]) as db:
        with pytest.raises(errors.InsufficientPrivilege):
            db.execute('DELETE FROM identity.key_events')
    with psycopg.connect(token_db[1]) as db:
        with pytest.raises(errors.InsufficientPrivilege):
            db.execute('DELETE FROM directory.customers')
    with psycopg.connect(token_db[1]) as db:
        with pytest.raises(errors.InsufficientPrivilege):
            db.execute('TRUNCATE identity.key_events')


def test_revoked_keys_stay_revoked(service, token_db):
    with psycopg.connect(token_db[1]) as db:
        with pytest.raises(errors.InsufficientPrivilege):
            db.execute('UPDATE identity.api_keys SET revoked_at=NULL WHERE revoked_at IS NOT NULL')
