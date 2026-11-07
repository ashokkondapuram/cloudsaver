from datetime import datetime, timezone
from uuid import uuid4

import httpx
import pytest

from app.collectors import grafana_rightsizing as gk
from tests.test_enterprise import AUTH, TID, evidence, workspace

HOST = 'grafana.example.com'


@pytest.fixture(autouse=True)
def allow(monkeypatch):
    monkeypatch.setenv('CLOUDSAVER_OBSERVABILITY_ALLOWED_HOSTS', HOST)
    monkeypatch.setenv('CLOUDSAVER_OBSERVABILITY_SECRET_PRIMARY', 'test-grafana-token')


def connector_config(**extra):
    base = dict(name='Grafana dev', kind='grafana_mimir', base_url=f'https://{HOST}/', auth_kind='bearer_env',
                secret_ref='CLOUDSAVER_OBSERVABILITY_SECRET_PRIMARY', mimir_datasource_uid='mimir-uid-1',
                cluster_label='cluster', cluster_values=['dev-cluster'])
    base.update(extra)
    return gk.validate_connector(base, workspace())


def test_validate_grafana_connector():
    item = connector_config()
    assert item['kind'] == 'grafana_mimir'
    with pytest.raises(ValueError, match='Mimir datasource'):
        connector_config(mimir_datasource_uid='x')


def test_grafana_test_and_rightsizing_with_mock_frames(monkeypatch):
    def handler(request):
        if request.url.path.endswith('/api/datasources/uid/mimir-uid-1'):
            return httpx.Response(200, json=dict(name='Mimir', type='prometheus', uid='mimir-uid-1'))
        if request.url.path.endswith('/api/ds/query'):
            payload = request.read().decode()
            if 'kube_pod_owner' in payload:
                frame = dict(schema=dict(fields=[{}, dict(name='Value', labels=dict(namespace='ns', pod='p1', owner_kind='ReplicaSet', owner_name='rs-1'))]),
                             data=dict(values=[[1], [1]]))
                return httpx.Response(200, json=dict(results=dict(A=dict(frames=[frame]))))
            if 'kube_replicaset_owner' in payload:
                frame = dict(schema=dict(fields=[{}, dict(name='Value', labels=dict(namespace='ns', replicaset='rs-1', owner_kind='Deployment', owner_name='app'))]),
                             data=dict(values=[[1], [1]]))
                return httpx.Response(200, json=dict(results=dict(A=dict(frames=[frame]))))
            if 'horizontalpodautoscaler' in payload:
                return httpx.Response(200, json=dict(results=dict(A=dict(frames=[]))))
            if 'throttled_periods' in payload:
                frame = dict(schema=dict(fields=[{}, dict(name='Value', labels=dict(namespace='ns', pod='p1', container='app'))]),
                             data=dict(values=[[1700000000000], [0.0]]))
                return httpx.Response(200, json=dict(results=dict(A=dict(frames=[frame]))))
            if 'OOMKilled' in payload or 'last_terminated' in payload:
                return httpx.Response(200, json=dict(results=dict(A=dict(frames=[]))))
            if 'container_cpu_usage' in payload:
                frame = dict(schema=dict(fields=[{}, dict(name='Value', labels=dict(namespace='ns', pod='p1', container='app'))]),
                             data=dict(values=[[1700000000000], [0.1, 0.2, 0.15]]))
            elif 'memory_working_set' in payload:
                frame = dict(schema=dict(fields=[{}, dict(name='Value', labels=dict(namespace='ns', pod='p1', container='app'))]),
                             data=dict(values=[[1700000000000], [100000000, 120000000, 110000000]]))
            elif 'resource_requests' in payload and 'resource=\\"cpu\\"' in payload:
                frame = dict(schema=dict(fields=[{}, dict(name='Value', labels=dict(namespace='ns', pod='p1', container='app', resource='cpu'))]),
                             data=dict(values=[[1700000000000], [0.5]]))
            else:
                frame = dict(schema=dict(fields=[{}, dict(name='Value', labels=dict(namespace='ns', pod='p1', container='app', resource='memory'))]),
                             data=dict(values=[[1700000000000], [536870912]]))
            return httpx.Response(200, json=dict(results=dict(A=dict(frames=[frame]))))
        return httpx.Response(404)

    real_client = httpx.Client

    def client_factory(**kwargs):
        kwargs['transport'] = httpx.MockTransport(handler)
        return real_client(**kwargs)

    monkeypatch.setattr(gk.httpx, 'Client', client_factory)
    config = connector_config()
    assert gk.probe(config)['ok'] is True
    result = gk.run_rightsizing(config, cluster='dev-cluster', window_days=7)
    assert result['item_count'] >= 1
    row = result['items'][0]
    assert row['namespace'] == 'ns' and row['suggested_cpu_request'] is not None
    assert row['workload_kind'] == 'Deployment' and row['workload_name'] == 'app'
    assert 'safety_blocks' in row


def test_api_connectors_and_job(evidence, monkeypatch):
    from app.collectors import grafana_rightsizing as mod

    def stub_rightsizing(config, *, cluster=None, window_days=14):
        return dict(policy_version=mod.POLICY_VERSION, items=[], item_count=0, queried_at=datetime.now(timezone.utc).isoformat(),
                    window_days=window_days, window_start='', window_end='', cluster=cluster)

    def stub_probe(config):
        return dict(ok=True, uid=config['mimir_datasource_uid'])

    monkeypatch.setattr(mod, 'run_rightsizing', stub_rightsizing)
    monkeypatch.setattr(mod, 'probe', stub_probe)
    body = dict(connector=dict(name='Grafana dev', kind='grafana_mimir', base_url=f'https://{HOST}/', auth_kind='bearer_env',
                               secret_ref='CLOUDSAVER_OBSERVABILITY_SECRET_PRIMARY', mimir_datasource_uid='mimir-uid-1',
                               cluster_label='cluster', cluster_values=['dev-cluster']))
    settings, store, _ = evidence
    from fastapi.testclient import TestClient
    from app.main import create_app
    from tests.support import stub_scanner

    client = TestClient(create_app(settings, scanner=stub_scanner))
    response = client.post('/api/v1/kubernetes/grafana/connectors', json=body, headers=AUTH)
    assert response.status_code == 201, response.text
    created = response.json()
    assert created['kind'] == 'grafana_mimir'
    job = client.post('/api/v1/kubernetes/grafana/rightsizing/run', json=dict(
        idempotency_key=str(uuid4()), connector_id=created['id'], cluster='dev-cluster'), headers=AUTH).json()
    assert job['status'] == 'completed'
    again = client.get(f"/api/v1/kubernetes/grafana/rightsizing/jobs/{job['id']}", headers=AUTH).json()
    assert again['payload']['result']['item_count'] == 0
