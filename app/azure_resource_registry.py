"""Azure ARM resource types: API versions and normalized configuration fields."""
from __future__ import annotations

import re
from typing import Any

from app.collectors.azure_endpoint import arm_url

# Read-only inventory detail; api-version per provider namespace (Azure REST).
_CATALOG: dict[str, dict[str, Any]] = {
    'microsoft.compute/disks': {
        'arm_api_version': '2023-04-02',
        'normalized_fields': (
            'diskSizeGB', 'diskIOPSReadWrite', 'diskMBpsReadWrite', 'diskState', 'osType',
            'creationData', 'encryption', 'networkAccessPolicy', 'publicNetworkAccess',
        ),
    },
    'microsoft.compute/virtualmachines': {
        'arm_api_version': '2022-11-01',
        'normalized_fields': (
            'hardwareProfile', 'storageProfile', 'networkProfile', 'osProfile', 'diagnosticsProfile',
            'provisioningState', 'vmId', 'timeCreated',
        ),
    },
    'microsoft.network/publicipaddresses': {
        'arm_api_version': '2023-05-01',
        'normalized_fields': ('publicIPAllocationMethod', 'ipAddress', 'idleTimeoutInMinutes', 'sku', 'zones'),
    },
    'microsoft.network/networkinterfaces': {
        'arm_api_version': '2023-05-01',
        'normalized_fields': ('ipConfigurations', 'enableAcceleratedNetworking', 'provisioningState', 'macAddress'),
    },
    'microsoft.network/natgateways': {
        'arm_api_version': '2023-05-01',
        'normalized_fields': ('sku', 'idleTimeoutInMinutes', 'publicIpAddresses', 'subnet'),
    },
    'microsoft.network/applicationgateways': {
        'arm_api_version': '2023-05-01',
        'normalized_fields': ('sku', 'operationalState', 'enableHttp2', 'autoscaleConfiguration', 'backendAddressPools'),
    },
    'microsoft.web/serverfarms': {
        'arm_api_version': '2023-12-01',
        'normalized_fields': ('sku', 'kind', 'reserved', 'maximumNumberOfWorkers', 'targetWorkerCount', 'status'),
    },
    'microsoft.web/sites': {
        'arm_api_version': '2023-12-01',
        'normalized_fields': (
            'serverFarmId', 'state', 'enabled', 'httpsOnly', 'clientAffinityEnabled', 'siteConfig',
        ),
    },
    'microsoft.dbforpostgresql/flexibleservers': {
        'arm_api_version': '2023-06-01-preview',
        'normalized_fields': ('sku', 'storage', 'backup', 'highAvailability', 'network', 'version', 'state'),
    },
    'microsoft.sql/servers/databases': {
        'arm_api_version': '2023-08-01',
        'normalized_fields': ('sku', 'maxSizeBytes', 'status', 'collation', 'zoneRedundant', 'readScale'),
    },
    'microsoft.documentdb/databaseaccounts': {
        'arm_api_version': '2023-04-15',
        'normalized_fields': (
            'databaseAccountOfferType', 'enableAutomaticFailover', 'enableMultipleWriteLocations',
            'consistencyPolicy', 'locations', 'capabilities',
        ),
    },
    'microsoft.cache/redis': {
        'arm_api_version': '2023-08-01',
        'normalized_fields': ('sku', 'redisVersion', 'enableNonSslPort', 'minimumTlsVersion', 'shardCount', 'replicasPerMaster'),
    },
    'microsoft.storage/storageaccounts': {
        'arm_api_version': '2023-01-01',
        'normalized_fields': (
            'sku', 'kind', 'accessTier', 'minimumTlsVersion', 'allowBlobPublicAccess',
            'supportsHttpsTrafficOnly', 'encryption', 'networkRuleSet', 'isHnsEnabled',
        ),
    },
    'microsoft.cognitiveservices/accounts': {
        'arm_api_version': '2023-05-01',
        'normalized_fields': ('sku', 'kind', 'apiProperties', 'customSubDomainName', 'publicNetworkAccess'),
    },
    'microsoft.containerservice/managedclusters': {
        'arm_api_version': '2024-01-01',
        'normalized_fields': (
            'kubernetesVersion', 'agentPoolProfiles', 'networkProfile', 'apiServerAccessProfile',
            'powerState', 'nodeResourceGroup', 'fqdn', 'disableLocalAccounts',
        ),
    },
}

_SECRET_PATTERN = re.compile(r'(password|secret|key|token|connectionstring|credential)', re.I)


def catalog_entries():
    return [
        dict(provider='azure', resource_type=rtype, **meta)
        for rtype, meta in sorted(_CATALOG.items())
    ]


def arm_api_version(resource_type: str) -> str | None:
    entry = _CATALOG.get((resource_type or '').lower())
    return entry['arm_api_version'] if entry else None


def supports_arm_detail(resource_type: str) -> bool:
    return (resource_type or '').lower() in _CATALOG


def _sanitize_value(value: Any, depth: int = 0) -> Any:
    if depth > 12:
        return None
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            if _SECRET_PATTERN.search(str(key)):
                continue
            sanitized = _sanitize_value(item, depth + 1)
            if sanitized is not None:
                cleaned[key] = sanitized
        return cleaned or None
    if isinstance(value, list):
        items = [_sanitize_value(item, depth + 1) for item in value[:500]]
        return [item for item in items if item is not None]
    if isinstance(value, (str, int, float, bool)) or value is None:
        if isinstance(value, str) and len(value) > 16000:
            return value[:16000] + '…'
        return value
    return str(value)[:2000]


def _provider_resource_namespace(resource_type: str) -> str:
    namespace = (resource_type or '').lower().split('/')[0]
    return '.'.join(part.capitalize() for part in namespace.split('.'))


def _resource_type_suffix(resource_type: str) -> str:
    parts = (resource_type or '').lower().split('/')
    return '/'.join(parts[1:]) if len(parts) > 1 else ''


def _pick_api_version(versions: list[str]) -> str | None:
    if not versions:
        return None
    stable = [v for v in versions if 'preview' not in v.lower()]
    return (stable or versions)[0]


def resolve_arm_api_version(reader, subscription_id: str, resource_type: str, cache: dict) -> str | None:
    """Catalog entry first, then subscription provider metadata (Azure Resource Manager)."""
    rtype = (resource_type or '').lower()
    catalog = arm_api_version(rtype)
    if catalog:
        return catalog
    if not rtype.startswith('microsoft.'):
        return None
    suffix = _resource_type_suffix(rtype)
    if not suffix:
        return None
    version_key = (subscription_id, rtype)
    if version_key in cache:
        return cache[version_key]
    namespace = _provider_resource_namespace(rtype)
    provider_key = (subscription_id, namespace)
    if provider_key not in cache:
        payload = reader.get(
            arm_url(f'/subscriptions/{subscription_id}/providers/{namespace}'),
            {'api-version': '2022-09-01'},
        )
        types = {
            (entry.get('resourceType') or '').lower(): entry.get('apiVersions') or []
            for entry in payload.get('resourceTypes') or []
            if isinstance(entry, dict)
        }
        cache[provider_key] = types
    types_map = cache[provider_key]
    versions = types_map.get(suffix)
    if not versions:
        matches = [(key, vals) for key, vals in types_map.items() if suffix == key or suffix.startswith(f'{key}/')]
        if matches:
            matches.sort(key=lambda item: len(item[0]), reverse=True)
            versions = matches[0][1]
    resolved = _pick_api_version(list(versions or []))
    cache[version_key] = resolved
    return resolved


def normalize_arm_body(body: dict) -> dict:
    """Map a full ARM resource GET into scan-safe typed configuration (all properties, secrets stripped)."""
    if not isinstance(body, dict):
        raise ValueError('Invalid ARM resource body')
    props = body.get('properties') if isinstance(body.get('properties'), dict) else {}
    sku = _sanitize_value(body.get('sku'))
    tags = body.get('tags') if isinstance(body.get('tags'), dict) else {}
    typed = _sanitize_value(props) or {}
    result = {
        'resource_id': body.get('id'),
        'resource_type': body.get('type'),
        'location': body.get('location'),
        'tags': tags,
        'sku': sku,
        'provisioning_state': props.get('provisioningState'),
        'typed_configuration': typed,
        'identity': _sanitize_value(body.get('identity')),
        'zones': body.get('zones'),
        'kind': body.get('kind'),
        'managed_by': body.get('managedBy'),
        'plan': _sanitize_value(body.get('plan')),
    }
    return {key: value for key, value in result.items() if value is not None}
