"""Original platform APIs return with current isolation and publication review."""
import json
import os
import re
import secrets
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from sqlalchemy.engine import make_url

from identity.app import create_app
from identity.domain import IdentityError
from identity.knowledge.store import PostgresKnowledgeStore
from test_identity import build, OPERATOR


def test_original_platform_route_contracts_are_available():
    app = create_app(service=build(), callers={'portal': 'a' * 64})
    normalize = lambda path: re.sub(r'\{[^}]+\}', '{}', path)
    live = {(method.upper(), normalize(path)) for path, methods in app.openapi()['paths'].items()
            for method in methods}
    manifest = json.loads((Path(__file__).resolve().parents[2] / 'tests/fixtures/restored_673c20a_routes.json').read_text())
    missing = [route for route in manifest['platform'] if (route[0], normalize(route[1])) not in live]
    assert missing == []


@pytest.mark.parametrize('content', ['ops@example.com', '/subscriptions/private-client',
                                    '11111111-1111-4111-8111-111111111111', 'secret=private',
                                    'arn:aws:ec2:us-east-1:123456789012:instance/private'])
def test_knowledge_rejects_possible_client_identifiers_before_storage(content):
    service = build()
    assert service.knowledge_store is not service.store
    with pytest.raises(IdentityError):
        service.create_knowledge_publication({'title': 'Review pattern', 'summary': 'Synthetic review',
                                             'body': content}, OPERATOR)
    assert service.knowledge_store.state['knowledge_publications'] == {}
    assert service.store.state['knowledge_publications'] == {}


def test_publications_require_separate_author_technical_and_privacy_reviewers():
    service = build()
    row = service.create_knowledge_publication({'title': 'Synthetic disk retention',
                                               'summary': 'Check recovery requirements',
                                               'body': 'Inspect retention and independent backups.'}, OPERATOR)
    with pytest.raises(IdentityError):
        service.update_knowledge_publication(row['id'], {'version': row['version'], 'status': 'published'}, OPERATOR)
    for role, review, actor in [('KnowledgeReviewer', 'technical', 'independent-technical'),
                                 ('PrivacyReviewer', 'privacy', 'independent-privacy')]:
        row = service.review_knowledge_publication(row['id'], {'version': row['version'], 'review': review},
                                                  {'actor': actor, 'actor_type': 'operator', 'roles': [role]})
    row = service.update_knowledge_publication(row['id'], {'version': row['version'], 'status': 'published'}, OPERATOR)
    assert row['status'] == 'published'
    assert service.knowledge_metrics()['fresh_published'] == 1
    assert service.store.state['knowledge_publications'] == {}
    assert service.knowledge_store.state['events']
    assert service.store.state['events'] == []


def test_knowledge_never_uses_the_identity_database_or_runtime_identity():
    identity = 'postgresql://identity_app:unused@localhost/identity'
    with pytest.raises(ValueError, match='separate databases'):
        PostgresKnowledgeStore('postgresql://knowledge_app:unused@localhost/identity', identity)
    with pytest.raises(ValueError, match='separate runtime identity'):
        PostgresKnowledgeStore('postgresql://identity_app:unused@localhost/knowledge', identity)


@pytest.mark.postgres
def test_publications_persist_only_in_the_separate_postgres_database():
    privileged = os.getenv('CLOUDSAVER_TEST_PRIVILEGED_URL')
    if not privileged:
        pytest.skip('Use the disposable PostgreSQL test runner')
    name = 'knowledge_restoration_' + uuid4().hex
    secret = secrets.token_hex(32)
    created = False
    with psycopg.connect(privileged, autocommit=True) as admin:
        for role in ('knowledge_owner', 'knowledge_app'):
            admin.execute(sql.SQL('CREATE ROLE {} LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE PASSWORD {}')
                          .format(sql.Identifier(role), sql.Literal(secret)))
        try:
            admin.execute(sql.SQL('CREATE DATABASE {} OWNER knowledge_owner').format(sql.Identifier(name)))
            created = True
            admin.execute(sql.SQL('REVOKE ALL ON DATABASE {} FROM PUBLIC').format(sql.Identifier(name)))
            admin.execute(sql.SQL('GRANT CONNECT ON DATABASE {} TO knowledge_app').format(sql.Identifier(name)))
            base = make_url(privileged).set(database=name, password=secret)
            owner = base.set(username='knowledge_owner').render_as_string(hide_password=False)
            runtime = base.set(username='knowledge_app').render_as_string(hide_password=False)
            env = dict(os.environ, PLATFORM_KNOWLEDGE_MIGRATION_URL=owner,
                       PLATFORM_IDENTITY_MIGRATION_URL=os.environ['CLOUDSAVER_TEST_OWNER_URL'])
            subprocess.run([sys.executable, '-m', 'alembic', '-c', 'knowledge_alembic.ini', 'upgrade', 'head'],
                           cwd=Path(__file__).resolve().parents[1], env=env, check=True, capture_output=True, text=True)
            service = build()
            service.knowledge_store = PostgresKnowledgeStore(runtime, os.environ['CLOUDSAVER_TEST_APP_URL'])
            row = service.create_knowledge_publication({'title': 'Independent synthetic pattern',
                                                        'summary': 'Review storage retention',
                                                        'body': 'Verify independent recovery evidence.'}, OPERATOR)
            with psycopg.connect(runtime) as db:
                assert db.execute('SELECT title FROM knowledge.publications WHERE id=%s', (row['id'],)).fetchone()[0] == row['title']
                assert db.execute('SELECT count(*) FROM knowledge.audit').fetchone()[0] == 1
            assert admin.execute("SELECT to_regclass('knowledge.publications')").fetchone()[0] is None
            assert service.store.state['knowledge_publications'] == {}
        finally:
            if created:
                admin.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
            for role in ('knowledge_app', 'knowledge_owner'):
                admin.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(role)))
