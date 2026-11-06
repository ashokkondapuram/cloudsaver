"""Stream E — Azure Advisor signal enrichment."""

import pytest

from app.azure_rest_catalog import ADVISOR_RECOMMENDATIONS_API_VERSION, advisor_recommendations_url
from app.collectors.cloud_advisor import (
    enabled,
    enrich_inventory_advisor_signals,
    fetch_aws_trusted_advisor_recommendations,
    fetch_azure_advisor_recommendations,
    fetch_gcp_recommender_recommendations,
    normalize_azure_advisor_recommendation,
)

SUB = '11111111-1111-4111-8111-111111111111'
VM_ID = (
    f'/subscriptions/{SUB}/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1'
)


def test_advisor_catalog_url():
    url = advisor_recommendations_url(SUB)
    assert '/providers/Microsoft.Advisor/recommendations' in url
    assert ADVISOR_RECOMMENDATIONS_API_VERSION == '2023-01-01'


def test_normalize_azure_advisor_recommendation():
    item = {
        'id': f'/subscriptions/{SUB}/providers/Microsoft.Advisor/recommendations/rec-1',
        'name': 'rec-1',
        'properties': {
            'category': 'Cost',
            'impact': 'High',
            'recommendationTypeId': 'abc-123',
            'lastUpdated': '2026-01-01T00:00:00Z',
            'resourceMetadata': {'resourceId': VM_ID},
            'shortDescription': {'problem': 'Underutilized VM', 'solution': 'Resize or shut down'},
        },
    }
    normalized = normalize_azure_advisor_recommendation(item)
    assert normalized['source'] == 'azure_advisor'
    assert normalized['recommendation_id'] == 'rec-1'
    assert normalized['resource_id'] == VM_ID
    assert normalized['category'] == 'Cost'
    assert normalized['problem'] == 'Underutilized VM'


def test_fetch_azure_advisor_recommendations_mocked_get():
    calls: list[tuple] = []

    class Reader:
        def get(self, url, params=None):
            calls.append((url, params))
            if len(calls) == 1:
                return {
                    'value': [
                        {
                            'name': 'rec-1',
                            'properties': {
                                'category': 'Cost',
                                'impact': 'Medium',
                                'resourceMetadata': {'resourceId': VM_ID},
                                'shortDescription': {'problem': 'p', 'solution': 's'},
                            },
                        }
                    ],
                }
            raise AssertionError('unexpected page')

    signals = fetch_azure_advisor_recommendations(Reader(), SUB)
    assert len(signals) == 1
    assert signals[0]['recommendation_id'] == 'rec-1'
    assert calls[0][1]['api-version'] == ADVISOR_RECOMMENDATIONS_API_VERSION


def test_enrich_inventory_advisor_signals_attaches_by_resource_id(monkeypatch):
    monkeypatch.setenv('CLOUDSAVER_CLOUD_ADVISOR_ENABLED', 'true')

    class Reader:
        def get(self, url, params=None):
            return {
                'value': [
                    {
                        'name': 'rec-1',
                        'properties': {
                            'category': 'Cost',
                            'impact': 'High',
                            'resourceMetadata': {'resourceId': VM_ID},
                            'shortDescription': {'problem': 'Idle', 'solution': 'Stop'},
                        },
                    }
                ],
            }

    inventory = [
        {
            'resource_id': VM_ID,
            'evidence': {'source': 'Azure Resource Graph'},
        },
        {
            'resource_id': f'/subscriptions/{SUB}/resourceGroups/rg/providers/Microsoft.Compute/disks/d1',
            'evidence': {},
        },
    ]
    enrich_inventory_advisor_signals(Reader(), inventory, subscriptions=[SUB])
    signals = inventory[0]['evidence']['advisor_signals']
    assert len(signals) == 1
    assert signals[0]['recommendation_id'] == 'rec-1'
    assert 'resource_id' not in signals[0]
    assert 'advisor_signals' not in inventory[1]['evidence']


def test_enabled_respects_flag(monkeypatch):
    monkeypatch.delenv('CLOUDSAVER_CLOUD_ADVISOR_ENABLED', raising=False)
    assert enabled() is False
    monkeypatch.setenv('CLOUDSAVER_CLOUD_ADVISOR_ENABLED', 'true')
    assert enabled() is True


def test_aws_gcp_stubs_return_empty():
    assert fetch_aws_trusted_advisor_recommendations(object(), '123456789012') == []
    assert fetch_gcp_recommender_recommendations(object(), 'my-project') == []


def test_enrich_skipped_when_disabled(monkeypatch):
    monkeypatch.setenv('CLOUDSAVER_CLOUD_ADVISOR_ENABLED', 'false')

    class Reader:
        def get(self, url, params=None):
            raise AssertionError('Advisor GET must not run when disabled')

    inventory = [{'resource_id': VM_ID, 'evidence': {}}]
    enrich_inventory_advisor_signals(Reader(), inventory, subscriptions=[SUB])
    assert 'advisor_signals' not in inventory[0]['evidence']
