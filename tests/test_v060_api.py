import hashlib
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.remediation_terraform import generate_cloud_terraform_hcl
from app.trends import calculate_trend
from tests.fixtures.synthetic_findings import demo_cloud_findings, demo_workspace

TID = '11111111-1111-4111-8111-111111111111'
SUB = '22222222-2222-4222-8222-222222222222'
KEY = 'test-cloud-workspace-key-with-32-characters'


def workspace():
    return dict(tenant_id=TID, name='Test cloud workspace', subscription_ids=[SUB], plan_tier='ENTERPRISE',
                api_key_sha256=hashlib.sha256(KEY.encode()).hexdigest(),
                gcp_projects=[dict(project_id='test-cloudsaver', regions=['us-central1'])],
                kubernetes_clusters=[dict(cluster_id='demo-cluster', prometheus_url='https://prom.example',
                                         bearer_token_env='CLOUDSAVER_PROMETHEUS_TOKEN_PRIMARY')],
                aws_accounts=[dict(account_id='123456789012', region='us-east-1', credential_profile='test')])


def test_multi_cloud_restart_scope_and_trends(tmp_path, monkeypatch):
    settings = Settings('azure', str(tmp_path/'multi.sqlite'), (workspace(),))
    auth = {'Authorization':'Bearer '+KEY}

    def synthetic_scan(tenant, providers):
        return demo_cloud_findings(demo_workspace(tenant), providers)

    monkeypatch.setattr('app.multi_cloud.scan_multi_cloud', synthetic_scan)
    with TestClient(create_app(settings)) as client:
        assert client.get('/api/v1/me', headers=auth).json()['providers'] == ['azure','aws','gcp','kubernetes']
        first = client.post('/api/v1/scans/multi-cloud', headers=auth, json={'providers':['gcp','kubernetes']})
        assert first.status_code == 201
        first = first.json()
        assert first['total_items_found'] == 5 and first['total_monthly_waste_usd'] is None
        assert first['cloud_providers'] == ['gcp','kubernetes']
        second = client.post('/api/v1/scans/multi-cloud', headers=auth, json={'providers':['kubernetes','gcp']}).json()
        trend = client.get('/api/v1/trends', headers=auth).json()
        assert trend['total_snapshots'] == 2 and trend['direction'] == 'unknown'
        assert trend['new_findings_count'] == 0 and trend['resolved_findings_count'] == 0
        assert client.post('/api/v1/scans/multi-cloud', headers=auth, json={'providers':['gcp','gcp']}).status_code == 422
        assert client.post('/api/v1/scans/multi-cloud', headers=auth, json={'providers':['gcp'],'project_id':'foreign'}).status_code == 422
        assert client.get('/api/v1/trends?days=0', headers=auth).status_code == 422
        assert client.get('/api/v1/trends?scan_id='+str(uuid4()), headers=auth).status_code == 404
        export = client.post('/api/v1/scans/'+first['scan_id']+'/remediation-terraform', headers=auth,
                             json={'resource_ids':[first['findings'][0]['resource_id']]})
        assert export.status_code == 200
    with TestClient(create_app(settings)) as client:
        monkeypatch.setattr('app.multi_cloud.scan_multi_cloud', synthetic_scan)
        assert client.get('/api/v1/scans/'+second['scan_id'], headers=auth).json() == second


def test_multi_cloud_live_failure_does_not_persist_partial(tmp_path, monkeypatch):
    tenant = workspace()
    settings = Settings('azure', str(tmp_path/'multi.sqlite'), (tenant,))
    def failure(*args, **kwargs):
        raise RuntimeError('private credentials and provider message')
    monkeypatch.setattr('app.scanner_gcp.scan_gcp_project', failure)
    auth = {'Authorization':'Bearer '+KEY}
    with TestClient(create_app(settings)) as client:
        assert client.post('/api/v1/scans/multi-cloud', headers=auth, json={'providers':['aws']}).status_code == 422
        result = client.post('/api/v1/scans/multi-cloud', headers=auth, json={'providers':['gcp']})
        assert result.status_code == 502 and 'private' not in result.text
        assert client.get('/api/v1/scans', headers=auth).json() == []


@pytest.mark.parametrize('provider,expected', [('aws','aws_ebs_volume'),('gcp','google_compute_disk')])
def test_import_review_requires_owned_live_scope(provider, expected):
    tenant = demo_workspace(workspace())
    findings = demo_cloud_findings(tenant, [provider])
    scan = dict(mode='multi-cloud', status='completed', findings=findings)
    result = generate_cloud_terraform_hcl(scan, [findings[0]['resource_id']], tenant)
    assert expected in result and 'import {' in result and 'resource "' not in result
    assert 'delete' not in result and 'destroy' not in result
    if provider == 'aws':
        assert 'allowed_account_ids' in result
    else:
        assert 'projects/demo-cloudsaver/zones/us-central1-a/disks/archive' in result
    other = dict(tenant, aws_accounts=[], gcp_projects=[])
    with pytest.raises(ValueError, match='scope'):
        generate_cloud_terraform_hcl(scan, [findings[0]['resource_id']], other)
    with pytest.raises(ValueError, match='live'):
        generate_cloud_terraform_hcl(dict(scan, mode='azure'), [findings[0]['resource_id']], tenant)
    findings[0]['resource_name'] = 'foreign-name'
    if provider == 'aws':
        with pytest.raises(ValueError, match='identity'):
            generate_cloud_terraform_hcl(scan, [findings[0]['resource_id']], tenant)


def test_trend_compares_resource_identity_instead_of_count_and_isolates_scope():
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    def snapshot(id, offset, resource, amount, **kwargs):
        return dict(scan_id=id, timestamp=(now-timedelta(hours=offset)).isoformat(), status='completed',
            mode='multi-cloud', cloud_providers=['gcp'], scope_fingerprint='same', total_items_found=1,
            total_monthly_waste_usd=amount, findings=[dict(cloud_provider='gcp', rule_id='disk', resource_id=resource)]) | kwargs
    scans = [snapshot('old', 2, 'disk-a', 20), snapshot('other', 1, 'disk-b', 1000, scope_fingerprint='other'),
             snapshot('new', 0, 'disk-b', 10)]
    trend = calculate_trend(scans, now=now)
    assert trend['total_snapshots'] == 2 and trend['net_change_usd'] == -10
    assert trend['new_findings_count'] == 1 and trend['resolved_findings_count'] == 1
    assert trend['percentage_change'] == -50 and trend['direction'] == 'decreasing'
    assert calculate_trend([scans[0]], days=1, now=now)['net_change_usd'] is None


def test_gateway_routes_cloud_selection_and_trend_params(tmp_path):
    from services.gateway import create_app as gateway
    class Limiter:
        async def check(self, tid):
            assert tid == TID
    requests = []
    def reply(request):
        requests.append(request)
        return httpx.Response(200, json={'ok':True})
    settings = Settings('azure', str(tmp_path/'unused'), (workspace(),))
    with TestClient(gateway(settings, Limiter(), httpx.MockTransport(reply))) as client:
        auth = {'Authorization':'Bearer '+KEY}
        assert client.get('/api/v1/providers', headers=auth).status_code == 200
        assert client.post('/api/v1/scans/multi-cloud', headers=auth, json={'providers':['gcp']}).status_code == 201
        assert requests[-1].read() == b'{"providers":["gcp"]}'
        assert client.get('/api/v1/trends?days=7', headers=auth).status_code == 200
        assert requests[-1].url.params['days'] == '7'
        assert client.get('/api/v1/trends?days=900', headers=auth).status_code == 422
