import hashlib

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.operations import scheduled_interval, workspace_operations
from app.tenant_config import normalize_tenant
from app.tenant_registry import MemoryRegistry, VersionConflict
from services.tenant import create_app as tenant_service
from tests.identity_fake import FakeIdentity

CID = '22222222-2222-4222-8222-222222222222'

KEY = 'test-workspace-key-with-32-characters'
TID = '11111111-1111-4111-8111-111111111111'
SID = '33333333-3333-4333-8333-333333333333'
OTHER = '44444444-4444-4444-8444-444444444444'
ROLE = 'arn:aws:iam::123456789012:role/CloudSaverReader'
SLACK = 'https://hooks.slack.com/services/T000/B000/abcdef'


def tenant(**changes):
    return normalize_tenant(dict(tenant_id=TID, name='Workspace', subscription_ids=[SID], plan_tier='ENTERPRISE',
                                 customer_id=CID, api_key_sha256=hashlib.sha256(KEY.encode()).hexdigest(), **changes))


@pytest.fixture
def stack(tmp_path):
    registry = MemoryRegistry((tenant(),), platform={'scheduled_scans_enabled': True, 'automated_alerts_enabled': True})
    settings = Settings('azure', str(tmp_path / 'db.sqlite3'), registry.bootstrap, None, registry)
    fake = FakeIdentity()
    return TestClient(tenant_service(settings, identity_client=fake.client())), registry, settings, fake


def as_workspace(key=KEY):
    return {'Authorization': 'Bearer ' + key}


def body(**changes):
    return dict(version=1, subscription_ids=[SID], aws_accounts=[], gcp_projects=[],
                schedule={'frequency': 'daily'}, alerts={'enabled': False, 'channel': None}) | changes


def test_billing_admin_submits_plan_change_request(stack):
    client, registry, _settings, fake = stack
    plans = client.get('/api/v1/billing/plans', headers=as_workspace()).json()
    assert plans['current_tier'] == 'ENTERPRISE' and len(plans['items']) == 3
    assert plans.get('pending_request') is None
    submitted = client.post('/api/v1/billing/plan-requests', headers=as_workspace(),
                            json={'version': 1, 'plan_tier': 'GROWTH'})
    assert submitted.status_code == 202, submitted.text
    assert submitted.json()['status'] == 'pending_approval'
    assert registry.get(TID)['plan_tier'] == 'ENTERPRISE'
    assert fake.plan_requests[TID]['requested_plan_code'] == 'GROWTH'


def test_tenant_admin_changes_scopes_and_schedule_without_restart(stack):
    client, registry, settings = stack
    loaded = client.get('/api/v1/settings', headers=as_workspace()).json()
    assert loaded['editable'] is True and loaded['identity']['aws_external_id'] == TID
    aws = [{'account_id': '123456789012', 'region': 'us-east-1', 'role_arn': ROLE}]
    result = client.put('/api/v1/settings', headers=as_workspace(), json=body(subscription_ids=[SID, OTHER], aws_accounts=aws))
    assert result.status_code == 200, result.text
    assert result.json()['settings']['version'] == 2
    current = settings.tenants[0]
    assert current['subscription_ids'] == [SID, OTHER] and current['aws_accounts'][0]['role_arn'] == ROLE
    assert scheduled_interval(settings, current, 'ENTERPRISE') == 86400
    assert client.get('/api/v1/me', headers=as_workspace()).json()['scan_frequency'] == 'daily'


def test_stale_version_is_rejected(stack):
    client, _, _ = stack
    assert client.put('/api/v1/settings', headers=as_workspace(), json=body()).status_code == 200
    assert client.put('/api/v1/settings', headers=as_workspace(), json=body()).status_code == 409


@pytest.mark.parametrize('field,value', [
    ('aws_accounts', [{'account_id': '123456789012', 'region': 'us-east-1', 'role_arn': ROLE, 'external_id': 'x'}]),
    ('aws_accounts', [{'account_id': '210987654321', 'region': 'us-east-1', 'role_arn': ROLE}]),
    ('identity', {'azure_app_client_id': OTHER}),
    ('kubernetes_clusters', []),
])
def test_tenant_admin_cannot_set_identity_or_foreign_roles(stack, field, value):
    client, _, settings = stack
    assert client.put('/api/v1/settings', headers=as_workspace(), json=body(**{field: value})).status_code == 422
    assert settings.tenants[0]['version'] == 1


def test_plan_limits_are_enforced(stack):
    client, registry, _ = stack
    registry.update(TID, {'plan_tier': 'STARTER'}, 1, 'test')
    assert client.put('/api/v1/settings', headers=as_workspace(), json=body(version=2)).status_code == 402
    alerts = {'enabled': True, 'channel': 'slack', 'webhook_url': SLACK}
    assert client.put('/api/v1/settings', headers=as_workspace(),
                      json=body(version=2, schedule={'frequency': 'manual'}, alerts=alerts)).status_code == 402


def test_alerts_need_a_matching_write_only_webhook(stack):
    client, registry, settings = stack
    on = {'enabled': True, 'channel': 'slack'}
    assert client.put('/api/v1/settings', headers=as_workspace(), json=body(alerts=on)).status_code == 422
    teams_url = dict(on, webhook_url='https://example.webhook.office.com/hook')
    assert client.put('/api/v1/settings', headers=as_workspace(), json=body(alerts=teams_url)).status_code == 422
    saved = client.put('/api/v1/settings', headers=as_workspace(), json=body(alerts=dict(on, webhook_url=SLACK)))
    assert saved.status_code == 200
    assert SLACK not in saved.text and saved.json()['settings']['alerts']['webhook_configured'] is True
    assert registry.webhook_targets() == [{'tenant_id': TID, 'channel': 'slack', 'url': SLACK}]
    assert workspace_operations(settings.tenants[0], settings)['automated_alerts_enabled'] is True


@pytest.mark.parametrize('method,path', [
    ('GET', '/api/v1/admin/tenants'), ('POST', '/api/v1/admin/tenants'),
    ('PATCH', f'/api/v1/admin/tenants/{TID}'), ('GET', '/api/v1/admin/settings'), ('PUT', '/api/v1/admin/settings'),
])
def test_legacy_operator_routes_are_gone(stack, method, path):
    client, _, _ = stack
    assert client.request(method, path, headers=as_workspace(), json={}).status_code in (404, 405)


def test_deactivated_tenant_and_platform_switches_apply_without_restart(stack):
    client, registry, settings = stack
    registry.update_platform({'scheduled_scans_enabled': False}, registry.platform()['version'], 'test')
    assert scheduled_interval(settings, settings.tenants[0], 'ENTERPRISE') is None
    registry.update(TID, {'active': False}, 1, 'test')
    assert client.get('/api/v1/me', headers=as_workspace()).status_code == 401


def test_registry_rejects_unknown_fields_and_stale_writes():
    registry = MemoryRegistry((tenant(),))
    with pytest.raises(ValueError):
        registry.update(TID, {'api_key': 'x'}, 1, 'test')
    registry.update(TID, {'name': 'Renamed'}, 1, 'test')
    with pytest.raises(VersionConflict):
        registry.update(TID, {'name': 'Again'}, 1, 'test')
    assert registry.get(TID)['name'] == 'Renamed'


def test_env_mode_settings_are_read_only(tmp_path):
    settings = Settings('azure', str(tmp_path / 'db.sqlite3'), (tenant(),))
    client = TestClient(tenant_service(settings))
    assert client.get('/api/v1/settings', headers=as_workspace()).json()['editable'] is False
    assert client.put('/api/v1/settings', headers=as_workspace(), json=body()).status_code == 503
