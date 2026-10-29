"""Shared persistence for evidence features. PostgreSQL uses transaction-local RLS."""
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
from uuid import UUID
from app.governance_schema import TABLES as GOVERNANCE_TABLES, SQLITE as GOVERNANCE_SQLITE

TABLES = ('ai_inference_attempts', 'ai_inference_events', 'focus_imports', 'focus_charges',
          'ai_batches', 'ai_batch_items', 'ai_followups', 'resource_decisions', 'ai_connection_diagnostics',
          'savings_cases','savings_case_events','savings_evidence_receipts','savings_verified_actions',
          'agent_tasks', 'agent_task_events','ai_data_events','ai_data_retention','ai_data_holds',
          'billing_sync_runs','agent_gitops_syncs','billing_sync_jobs','finops_ownership','finops_anomalies',
          'finops_anomaly_events','finops_suppressions','savings_financial_claims','cloud_commitment_snapshots',
          'observability_connectors','observability_jobs','observability_snapshots')


CONTROL_PLANE_TABLES = ('cp_financial_scenarios','cp_action_assessments','cp_plans','cp_plan_versions',
                       'cp_plan_approvals','cp_gitops_deliveries','cp_gitops_checks','cp_commitment_reminders')
from app.engineering.schema import TABLES as ENGINEERING_TABLES, sqlite_schema as engineering_sqlite
TABLES=TABLES+GOVERNANCE_TABLES+CONTROL_PLANE_TABLES+tuple(ENGINEERING_TABLES)


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
                        raise ValueError(f'Apply forced-RLS migrations through 0027_engineering_workloads before startup ({table})')
                if not db.execute("SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='ai_data_holds' AND column_name='released_at'").fetchone():
                    raise ValueError('Apply migration 0019_multicloud_governance_and_pillars before AI startup')
        else:
            Path(self.path).parent.mkdir(parents=True,exist_ok=True)
            with self.transaction(str(UUID(int=0))) as db:
                existing=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='ai_inference_attempts'").fetchone()
                if existing and 'content_erased_at' not in {r[1] for r in db.execute('PRAGMA table_info(ai_inference_attempts)').fetchall()}:
                    db.execute('ALTER TABLE ai_inference_attempts ADD COLUMN content_erased_at TEXT')
                for table,columns in (('ai_data_events',('cloud_provider','scope_id')),('ai_data_holds',('released_at','released_by','release_reason','review_ticket'))):
                    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=%s",(table,)).fetchone():
                        present={r[1] for r in db.execute('PRAGMA table_info('+table+')').fetchall()}
                        for column in columns:
                            if column not in present:db.execute('ALTER TABLE '+table+' ADD COLUMN '+column+' TEXT')
                db.db.executescript('''
                CREATE TABLE IF NOT EXISTS ai_data_events (
                    id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,purpose TEXT NOT NULL,decision TEXT NOT NULL,
                    reason TEXT NOT NULL,policy_digest TEXT NOT NULL,target_id TEXT,metadata TEXT NOT NULL,actor TEXT NOT NULL,created_at TEXT NOT NULL,cloud_provider TEXT,scope_id TEXT);
                CREATE TABLE IF NOT EXISTS ai_data_retention (
                    attempt_id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,purpose TEXT NOT NULL,policy_digest TEXT NOT NULL,
                    expires_at TEXT NOT NULL,erased_at TEXT,created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS ai_data_holds (
                    id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,attempt_id TEXT NOT NULL,review_reference TEXT NOT NULL,
                    hold_until TEXT NOT NULL,actor TEXT NOT NULL,created_at TEXT NOT NULL,released_at TEXT,released_by TEXT,release_reason TEXT,review_ticket TEXT);
                CREATE TABLE IF NOT EXISTS _ai_hold_release_permits(id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS _ai_erasure_permits (attempt_id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL);
                CREATE TRIGGER IF NOT EXISTS ai_data_events_no_update BEFORE UPDATE ON ai_data_events
                    BEGIN SELECT RAISE(ABORT,'Data-use audit is append-only'); END;
                CREATE TRIGGER IF NOT EXISTS ai_data_events_no_delete BEFORE DELETE ON ai_data_events
                    BEGIN SELECT RAISE(ABORT,'Data-use audit is append-only'); END;
                DROP TRIGGER IF EXISTS ai_data_holds_no_update;
                CREATE TRIGGER ai_data_holds_no_update BEFORE UPDATE ON ai_data_holds
                    WHEN NOT(OLD.released_at IS NULL AND NEW.released_at IS NOT NULL AND OLD.id=NEW.id AND OLD.tenant_id=NEW.tenant_id
                      AND OLD.attempt_id=NEW.attempt_id AND OLD.hold_until=NEW.hold_until AND OLD.review_reference=NEW.review_reference
                      AND OLD.actor=NEW.actor AND OLD.created_at=NEW.created_at
                      AND EXISTS(SELECT 1 FROM _ai_hold_release_permits WHERE id=OLD.id AND tenant_id=OLD.tenant_id))
                    BEGIN SELECT RAISE(ABORT,'Legal holds are append-only'); END;
                CREATE TRIGGER IF NOT EXISTS ai_data_holds_no_delete BEFORE DELETE ON ai_data_holds
                    BEGIN SELECT RAISE(ABORT,'Legal holds are append-only'); END;
                CREATE TABLE IF NOT EXISTS billing_sync_jobs (
                    id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,request_key TEXT NOT NULL,state TEXT NOT NULL,
                    payload TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,
                    lease_token TEXT,lease_until TEXT,UNIQUE(tenant_id,request_key));
                CREATE TABLE IF NOT EXISTS cloud_commitment_snapshots (
                    id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,provider TEXT NOT NULL,scope_id TEXT NOT NULL,
                    job_id TEXT,status TEXT NOT NULL,payload TEXT NOT NULL,observed_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS observability_connectors (
                    id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,name TEXT NOT NULL,kind TEXT NOT NULL,config TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,version INTEGER NOT NULL DEFAULT 1,created_by_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,updated_at TEXT NOT NULL,UNIQUE(tenant_id,name));
                CREATE TABLE IF NOT EXISTS observability_jobs (
                    id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,request_key TEXT NOT NULL,state TEXT NOT NULL,payload TEXT NOT NULL,
                    lease_token TEXT,lease_until TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,UNIQUE(tenant_id,request_key));
                CREATE TABLE IF NOT EXISTS observability_snapshots (
                    id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,connector_id TEXT NOT NULL,job_id TEXT,status TEXT NOT NULL,
                    payload TEXT NOT NULL,observed_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS billing_sync_runs (
                    id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,binding_key TEXT NOT NULL,state TEXT NOT NULL,
                    payload TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,lease_until TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS agent_gitops_syncs (
                    id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,binding_key TEXT NOT NULL,state TEXT NOT NULL,
                    payload TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,lease_until TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS agent_tasks (
                    id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,provider TEXT NOT NULL,scope_id TEXT NOT NULL,
                    resource_id TEXT NOT NULL,scan_id TEXT NOT NULL,request_key TEXT NOT NULL,fingerprint TEXT NOT NULL,
                    state TEXT NOT NULL,version INTEGER NOT NULL,payload TEXT NOT NULL,actor TEXT NOT NULL,
                    created_at TEXT NOT NULL,updated_at TEXT NOT NULL,UNIQUE(tenant_id,request_key));
                CREATE TABLE IF NOT EXISTS agent_task_events (
                    id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,task_id TEXT NOT NULL,version INTEGER NOT NULL,
                    action TEXT NOT NULL,actor TEXT NOT NULL,payload TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(task_id,version));
                DROP TRIGGER IF EXISTS agent_events_no_update;
                UPDATE agent_task_events SET payload=json_set(json_remove(payload,'$.plan'),'$.plan_body_removed_by_data_governance',json('true'))
                    WHERE json_type(payload,'$.plan') IS NOT NULL;
                CREATE TRIGGER IF NOT EXISTS agent_events_no_update BEFORE UPDATE ON agent_task_events
                    BEGIN SELECT RAISE(ABORT,'Agent audit events are append-only'); END;
                CREATE TRIGGER IF NOT EXISTS agent_events_no_delete BEFORE DELETE ON agent_task_events
                    BEGIN SELECT RAISE(ABORT,'Agent audit events are append-only'); END;
                UPDATE agent_tasks SET payload=json_set(payload,'$.data_retention_expires_at',strftime('%Y-%m-%dT%H:%M:%SZ','now','+7 days'))
                    WHERE json_extract(payload,'$.data_retention_expires_at') IS NULL;
                CREATE TABLE IF NOT EXISTS finops_ownership (
                    id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,provider TEXT NOT NULL,scope_id TEXT NOT NULL,resource_id TEXT NOT NULL,
                    version INTEGER NOT NULL,payload TEXT NOT NULL,actor TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(tenant_id,provider,scope_id,resource_id,version));
                CREATE TABLE IF NOT EXISTS finops_anomalies (
                    id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,fingerprint TEXT NOT NULL,provider TEXT NOT NULL,scope_id TEXT NOT NULL,resource_id TEXT,currency TEXT NOT NULL,
                    state TEXT NOT NULL,version INTEGER NOT NULL,payload TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,UNIQUE(tenant_id,fingerprint));
                CREATE TABLE IF NOT EXISTS finops_anomaly_events (
                    id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,anomaly_id TEXT NOT NULL,version INTEGER NOT NULL,action TEXT NOT NULL,payload TEXT NOT NULL,
                    actor TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(tenant_id,anomaly_id,version));
                CREATE TABLE IF NOT EXISTS finops_suppressions (
                    id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,provider TEXT NOT NULL,scope_id TEXT NOT NULL,resource_id TEXT,start_date TEXT NOT NULL,end_date TEXT NOT NULL,
                    payload TEXT NOT NULL,actor TEXT NOT NULL,created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS savings_financial_claims (
                    id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,case_id TEXT NOT NULL,provider TEXT NOT NULL,scope_id TEXT NOT NULL,resource_id TEXT NOT NULL,currency TEXT NOT NULL,
                    period_start TEXT NOT NULL,period_end TEXT NOT NULL,receipt_id TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 1,amount TEXT NOT NULL,evidence TEXT NOT NULL,ledger_digest TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(tenant_id,case_id,receipt_id));
                CREATE TRIGGER IF NOT EXISTS finops_ownership_no_update BEFORE UPDATE ON finops_ownership BEGIN SELECT RAISE(ABORT,'Ownership versions are append-only'); END;
                CREATE TRIGGER IF NOT EXISTS finops_ownership_no_delete BEFORE DELETE ON finops_ownership BEGIN SELECT RAISE(ABORT,'Ownership versions are append-only'); END;
                CREATE TRIGGER IF NOT EXISTS finops_anomaly_events_no_update BEFORE UPDATE ON finops_anomaly_events BEGIN SELECT RAISE(ABORT,'Investigation events are append-only'); END;
                CREATE TRIGGER IF NOT EXISTS finops_anomaly_events_no_delete BEFORE DELETE ON finops_anomaly_events BEGIN SELECT RAISE(ABORT,'Investigation events are append-only'); END;
                CREATE TRIGGER IF NOT EXISTS savings_claims_no_update BEFORE UPDATE ON savings_financial_claims BEGIN SELECT RAISE(ABORT,'Financial claims are append-only'); END;
                CREATE TRIGGER IF NOT EXISTS savings_claims_no_delete BEFORE DELETE ON savings_financial_claims BEGIN SELECT RAISE(ABORT,'Financial claims are append-only'); END;
                CREATE TABLE IF NOT EXISTS savings_cases (
                    id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,provider TEXT NOT NULL,scope_id TEXT NOT NULL,
                    resource_id TEXT NOT NULL,baseline_scan_id TEXT NOT NULL,request_key TEXT NOT NULL,fingerprint TEXT NOT NULL,
                    state TEXT NOT NULL,version INTEGER NOT NULL,payload TEXT NOT NULL,verification TEXT,
                    actor TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,UNIQUE(tenant_id,request_key));
                CREATE TABLE IF NOT EXISTS savings_case_events (
                    id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,case_id TEXT NOT NULL,action TEXT NOT NULL,
                    version INTEGER NOT NULL,payload TEXT NOT NULL,actor TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(case_id,version));
                CREATE TABLE IF NOT EXISTS savings_evidence_receipts (
                    id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,receipt_key TEXT NOT NULL,source_id TEXT NOT NULL,provider TEXT NOT NULL,
                    scope_id TEXT NOT NULL,resource_id TEXT NOT NULL,kind TEXT NOT NULL,fingerprint TEXT NOT NULL,payload TEXT NOT NULL,
                    issued_at TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(tenant_id,source_id,receipt_key));
                CREATE TRIGGER IF NOT EXISTS savings_events_no_update BEFORE UPDATE ON savings_case_events
                    BEGIN SELECT RAISE(ABORT,'Savings events are append-only'); END;
                CREATE TRIGGER IF NOT EXISTS savings_events_no_delete BEFORE DELETE ON savings_case_events
                    BEGIN SELECT RAISE(ABORT,'Savings events are append-only'); END;
                CREATE TRIGGER IF NOT EXISTS savings_receipts_no_update BEFORE UPDATE ON savings_evidence_receipts
                    BEGIN SELECT RAISE(ABORT,'Evidence receipts are append-only'); END;
                CREATE TRIGGER IF NOT EXISTS savings_receipts_no_delete BEFORE DELETE ON savings_evidence_receipts
                    BEGIN SELECT RAISE(ABORT,'Evidence receipts are append-only'); END;
                CREATE TABLE IF NOT EXISTS savings_verified_actions (
                    id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,case_id TEXT NOT NULL,event_key TEXT NOT NULL,
                    receipt_id TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(tenant_id,event_key));
                CREATE TRIGGER IF NOT EXISTS savings_actions_no_update BEFORE UPDATE ON savings_verified_actions
                    BEGIN SELECT RAISE(ABORT,'Verified actions are append-only'); END;
                CREATE TRIGGER IF NOT EXISTS savings_actions_no_delete BEFORE DELETE ON savings_verified_actions
                    BEGIN SELECT RAISE(ABORT,'Verified actions are append-only'); END;
                CREATE TABLE IF NOT EXISTS ai_connection_diagnostics (
                    id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,provider TEXT NOT NULL,target_id TEXT NOT NULL,
                    actor TEXT NOT NULL,result TEXT NOT NULL,created_at TEXT NOT NULL);
                CREATE TRIGGER IF NOT EXISTS ai_diagnostics_no_update BEFORE UPDATE ON ai_connection_diagnostics
                    BEGIN SELECT RAISE(ABORT,'AI diagnostics are append-only'); END;
                CREATE TRIGGER IF NOT EXISTS ai_diagnostics_no_delete BEFORE DELETE ON ai_connection_diagnostics
                    BEGIN SELECT RAISE(ABORT,'AI diagnostics are append-only'); END;
                CREATE TABLE IF NOT EXISTS ai_inference_attempts (
                    id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, request_key TEXT NOT NULL, fingerprint TEXT NOT NULL,
                    scan_id TEXT NOT NULL, metadata TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',response TEXT,
                    input_tokens INTEGER,output_tokens INTEGER,created_at TEXT NOT NULL,completed_at TEXT,content_erased_at TEXT,
                    UNIQUE(tenant_id,request_key),UNIQUE(id,tenant_id));
                CREATE INDEX IF NOT EXISTS ai_history ON ai_inference_attempts(tenant_id,created_at DESC,id DESC);
                CREATE TABLE IF NOT EXISTS ai_inference_events (
                    id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,attempt_id TEXT NOT NULL,action TEXT NOT NULL,created_at TEXT NOT NULL);
                DROP TRIGGER IF EXISTS immutable_inference_outcome;
                CREATE TRIGGER immutable_inference_outcome BEFORE UPDATE ON ai_inference_attempts
                    WHEN OLD.status<>'pending' OR NEW.status NOT IN ('completed','uncertain')
                    BEGIN
                      SELECT CASE WHEN NOT(NEW.response IS NULL AND NEW.content_erased_at IS NOT NULL AND OLD.status=NEW.status
                        AND OLD.input_tokens IS NEW.input_tokens AND OLD.output_tokens IS NEW.output_tokens
                        AND OLD.completed_at IS NEW.completed_at AND OLD.metadata=NEW.metadata
                        AND OLD.fingerprint=NEW.fingerprint AND OLD.request_key=NEW.request_key
                        AND OLD.tenant_id=NEW.tenant_id AND OLD.scan_id=NEW.scan_id AND OLD.id=NEW.id AND OLD.created_at=NEW.created_at
                        AND EXISTS(SELECT 1 FROM _ai_erasure_permits WHERE attempt_id=OLD.id AND tenant_id=OLD.tenant_id))
                        THEN RAISE(ABORT,'Inference outcomes are final') END;
                    END;
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
                CREATE TABLE IF NOT EXISTS cp_plans (
                    id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,objective TEXT NOT NULL,owner_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,UNIQUE(tenant_id,id));
                CREATE TRIGGER IF NOT EXISTS cp_plans_no_update BEFORE UPDATE ON cp_plans BEGIN SELECT RAISE(ABORT,'Plans are append-only'); END;
                CREATE TRIGGER IF NOT EXISTS cp_plans_no_delete BEFORE DELETE ON cp_plans BEGIN SELECT RAISE(ABORT,'Plans are append-only'); END;
                CREATE TABLE IF NOT EXISTS cp_plan_versions (
                    id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,plan_id TEXT NOT NULL,version INTEGER NOT NULL CHECK (version>=1),
                    identity_digest TEXT NOT NULL,targets TEXT NOT NULL,parameters TEXT NOT NULL,
                    policy_digest TEXT NOT NULL,evidence_digest TEXT NOT NULL,state TEXT NOT NULL DEFAULT 'draft',
                    created_by_hash TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,
                    UNIQUE(tenant_id,plan_id,version),UNIQUE(tenant_id,id),
                    CHECK (state IN ('draft','evidence_required','assessed','review_requested','approved','queued','running',
                      'verification_pending','verified','failed','reconciliation_required','cancelled','expired')));
                CREATE TRIGGER IF NOT EXISTS cp_plan_versions_restricted_update BEFORE UPDATE ON cp_plan_versions
                    WHEN NOT(OLD.id=NEW.id AND OLD.tenant_id=NEW.tenant_id AND OLD.plan_id=NEW.plan_id AND OLD.version=NEW.version
                      AND OLD.identity_digest=NEW.identity_digest AND OLD.targets=NEW.targets AND OLD.parameters=NEW.parameters
                      AND OLD.policy_digest=NEW.policy_digest AND OLD.evidence_digest=NEW.evidence_digest
                      AND OLD.created_by_hash=NEW.created_by_hash AND OLD.created_at=NEW.created_at)
                    BEGIN SELECT RAISE(ABORT,'Only state and updated_at may change on a plan version'); END;
                CREATE TRIGGER IF NOT EXISTS cp_plan_versions_no_delete BEFORE DELETE ON cp_plan_versions BEGIN SELECT RAISE(ABORT,'Plan versions are append-only'); END;
                CREATE TABLE IF NOT EXISTS cp_plan_approvals (
                    id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,plan_version_id TEXT NOT NULL,identity_digest TEXT NOT NULL,
                    approver_hash TEXT NOT NULL,verified_human INTEGER NOT NULL CHECK (verified_human=1),expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,CHECK (expires_at>created_at));
                CREATE TRIGGER IF NOT EXISTS cp_plan_approvals_no_update BEFORE UPDATE ON cp_plan_approvals BEGIN SELECT RAISE(ABORT,'Approvals are append-only'); END;
                CREATE TRIGGER IF NOT EXISTS cp_plan_approvals_no_delete BEFORE DELETE ON cp_plan_approvals BEGIN SELECT RAISE(ABORT,'Approvals are append-only'); END;
                CREATE TABLE IF NOT EXISTS cp_action_assessments (
                    id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,idempotency_key TEXT NOT NULL,action_id TEXT NOT NULL,
                    rule_version TEXT NOT NULL,findings TEXT NOT NULL,decision TEXT NOT NULL,
                    evidence_digest TEXT NOT NULL,policy_digest TEXT NOT NULL,created_by_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,UNIQUE(tenant_id,idempotency_key),
                    CHECK (decision IN ('eligible_for_review','blocked','evidence_required','unsupported','expired')));
                CREATE INDEX IF NOT EXISTS cp_action_assessments_action ON cp_action_assessments(tenant_id,action_id,created_at DESC);
                CREATE TRIGGER IF NOT EXISTS cp_action_assessments_no_update BEFORE UPDATE ON cp_action_assessments BEGIN SELECT RAISE(ABORT,'Action assessments are append-only'); END;
                CREATE TRIGGER IF NOT EXISTS cp_action_assessments_no_delete BEFORE DELETE ON cp_action_assessments BEGIN SELECT RAISE(ABORT,'Action assessments are append-only'); END;
                CREATE TABLE IF NOT EXISTS cp_financial_scenarios (
                    id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,idempotency_key TEXT NOT NULL,currency TEXT NOT NULL,
                    input TEXT NOT NULL,result TEXT NOT NULL,status TEXT NOT NULL,evidence_digest TEXT,
                    created_by_hash TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(tenant_id,idempotency_key));
                CREATE TRIGGER IF NOT EXISTS cp_financial_scenarios_no_update BEFORE UPDATE ON cp_financial_scenarios BEGIN SELECT RAISE(ABORT,'Financial scenarios are append-only'); END;
                CREATE TRIGGER IF NOT EXISTS cp_financial_scenarios_no_delete BEFORE DELETE ON cp_financial_scenarios BEGIN SELECT RAISE(ABORT,'Financial scenarios are append-only'); END;
                CREATE TABLE IF NOT EXISTS cp_gitops_deliveries (
                    id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,delivery_id TEXT NOT NULL,repo_id TEXT NOT NULL,
                    received_at TEXT NOT NULL,UNIQUE(tenant_id,delivery_id));
                CREATE TRIGGER IF NOT EXISTS cp_gitops_deliveries_no_update BEFORE UPDATE ON cp_gitops_deliveries BEGIN SELECT RAISE(ABORT,'Deliveries are append-only'); END;
                CREATE TRIGGER IF NOT EXISTS cp_gitops_deliveries_no_delete BEFORE DELETE ON cp_gitops_deliveries BEGIN SELECT RAISE(ABORT,'Deliveries are append-only'); END;
                CREATE TABLE IF NOT EXISTS cp_gitops_checks (
                    id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,repo_id TEXT NOT NULL,base_sha TEXT NOT NULL,
                    head_sha TEXT NOT NULL,plan_digest TEXT NOT NULL,policy_digest TEXT NOT NULL,
                    evidence_digest TEXT NOT NULL,decision TEXT NOT NULL,trusted_plan INTEGER NOT NULL,
                    conclusion TEXT NOT NULL,created_at TEXT NOT NULL,
                    UNIQUE(tenant_id,repo_id,base_sha,head_sha,plan_digest,policy_digest,evidence_digest));
                CREATE INDEX IF NOT EXISTS cp_gitops_checks_head ON cp_gitops_checks(tenant_id,repo_id,head_sha);
                CREATE TRIGGER IF NOT EXISTS cp_gitops_checks_no_update BEFORE UPDATE ON cp_gitops_checks BEGIN SELECT RAISE(ABORT,'Checks are append-only'); END;
                CREATE TRIGGER IF NOT EXISTS cp_gitops_checks_no_delete BEFORE DELETE ON cp_gitops_checks BEGIN SELECT RAISE(ABORT,'Checks are append-only'); END;
                CREATE TABLE IF NOT EXISTS cp_commitment_reminders (
                    id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,commitment_id TEXT NOT NULL,threshold_days INTEGER NOT NULL,
                    days_remaining INTEGER NOT NULL,created_at TEXT NOT NULL,UNIQUE(tenant_id,commitment_id,threshold_days));
                CREATE TRIGGER IF NOT EXISTS cp_commitment_reminders_no_update BEFORE UPDATE ON cp_commitment_reminders BEGIN SELECT RAISE(ABORT,'Reminders are append-only'); END;
                CREATE TRIGGER IF NOT EXISTS cp_commitment_reminders_no_delete BEFORE DELETE ON cp_commitment_reminders BEGIN SELECT RAISE(ABORT,'Reminders are append-only'); END;
                INSERT OR IGNORE INTO ai_data_retention(attempt_id,tenant_id,purpose,policy_digest,expires_at,created_at)
                    SELECT id,tenant_id,'legacy_inference','0000000000000000000000000000000000000000000000000000000000000000',
                    strftime('%Y-%m-%dT%H:%M:%SZ','now','+7 days'),strftime('%Y-%m-%dT%H:%M:%SZ','now') FROM ai_inference_attempts;
                ''')

            with self.transaction(str(UUID(int=0)),write=True) as db:
                db.db.executescript(GOVERNANCE_SQLITE)
                db.db.executescript(engineering_sqlite())

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
            db.execute('PRAGMA foreign_keys=ON')
            try:
                db.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
                yield Connection(db,False)
                db.commit()
            except BaseException:
                db.rollback()
                raise
            finally:
                db.close()
