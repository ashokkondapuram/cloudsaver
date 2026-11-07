"""Grafana Kubernetes rightsizing jobs (reuses observability_connectors + observability_jobs)."""
from uuid import uuid4

from app.observability_store import ObservabilityStore, _now
from app.v150_store import WorkflowConflict

TERMINAL = {'completed', 'failed', 'partial'}


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
        now = _now().isoformat()
        with self.store.transaction(tid, write=True) as db:
            if db.postgres:
                db.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', ('grafana-k8s:' + tid,))
            prior = db.execute('SELECT id FROM observability_jobs WHERE tenant_id=%s AND request_key=%s',
                               (tid, 'grafana:' + key)).fetchone()
            if prior:
                return self.job(tid, str(prior[0]))
            job_id = str(uuid4())
            payload = dict(kind='grafana_rightsizing', connector_id=connector_id, cluster=cluster, window_days=window_days,
                           connector=connector, result=None, error=None)
            db.execute("INSERT INTO observability_jobs(id,tenant_id,request_key,state,payload,created_at,updated_at) "
                       "VALUES(%s,%s,%s,'queued',%s,%s,%s)",
                       (job_id, tid, 'grafana:' + key, db.json(payload), now, now))
        return self.job(tid, job_id)

    def execute(self, tenant, job_id):
        from app.collectors.grafana_rightsizing import run_rightsizing
        tid = tenant['tenant_id']
        job = self.job(tid, job_id)
        if job is None:
            return None
        if job['status'] in TERMINAL and job['payload'].get('result') is not None:
            return job
        payload = job['payload']
        now = _now().isoformat()
        try:
            result = run_rightsizing(payload['connector'], cluster=payload.get('cluster'),
                                     window_days=int(payload.get('window_days') or 14))
            payload['result'] = result
            state = 'completed'
        except Exception as error:  # noqa: BLE001 — persist safe error message for operators
            payload['error'] = str(error)[:500]
            state = 'failed'
        with self.store.transaction(tid, write=True) as db:
            db.execute('UPDATE observability_jobs SET state=%s,payload=%s,updated_at=%s WHERE tenant_id=%s AND id=%s',
                       (state, db.json(payload), now, tid, job_id))
        return self.job(tid, job_id)
