"""Cost Explorer billing reader pagination and retry policy (no live AWS)."""
from datetime import date
from types import SimpleNamespace

import pytest

from app.collectors import billing_sync


def _metrics(billed, effective='0', unit='USD'):
    return {
        'UnblendedCost': {'Amount': billed, 'Unit': unit},
        'AmortizedCost': {'Amount': effective, 'Unit': unit},
    }


def test_aws_cost_explorer_config_matches_provider_retry_attempts():
    config = billing_sync._aws_cost_explorer_config()
    assert config.retries['max_attempts'] == 3
    assert config.retries['mode'] == 'adaptive'


def test_aws_rows_follows_cost_explorer_pagination(monkeypatch):
    pages = []

    class CE:
        def __init__(self):
            self.calls = 0

        def get_cost_and_usage(self, **args):
            self.calls += 1
            if 'NextPageToken' in args:
                assert args['NextPageToken'] == 'page-2'
                return {
                    'ResultsByTime': [{
                        'TimePeriod': {'Start': '2026-10-02'},
                        'Groups': [{'Keys': ['Tax'], 'Metrics': _metrics('1.00', '1.00')}],
                    }],
                }
            assert args['Filter']['Dimensions']['Values'] == ['123456789012']
            return {
                'NextPageToken': 'page-2',
                'ResultsByTime': [{
                    'TimePeriod': {'Start': '2026-10-01'},
                    'Groups': [{'Keys': ['Usage'], 'Metrics': _metrics('5', '4')}],
                }],
            }

        def close(self):
            pages.append('closed')

    captured = {}

    def client(service, *, region_name, config):
        captured['service'] = service
        captured['region_name'] = region_name
        captured['config'] = config
        return CE()

    monkeypatch.setattr(
        'app.cloud_identity.aws_session',
        lambda *a, **kw: SimpleNamespace(client=client),
    )
    tenant = dict(aws_accounts=[dict(account_id='123456789012', region='us-east-1')])
    rows, grain, _ = billing_sync.aws_rows(
        dict(scope_id='123456789012'),
        tenant,
        date(2026, 10, 1),
        date(2026, 10, 3),
    )
    assert captured['service'] == 'ce'
    assert captured['region_name'] == 'us-east-1'
    assert captured['config'].retries['mode'] == 'adaptive'
    assert len(rows) == 2
    assert {r['day'].isoformat() for r in rows} == {'2026-10-01', '2026-10-02'}
    assert grain == 'account'
    assert pages == ['closed']


def test_aws_rows_raises_when_pagination_never_terminates(monkeypatch):
    class CE:
        def get_cost_and_usage(self, **_):
            return {
                'NextPageToken': 'forever',
                'ResultsByTime': [{
                    'TimePeriod': {'Start': '2026-10-01'},
                    'Groups': [{'Keys': ['Usage'], 'Metrics': _metrics('1', '1')}],
                }],
            }

        def close(self):
            pass

    monkeypatch.setattr(
        'app.cloud_identity.aws_session',
        lambda *a, **kw: SimpleNamespace(client=lambda *a, **kw: CE()),
    )
    tenant = dict(aws_accounts=[dict(account_id='123456789012', region='us-east-1')])
    with pytest.raises(ValueError, match='pagination limit exceeded'):
        billing_sync.aws_rows(dict(scope_id='123456789012'), tenant, date(2026, 10, 1), date(2026, 10, 2))
