import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.grafana_k8s_store import GrafanaK8sStore, _request_hash
from app.v150_store import WorkflowConflict
from tests.test_enterprise import evidence, workspace


def _connector(repo, tenant, *, name='Grafana', uid='mimir-uid'):
    connector = dict(
        name=name, kind='grafana_mimir', base_url='https://grafana.example.com/', auth_kind='none',
        mimir_datasource_uid=uid, cluster_label='cluster', cluster_values=['dev'], schedule='manual',
        queries=[], services=[], mappings={}, thresholds={}, trace_window_hours=1,
    )
    return repo.connectors.create(tenant, connector)

def test_idempotency_hash_binds_request_fields():
    h1 = _request_hash(connector_id='a', cluster='c1', window_days=14)
    h2 = _request_hash(connector_id='a', cluster='c2', window_days=14)
    assert h1 != h2


def test_submit_rejects_idempotency_mismatch(evidence, monkeypatch):
    settings, store, _ = evidence
    tenant = workspace()
    repo = GrafanaK8sStore(store)
    connector = dict(
        name='Grafana', kind='grafana_mimir', base_url='https://grafana.example.com/', auth_kind='none',
        mimir_datasource_uid='mimir-uid-1', cluster_label='cluster', cluster_values=['dev'], schedule='manual',
        queries=[], services=[], mappings={}, thresholds={}, trace_window_hours=1,
    )
    created = repo.connectors.create(tenant, {**connector, 'cluster_values': ['dev', 'prod']})
    key = str(uuid4())
    repo.submit(tenant, key, created['id'], cluster='dev', window_days=14)
    with pytest.raises(WorkflowConflict, match='different job parameters'):
        repo.submit(tenant, key, created['id'], cluster='prod', window_days=14)


def test_failed_job_is_not_reexecuted_on_replay(evidence, monkeypatch):
    settings, store, _ = evidence
    tenant = workspace()
    repo = GrafanaK8sStore(store)
    connector = dict(
        name='Grafana2', kind='grafana_mimir', base_url='https://grafana.example.com/', auth_kind='none',
        mimir_datasource_uid='mimir-uid-2', cluster_label='cluster', cluster_values=['dev'], schedule='manual',
        queries=[], services=[], mappings={}, thresholds={}, trace_window_hours=1,
    )
    created = repo.connectors.create(tenant, connector)
    key = str(uuid4())
    calls = []

    def boom(*_a, **_k):
        calls.append(1)
        raise RuntimeError('http://grafana.example.com/query?secret=1')

    monkeypatch.setattr('app.collectors.grafana_rightsizing.run_rightsizing', boom)
    job = repo.submit(tenant, key, created['id'], window_days=14)
    repo.process_job(tenant, job['id'])
    failed = repo.job(tenant['tenant_id'], job['id'])
    assert failed['status'] == 'failed'
    assert failed['payload']['error']['error_code'] == 'GRAFANA_QUERY_FAILED'
    assert 'secret' not in json.dumps(failed['payload']['error'])
    assert calls == [1]
    replay = repo.submit(tenant, key, created['id'], window_days=14)
    assert replay['id'] == job['id']
    assert calls == [1]


def test_concurrent_job_limit_blocks_second_submit(evidence, monkeypatch):
    _, store, _ = evidence
    tenant = workspace()
    repo = GrafanaK8sStore(store)
    created = _connector(repo, tenant, name='G1', uid='mimir-a')
    monkeypatch.setenv('CLOUDSAVER_GRAFANA_MAX_CONCURRENT_JOBS', '1')
    repo.submit(tenant, str(uuid4()), created['id'], window_days=14)
    other = _connector(repo, tenant, name='G2', uid='mimir-b')
    with pytest.raises(WorkflowConflict, match='active for this workspace'):
        repo.submit(tenant, str(uuid4()), other['id'], window_days=14)


def test_attempt_history_records_finished_state(evidence, monkeypatch):
    _, store, _ = evidence
    tenant = workspace()
    repo = GrafanaK8sStore(store)
    created = _connector(repo, tenant, name='G3', uid='mimir-c')
    monkeypatch.setattr(
        'app.collectors.grafana_rightsizing.run_rightsizing',
        lambda *_a, **_k: dict(policy_version='test', items=[], item_count=0),
    )
    job = repo.submit(tenant, str(uuid4()), created['id'], window_days=14)
    repo.process_job(tenant, job['id'])
    finished = repo.job(tenant['tenant_id'], job['id'])
    attempts = finished['payload']['attempts']
    assert len(attempts) == 1
    assert attempts[0]['state'] == 'completed'
    assert attempts[0]['finished_at']
    assert 'active_attempt' not in finished['payload']


def test_job_deadline_expires_before_queries(evidence, monkeypatch):
    from app.collectors.grafana_rightsizing import JobDeadlineExceeded

    _, store, _ = evidence
    tenant = workspace()
    repo = GrafanaK8sStore(store)
    created = _connector(repo, tenant, name='G4', uid='mimir-d')
    monkeypatch.setenv('CLOUDSAVER_GRAFANA_JOB_DEADLINE_MINUTES', '60')

    def slow(*_a, **_k):
        raise JobDeadlineExceeded()

    monkeypatch.setattr('app.collectors.grafana_rightsizing.run_rightsizing', slow)
    job = repo.submit(tenant, str(uuid4()), created['id'], window_days=14)
    tid = tenant['tenant_id']
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    with store.transaction(tid, write=True) as db:
        from app.enterprise_store import decode
        row = db.execute('SELECT payload FROM observability_jobs WHERE tenant_id=%s AND id=%s', (tid, job['id'])).fetchone()
        payload = decode(row[0])
        payload['deadline_at'] = past
        db.execute('UPDATE observability_jobs SET payload=%s WHERE tenant_id=%s AND id=%s', (db.json(payload), tid, job['id']))
    expired = repo.process_job(tenant, job['id'])
    assert expired['status'] == 'expired'
    assert expired['payload']['error']['error_code'] == 'GRAFANA_JOB_DEADLINE_EXCEEDED'


def test_lost_lease_prevents_stale_commit(evidence, monkeypatch):
    _, store, _ = evidence
    tenant = workspace()
    repo = GrafanaK8sStore(store)
    created = _connector(repo, tenant, name='G5', uid='mimir-e')
    tid = tenant['tenant_id']
    job = repo.submit(tenant, str(uuid4()), created['id'], window_days=14)
    ok = dict(policy_version='test', items=[], item_count=0)
    steals = []

    def steal_lease_during_query(*_a, **_k):
        if not steals:
            steals.append(1)
            with store.transaction(tid, write=True) as db:
                db.execute(
                    "UPDATE observability_jobs SET lease_token=%s,lease_until=%s WHERE tenant_id=%s AND id=%s",
                    (str(uuid4()), (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat(), tid, job['id']),
                )
        return ok

    monkeypatch.setattr('app.collectors.grafana_rightsizing.run_rightsizing', steal_lease_during_query)
    with pytest.raises(WorkflowConflict, match='lease was lost'):
        repo.process_job(tenant, job['id'], worker_id='w1')
    repo.process_job(tenant, job['id'], worker_id='w2')
    finished = repo.job(tid, job['id'])
    assert finished['status'] == 'completed'
    assert len(finished['payload']['attempts']) == 2
