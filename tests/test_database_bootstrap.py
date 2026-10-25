"""Exercise the actual first-boot failure on an isolated PostgreSQL cluster."""
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb

from database.bootstrap import ensure_database_bootstrap
from scripts.test_postgres import docker

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.postgres


@pytest.fixture(scope='module')
def bootstrap_database(tmp_path_factory):
    if not os.getenv('CLOUDSAVER_TEST_PRIVILEGED_URL'):
        pytest.skip('Use python scripts/test_postgres.py for disposable PostgreSQL tests')
    name = 'cloudsaver-bootstrap-test-' + secrets.token_hex(6)
    password = secrets.token_hex(32)
    settings = tmp_path_factory.mktemp('bootstrap') / 'postgres.env'
    settings.write_text(f'POSTGRES_PASSWORD={password}\nPOSTGRES_DB=cloudsaver_test\n')
    settings.chmod(0o600)
    started = False
    try:
        docker('run', '-d', '--name', name, '--env-file', str(settings),
               '--tmpfs', '/var/lib/postgresql/data', '-p', '127.0.0.1::5432', 'postgres:16-alpine')
        started = True
        info = json.loads(docker('inspect', name))[0]
        port = info['NetworkSettings']['Ports']['5432/tcp'][0]['HostPort']
        url = f'postgresql://postgres:{password}@127.0.0.1:{port}/cloudsaver_test'
        deadline = time.monotonic() + 60
        while True:
            try:
                with psycopg.connect(url, connect_timeout=2):
                    break
            except psycopg.OperationalError:
                if time.monotonic() >= deadline:
                    raise RuntimeError('Bootstrap test PostgreSQL did not become ready') from None
                time.sleep(0.5)
        yield url, port
    finally:
        if started:
            docker('rm', '-f', name)


def test_missing_role_recovery_migrations_and_repeat_preserve_data(bootstrap_database):
    url, port = bootstrap_database
    secret = "bootstrap'quoted\\password"
    tenant, scan = uuid4(), uuid4()
    payload = {'scan_id': str(scan), 'findings': []}
    with psycopg.connect(url) as db:
        # Match a partially initialized volume: existing data, no app role.
        db.execute('CREATE TABLE scans (id uuid PRIMARY KEY, tenant_id uuid NOT NULL, '
                   'timestamp timestamptz NOT NULL, payload jsonb NOT NULL)')
        db.execute('INSERT INTO scans VALUES (%s, %s, now(), %s)', (scan, tenant, Jsonb(payload)))

    with pytest.raises(RuntimeError, match='role cloudsaver_app is missing'):
        with psycopg.connect(url) as db:
            ensure_database_bootstrap(db, None)

    env = os.environ.copy()
    env.update(CLOUDSAVER_MIGRATION_URL=url, CLOUDSAVER_DB_PASSWORD=secret)
    subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', 'head'],
                   cwd=ROOT, env=env, check=True, capture_output=True, text=True)
    with psycopg.connect(url) as db:
        assert db.execute('SELECT version_num FROM alembic_version').fetchone()[0] == '0021_billing_jobs'
        assert db.execute('SELECT payload FROM scans WHERE id = %s', (scan,)).fetchone()[0] == payload

    # An attempted implicit password rotation is ignored on a subsequent run.
    env['CLOUDSAVER_DB_PASSWORD'] = secrets.token_hex(32)
    subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', 'head'],
                   cwd=ROOT, env=env, check=True, capture_output=True, text=True)
    with psycopg.connect(host='127.0.0.1', port=port, dbname='cloudsaver_test',
                         user='cloudsaver_app', password=secret) as db:
        assert db.execute('SELECT rolcanlogin, rolsuper, rolbypassrls, rolcreatedb, '
                          'rolcreaterole, rolreplication FROM pg_roles '
                          "WHERE rolname = current_user").fetchone() == (True, False, False, False, False, False)
        assert db.execute('SELECT count(*) FROM scans').fetchone()[0] == 0
        db.execute("SELECT set_config('app.current_tenant_id', %s, true)", (str(tenant),))
        assert db.execute('SELECT payload FROM scans WHERE id = %s', (scan,)).fetchone()[0] == payload
        db.execute("SELECT set_config('app.current_tenant_id', %s, true)", (str(uuid4()),))
        assert db.execute('SELECT count(*) FROM scans').fetchone()[0] == 0

    with psycopg.connect(url) as db:
        db.execute('ALTER ROLE cloudsaver_app BYPASSRLS')
    try:
        with pytest.raises(RuntimeError, match='without SUPERUSER, BYPASSRLS'):
            with psycopg.connect(url) as db:
                ensure_database_bootstrap(db, secret)
        with psycopg.connect(url) as db:
            assert db.execute("SELECT rolbypassrls FROM pg_roles WHERE rolname = 'cloudsaver_app'").fetchone()[0]
    finally:
        with psycopg.connect(url) as db:
            db.execute('ALTER ROLE cloudsaver_app NOBYPASSRLS')
