"""Expand-only upgrade preserves the prior control-plane history."""
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit,urlunsplit
from uuid import uuid4

import psycopg
from app.engineering.contracts import WorkloadCreate
from app.engineering.repository import Engineering
from app.enterprise_store import EnterpriseStore
from tests.test_outcomes import financial_postgres  # noqa: F401

ROOT=Path(__file__).resolve().parents[1]


def test_upgrade_from_0026_preserves_history_and_refuses_populated_downgrade(financial_postgres):
    owner=urlunsplit(urlsplit(os.environ['CLOUDSAVER_TEST_OWNER_URL'])._replace(path=urlsplit(financial_postgres).path))
    env={**os.environ,'CLOUDSAVER_MIGRATION_URL':owner}
    def migration(*args):
        return subprocess.run([sys.executable,'-m','alembic',*args],cwd=ROOT,env=env,capture_output=True,text=True)
    assert migration('downgrade','0026_control_plane').returncode==0
    tenant,plan,sub=str(uuid4()),str(uuid4()),str(uuid4())
    with psycopg.connect(financial_postgres) as db:
        db.execute("SELECT set_config('app.current_tenant_id',%s,true)",(tenant,))
        db.execute('INSERT INTO cp_plans(id,tenant_id,objective,owner_hash,created_at) VALUES(%s,%s,%s,%s,now())',(plan,tenant,'Retain existing plan','a'*64))
    assert migration('upgrade','head').returncode==0
    store=EnterpriseStore(SimpleNamespace(database_url=financial_postgres,database='/tmp/unused-engineering.db'))
    with store.transaction(tenant) as db:
        assert db.execute('SELECT objective FROM cp_plans WHERE id=%s',(plan,)).fetchone()[0]=='Retain existing plan'
    workload=Engineering(store).create(dict(tenant_id=tenant,subscription_ids=[sub]),
        WorkloadCreate.model_validate_json(__import__('json').dumps(dict(name='Upgrade test',environment='dev',owner='Owner',team='Team',scope_id=sub))),str(uuid4()))
    result=migration('downgrade','0026_control_plane')
    assert result.returncode!=0 and 'data-preserving rollback' in result.stderr
    with psycopg.connect(owner) as db:
        assert db.execute('SELECT version_num FROM alembic_version').fetchone()[0]=='0027_engineering_workloads'
    with store.transaction(tenant) as db:
        assert str(db.execute('SELECT id FROM engineering_workloads').fetchone()[0])==workload['id']
        assert db.execute("SELECT relforcerowsecurity FROM pg_class WHERE oid='engineering_workloads'::regclass").fetchone()[0]
