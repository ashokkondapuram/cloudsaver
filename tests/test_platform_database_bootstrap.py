"""Exercise platform DB initialization without touching an existing volume."""
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time

import psycopg
import pytest
from sqlalchemy.engine import URL

from scripts.test_postgres import docker

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.postgres


@pytest.fixture(scope='module')
def platform_bootstrap_database(tmp_path_factory):
    if not os.getenv('CLOUDSAVER_TEST_PRIVILEGED_URL'):
        pytest.skip('Use python scripts/test_postgres.py for disposable PostgreSQL tests')
    name = 'cloudsaver-platform-bootstrap-' + secrets.token_hex(6)
    directory = tmp_path_factory.mktemp('platform-bootstrap')
    initializer = directory / '00-identity.sh'
    initializer.write_bytes((ROOT / 'platform/platform-db/init.sh').read_bytes())
    initializer.chmod(0o755)
    bootstrap = directory / 'platform-bootstrap.sql'
    bootstrap.write_bytes((ROOT / 'platform/platform-db/bootstrap.sql').read_bytes())
    bootstrap.chmod(0o644)
    passwords = {'postgres': secrets.token_hex(32),
                 'identity_owner': "owner'quoted\\" + secrets.token_hex(16),
                 'identity_app': "app'quoted\\" + secrets.token_hex(16)}
    settings = directory / 'postgres.env'
    settings.write_text('POSTGRES_PASSWORD=' + passwords['postgres'] + '\nPOSTGRES_USER=postgres\n'
                        'IDENTITY_DB_OWNER_PASSWORD=' + passwords['identity_owner'] + '\n'
                        'IDENTITY_DB_APP_PASSWORD=' + passwords['identity_app'] + '\n')
    settings.chmod(0o600)
    started = False
    try:
        docker('run', '-d', '--name', name, '--env-file', str(settings),
               '--mount', f'type=bind,source={initializer},target=/docker-entrypoint-initdb.d/00-identity.sh,readonly',
               '--mount', f'type=bind,source={bootstrap},target=/opt/cloudsaver/platform-bootstrap.sql,readonly',
               '--tmpfs', '/var/lib/postgresql/data', '-p', '127.0.0.1::5432', 'postgres:16-alpine')
        started = True
        info = json.loads(docker('inspect', name))[0]
        port = info['NetworkSettings']['Ports']['5432/tcp'][0]['HostPort']
        admin = URL.create('postgresql', username='postgres', password=passwords['postgres'],
                           host='127.0.0.1', port=int(port), database='postgres').render_as_string(hide_password=False)
        deadline = time.monotonic() + 60
        while True:
            try:
                with psycopg.connect(admin, connect_timeout=2):
                    break
            except psycopg.OperationalError:
                if time.monotonic() >= deadline:
                    raise RuntimeError('Platform bootstrap test PostgreSQL did not become ready') from None
                time.sleep(0.5)
        yield name, directory, port, passwords, admin
    finally:
        if started:
            docker('rm', '-f', name)


def test_platform_bootstrap_and_explicit_password_repair_preserve_data(platform_bootstrap_database):
    name, directory, port, passwords, admin = platform_bootstrap_database

    def connect(role, password):
        return psycopg.connect(host='127.0.0.1', port=port, dbname='identity', user=role,
                               password=password, connect_timeout=3)

    with connect('identity_owner', passwords['identity_owner']) as db:
        db.execute('CREATE TABLE public.recovery_test (value text)')
        db.execute("INSERT INTO public.recovery_test VALUES ('retained history')")
    with psycopg.connect(admin) as db:
        assert db.execute('SELECT rolname, rolcanlogin, rolsuper, rolbypassrls, '
                          'rolcreatedb, rolcreaterole, rolreplication FROM pg_roles '
                          "WHERE rolname LIKE 'identity_%' ORDER BY rolname").fetchall() == [
            ('identity_app', True, False, False, False, False, False),
            ('identity_owner', True, False, False, False, False, False),
            ('identity_retention', False, False, False, False, False, False)]
        assert db.execute("SELECT has_database_privilege('identity_app', 'identity', 'CONNECT')").fetchone()[0]

    replacement = {'identity_owner': secrets.token_hex(32), 'identity_app': secrets.token_hex(32)}
    settings = directory / 'replacement.env'
    settings.write_text('IDENTITY_DB_OWNER_PASSWORD=' + replacement['identity_owner'] + '\n'
                        'IDENTITY_DB_APP_PASSWORD=' + replacement['identity_app'] + '\n')
    settings.chmod(0o600)

    def initialize(*args):
        output = docker('exec', '--env-file', str(settings), name, 'sh',
                        '/docker-entrypoint-initdb.d/00-identity.sh', *args)
        assert all(secret not in output for secret in [*passwords.values(), *replacement.values()])
        return output

    assert 'existing role passwords preserved' in initialize()
    for role in replacement:
        with connect(role, passwords[role]):
            pass
        with pytest.raises(psycopg.OperationalError):
            connect(role, replacement[role])

    # Unsafe role attributes block recovery before any password changes commit.
    with psycopg.connect(admin) as db:
        db.execute('ALTER ROLE identity_app BYPASSRLS')
    try:
        with pytest.raises(subprocess.CalledProcessError):
            initialize('--reset-passwords')
        with connect('identity_owner', passwords['identity_owner']):
            pass
    finally:
        with psycopg.connect(admin) as db:
            db.execute('ALTER ROLE identity_app NOBYPASSRLS')

    # Do not take ownership of an unrelated existing database during recovery.
    with psycopg.connect(admin, autocommit=True) as db:
        db.execute('ALTER DATABASE identity OWNER TO postgres')
    try:
        with pytest.raises(subprocess.CalledProcessError):
            initialize('--reset-passwords')
    finally:
        with psycopg.connect(admin, autocommit=True) as db:
            db.execute('ALTER DATABASE identity OWNER TO identity_owner')
    with connect('identity_owner', passwords['identity_owner']):
        pass

    assert 'passwords aligned' in initialize('--reset-passwords')
    assert 'passwords aligned' in initialize('--reset-passwords')
    for role in replacement:
        with connect(role, replacement[role]):
            pass
        with pytest.raises(psycopg.OperationalError):
            connect(role, passwords[role])

    with connect('identity_owner', replacement['identity_owner']) as db:
        assert db.execute('SELECT value FROM public.recovery_test').fetchone()[0] == 'retained history'
    with psycopg.connect(admin) as db:
        # Retention remains a NOLOGIN role that the migration owner can assume.
        assert db.execute("SELECT pg_has_role('identity_owner', 'identity_retention', 'MEMBER')").fetchone()[0]

    owner = URL.create('postgresql', username='identity_owner', password=replacement['identity_owner'],
                       host='127.0.0.1', port=int(port), database='identity').render_as_string(hide_password=False)
    env = dict(os.environ, PLATFORM_IDENTITY_MIGRATION_URL=owner)
    subprocess.run([sys.executable, '-m', 'alembic', '-c', 'identity_alembic.ini', 'upgrade', 'head'],
                   cwd=ROOT / 'platform', env=env, check=True, capture_output=True, text=True)
    with connect('identity_owner', replacement['identity_owner']) as db:
        assert db.execute('SELECT version_num FROM identity.alembic_version').fetchone()[0] == 'i0013_multicloud_analysis_catalog'
        assert db.execute('SELECT value FROM public.recovery_test').fetchone()[0] == 'retained history'
