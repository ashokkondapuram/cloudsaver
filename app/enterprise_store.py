"""Shared persistence for evidence features. PostgreSQL uses transaction-local RLS."""
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
from uuid import UUID

TABLES = ('ai_inference_attempts', 'ai_inference_events', 'focus_imports', 'focus_charges',
          'ai_batches', 'ai_batch_items', 'ai_followups', 'resource_decisions')


class Connection:
    def __init__(self, db, postgres):
        self.db, self.postgres = db, postgres

    def execute(self, query, parameters=()):
        return self.db.execute(query if self.postgres else query.replace('%s','?'), parameters)

    def json(self, value):
        if self.postgres:
            from psycopg.types.json import Jsonb
            return Jsonb(value)
        return json.dumps(value, sort_keys=True, separators=(',',':'))


def decode(value):
    return json.loads(value) if isinstance(value,str) else value


class EnterpriseStore:
    def __init__(self, settings):
        self.url, self.path = settings.database_url, settings.database
        if self.url:
            from app.store import PostgresStore
            PostgresStore(self.url)
            with self.transaction(str(UUID(int=0))) as db:
                for table in TABLES:
                    flags=db.execute('SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid=to_regclass(%s)',('public.'+table,)).fetchone()
                    if flags != (True,True):
                        raise ValueError(f'Apply forced-RLS migrations through 0010_resource_assessment before startup ({table})')
        else:
            Path(self.path).parent.mkdir(parents=True,exist_ok=True)
            with self.transaction(str(UUID(int=0))) as db:
                db.db.executescript('''
                CREATE TABLE IF NOT EXISTS ai_inference_attempts (
                    id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, request_key TEXT NOT NULL, fingerprint TEXT NOT NULL,
                    scan_id TEXT NOT NULL, metadata TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',response TEXT,
                    input_tokens INTEGER,output_tokens INTEGER,created_at TEXT NOT NULL,completed_at TEXT,
                    UNIQUE(tenant_id,request_key),UNIQUE(id,tenant_id));
                CREATE INDEX IF NOT EXISTS ai_history ON ai_inference_attempts(tenant_id,created_at DESC,id DESC);
                CREATE TABLE IF NOT EXISTS ai_inference_events (
                    id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,attempt_id TEXT NOT NULL,action TEXT NOT NULL,created_at TEXT NOT NULL);
                CREATE TRIGGER IF NOT EXISTS immutable_inference_outcome BEFORE UPDATE ON ai_inference_attempts
                    WHEN OLD.status<>'pending' OR NEW.status NOT IN ('completed','uncertain')
                    BEGIN SELECT RAISE(ABORT,'Inference outcomes are final'); END;
                CREATE TABLE IF NOT EXISTS focus_imports (
                    id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,source_id TEXT NOT NULL,fingerprint TEXT NOT NULL,
                    provider TEXT NOT NULL,sub_account TEXT NOT NULL,currency TEXT NOT NULL,
                    period_start TEXT NOT NULL,period_end TEXT NOT NULL,complete INTEGER NOT NULL,
                    records INTEGER NOT NULL,inserted INTEGER NOT NULL,actor TEXT NOT NULL,created_at TEXT NOT NULL,
                    UNIQUE(tenant_id,source_id),UNIQUE(id,tenant_id));
                CREATE TABLE IF NOT EXISTS focus_charges (
                    id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,import_id TEXT NOT NULL,provider TEXT NOT NULL,
                    billing_account TEXT NOT NULL,sub_account TEXT NOT NULL,charge_id TEXT NOT NULL,fingerprint TEXT NOT NULL,
                    currency TEXT NOT NULL,period_start TEXT NOT NULL,period_end TEXT NOT NULL,resource_id TEXT,charge_category TEXT NOT NULL,
                    billed_cost TEXT NOT NULL,effective_cost TEXT NOT NULL,list_cost TEXT,
                    UNIQUE(tenant_id,provider,billing_account,charge_id));
                CREATE INDEX IF NOT EXISTS focus_period ON focus_charges(tenant_id,currency,period_start,period_end);
                CREATE TABLE IF NOT EXISTS ai_batches (
                    id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,request_key TEXT NOT NULL,scan_id TEXT NOT NULL,
                    target_id TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'queued',total INTEGER NOT NULL,resume_after TEXT,
                    actor TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,UNIQUE(tenant_id,request_key));
                CREATE UNIQUE INDEX IF NOT EXISTS ai_batch_active ON ai_batches(tenant_id,scan_id)
                    WHERE status IN ('queued','running','waiting_for_budget');
                CREATE TABLE IF NOT EXISTS ai_batch_items (
                    id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,batch_id TEXT NOT NULL,resource_key TEXT NOT NULL,
                    evidence_digest TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'queued',attempt_id TEXT,reason TEXT,
                    updated_at TEXT NOT NULL,UNIQUE(batch_id,resource_key));
                CREATE TABLE IF NOT EXISTS ai_followups (
                    id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,scan_id TEXT NOT NULL,resource_key TEXT NOT NULL,
                    attempt_id TEXT NOT NULL,question TEXT NOT NULL,actor TEXT NOT NULL,created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS resource_decisions (
                    id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,resource_key TEXT NOT NULL,scan_id TEXT NOT NULL,
                    decision TEXT NOT NULL,note TEXT NOT NULL DEFAULT '',defer_until TEXT,evidence_digest TEXT NOT NULL,
                    actor TEXT NOT NULL,created_at TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS resource_decision_latest ON resource_decisions(tenant_id,resource_key,created_at DESC,id DESC);
                ''')

    @contextmanager
    def transaction(self, tenant_id, *, write=False):
        tenant_id=str(UUID(tenant_id))
        if self.url:
            from database.connection import connect
            with connect(self.url) as db:
                db.execute("SELECT set_config('app.current_tenant_id',%s,true)",(tenant_id,))
                db.execute("SET LOCAL statement_timeout='10s'")
                if write:
                    db.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",('enterprise:'+tenant_id,))
                yield Connection(db,True)
        else:
            db=sqlite3.connect(self.path,timeout=10)
            try:
                db.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
                yield Connection(db,False)
                db.commit()
            except BaseException:
                db.rollback()
                raise
            finally:
                db.close()
