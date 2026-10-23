import pytest

from app.access_probe import run_probe, MESSAGES


TID = '11111111-1111-4111-8111-111111111111'


def test_probe_never_returns_secrets(monkeypatch):
    monkeypatch.setenv('CLOUDSAVER_CLOUD_IDENTITY', 'managed_identity')
    monkeypatch.setattr('app.cloud_identity.managed_identity_token', lambda *a, **k: 'secret-token-value')
    result = run_probe(include_managed_identity=True)
    text = repr(result)
    assert 'secret-token-value' not in text
    assert all('token' not in (row.get('message') or '').lower() for row in result['providers'])


def test_probe_messages_are_fixed_strings():
    assert MESSAGES['ok'] == 'Access is ready.'


def test_probe_workspace_without_scopes_marks_not_configured(monkeypatch):
    monkeypatch.setenv('CLOUDSAVER_CLOUD_IDENTITY', 'managed_identity')
    monkeypatch.setattr('app.cloud_identity.managed_identity_token', lambda *a, **k: 't')
    tenant = {'tenant_id': TID, 'subscription_ids': [], 'aws_accounts': [], 'gcp_projects': [], 'identity': {}}
    result = run_probe(tenant, {'resource_access': {}})
    statuses = {row['provider']: row['status'] for row in result['providers']}
    assert statuses['azure'] == 'not_configured'
