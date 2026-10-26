"""Resolve platform resource access settings for CloudSaver runtime."""
import os

from app.cloud_identity import TOKEN_EXCHANGE, WORKLOAD_PROVIDER
import re
from uuid import UUID


def _uuid(value):
    if not value:
        return None
    try:
        return str(UUID(str(value))).lower()
    except (ValueError, TypeError):
        return None


def env_defaults():
    client_id = os.getenv('AZURE_CLIENT_ID') or os.getenv('AZURE_MANAGED_IDENTITY_CLIENT_ID')
    access = os.getenv('CLOUDSAVER_AZURE_ACCESS', 'federated')
    if access not in ('federated', 'direct'):
        access = 'federated'
    return {
        'managed_identity_client_id': _uuid(client_id),
        'azure_access': access,
        'azure_app_client_id': _uuid(os.getenv('CLOUDSAVER_AZURE_APP_CLIENT_ID')),
        'azure_token_audience': os.getenv('CLOUDSAVER_AZURE_TOKEN_AUDIENCE', TOKEN_EXCHANGE),
        'aws_hub_role_arn': os.getenv('CLOUDSAVER_AWS_HUB_ROLE_ARN') or None,
        'aws_token_audience': os.getenv('CLOUDSAVER_AWS_TOKEN_AUDIENCE', TOKEN_EXCHANGE),
        'gcp_workload_provider': os.getenv('CLOUDSAVER_GCP_WORKLOAD_PROVIDER') or None,
        'gcp_token_audience': os.getenv('CLOUDSAVER_GCP_TOKEN_AUDIENCE', TOKEN_EXCHANGE),
    }


ROLE_ARN = re.compile(r'arn:aws:iam::[0-9]{12}:role/[A-Za-z0-9+=,.@_/-]{1,512}')


def platform_resource_access(platform):
    if not platform:
        return {}
    return platform.get('resource_access') or {}


def resolve(platform, workspace_identity=None):
    """Per-key precedence: workspace (azure app only), platform, environment."""
    env = env_defaults()
    stored = platform_resource_access(platform)
    identity = workspace_identity or {}

    def pick(key):
        if key == 'azure_app_client_id' and identity.get('azure_app_client_id'):
            return identity['azure_app_client_id'], 'workspace'
        if stored.get(key):
            return stored[key], 'platform'
        if env.get(key):
            return env[key], 'environment'
        return None, 'unset'

    return {key: {'value': pick(key)[0], 'source': pick(key)[1]} for key in env.keys()}


def resolved_values(platform, workspace_identity=None):
    return {key: item['value'] for key, item in resolve(platform, workspace_identity).items()}


def runtime_settings(tenant=None):
    from app.resource_access import env_defaults, resolved_values
    try:
        from app.config import Settings
        loaded = Settings.load()
        registry = loaded.registry
        if registry is not None:
            platform = registry.platform()
            identity = (tenant or {}).get('identity')
            if tenant and tenant.get('tenant_id'):
                stored = registry.get(tenant['tenant_id'])
                if stored:
                    identity = stored.get('identity')
            return resolved_values(platform, identity)
    except Exception:
        pass
    return env_defaults()
