"""Platform resource access settings: validation, environment fallbacks and effective resolution."""
import os
import re
from uuid import UUID

from identity.validation import ROLE_ARN_STRICT, WORKLOAD_PROVIDER, matches

RESOURCE_KEYS = (
    'managed_identity_client_id', 'azure_access', 'azure_app_client_id', 'aws_hub_role_arn',
    'aws_token_audience', 'gcp_workload_provider', 'gcp_token_audience',
)
AUDIENCE = re.compile(r'^(api|https)://[A-Za-z0-9._~:/-]{1,200}$')
TOKEN_EXCHANGE = 'api://AzureADTokenExchange'

GUID_ERROR = 'Enter a client ID in GUID format, such as 00000000-0000-0000-0000-000000000000.'
ARN_ERROR = 'Enter a role ARN such as arn:aws:iam::123456789012:role/CloudSaverHub.'


def _uuid(value, message=GUID_ERROR):
    try:
        return str(UUID(str(value))).lower()
    except (ValueError, TypeError):
        raise ValueError(message) from None


def _audience(value):
    if not matches(AUDIENCE, value):
        raise ValueError('Enter a token audience such as api://AzureADTokenExchange.')
    return value


def env_defaults():
    client_id = os.getenv('AZURE_CLIENT_ID') or os.getenv('AZURE_MANAGED_IDENTITY_CLIENT_ID')
    access = os.getenv('CLOUDSAVER_AZURE_ACCESS', 'federated')
    if access not in ('federated', 'direct'):
        access = 'federated'
    return {
        'managed_identity_client_id': _uuid(client_id, GUID_ERROR) if client_id else None,
        'azure_access': access,
        'azure_app_client_id': _uuid(os.getenv('CLOUDSAVER_AZURE_APP_CLIENT_ID'), GUID_ERROR)
        if os.getenv('CLOUDSAVER_AZURE_APP_CLIENT_ID') else None,
        'aws_hub_role_arn': os.getenv('CLOUDSAVER_AWS_HUB_ROLE_ARN') or None,
        'aws_token_audience': os.getenv('CLOUDSAVER_AWS_TOKEN_AUDIENCE', TOKEN_EXCHANGE),
        'gcp_workload_provider': os.getenv('CLOUDSAVER_GCP_WORKLOAD_PROVIDER') or None,
        'gcp_token_audience': os.getenv('CLOUDSAVER_GCP_TOKEN_AUDIENCE', TOKEN_EXCHANGE),
    }


def normalize_resource_access(value, *, partial=False):
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError('Unknown resource access setting')
    unknown = set(value) - set(RESOURCE_KEYS)
    if unknown:
        raise ValueError('Unknown resource access setting')
    result = {}
    for key, raw in value.items():
        if raw is None:
            continue
        if raw == '':
            result[key] = None
            continue
        if key == 'managed_identity_client_id':
            result[key] = _uuid(raw)
        elif key == 'azure_access':
            if raw not in ('federated', 'direct'):
                raise ValueError('Choose federated or direct Azure access.')
            result[key] = raw
        elif key == 'azure_app_client_id':
            result[key] = _uuid(raw)
        elif key == 'aws_hub_role_arn':
            if not re.fullmatch(ROLE_ARN_STRICT, raw):
                raise ValueError(ARN_ERROR)
            result[key] = raw
        elif key in ('aws_token_audience', 'gcp_token_audience'):
            result[key] = _audience(raw)
        elif key == 'gcp_workload_provider':
            if not re.fullmatch(WORKLOAD_PROVIDER, raw):
                raise ValueError('Enter a valid GCP workload identity provider resource name.')
            result[key] = raw
    return result


def merge_resource_access(current, patch):
    merged = dict(current or {})
    for key, value in patch.items():
        if value is None:
            merged.pop(key, None)
        else:
            merged[key] = value
    return merged


def _platform_value(platform_value, key, env):
    if platform_value and platform_value.get(key):
        return platform_value[key], 'platform'
    fallback = env.get(key)
    if fallback:
        return fallback, 'environment'
    return None, 'unset'


def effective_resource_access(platform_value, workspace_identity=None, env=None):
    env = env or env_defaults()
    items = {}
    for key in RESOURCE_KEYS:
        if key == 'azure_app_client_id' and workspace_identity and workspace_identity.get('azure_app_client_id'):
            items[key] = {'value': workspace_identity['azure_app_client_id'], 'source': 'workspace'}
        else:
            value, source = _platform_value(platform_value, key, env)
            items[key] = {'value': value, 'source': source}
    return items
