"""Validation shared by the bootstrap seed, the tenant registry and the settings API."""
import re
from uuid import UUID

from app.cloud_scope import SERVICE_ACCOUNT, matches, normalize_sources

TIERS = ('STARTER', 'GROWTH', 'ENTERPRISE')
FREQUENCIES = ('manual', 'daily', 'hourly')
CHANNELS = ('slack', 'teams')


def default_frequency(tier):
    return {'ENTERPRISE': 'hourly', 'GROWTH': 'daily'}.get(tier, 'manual')


def normalize_identity(value):
    """Operator-owned bindings; tenant admins cannot point CloudSaver at another tenant's identity."""
    value = value or {}
    if not isinstance(value, dict) or set(value) - {'azure_app_client_id', 'gcp_service_account'}:
        raise ValueError('Unknown identity setting')
    result = {}
    if value.get('azure_app_client_id'):
        try:
            result['azure_app_client_id'] = str(UUID(str(value['azure_app_client_id'])))
        except ValueError:
            raise ValueError('Azure app client ID must be a UUID') from None
    if value.get('gcp_service_account'):
        if not matches(SERVICE_ACCOUNT, value['gcp_service_account']):
            raise ValueError('Invalid GCP service account email')
        result['gcp_service_account'] = value['gcp_service_account']
    return result


def normalize_schedule(value, tier):
    value = value or {}
    if not isinstance(value, dict) or set(value) - {'frequency'}:
        raise ValueError('Unknown schedule setting')
    frequency = value.get('frequency') or default_frequency(tier)
    if frequency not in FREQUENCIES:
        raise ValueError('Scan frequency must be manual, daily or hourly')
    return {'frequency': frequency}


def normalize_alerts(value):
    value = value or {}
    if not isinstance(value, dict) or set(value) - {'enabled', 'channel'}:
        raise ValueError('Unknown alert setting')
    enabled = value.get('enabled', False)
    channel = value.get('channel')
    if not isinstance(enabled, bool) or (channel is not None and channel not in CHANNELS):
        raise ValueError('Alerts require a boolean switch and a Slack or Teams channel')
    if enabled and channel is None:
        raise ValueError('Choose a Slack or Teams channel before enabling alerts')
    return {'enabled': enabled, 'channel': channel}


def normalize_tenant(raw, *, require_scope=False):
    """Return the canonical tenant dict or raise ValueError with a safe message."""
    if not isinstance(raw, dict):
        raise ValueError('Each tenant must be an object')
    try:
        tenant_id = str(UUID(str(raw['tenant_id'])))
        subscriptions = [str(UUID(str(s))) for s in raw.get('subscription_ids', [])]
    except (KeyError, ValueError, TypeError):
        raise ValueError('Tenant and subscription IDs must be UUIDs') from None
    name = raw.get('name')
    if not isinstance(name, str) or not name.strip() or len(name) > 120:
        raise ValueError('Each tenant requires a name of 1–120 characters')
    if len(subscriptions) > 100 or len(set(subscriptions)) != len(subscriptions):
        raise ValueError('Configure up to 100 unique subscription IDs')
    sources = normalize_sources(raw)
    if require_scope and not subscriptions and not any(sources.values()):
        raise ValueError('Configure unique subscription IDs or explicit cloud sources per tenant')
    digest = raw.get('api_key_sha256', '')
    if not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest):
        raise ValueError('api_key_sha256 must be a lowercase SHA256 hex digest')
    tier = raw.get('plan_tier', 'STARTER')
    if tier not in TIERS:
        raise ValueError('Invalid plan tier')
    active = raw.get('active', True)
    if not isinstance(active, bool):
        raise ValueError('Tenant status must be a boolean')
    return dict(tenant_id=tenant_id, name=name.strip(), subscription_ids=subscriptions,
                api_key_sha256=digest, plan_tier=tier, active=active,
                identity=normalize_identity(raw.get('identity')),
                schedule=normalize_schedule(raw.get('schedule'), tier),
                alerts=normalize_alerts(raw.get('alerts')),
                version=int(raw.get('version', 0)), **sources)


SCOPE_KEYS = ('subscription_ids', 'aws_accounts', 'gcp_projects', 'kubernetes_clusters')
CONFIG_KEYS = SCOPE_KEYS + ('identity', 'schedule', 'alerts')


def config_of(tenant):
    return {key: tenant[key] for key in CONFIG_KEYS}
