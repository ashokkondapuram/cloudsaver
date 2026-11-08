from datetime import datetime, timezone
from uuid import uuid4

import httpx
import pytest

from app.collectors import grafana_rightsizing as gk
from app.collectors.observability import tenant_secret_prefix
from tests.test_enterprise import AUTH, TID, evidence, workspace

HOST = 'grafana.example.com'
SECRET_REF = tenant_secret_prefix({'tenant_id': TID}) + 'PRIMARY'


@pytest.fixture(autouse=True)
def allow(monkeypatch):
    monkeypatch.setenv('CLOUDSAVER_OBSERVABILITY_ALLOWED_HOSTS', HOST)
    monkeypatch.setenv(SECRET_REF, 'test-grafana-token')
    monkeypatch.setenv('CLOUDSAVER_GRAFANA_RIGHTSIZING_INLINE', 'true')


def connector_config(**extra):
    base = dict(name='Grafana dev', kind='grafana_mimir', base_url=f'https://{HOST}/', auth_kind='bearer_env',
                secret_ref=SECRET_REF, mimir_datasource_uid='mimir-uid-1',
                cluster_label='cluster', cluster_values=['dev-cluster'])
    base.update(extra)
    return gk.validate_connector(base, workspace())


def test_grafana_client_blocks_private_destination_before_any_request(monkeypatch):
    config = connector_config(base_url='https://127.0.0.1/', cluster_values=['dev-cluster'])
    monkeypatch.delenv('CLOUDSAVER_OBSERVABILITY_ALLOWED_HOSTS', raising=False)
    result = gk.probe(config)
    assert result == dict(ok=False, error_code='OBSERVABILITY_DESTINATION_BLOCKED')


def test_validate_grafana_connector():
    item = connector_config()
    assert item['kind'] == 'grafana_mimir'
    assert item['latency_query'] is None
    with pytest.raises(ValueError, match='Mimir datasource'):
        connector_config(mimir_datasource_uid='x')


def test_validate_latency_query_on_connector():
    item = connector_config(latency_query='histogram_quantile(0.99, sum by (namespace, pod, container, le) (rate(http_request_duration_seconds_bucket{{{cluster_matcher}}}[5m])))')
    assert 'latency_query' in item and item['latency_datasource_uid'] == item['mimir_datasource_uid']
    with pytest.raises(ValueError, match='latency_datasource_uid'):
        connector_config(latency_datasource_uid='bad')


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
    assert row.get('latency_basis') is None


def test_rightsizing_latency_series_when_query_configured(monkeypatch):
    latency_query = (
        'histogram_quantile(0.99, sum by (namespace, pod, container) '
        '(rate(latency_bucket{' + '{cluster_matcher},container!=""' + '}[5m])))'
    )

    def handler(request):
        if request.url.path.endswith('/api/datasources/uid/mimir-uid-1'):
            return httpx.Response(200, json=dict(name='Mimir', type='prometheus', uid='mimir-uid-1'))
        if request.url.path.endswith('/api/ds/query'):
            payload = request.read().decode()
            if 'latency_bucket' in payload:
                frame = dict(schema=dict(fields=[{}, dict(name='Value', labels=dict(namespace='ns', pod='p1', container='app'))]),
                             data=dict(values=[[1700000000000, 1700000300000], [25.0, 30.0]]))
                return httpx.Response(200, json=dict(results=dict(A=dict(frames=[frame]))))
            if 'kube_pod_owner' in payload:
                frame = dict(schema=dict(fields=[{}, dict(name='Value', labels=dict(namespace='ns', pod='p1', owner_kind='ReplicaSet', owner_name='rs-1'))]),
                             data=dict(values=[[1], [1]]))
                return httpx.Response(200, json=dict(results=dict(A=dict(frames=[frame]))))
            if 'kube_replicaset_owner' in payload:
                frame = dict(schema=dict(fields=[{}, dict(name='Value', labels=dict(namespace='ns', replicaset='rs-1', owner_kind='Deployment', owner_name='app'))]),
                             data=dict(values=[[1], [1]]))
                return httpx.Response(200, json=dict(results=dict(A=dict(frames=[frame]))))
            if 'horizontalpodautoscaler' in payload or 'OOMKilled' in payload or 'last_terminated' in payload:
                return httpx.Response(200, json=dict(results=dict(A=dict(frames=[]))))
            if 'throttled_periods' in payload:
                frame = dict(schema=dict(fields=[{}, dict(name='Value', labels=dict(namespace='ns', pod='p1', container='app'))]),
                             data=dict(values=[[1700000000000], [0.0]]))
                return httpx.Response(200, json=dict(results=dict(A=dict(frames=[frame]))))
            if 'container_cpu_usage' in payload:
                frame = dict(schema=dict(fields=[{}, dict(name='Value', labels=dict(namespace='ns', pod='p1', container='app'))]),
                             data=dict(values=[[1700000000000], [0.1, 0.2]]))
            elif 'memory_working_set' in payload:
                frame = dict(schema=dict(fields=[{}, dict(name='Value', labels=dict(namespace='ns', pod='p1', container='app'))]),
                             data=dict(values=[[1700000000000], [100000000, 120000000]]))
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
    config = connector_config(latency_query=latency_query, latency_unit='milliseconds')
    row = gk.run_rightsizing(config, cluster='dev-cluster', window_days=7)['items'][0]
    assert row['latency_basis'] == 'observability_latency_query'
    assert row['latency_p99_ms'] == 30.0
    assert row['latency_p99_series']['points'][0]['value'] == 25.0


def test_rightsizing_blocks_patch_when_latency_near_slo_target(monkeypatch):
    latency_query = (
        'histogram_quantile(0.99, sum by (namespace, pod, container) '
        '(rate(latency_bucket{' + '{cluster_matcher},container!=""' + '}[5m])))'
    )

    def handler(request):
        if request.url.path.endswith('/api/datasources/uid/mimir-uid-1'):
            return httpx.Response(200, json=dict(name='Mimir', type='prometheus', uid='mimir-uid-1'))
        if request.url.path.endswith('/api/ds/query'):
            payload = request.read().decode()
            if 'latency_bucket' in payload:
                frame = dict(schema=dict(fields=[{}, dict(name='Value', labels=dict(namespace='ns', pod='p1', container='app'))]),
                             data=dict(values=[[1700000000000], [95.0]]))
                return httpx.Response(200, json=dict(results=dict(A=dict(frames=[frame]))))
            if 'kube_pod_owner' in payload:
                frame = dict(schema=dict(fields=[{}, dict(name='Value', labels=dict(namespace='ns', pod='p1', owner_kind='ReplicaSet', owner_name='rs-1'))]),
                             data=dict(values=[[1], [1]]))
                return httpx.Response(200, json=dict(results=dict(A=dict(frames=[frame]))))
            if 'kube_replicaset_owner' in payload:
                frame = dict(schema=dict(fields=[{}, dict(name='Value', labels=dict(namespace='ns', replicaset='rs-1', owner_kind='Deployment', owner_name='app'))]),
                             data=dict(values=[[1], [1]]))
                return httpx.Response(200, json=dict(results=dict(A=dict(frames=[frame]))))
            if 'horizontalpodautoscaler' in payload or 'OOMKilled' in payload or 'last_terminated' in payload:
                return httpx.Response(200, json=dict(results=dict(A=dict(frames=[]))))
            if 'throttled_periods' in payload:
                frame = dict(schema=dict(fields=[{}, dict(name='Value', labels=dict(namespace='ns', pod='p1', container='app'))]),
                             data=dict(values=[[1700000000000], [0.0]]))
                return httpx.Response(200, json=dict(results=dict(A=dict(frames=[frame]))))
            if 'container_cpu_usage' in payload:
                frame = dict(schema=dict(fields=[{}, dict(name='Value', labels=dict(namespace='ns', pod='p1', container='app'))]),
                             data=dict(values=[[1700000000000], [0.1, 0.2]]))
            elif 'memory_working_set' in payload:
                frame = dict(schema=dict(fields=[{}, dict(name='Value', labels=dict(namespace='ns', pod='p1', container='app'))]),
                             data=dict(values=[[1700000000000], [100000000, 120000000]]))
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
    config = connector_config(latency_query=latency_query, slo_latency_target_ms=100)
    result = gk.run_rightsizing(config, cluster='dev-cluster', window_days=7)
    row = result['items'][0]
    assert 'BLOCKED_BY_TAIL_LATENCY_PROXIMITY' in row['safety_blocks']
    assert row['patch_eligible'] is False
    assert result['latency_query_status'] == 'observed'


def test_two_clusters_with_same_workload_identity_stay_isolated(monkeypatch):
    def handler(request):
        if request.url.path.endswith('/api/datasources/uid/mimir-uid-1'):
            return httpx.Response(200, json=dict(name='Mimir', type='prometheus', uid='mimir-uid-1'))
        if request.url.path.endswith('/api/ds/query'):
            payload = request.read().decode()
            cluster = 'cluster-a' if 'cluster-a' in payload else 'cluster-b'
            if 'kube_pod_owner' in payload or 'kube_replicaset_owner' in payload or 'horizontalpodautoscaler' in payload:
                return httpx.Response(200, json=dict(results=dict(A=dict(frames=[]))))
            cpu = 0.4 if cluster == 'cluster-a' else 0.05
            req = 0.8 if cluster == 'cluster-a' else 0.2
            if 'container_cpu_usage' in payload:
                frame = dict(schema=dict(fields=[{}, dict(name='Value', labels=dict(cluster=cluster, namespace='ns', pod='p1', container='app'))]),
                             data=dict(values=[[1700000000000], [cpu]]))
            elif 'resource_requests' in payload and 'resource=\\"cpu\\"' in payload:
                frame = dict(schema=dict(fields=[{}, dict(name='Value', labels=dict(cluster=cluster, namespace='ns', pod='p1', container='app', resource='cpu'))]),
                             data=dict(values=[[1700000000000], [req]]))
            else:
                frame = dict(schema=dict(fields=[{}, dict(name='Value', labels=dict(cluster=cluster, namespace='ns', pod='p1', container='app'))]),
                             data=dict(values=[[1700000000000], [0.0]]))
            return httpx.Response(200, json=dict(results=dict(A=dict(frames=[frame]))))
        return httpx.Response(404)

    real_client = httpx.Client

    def client_factory(**kwargs):
        kwargs['transport'] = httpx.MockTransport(handler)
        return real_client(**kwargs)

    monkeypatch.setattr(gk.httpx, 'Client', client_factory)
    config = connector_config(cluster_values=['cluster-a', 'cluster-b'])
    result = gk.run_rightsizing(config, window_days=7)
    by_cluster = {row['cluster']: row for row in result['items']}
    assert by_cluster['cluster-a']['suggested_cpu_request'] != by_cluster['cluster-b']['suggested_cpu_request']


def test_hpa_query_failure_blocks_cpu_downsize(monkeypatch):
    def handler(request):
        if request.url.path.endswith('/api/datasources/uid/mimir-uid-1'):
            return httpx.Response(200, json=dict(name='Mimir', type='prometheus', uid='mimir-uid-1'))
        if request.url.path.endswith('/api/ds/query'):
            payload = request.read().decode()
            if 'horizontalpodautoscaler' in payload:
                return httpx.Response(503)
            if 'kube_pod_owner' in payload or 'kube_replicaset_owner' in payload:
                return httpx.Response(200, json=dict(results=dict(A=dict(frames=[]))))
            if 'container_cpu_usage' in payload:
                frame = dict(schema=dict(fields=[{}, dict(name='Value', labels=dict(namespace='ns', pod='p1', container='app'))]),
                             data=dict(values=[[1700000000000], [0.05]]))
            elif 'resource_requests' in payload and 'resource=\\"cpu\\"' in payload:
                frame = dict(schema=dict(fields=[{}, dict(name='Value', labels=dict(namespace='ns', pod='p1', container='app', resource='cpu'))]),
                             data=dict(values=[[1700000000000], [0.5]]))
            else:
                frame = dict(schema=dict(fields=[{}, dict(name='Value', labels=dict(namespace='ns', pod='p1', container='app'))]),
                             data=dict(values=[[1700000000000], [0.0]]))
            return httpx.Response(200, json=dict(results=dict(A=dict(frames=[frame]))))
        return httpx.Response(404)

    real_client = httpx.Client

    def client_factory(**kwargs):
        kwargs['transport'] = httpx.MockTransport(handler)
        return real_client(**kwargs)

    monkeypatch.setattr(gk.httpx, 'Client', client_factory)
    row = gk.run_rightsizing(connector_config(), cluster='dev-cluster', window_days=7)['items'][0]
    assert row['hpa_managed'] is None
    assert 'HPA_STATUS_NOT_OBSERVED' in row['safety_blocks']
    assert row['patch_eligible'] is False


def test_api_connectors_and_job(evidence, monkeypatch):
    from app.collectors import grafana_rightsizing as mod
    monkeypatch.setenv('CLOUDSAVER_GRAFANA_RIGHTSIZING_INLINE', 'true')

    def stub_rightsizing(config, *, cluster=None, window_days=14, deadline_at=None):
        return dict(policy_version=mod.POLICY_VERSION, items=[], item_count=0, queried_at=datetime.now(timezone.utc).isoformat(),
                    window_days=window_days, window_start='', window_end='', cluster=cluster)

    def stub_probe(config):
        return dict(ok=True, uid=config['mimir_datasource_uid'])

    monkeypatch.setattr(mod, 'run_rightsizing', stub_rightsizing)
    monkeypatch.setattr(mod, 'probe', stub_probe)
    body = dict(connector=dict(name='Grafana dev', kind='grafana_mimir', base_url=f'https://{HOST}/', auth_kind='bearer_env',
                               secret_ref=SECRET_REF, mimir_datasource_uid='mimir-uid-1',
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
