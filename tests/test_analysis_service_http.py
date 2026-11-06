"""HTTP tests for standalone analysis-service."""
import json

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from services.analysis_service_app import create_app
from tests.test_enterprise import AUTH, TID, SUB, KEY
import hashlib


class Validator:
    def __call__(self, _credentials):
        from tests.test_enterprise import workspace

        return workspace()


@pytest.fixture
def settings(tmp_path, monkeypatch):
    monkeypatch.setenv(
        'CLOUDSAVER_BILLING_CONNECTORS',
        json.dumps([dict(tenant_id=TID, provider='azure', scope_id=SUB)]),
    )
    return Settings(
        'azure',
        str(tmp_path / 'analysis.sqlite3'),
        (
            dict(
                tenant_id=TID,
                name='Analysis',
                subscription_ids=[SUB],
                api_key_sha256=hashlib.sha256(KEY.encode()).hexdigest(),
            ),
        ),
    )


def test_analysis_service_health(settings):
    client = TestClient(create_app(settings))
    assert client.get('/healthz').status_code == 200
    ready = client.get('/readyz')
    assert ready.status_code == 200


def test_analyze_contexts_endpoint(settings):
    client = TestClient(create_app(settings, identity_validator=Validator()))
    body = {
        'contexts': [
            {
                'provider': 'azure',
                'resource_id': '/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg/providers/Microsoft.Compute/disks/d1',
                'resource_type': 'microsoft.compute/disks',
                'config': {'disk_state': 'Unattached'},
                'cost': {'actual_amortized_30d_usd': 5.0},
            }
        ]
    }
    response = client.post('/api/v1/analysis/resources', json=body, headers=AUTH)
    assert response.status_code == 200
    payload = response.json()
    assert payload['finding_count'] >= 1
    assert payload['account_pillar_scores']['COST_OPTIMIZATION'] < 100
