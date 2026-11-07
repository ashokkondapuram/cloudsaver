import os

import pytest
from fastapi.testclient import TestClient

from services.analysis_service import create_app


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('CLOUDSAVER_ANALYSIS_INTERNAL_TOKEN', 'test-analysis-token')
    from app.config import Settings
    from tests.test_enterprise import workspace
    app = create_app(Settings('azure', ':memory:', (workspace(),)))
    with TestClient(app) as test_client:
        yield test_client


def test_analyze_resource_requires_service_token(client):
    body = dict(
        resource=dict(
            cloud_provider='azure',
            resource_id='/subscriptions/x/resourceGroups/rg/providers/Microsoft.Compute/disks/d1',
            resource_type='Microsoft.Compute/disks',
            resource_name='d1',
            resource_group='rg',
            subscription_id='x',
            evidence=dict(disk_state='Unattached'),
        ),
        arg_findings=[],
        policies={'AZURE_DISK_UNATTACHED_RETENTION': {'enabled': True}},
        observed_at='2026-11-05T12:00:00+00:00',
    )
    denied = client.post('/internal/v1/analysis/resource', json=body)
    assert denied.status_code == 401
    ok = client.post(
        '/internal/v1/analysis/resource',
        json=body,
        headers={'Authorization': 'Bearer test-analysis-token'},
    )
    assert ok.status_code == 200
    payload = ok.json()
    assert 'evaluations' in payload
    assert 'findings' in payload
    assert 'recommendations' in payload
    assert payload['resource']['evidence']['fetch_stages']['analysis'] == 'completed'


def test_analysis_client_uses_local_when_url_unset(monkeypatch):
    monkeypatch.delenv('ANALYSIS_SERVICE_URL', raising=False)
    from app.analysis_client import analyze_resource

    resource = dict(
        cloud_provider='azure',
        resource_id='/subscriptions/x/resourceGroups/rg/providers/Microsoft.Compute/disks/d1',
        resource_type='Microsoft.Compute/disks',
        resource_name='d1',
        resource_group='rg',
        subscription_id='x',
        evidence=dict(disk_state='Unattached'),
    )
    result = analyze_resource(
        resource,
        policies={'AZURE_DISK_UNATTACHED_RETENTION': {'enabled': True}},
        observed_at='2026-11-05T12:00:00+00:00',
    )
    assert result['evaluations']
    assert resource['evidence']['fetch_stages']['analysis'] == 'completed'
