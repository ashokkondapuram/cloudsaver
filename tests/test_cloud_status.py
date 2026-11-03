import json

import pytest

from app.cloud_status import billing_scope_rows, cloud_status

TID = '11111111-1111-4111-8111-111111111111'
SUB = '22222222-2222-4222-8222-222222222222'


def test_billing_scope_rows_require_connector_and_workspace_scope(monkeypatch):
    monkeypatch.setenv(
        'CLOUDSAVER_BILLING_CONNECTORS',
        json.dumps([dict(tenant_id=TID, provider='azure', scope_id=SUB)]),
    )
    tenant = dict(tenant_id=TID, subscription_ids=[])
    rows = billing_scope_rows(tenant)
    assert rows['scopes'][0]['authorized_for_workspace'] is False
    tenant['subscription_ids'] = [SUB]
    rows = billing_scope_rows(tenant)
    assert rows['scopes'][0]['authorized_for_workspace'] is True


def test_cloud_status_includes_subscriptions(monkeypatch):
    monkeypatch.setenv('CLOUDSAVER_CLOUD_IDENTITY', 'developer')
    monkeypatch.setenv('CLOUDSAVER_BILLING_CONNECTORS', '[]')
    tenant = dict(tenant_id=TID, subscription_ids=[SUB], identity={})
    summary = cloud_status(tenant, {})
    assert summary['subscription_ids'] == [SUB]
    assert 'access' in summary and 'billing' in summary
