"""Grafana Kubernetes rightsizing jobs (observability_connectors + observability_jobs)."""
from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import timedelta
from uuid import uuid4

from app.observability_store import ObservabilityStore, _now
from app.v150_store import WorkflowConflict

TERMINAL = {'completed', 'failed', 'partial', 'expired'}
LEASE_MINUTES = int(os.getenv('CLOUDSAVER_GRAFANA_JOB_LEASE_MINUTES', '15'))
MAX_ATTEMPTS = int(os.getenv('CLOUDSAVER_GRAFANA_JOB_MAX_ATTEMPTS', '3'))
JOB_DEADLINE_MINUTES = int(os.getenv('CLOUDSAVER_GRAFANA_JOB_DEADLINE_MINUTES', '60'))
MAX_CONCURRENT_JOBS = int(os.getenv('CLOUDSAVER_GRAFANA_MAX_CONCURRENT_JOBS', '1'))
LOG = logging.getLogger('cloudsaver.grafana_rightsizing')


def _job_deadline_at(created_at: str):
    start = datetime_or_none(created_at)
    if start is None:
        return None
    return start + timedelta(minutes=JOB_DEADLINE_MINUTES)


def _finalize_attempt(payload: dict, *, state: str, finished_at: str, error: dict | None = None) -> None:
    attempt = dict(payload.get('active_attempt') or {})
    attempt['finished_at'] = finished_at
    attempt['state'] = state
    if error:
        attempt['error_code'] = error.get('error_code')
    attempts = list(payload.get('attempts') or [])
    if attempts and attempts[-1].get('token') == attempt.get('token'):
        attempts[-1] = {**attempts[-1], **attempt}
    else:
        attempts.append(attempt)
    payload['attempts'] = attempts
    payload.pop('active_attempt', None)


def _expire_job(db, tid, job_id, payload, *, now, created_at: str | None = None):
    deadline = payload.get('deadline_at')
    if not deadline and created_at:
        end = _job_deadline_at(created_at)
        deadline = end.isoformat() if end else None
    finished = now.isoformat()
    payload = {
        **payload,
        'deadline_at': deadline,
        'error': dict(error_code='GRAFANA_JOB_DEADLINE_EXCEEDED', retryable=True, correlation_id=job_id),
    }
    _finalize_attempt(payload, state='expired', finished_at=finished, error=payload['error'])
    db.execute(
        "UPDATE observability_jobs SET state='expired',payload=%s,updated_at=%s,lease_until=NULL,lease_token=NULL "
        'WHERE tenant_id=%s AND id=%s',
        (db.json(payload), finished, tid, job_id),
    )


def _request_hash(*, connector_id: str, cluster: str | None, window_days: int) -> str:
    blob = json.dumps(
        dict(operation='grafana_rightsizing', connector_id=str(connector_id), cluster=cluster, window_days=int(window_days)),
        sort_keys=True,
    )
    return hashlib.sha256(blob.encode()).hexdigest()


class GrafanaK8sStore:
    def __init__(self, store):
        self.store = store
        self.connectors = ObservabilityStore(store)

    def list_connectors(self, tid):
        return [c for c in self.connectors.connectors(tid) if c.get('kind') == 'grafana_mimir']

    def connector(self, tid, connector_id):
        item = self.connectors.connector(tid, connector_id)
        if item and item.get('kind') == 'grafana_mimir':
            return item
        return None

    @staticmethod
    def _job(row):
        if not row:
            return None
        payload = row[2] if isinstance(row[2], dict) else {}
        return dict(id=str(row[0]), status=row[1], payload=payload, created_at=str(row[3]), updated_at=str(row[4]),
                    poll_url='/api/v1/kubernetes/grafana/rightsizing/jobs/' + str(row[0]))

    def job(self, tid, job_id):
        from app.enterprise_store import decode
        with self.store.transaction(tid) as db:
            row = db.execute('SELECT id,state,payload,created_at,updated_at FROM observability_jobs WHERE tenant_id=%s AND id=%s',
                             (tid, job_id)).fetchone()
        if not row:
            return None
        row = (row[0], row[1], decode(row[2]), row[3], row[4])
        return self._job(row)

    def submit(self, tenant, key, connector_id, *, cluster=None, window_days=14):
        tid = tenant['tenant_id']
        connector = self.connector(tid, connector_id)
        if connector is None:
            raise WorkflowConflict('Grafana connector not found.')
        if not connector.get('enabled'):
            raise WorkflowConflict('Enable the Grafana connector first.')
        if cluster is not None and cluster not in connector.get('cluster_values', []):
            raise WorkflowConflict('Choose a cluster value configured on the connector.')
        req_hash = _request_hash(connector_id=connector_id, cluster=cluster, window_days=window_days)
        now = _now().isoformat()
        with self.store.transaction(tid, write=True) as db:
            if db.postgres:
                db.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', ('grafana-k8s:' + tid,))
            prior = db.execute(
                'SELECT id,payload FROM observability_jobs WHERE tenant_id=%s AND request_key=%s',
                (tid, 'grafana:' + key),
            ).fetchone()
            if prior:
                from app.enterprise_store import decode
                payload = decode(prior[1])
                if payload.get('request_hash') != req_hash:
                    raise WorkflowConflict('Idempotency key was already used with different job parameters.')
                return self.job(tid, str(prior[0]))
            kind_filter = "payload->>'kind'='grafana_rightsizing'" if db.postgres else "json_extract(payload,'$.kind')='grafana_rightsizing'"
            connector_filter = "payload->>'connector_id'=%s" if db.postgres else "json_extract(payload,'$.connector_id')=%s"
            running = db.execute(
                f"SELECT 1 FROM observability_jobs WHERE tenant_id=%s AND state='running' AND {kind_filter} "
                f"AND {connector_filter} LIMIT 1",
                (tid, str(connector_id)),
            ).fetchone()
            if running:
                raise WorkflowConflict('Another rightsizing job is already running for this connector.')
            active = db.execute(
                f"SELECT COUNT(*) FROM observability_jobs WHERE tenant_id=%s AND state IN ('queued','running') "
                f"AND {kind_filter}",
                (tid,),
            ).fetchone()[0]
            if int(active) >= MAX_CONCURRENT_JOBS:
                raise WorkflowConflict(
                    f'At most {MAX_CONCURRENT_JOBS} Grafana rightsizing job(s) may be active for this workspace.'
                )
            job_id = str(uuid4())
            deadline = (_now() + timedelta(minutes=JOB_DEADLINE_MINUTES)).isoformat()
            payload = dict(
                kind='grafana_rightsizing', connector_id=str(connector_id), cluster=cluster, window_days=window_days,
                request_hash=req_hash, connector=connector, result=None, error=None, attempts=[],
                deadline_at=deadline,
            )
            db.execute(
                "INSERT INTO observability_jobs(id,tenant_id,request_key,state,payload,created_at,updated_at) "
                "VALUES(%s,%s,%s,'queued',%s,%s,%s)",
                (job_id, tid, 'grafana:' + key, db.json(payload), now, now),
            )
        job = self.job(tid, job_id)
        if os.getenv('CLOUDSAVER_GRAFANA_RIGHTSIZING_INLINE', 'false').lower() == 'true':
            self.process_job(tenant, job_id)
            job = self.job(tid, job_id)
        return job

    def _claim(self, tid, job_id, *, worker_id: str):
        from datetime import datetime, timezone

        now = _now()
        token = str(uuid4())
        lease_until = (now + timedelta(minutes=LEASE_MINUTES)).isoformat()
        with self.store.transaction(tid, write=True) as db:
            suffix = ' FOR UPDATE' if db.postgres else ''
            row = db.execute(
                'SELECT state,payload,lease_token,lease_until,created_at FROM observability_jobs WHERE tenant_id=%s AND id=%s' + suffix,
                (tid, job_id),
            ).fetchone()
            if not row:
                return None
            state = row[0]
            if state in TERMINAL:
                return None
            from app.enterprise_store import decode
            payload = decode(row[1])
            deadline = datetime_or_none(payload.get('deadline_at')) or _job_deadline_at(str(row[4]))
            if deadline and now.replace(tzinfo=timezone.utc) >= deadline:
                _expire_job(db, tid, job_id, payload, now=now, created_at=str(row[4]))
                return None
            if state == 'running':
                lease_until_raw = row[3]
                lease_end = datetime_or_none(lease_until_raw)
                if lease_end and lease_end > now.replace(tzinfo=timezone.utc):
                    return None
            attempts = payload.get('attempts') or []
            if len(attempts) >= MAX_ATTEMPTS:
                db.execute(
                    "UPDATE observability_jobs SET state='failed',payload=%s,updated_at=%s WHERE tenant_id=%s AND id=%s",
                    (db.json({**payload, 'error': dict(error_code='GRAFANA_JOB_ATTEMPTS_EXCEEDED', retryable=False, correlation_id=job_id)}), now.isoformat(), tid, job_id),
                )
                return None
            attempt = dict(worker_id=worker_id, claimed_at=now.isoformat(), token=token)
            payload['attempts'] = [*attempts, attempt]
            payload['active_attempt'] = attempt
            updated = db.execute(
                "UPDATE observability_jobs SET state='running',lease_token=%s,lease_until=%s,payload=%s,updated_at=%s "
                "WHERE tenant_id=%s AND id=%s AND state IN ('queued','running')",
                (token, lease_until, db.json(payload), now.isoformat(), tid, job_id),
            )
            if getattr(updated, 'rowcount', 1) == 0:
                return None
        return dict(id=job_id, token=token, payload=payload)

    def process_job(self, tenant, job_id, *, worker_id: str | None = None) -> dict | None:
        from app.collectors.grafana_rightsizing import map_rightsizing_error, run_rightsizing

        tid = tenant['tenant_id']
        worker_id = worker_id or str(uuid4())
        job = self.job(tid, job_id)
        if job is None:
            return None
        if job['status'] in TERMINAL:
            return job
        claim = self._claim(tid, job_id, worker_id=worker_id)
        if claim is None:
            return self.job(tid, job_id)
        payload = claim['payload']
        connector = self.connector(tid, payload['connector_id'])
        if connector is None or not connector.get('enabled'):
            payload['error'] = dict(error_code='GRAFANA_CONNECTOR_UNAVAILABLE', retryable=False, correlation_id=job_id)
            state = 'failed'
        else:
            payload['connector'] = connector
            correlation = job_id
            deadline = datetime_or_none(payload.get('deadline_at'))
            try:
                result = run_rightsizing(
                    connector,
                    cluster=payload.get('cluster'),
                    window_days=int(payload.get('window_days') or 14),
                    deadline_at=deadline,
                )
                payload['result'] = result
                payload['error'] = None
                state = 'completed'
            except Exception as error:  # noqa: BLE001
                LOG.warning('grafana rightsizing job failed', exc_info=error)
                payload['error'] = map_rightsizing_error(error, correlation_id=correlation)
                payload.pop('result', None)
                from app.collectors.grafana_rightsizing import JobDeadlineExceeded
                state = 'expired' if isinstance(error, JobDeadlineExceeded) else 'failed'
        now = _now().isoformat()
        with self.store.transaction(tid, write=True) as db:
            suffix = ' FOR UPDATE' if db.postgres else ''
            current = db.execute(
                'SELECT state,lease_token FROM observability_jobs WHERE tenant_id=%s AND id=%s' + suffix,
                (tid, job_id),
            ).fetchone()
            if not current or str(current[1]) != claim['token']:
                raise WorkflowConflict('Grafana job lease was lost; result was not committed.')
            _finalize_attempt(payload, state=state, finished_at=now, error=payload.get('error'))
            payload['completed_at'] = now if state in ('completed', 'failed', 'expired') else payload.get('completed_at')
            updated = db.execute(
                'UPDATE observability_jobs SET state=%s,payload=%s,updated_at=%s,lease_until=NULL,lease_token=NULL '
                'WHERE tenant_id=%s AND id=%s AND lease_token=%s',
                (state, db.json(payload), now, tid, job_id, claim['token']),
            )
            if getattr(updated, 'rowcount', 1) == 0:
                raise WorkflowConflict('Grafana job lease was lost; result was not committed.')
        return self.job(tid, job_id)

    def claim_next(self, tid, *, worker_id: str | None = None) -> dict | None:
        worker_id = worker_id or str(uuid4())
        now = _now()
        with self.store.transaction(tid, write=True) as db:
            suffix = ' FOR UPDATE SKIP LOCKED' if db.postgres else ''
            kind_filter = "payload->>'kind'='grafana_rightsizing'" if db.postgres else "json_extract(payload,'$.kind')='grafana_rightsizing'"
            row = db.execute(
                f"SELECT id FROM observability_jobs WHERE tenant_id=%s AND state='queued' AND {kind_filter} "
                'ORDER BY created_at LIMIT 1' + suffix,
                (tid,),
            ).fetchone()
            if not row:
                return None
            job_id = str(row[0])
        return self.process_job({'tenant_id': tid}, job_id, worker_id=worker_id)

    def execute(self, tenant, job_id):
        """Compatibility alias: only processes when explicitly invoked (inline mode / worker)."""
        job = self.job(tenant['tenant_id'], job_id)
        if job is None:
            return None
        if job['status'] in TERMINAL:
            return job
        return self.process_job(tenant, job_id)


def datetime_or_none(value):
    if value is None:
        return None
    try:
        from datetime import datetime, timezone
        return datetime.fromisoformat(str(value).replace('Z', '+00:00')).astimezone(timezone.utc).replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None
