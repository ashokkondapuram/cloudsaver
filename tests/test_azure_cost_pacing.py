import os
from datetime import date

import pytest

from app.collectors import billing_sync

START, END = date(2026, 10, 1), date(2026, 10, 3)
SUB = '00000000-0000-0000-0000-000000000001'


class Credential:
    token = 'placeholder-token'

    def get_token(self, *_):
        return self

    def refresh(self, *_):
        pass

    def close(self):
        pass


def test_azure_cost_pacing_development_has_no_spacing(monkeypatch):
    monkeypatch.setenv('CLOUDSAVER_ENVIRONMENT', 'development')
    monkeypatch.setenv('CLOUDSAVER_AZURE_COST_INTERVAL_SECONDS', '45')
    interval, deadline = billing_sync._azure_cost_pacing()
    assert interval == 0.0
    assert deadline >= 120


def test_azure_cost_pacing_production_respects_interval(monkeypatch):
    monkeypatch.setenv('CLOUDSAVER_ENVIRONMENT', 'production')
    monkeypatch.setenv('CLOUDSAVER_AZURE_COST_INTERVAL_SECONDS', '20')
    interval, deadline = billing_sync._azure_cost_pacing()
    assert interval == 20.0
    assert deadline >= interval + 90


def test_azure_per_resource_query_rejects_continuation(monkeypatch):
    calls = []

    def post(url, token, body, scope_id=None):
        calls.append((url, body['type']))
        nxt = (
            f'https://management.azure.com/subscriptions/{SUB}/providers/Microsoft.CostManagement/query'
            '?api-version=2023-11-01&skiptoken=next'
        )
        return {
            'properties': {
                'columns': [
                    {'name': 'UsageDate'},
                    {'name': 'ResourceId'},
                    {'name': 'Currency'},
                    {'name': 'PreTaxCost'},
                ],
                'rows': [[20261001, '/sub/r1', 'USD', '1.0']],
                'nextLink': nxt,
            }
        }

    monkeypatch.setattr(billing_sync, '_post', post)
    with pytest.raises(ValueError, match='continuation pages are not imported'):
        billing_sync._azure_resource_query(
            f'https://management.azure.com/subscriptions/{SUB}/providers/Microsoft.CostManagement/query?api-version=2023-11-01',
            Credential(),
            'ActualCost',
            START,
            END,
            SUB,
            '/sub/r1',
        )
    assert len(calls) == 1


def test_azure_per_resource_query_returns_single_page(monkeypatch):
    monkeypatch.setattr(
        billing_sync,
        '_post',
        lambda *_: {
            'properties': {
                'columns': [
                    {'name': 'UsageDate'},
                    {'name': 'ResourceId'},
                    {'name': 'Currency'},
                    {'name': 'PreTaxCost'},
                ],
                'rows': [[20261001, '/sub/r1', 'USD', '2.5']],
            }
        },
    )
    rows = billing_sync._azure_resource_query(
        'https://management.azure.com/q',
        Credential(),
        'ActualCost',
        START,
        END,
        SUB,
        '/sub/r1',
    )
    assert rows == [
        dict(usagedate=20261001, resourceid='/sub/r1', currency='USD', pretaxcost='2.5')
    ]


def test_bigquery_post_configures_bounded_attempts(monkeypatch):
    monkeypatch.setenv('CLOUDSAVER_GCP_BIGQUERY_ATTEMPTS', '2')
    captured = {}

    def fake_read_json(client, method, url, **kwargs):
        captured['attempts'] = kwargs.get('attempts')
        return {'jobComplete': True, 'rows': []}

    monkeypatch.setattr('app.provider_retry.read_json', fake_read_json)
    billing_sync._post(
        'https://bigquery.googleapis.com/bigquery/v2/projects/my-project-12345/queries',
        'token',
        {'query': 'SELECT 1', 'useLegacySql': False},
    )
    assert captured['attempts'] == 2
