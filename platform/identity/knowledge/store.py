"""Knowledge has its own database and credentials; no operational database fallback."""
from contextlib import contextmanager

from identity.domain import Unavailable


class DisabledStore:
    @contextmanager
    def transaction(self):
        raise Unavailable('Shared knowledge is unavailable. Configure the separate knowledge database.')
        yield


class KnowledgeTx:
    def __init__(self, db):
        self.db = db

    def list_knowledge_publications(self, status=None, limit=50, offset=0):
        return [dict(row) for row in self.db.execute('SELECT * FROM knowledge.publications '
            'WHERE (%s::text IS NULL OR status=%s) ORDER BY created_at DESC,id DESC LIMIT %s OFFSET %s',
            (status, status, limit, offset)).fetchall()]

    def get_knowledge_publication(self, key):
        row = self.db.execute('SELECT * FROM knowledge.publications WHERE id=%s FOR UPDATE', (key,)).fetchone()
        return dict(row) if row else None

    def insert_knowledge_publication(self, row):
        from psycopg.types.json import Jsonb
        columns = tuple(row)
        values = [Jsonb(row[key]) if key in ('reviews', 'applicability') else row[key] for key in columns]
        self.db.execute('INSERT INTO knowledge.publications (' + ','.join(columns) + ') VALUES (' +
                        ','.join(['%s'] * len(values)) + ')', values)

    def update_knowledge_publication(self, key, version, fields):
        from psycopg.types.json import Jsonb
        allowed = {'title', 'summary', 'body', 'status', 'quality_score', 'updated_at', 'updated_by',
                   'reviews', 'source_kind', 'source_url', 'applicability'}
        if not fields.keys() <= allowed:
            raise ValueError('Unsupported knowledge field')
        values = [Jsonb(value) if name in ('reviews', 'applicability') else value for name, value in fields.items()]
        row = self.db.execute('UPDATE knowledge.publications SET ' + ','.join(name + '=%s' for name in fields) +
            ',version=version+1 WHERE id=%s AND version=%s RETURNING *', values + [key, version]).fetchone()
        return dict(row) if row else None

    def append_event(self, row):
        from psycopg.types.json import Jsonb
        self.db.execute('INSERT INTO knowledge.audit(id,occurred_at,actor,action,details) VALUES (%s,%s,%s,%s,%s)',
            (row['id'], row['occurred_at'], row['actor'], row['action'], Jsonb(row['details'])))


class PostgresKnowledgeStore:
    def __init__(self, url, identity_url=None):
        from sqlalchemy.engine import make_url
        parsed = make_url(url)
        if parsed.get_backend_name() != 'postgresql' or not parsed.database:
            raise ValueError('Knowledge requires a dedicated PostgreSQL database')
        if identity_url:
            identity = make_url(identity_url)
            if parsed.database == identity.database:
                raise ValueError('Knowledge and identity must use separate databases')
            if parsed.username == identity.username:
                raise ValueError('Knowledge requires a separate runtime identity')
        self.url = url

    @contextmanager
    def transaction(self):
        from psycopg.rows import dict_row
        from identity.db import connect
        with connect(self.url, row_factory=dict_row) as db:
            role = db.execute('SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user').fetchone()
            if not role or role['rolsuper'] or role['rolbypassrls']:
                raise ValueError('Knowledge must use an unprivileged runtime role')
            db.execute("SET LOCAL statement_timeout='5s'")
            yield KnowledgeTx(db)
