"""Commit request intent before external I/O; fence every completion with its lease."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import time
from uuid import UUID, uuid4

from app.store import PostgresStore


class ReviewConflict(ValueError):
    pass


class ReviewRepository:
    columns = 'id,scan_id,target_id,repository,branch,status,attempts,result,created_at,updated_at'

    def __init__(self,store):
        self.store, self.postgres = store, isinstance(store,PostgresStore)
        if self.postgres:
            with store.connection(str(uuid4())) as db:
                flags = db.execute("SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid=to_regclass('public.gitops_requests')").fetchone()
                if flags != (True,True):
                    raise ValueError('Apply migration 0006_gitops_requests with forced RLS')
                if db.execute("SELECT pg_has_role(current_user,relowner,'USAGE') FROM pg_class WHERE oid='public.gitops_requests'::regclass").fetchone()[0]:
                    raise ValueError('GitOps runtime must not own its storage table')
        else:
            with store.connection() as db:
                db.execute('''CREATE TABLE IF NOT EXISTS gitops_requests (
                    id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, scan_id TEXT NOT NULL,
                    idempotency_digest TEXT NOT NULL, fingerprint TEXT NOT NULL,
                    target_id TEXT NOT NULL, repository TEXT NOT NULL, branch TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('pending','publishing','open','uncertain')),
                    attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts BETWEEN 0 AND 4),
                    lease_token TEXT, lease_until REAL NOT NULL DEFAULT 0, result TEXT,
                    created_at TEXT NOT NULL,updated_at TEXT NOT NULL,
                    UNIQUE(tenant_id,idempotency_digest),
                    FOREIGN KEY(scan_id,tenant_id) REFERENCES scans(id,tenant_id))''')
                db.execute('CREATE UNIQUE INDEX IF NOT EXISTS scans_id_owner ON scans(id,tenant_id)')

    @contextmanager
    def transaction(self,tenant_id):
        tenant_id = str(UUID(tenant_id))
        if self.postgres:
            with self.store.connection(tenant_id) as db:
                yield db
        else:
            with self.store.connection() as db:
                db.execute('PRAGMA foreign_keys=ON')
                db.execute('BEGIN IMMEDIATE')
                yield db

    def execute(self,db,query,args=()):
        return db.execute(query if self.postgres else query.replace('%s','?'),args)

    def record(self,row):
        if row is None:
            return None
        value = dict(zip(self.columns.split(','),row))
        value['id'],value['scan_id'] = str(value['id']),str(value['scan_id'])
        if isinstance(value['result'],str):
            value['result'] = json.loads(value['result'])
        for key in ('created_at','updated_at'):
            if isinstance(value[key],datetime):
                value[key] = value[key].isoformat()
        return value

    def reserve(self,tenant_id,key,package):
        digest = hashlib.sha256(key.encode()).hexdigest()
        now = datetime.now(timezone.utc).isoformat()
        with self.transaction(tenant_id) as db:
            if self.postgres:
                db.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',(tenant_id+digest,))
            existing = self.execute(db,'SELECT id,fingerprint FROM gitops_requests WHERE tenant_id=%s AND idempotency_digest=%s',(tenant_id,digest)).fetchone()
            if existing:
                if existing[1] != package['fingerprint']:
                    raise ReviewConflict('Request key already belongs to a different review package')
                return str(existing[0])
            id = str(uuid4())
            self.execute(db,"""INSERT INTO gitops_requests
                (id,tenant_id,scan_id,idempotency_digest,fingerprint,target_id,repository,branch,status,created_at,updated_at)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,'pending',%s,%s)""",
                (id,tenant_id,package['scan_id'],digest,package['fingerprint'],package['target_id'],package['repository'],package['branch'],now,now))
            return id

    def get(self,tenant_id,id):
        try:
            id = str(UUID(id))
        except ValueError:
            return None
        with self.transaction(tenant_id) as db:
            return self.record(self.execute(db,'SELECT '+self.columns+' FROM gitops_requests WHERE tenant_id=%s AND id=%s',(tenant_id,id)).fetchone())

    def list(self,tenant_id,limit=50):
        with self.transaction(tenant_id) as db:
            return [self.record(r) for r in self.execute(db,'SELECT '+self.columns+' FROM gitops_requests WHERE tenant_id=%s ORDER BY created_at DESC LIMIT %s',(tenant_id,limit)).fetchall()]

    def claim(self,tenant_id,id,token):
        now = time.time()
        with self.transaction(tenant_id) as db:
            row = self.execute(db,'SELECT status,attempts,lease_until FROM gitops_requests WHERE tenant_id=%s AND id=%s'+(' FOR UPDATE' if self.postgres else ''),(tenant_id,id)).fetchone()
            if row is None:
                raise ReviewConflict('Review request not found')
            if row[0]=='open':
                return False
            if row[2]>now:
                raise ReviewConflict('Review is publishing; use request history before retrying')
            if row[1]>=4:
                raise ReviewConflict('Review reached its attempt limit; inspect GitHub before taking further action')
            self.execute(db,"UPDATE gitops_requests SET status='publishing',attempts=attempts+1,lease_token=%s,lease_until=%s,updated_at=%s WHERE tenant_id=%s AND id=%s",
                (token,now+600,datetime.now(timezone.utc).isoformat(),tenant_id,id))
            return True

    def finish(self,tenant_id,id,token,result=None):
        value = json.dumps(result) if result is not None else None
        if self.postgres and result is not None:
            from psycopg.types.json import Jsonb
            value = Jsonb(result)
        with self.transaction(tenant_id) as db:
            changed = self.execute(db,"UPDATE gitops_requests SET status=%s,result=%s,lease_token=NULL,lease_until=0,updated_at=%s WHERE tenant_id=%s AND id=%s AND lease_token=%s AND status='publishing'",
                ('open' if result else 'uncertain',value,datetime.now(timezone.utc).isoformat(),tenant_id,id,token)).rowcount
            if changed != 1:
                raise ReviewConflict('A newer publisher owns this request; inspect request history')
