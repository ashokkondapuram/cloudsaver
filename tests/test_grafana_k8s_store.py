import json
from uuid import uuid4

import pytest

from app.grafana_k8s_store import GrafanaK8sStore, _request_hash
from app.v150_store import WorkflowConflict
from tests.test_enterprise import evidence, workspace

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
