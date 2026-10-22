"""Run integration tests against a disposable PostgreSQL 16 container.

No existing database is modified. Requires Docker, requirements-dev.txt and a
published loopback port. Credentials live only in a temporary private directory.
"""
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import time

import psycopg
from psycopg import sql

ROOT = Path(__file__).resolve().parents[1]


def docker(*args):
    env = os.environ.copy()
    for key in ('DOCKER_HOST', 'DOCKER_CONTEXT', 'DOCKER_TLS', 'DOCKER_TLS_VERIFY', 'DOCKER_CERT_PATH'):
        env.pop(key, None)
    return subprocess.check_output(['docker', '--host=unix:///var/run/docker.sock', *args],
                                   env=env, text=True, stderr=subprocess.PIPE).strip()


def main():
    name = 'cloudsaver-test-' + secrets.token_hex(6)
    password = secrets.token_hex(32)
    with tempfile.TemporaryDirectory(prefix='cloudsaver-postgres-') as temporary:
        settings = Path(temporary) / 'postgres.env'
        settings.write_text(f'POSTGRES_PASSWORD={password}\nPOSTGRES_DB=cloudsaver_test\n')
        settings.chmod(0o600)
        try:
            docker('run', '-d', '--name', name, '--env-file', str(settings),
                   '--tmpfs', '/var/lib/postgresql/data', '-p', '127.0.0.1::5432', 'postgres:16-alpine')
            info = json.loads(docker('inspect', name))[0]
            port = info['NetworkSettings']['Ports']['5432/tcp'][0]['HostPort']
            privileged = f'postgresql://postgres:{password}@127.0.0.1:{port}/cloudsaver_test'
            deadline = time.monotonic() + 60
            while True:
                try:
                    with psycopg.connect(privileged, connect_timeout=2) as db:
                        for role in ('cloudsaver_owner', 'cloudsaver_app'):
                            db.execute(sql.SQL('CREATE ROLE {} LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE PASSWORD {}').format(
                                sql.Identifier(role), sql.Literal(password)))
                        db.execute('ALTER DATABASE cloudsaver_test OWNER TO cloudsaver_owner')
                        db.execute('GRANT ALL ON SCHEMA public TO cloudsaver_owner')
                    break
                except psycopg.OperationalError:
                    if time.monotonic() > deadline:
                        raise RuntimeError('Disposable PostgreSQL did not become ready') from None
                    time.sleep(0.5)
            env = os.environ.copy()
            env.update(CLOUDSAVER_TEST_OWNER_URL=privileged.replace('://postgres:', '://cloudsaver_owner:'),
                       CLOUDSAVER_TEST_APP_URL=privileged.replace('://postgres:', '://cloudsaver_app:'),
                       CLOUDSAVER_TEST_PRIVILEGED_URL=privileged)
            return subprocess.call([sys.executable, '-m', 'pytest', '-q', *sys.argv[1:]], cwd=ROOT, env=env)
        finally:
            docker('rm', '-f', name)


if __name__ == '__main__':
    raise SystemExit(main())
