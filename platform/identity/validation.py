"""Cloud scope and identity-binding rules, owned by the platform.

These mirror the rules CloudSaver's scanners apply, so the directory never accepts a scope a scanner would
reject. They are a copy, not an import: the two products share only the HTTP contract.
"""
import re
from urllib.parse import urlsplit
from uuid import UUID

PROJECT = r'[a-z][a-z0-9-]{4,28}[a-z0-9]'
NAME = r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?'
REGION = r'[a-z]+(?:-[a-z]+)+-?[0-9]+'
ROLE_ARN = r'arn:aws:iam::([0-9]{12}):role/[A-Za-z0-9+=,.@_/-]{1,512}'
SERVICE_ACCOUNT = r'[a-z][a-z0-9-]{4,28}[a-z0-9]@' + PROJECT + r'\.iam\.gserviceaccount\.com'


def matches(pattern, value):
    return isinstance(value, str) and re.fullmatch(pattern, value) is not None


def normalize_sources(tenant):
    result = {}
    specs = (
        ('aws_accounts', ('account_id', 'region', 'role_arn')),
        ('gcp_projects', ('project_id', 'regions')),
        ('kubernetes_clusters', ('cluster_id', 'prometheus_url', 'bearer_token_env')),
    )
    for key, fields in specs:
        if key not in tenant:
            continue
        entries = tenant.get(key, [])
        if not isinstance(entries, list) or len(entries) > 100:
            raise ValueError('Cloud sources must be bounded lists')
        normalized, seen = [], set()
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) - set(fields):
                raise ValueError('Unknown cloud source configuration field')
            if key == 'aws_accounts':
                if not matches(r'[0-9]{12}', entry.get('account_id')) or not matches(REGION, entry.get('region')):
                    raise ValueError('Invalid AWS account/region')
                role = re.fullmatch(ROLE_ARN, entry.get('role_arn') or '')
                if not role or role[1] != entry['account_id']:
                    raise ValueError('Each AWS account requires a reader role ARN in the same account')
                identity = (entry['account_id'], entry['region'])
            elif key == 'gcp_projects':
                if not matches(PROJECT, entry.get('project_id')):
                    raise ValueError('Invalid GCP project ID')
                regions = entry.get('regions')
                if (not isinstance(regions, list) or not 1 <= len(regions) <= 50
                        or any(not matches(REGION, r) for r in regions) or len(set(regions)) != len(regions)):
                    raise ValueError('Explicit unique GCP regions are required for regional disks')
                identity = entry['project_id']
            else:
                if not matches(NAME, entry.get('cluster_id')):
                    raise ValueError('Invalid Kubernetes cluster ID')
                url = urlsplit(entry.get('prometheus_url', ''))
                if url.scheme != 'https' or not url.hostname or url.username or url.password or url.query or url.fragment:
                    raise ValueError('Prometheus requires an operator-configured HTTPS URL')
                if not matches(r'CLOUDSAVER_PROMETHEUS_TOKEN_[A-Z0-9_]{1,80}', entry.get('bearer_token_env', '')):
                    raise ValueError('Explicit Prometheus bearer-token environment binding required')
                identity = entry['cluster_id']
            if identity in seen:
                raise ValueError('Duplicate cloud source')
            seen.add(identity)
            normalized.append(dict(entry))
        result[key] = normalized
    return result


def normalize_identity(value):
    """Operator-owned bindings; a workspace can't point CloudSaver at another tenant's identity."""
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
