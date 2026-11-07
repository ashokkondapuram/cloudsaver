"""Durable Code Mode run history (tenant-scoped)."""
from datetime import datetime, timezone
import hashlib
import json
from uuid import uuid4

from pydantic import Field, field_validator

from app.agent_contract import Strict
from app.code_mode_executor import execute_snippet, snippet_digest, ExecutionUnavailable
from app.enterprise_store import decode
from app.principals import actor


class RunRequest(Strict):
    request_key: str
    snippet: str = Field(min_length=20, max_length=16_384)
    input: dict = Field(default_factory=dict)
    acknowledge_sandbox: bool

    @field_validator('request_key')
    @classmethod
    def identifier(cls, value):
        from uuid import UUID
        return str(UUID(value))

    @field_validator('input')
    @classmethod
    def bounded_input(cls, value):
        encoded = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
        if len(encoded) > 8192:
            raise ValueError('Input JSON exceeds 8 KB.')
        return value


COLUMNS = 'id,tenant_id,state,version,snippet_digest,payload,result,actor,created_at,updated_at'


class CodeModeConflict(ValueError):
    pass


class CodeModeRepository:
    def __init__(self, store, clock=None):
        self.store = store
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def _row(self, db, tenant_id, run_id):
        row = db.execute(
            f'SELECT {COLUMNS} FROM code_mode_runs WHERE tenant_id=%s AND id=%s',
            (tenant_id, run_id),
        ).fetchone()
        if not row:
            return None
        item = dict(zip(COLUMNS.split(','), row))
        for key in ('id', 'tenant_id', 'created_at', 'updated_at'):
            item[key] = str(item[key])
        item['payload'] = decode(item['payload'])
        item['result'] = decode(item['result']) if item['result'] is not None else None
        return item

    def _event(self, db, run, action, who, details):
        db.execute(
            'INSERT INTO code_mode_run_events(id,tenant_id,run_id,version,action,actor,payload,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)',
            (
                str(uuid4()),
                run['tenant_id'],
                run['id'],
                run['version'],
                action,
                who,
                db.json(details),
                self.clock().isoformat(),
            ),
        )

    def list_runs(self, tenant, limit=25):
        with self.store.transaction(tenant['tenant_id']) as db:
            rows = db.execute(
                'SELECT id FROM code_mode_runs WHERE tenant_id=%s ORDER BY created_at DESC,id DESC LIMIT %s',
                (tenant['tenant_id'], limit),
            ).fetchall()
            return [self._row(db, tenant['tenant_id'], str(row[0])) for row in rows]

    def get(self, tenant, run_id):
        with self.store.transaction(tenant['tenant_id']) as db:
            return self._row(db, tenant['tenant_id'], run_id)

    def create_and_execute(self, tenant, body: RunRequest):
        if not body.acknowledge_sandbox:
            raise ValueError('Confirm isolated sandbox execution before running Code Mode.')
        from app.code_mode_validate import validate_snippet
        validate_snippet(body.snippet)
        tid = tenant['tenant_id']
        now = self.clock().isoformat()
        digest = snippet_digest(body.snippet)
        fingerprint = hashlib.sha256(
            json.dumps(
                {'request_key': body.request_key, 'digest': digest, 'input': body.input},
                sort_keys=True,
                separators=(',', ':'),
            ).encode('utf-8'),
        ).hexdigest()
        with self.store.transaction(tid, write=True) as db:
            prior = db.execute(
                'SELECT id,fingerprint FROM code_mode_runs WHERE tenant_id=%s AND request_key=%s',
                (tid, body.request_key),
            ).fetchone()
            if prior:
                if prior[1] != fingerprint:
                    raise CodeModeConflict('Idempotency key belongs to another snippet.')
                return self._row(db, tid, str(prior[0]))
            run_id = str(uuid4())
            payload = {
                'input': body.input,
                'snippet_chars': len(body.snippet),
                'snippet_stored': False,
            }
            inserted = db.execute(
                '''INSERT INTO code_mode_runs(id,tenant_id,state,version,snippet_digest,payload,result,actor,request_key,fingerprint,created_at,updated_at)
                   VALUES(%s,%s,'reconciliation_required',1,%s,%s,NULL,%s,%s,%s,%s,%s) ON CONFLICT(tenant_id,request_key) DO NOTHING''',
                (run_id, tid, digest, db.json(payload), actor(tenant), body.request_key, fingerprint, now, now),
            )
            if not inserted.rowcount:
                prior = db.execute('SELECT id,fingerprint FROM code_mode_runs WHERE tenant_id=%s AND request_key=%s', (tid, body.request_key)).fetchone()
                if prior[1] != fingerprint:
                    raise CodeModeConflict('Idempotency key belongs to another snippet.')
                return self._row(db, tid, str(prior[0]))
            run = self._row(db, tid, run_id)
            self._event(db, run, 'run_requested', actor(tenant), {'snippet_digest': digest})
        # Intent is committed before invoking any adapter. A replay of an
        # interrupted run returns its existing record and never dispatches again.
        try:
            result = execute_snippet(run_id=run_id, tenant_id=tid, snippet=body.snippet, input_value=body.input)
            if (not isinstance(result, dict) or result.get('status') not in ('succeeded', 'failed')
                    or result.get('snippet_digest') != digest or result.get('run_id') != run_id
                    or result.get('tenant_id') != tid):
                raise ValueError('Invalid execution response')
            state = 'succeeded' if result['status'] == 'succeeded' else 'failed'
        except ExecutionUnavailable:
            result = {'status': 'failed', 'error': 'Execution is unavailable', 'snippet_digest': digest}
            state = 'failed'
        except Exception:
            result = {'status': 'unknown', 'error': 'Execution outcome requires reconciliation', 'snippet_digest': digest}
            state = 'reconciliation_required'
        updated = self.clock().isoformat()
        with self.store.transaction(tid, write=True) as db:
            changed = db.execute(
                'UPDATE code_mode_runs SET state=%s,version=2,result=%s,updated_at=%s WHERE tenant_id=%s AND id=%s AND version=1',
                (state, db.json(result), updated, tid, run_id),
            ).rowcount
            run = self._row(db, tid, run_id)
            if changed:
                self._event(db, run, 'run_reconciliation_required' if state == 'reconciliation_required' else 'run_completed', actor(tenant), {'state': state, 'worker_ref': result.get('worker_ref')})
            return run

    def events(self, tenant, run_id):
        with self.store.transaction(tenant['tenant_id']) as db:
            rows = db.execute(
                'SELECT version,action,actor,payload,created_at FROM code_mode_run_events WHERE tenant_id=%s AND run_id=%s ORDER BY version,id',
                (tenant['tenant_id'], run_id),
            ).fetchall()
            return [
                {
                    'version': row[0],
                    'action': row[1],
                    'actor': row[2],
                    'payload': decode(row[3]),
                    'created_at': str(row[4]),
                }
                for row in rows
            ]
