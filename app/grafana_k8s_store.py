"""Durable Grafana rightsizing jobs with renewable, expiring ownership."""
from __future__ import annotations
import hashlib
import json
import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from app.observability_store import ObservabilityStore, _now
from app.v150_store import WorkflowConflict

TERMINAL = {'completed', 'failed', 'partial', 'expired'}
LEASE_MINUTES = int(os.getenv('CLOUDSAVER_GRAFANA_JOB_LEASE_MINUTES', '15'))
MAX_ATTEMPTS = int(os.getenv('CLOUDSAVER_GRAFANA_JOB_MAX_ATTEMPTS', '3'))
JOB_DEADLINE_MINUTES = int(os.getenv('CLOUDSAVER_GRAFANA_JOB_DEADLINE_MINUTES', '60'))
MAX_CONCURRENT_JOBS = int(os.getenv('CLOUDSAVER_GRAFANA_MAX_CONCURRENT_JOBS', '1'))
LOG = logging.getLogger('cloudsaver.grafana_rightsizing')

def datetime_or_none(value):
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00')).astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None

def _request_hash(*, connector_id, cluster, window_days):
    data = dict(operation='grafana_rightsizing', connector_id=str(connector_id), cluster=cluster, window_days=int(window_days))
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

def _job_deadline_at(created_at):
    start = datetime_or_none(created_at)
    return start + timedelta(minutes=JOB_DEADLINE_MINUTES) if start else None

def _finalize_attempt(payload, *, state, finished_at, error=None):
    attempt = dict(payload.pop('active_attempt', {}) or {})
    if not attempt:
        return
    attempt.update(state=state, finished_at=finished_at)
    if error:
        attempt['error_code'] = error.get('error_code')
    attempts = list(payload.get('attempts') or [])
    for index in range(len(attempts) - 1, -1, -1):
        if attempts[index].get('token') == attempt.get('token'):
            attempts[index] = {**attempts[index], **attempt}
            break
    else:
        attempts.append(attempt)
    payload['attempts'] = attempts

def _safe_error(value, job_id):
    from app.collectors.grafana_rightsizing import PUBLIC_ERROR_CODES
    allowed = {code for code, _ in PUBLIC_ERROR_CODES.values()} | {
        'GRAFANA_QUERY_FAILED', 'GRAFANA_RESPONSE_INVALID', 'GRAFANA_RESPONSE_TOO_LARGE',
        'GRAFANA_JOB_DEADLINE_EXCEEDED', 'GRAFANA_JOB_ATTEMPTS_EXCEEDED',
        'GRAFANA_CONNECTOR_UNAVAILABLE', 'GRAFANA_POLICY_VALIDATION_FAILED',
    }
    if not value:
        return None
    code = value.get('error_code') if isinstance(value, dict) else None
    return dict(error_code=code if code in allowed else 'GRAFANA_QUERY_FAILED',
                retryable=value.get('retryable') is True if isinstance(value, dict) else False,
                correlation_id=str(job_id))

class GrafanaK8sStore:
    def __init__(self, store):
        self.store = store
        self.connectors = ObservabilityStore(store)

    def list_connectors(self, tid):
        return [c for c in self.connectors.connectors(tid) if c.get('kind') == 'grafana_mimir']

    def connector(self, tid, connector_id):
        item = self.connectors.connector(tid, connector_id)
        return item if item and item.get('kind') == 'grafana_mimir' else None

    @staticmethod
    def _job(row):
        if not row:
            return None
        payload = dict(row[2]) if isinstance(row[2], dict) else {}
        payload['error'] = _safe_error(payload.get('error'), row[0])
        for field in ('attempts',):
            payload[field] = [{k: a[k] for k in ('claimed_at', 'finished_at', 'state') if k in a}
                              for a in payload.get(field, []) if isinstance(a, dict)]
        payload.pop('active_attempt', None)
        return dict(id=str(row[0]), status=row[1], payload=payload, created_at=str(row[3]),
                    updated_at=str(row[4]), poll_url='/api/v1/kubernetes/grafana/rightsizing/jobs/' + str(row[0]))

    def job(self, tid, job_id):
        from app.enterprise_store import decode
        with self.store.transaction(tid) as db:
            row = db.execute('SELECT id,state,payload,created_at,updated_at FROM observability_jobs WHERE tenant_id=%s AND id=%s', (tid, job_id)).fetchone()
        return self._job((row[0], row[1], decode(row[2]), row[3], row[4])) if row else None

    @staticmethod
    def _filters(db):
        return "payload->>'kind'='grafana_rightsizing'" if db.postgres else "json_extract(payload,'$.kind')='grafana_rightsizing'"

    def _finish_locked(self, db, tid, job_id, payload, state, now, error=None):
        payload['error'] = error
        if state == 'expired':
            payload.pop('result', None)
        payload['completed_at'] = now.isoformat()
        _finalize_attempt(payload, state=state, finished_at=now.isoformat(), error=error)
        db.execute('UPDATE observability_jobs SET state=%s,payload=%s,updated_at=%s,lease_until=NULL,lease_token=NULL WHERE tenant_id=%s AND id=%s',
                   (state, db.json(payload), now.isoformat(), tid, job_id))

    def submit(self, tenant, key, connector_id, *, cluster=None, window_days=14):
        from app.enterprise_store import decode
        tid = tenant['tenant_id']
        connector = self.connector(tid, connector_id)
        if not connector or not connector.get('enabled'):
            raise WorkflowConflict('Enable an available Grafana connector first.')
        if cluster is not None and cluster not in connector.get('cluster_values', []):
            raise WorkflowConflict('Choose a cluster value configured on the connector.')
        digest = _request_hash(connector_id=connector_id, cluster=cluster, window_days=window_days)
        now = _now()
        with self.store.transaction(tid, write=True) as db:
            if db.postgres:
                db.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', ('grafana-k8s:' + tid,))
            prior = db.execute('SELECT id,payload FROM observability_jobs WHERE tenant_id=%s AND request_key=%s', (tid, 'grafana:' + key)).fetchone()
            if prior:
                if decode(prior[1]).get('request_hash') != digest:
                    raise WorkflowConflict('Idempotency key was already used with different job parameters.')
                job_id = str(prior[0])
            else:
                lock = ' FOR UPDATE' if db.postgres else ''
                rows = db.execute(f"SELECT id,payload,created_at FROM observability_jobs WHERE tenant_id=%s AND state IN ('queued','running') AND {self._filters(db)}" + lock, (tid,)).fetchall()
                active = []
                for row in rows:
                    payload = decode(row[1])
                    deadline = datetime_or_none(payload.get('deadline_at')) or _job_deadline_at(str(row[2]))
                    if deadline and deadline <= now:
                        error = dict(error_code='GRAFANA_JOB_DEADLINE_EXCEEDED', retryable=True, correlation_id=str(row[0]))
                        self._finish_locked(db, tid, str(row[0]), payload, 'expired', now, error)
                    else:
                        active.append(payload)
                if len(active) >= MAX_CONCURRENT_JOBS:
                    raise WorkflowConflict(f'At most {MAX_CONCURRENT_JOBS} Grafana rightsizing job(s) may be active for this workspace.')
                if any(p.get('connector_id') == str(connector_id) for p in active):
                    raise WorkflowConflict('Another rightsizing job is active for this connector.')
                job_id = str(uuid4())
                payload = dict(kind='grafana_rightsizing', connector_id=str(connector_id), cluster=cluster,
                               window_days=window_days, request_hash=digest, connector=connector,
                               result=None, error=None, attempts=[],
                               deadline_at=(now + timedelta(minutes=JOB_DEADLINE_MINUTES)).isoformat())
                db.execute("INSERT INTO observability_jobs(id,tenant_id,request_key,state,payload,created_at,updated_at) VALUES(%s,%s,%s,'queued',%s,%s,%s)",
                           (job_id, tid, 'grafana:' + key, db.json(payload), now.isoformat(), now.isoformat()))
        if os.getenv('CLOUDSAVER_GRAFANA_RIGHTSIZING_INLINE', 'false').lower() == 'true':
            return self.process_job(tenant, job_id)
        return self.job(tid, job_id)

    def _claim(self, tid, job_id, *, worker_id):
        from app.enterprise_store import decode
        with self.store.transaction(tid, write=True) as db:
            suffix = ' FOR UPDATE' if db.postgres else ''
            row = db.execute('SELECT state,payload,lease_token,lease_until,created_at FROM observability_jobs WHERE tenant_id=%s AND id=%s' + suffix, (tid, job_id)).fetchone()
            if not row or row[0] in TERMINAL:
                return None
            now = _now()
            payload = decode(row[1])
            if payload.get('kind') != 'grafana_rightsizing':
                return None
            deadline = datetime_or_none(payload.get('deadline_at')) or _job_deadline_at(str(row[4]))
            if deadline is None or deadline <= now:
                error = dict(error_code='GRAFANA_JOB_DEADLINE_EXCEEDED', retryable=True, correlation_id=job_id)
                self._finish_locked(db, tid, job_id, payload, 'expired', now, error)
                return None
            lease = datetime_or_none(row[3])
            if row[0] == 'running' and lease and lease > now:
                return None
            _finalize_attempt(payload, state='abandoned', finished_at=now.isoformat())
            if len(payload.get('attempts', [])) >= MAX_ATTEMPTS:
                error = dict(error_code='GRAFANA_JOB_ATTEMPTS_EXCEEDED', retryable=False, correlation_id=job_id)
                self._finish_locked(db, tid, job_id, payload, 'failed', now, error)
                return None
            token = str(uuid4())
            attempt = dict(worker_id=worker_id, claimed_at=now.isoformat(), token=token)
            payload.update(active_attempt=attempt, deadline_at=deadline.isoformat())
            payload['attempts'] = [*payload.get('attempts', []), attempt]
            db.execute("UPDATE observability_jobs SET state='running',lease_token=%s,lease_until=%s,payload=%s,updated_at=%s WHERE tenant_id=%s AND id=%s",
                       (token, min(deadline, now + timedelta(minutes=LEASE_MINUTES)).isoformat(), db.json(payload), now.isoformat(), tid, job_id))
        return dict(id=job_id, token=token, payload=payload)

    def _heartbeat(self, tid, job_id, token, deadline):
        now = _now()
        if now >= deadline:
            return False
        with self.store.transaction(tid, write=True) as db:
            update = db.execute("UPDATE observability_jobs SET lease_until=%s,updated_at=%s WHERE tenant_id=%s AND id=%s AND state='running' AND lease_token=%s AND lease_until>%s",
                                (min(deadline, now + timedelta(minutes=LEASE_MINUTES)).isoformat(), now.isoformat(), tid, job_id, token, now.isoformat()))
            return update.rowcount == 1

    def process_job(self, tenant, job_id, *, worker_id=None):
        from app.collectors.grafana_rightsizing import JobDeadlineExceeded, map_rightsizing_error, run_rightsizing
        tid = tenant['tenant_id']
        claim = self._claim(tid, job_id, worker_id=worker_id or str(uuid4()))
        if claim is None:
            return self.job(tid, job_id)
        payload = claim['payload']
        deadline = datetime_or_none(payload['deadline_at'])
        stop, lost = threading.Event(), threading.Event()
        def renew():
            while not stop.wait(max(0.1, min(20.0, LEASE_MINUTES * 20.0))):
                try:
                    if not self._heartbeat(tid, job_id, claim['token'], deadline):
                        lost.set()
                        return
                except Exception:
                    lost.set()
                    LOG.warning('grafana lease renewal failed job_id=%s', job_id)
                    return
        thread = threading.Thread(target=renew, daemon=True)
        thread.start()
        state = 'failed'
        try:
            connector = self.connector(tid, payload['connector_id'])
            if not connector or not connector.get('enabled'):
                payload['error'] = dict(error_code='GRAFANA_CONNECTOR_UNAVAILABLE', retryable=False, correlation_id=job_id)
            else:
                payload['connector'] = connector
                result = run_rightsizing(connector, cluster=payload.get('cluster'), window_days=int(payload['window_days']), deadline_at=deadline)
                if _now() >= deadline:
                    raise JobDeadlineExceeded()
                payload.update(result=result, error=None)
                state = 'completed'
        except Exception as error:
            payload['error'] = map_rightsizing_error(error, correlation_id=job_id)
            payload.pop('result', None)
            state = 'expired' if isinstance(error, JobDeadlineExceeded) else 'failed'
            LOG.warning('grafana job failed job_id=%s error_code=%s', job_id, payload['error']['error_code'])
        finally:
            stop.set()
            thread.join(timeout=2)
        with self.store.transaction(tid, write=True) as db:
            suffix = ' FOR UPDATE' if db.postgres else ''
            row = db.execute('SELECT state,lease_token,lease_until FROM observability_jobs WHERE tenant_id=%s AND id=%s' + suffix, (tid, job_id)).fetchone()
            now = _now()
            if not row or row[0] != 'running' or str(row[1]) != claim['token'] or lost.is_set():
                raise WorkflowConflict('Grafana job lease was lost; result was not committed.')
            if now >= deadline:
                payload.pop('result', None)
                payload['error'] = dict(error_code='GRAFANA_JOB_DEADLINE_EXCEEDED', retryable=True, correlation_id=job_id)
                state = 'expired'
            elif not datetime_or_none(row[2]) or datetime_or_none(row[2]) <= now:
                raise WorkflowConflict('Grafana job lease was lost; result was not committed.')
            self._finish_locked(db, tid, job_id, payload, state, now, payload.get('error'))
        return self.job(tid, job_id)

    def claim_next(self, tid, *, worker_id=None):
        now = _now().isoformat()
        with self.store.transaction(tid) as db:
            rows = db.execute(f"SELECT id FROM observability_jobs WHERE tenant_id=%s AND {self._filters(db)} AND (state='queued' OR (state='running' AND (lease_until IS NULL OR lease_until<=%s))) ORDER BY created_at LIMIT 20", (tid, now)).fetchall()
        for row in rows:
            result = self.process_job({'tenant_id': tid}, str(row[0]), worker_id=worker_id)
            if result and result['status'] in TERMINAL:
                return result
        return None

    def execute(self, tenant, job_id):
        return self.process_job(tenant, job_id)
