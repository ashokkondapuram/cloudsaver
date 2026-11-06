"""Azure ARM types: API detail, analysis rules, monitor metrics, and evidence contracts."""
from __future__ import annotations

import re
from typing import Any, Mapping

from app.azure_rest_catalog import provider_metadata_params
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
    'microsoft.compute/virtualmachinescalesets': {
        'arm_api_version': '2022-11-01',
        'normalized_fields': ('sku', 'virtualMachineProfile', 'upgradePolicy', 'overprovision', 'singlePlacementGroup'),
    },
    'microsoft.network/networksecuritygroups': {
        'arm_api_version': '2023-05-01',
        'normalized_fields': ('securityRules', 'defaultSecurityRules', 'networkInterfaces', 'subnets'),
    },
    'microsoft.network/loadbalancers': {
        'arm_api_version': '2023-05-01',
        'normalized_fields': ('frontendIPConfigurations', 'backendAddressPools', 'loadBalancingRules', 'probes', 'sku'),
    },
    'microsoft.dbformysql/flexibleservers': {
        'arm_api_version': '2023-06-01-preview',
        'normalized_fields': ('sku', 'storage', 'backup', 'highAvailability', 'network', 'version', 'state'),
    },
    'microsoft.containerinstance/containergroups': {
        'arm_api_version': '2023-05-01',
        'normalized_fields': ('containers', 'imageRegistryCredentials', 'ipAddress', 'osType', 'restartPolicy'),
    },
    'microsoft.servicebus/namespaces': {
        'arm_api_version': '2022-10-01-preview',
        'normalized_fields': ('sku', 'disableLocalAuth', 'zoneRedundant', 'minimumTlsVersion'),
    },
    'microsoft.eventhub/namespaces': {
        'arm_api_version': '2023-01-01-preview',
        'normalized_fields': ('sku', 'isAutoInflateEnabled', 'kafkaEnabled', 'disableLocalAuth', 'zoneRedundant'),
    },
    'microsoft.keyvault/vaults': {
        'arm_api_version': '2023-02-01',
        'normalized_fields': ('sku', 'tenantId', 'enableRbacAuthorization', 'enableSoftDelete', 'publicNetworkAccess'),
    },
    'microsoft.logic/workflows': {
        'arm_api_version': '2019-05-01',
        'normalized_fields': ('state', 'definition', 'parameters', 'accessEndpoint', 'endpointsConfiguration'),
    },
    'microsoft.synapse/workspaces': {
        'arm_api_version': '2021-06-01',
        'normalized_fields': ('defaultDataLakeStorage', 'sqlAdministratorLogin', 'managedResourceGroupName', 'publicNetworkAccess'),
    },
}

# Per-type analysis rules — sourced from analysis_rule_catalog (VM ≠ VMSS bindings).
from app.analysis_rule_catalog import azure_rules_by_resource_type

_TYPE_ANALYSIS_RULES: dict[str, tuple[str, ...]] = azure_rules_by_resource_type()

# Top-level evidence keys collectors and assessment expect per type (configuration + derived).
_EVIDENCE_FIELDS: dict[str, tuple[str, ...]] = {
    'microsoft.compute/disks': (
        'disk_state', 'size_gb', 'provisioned_iops', 'encrypted', 'target_disk',
    ),
    'microsoft.compute/virtualmachines': ('power_state', 'vm_size', 'encrypted'),
    'microsoft.compute/virtualmachinescalesets': ('vm_size', 'power_state'),
    'microsoft.network/publicipaddresses': ('association_verified',),
    'microsoft.network/natgateways': ('routing_verified', 'flow_log_coverage_ratio'),
    'microsoft.network/applicationgateways': (
        'dependencies_verified', 'operational_state', 'backend_pool_count',
    ),
    'microsoft.network/loadbalancers': ('dependencies_verified',),
    'microsoft.network/networkinterfaces': ('nic_orphaned', 'association_verified'),
    'microsoft.network/networksecuritygroups': ('nsg_orphaned',),
    'microsoft.web/serverfarms': ('hosted_app_count', 'sku_tier', 'sku_name', 'https_only'),
    'microsoft.web/sites': ('site_state', 'https_only', 'health_probes_enabled', 'managed_secrets'),
    'microsoft.dbforpostgresql/flexibleservers': (
        'backup_retention_days', 'multi_az', 'tls_required', 'publicly_accessible',
    ),
    'microsoft.dbformysql/flexibleservers': (
        'backup_retention_days', 'multi_az', 'tls_required', 'publicly_accessible',
    ),
    'microsoft.sql/servers/databases': ('multi_az', 'publicly_accessible'),
    'microsoft.documentdb/databaseaccounts': (
        'manual_throughput', 'ru_average_percent', 'multi_az',
    ),
    'microsoft.cache/redis': ('tls_required', 'encrypted'),
    'microsoft.storage/storageaccounts': (
        'encrypted', 'tls_required', 'allow_blob_public_access', 'lifecycle_policy_verified',
    ),
    'microsoft.cognitiveservices/accounts': (
        'provisioned_mode', 'dependencies_verified', 'commitment_lock_conflict',
    ),
    'microsoft.containerservice/managedclusters': ('kubernetes_version', 'power_state', 'multi_az'),
    'microsoft.containerinstance/containergroups': ('power_state',),
    'microsoft.servicebus/namespaces': ('disable_local_auth', 'tls_required'),
    'microsoft.eventhub/namespaces': ('disable_local_auth',),
    'microsoft.keyvault/vaults': ('encrypted', 'public_network_access'),
    'microsoft.logic/workflows': ('site_state',),
    'microsoft.synapse/workspaces': ('publicly_accessible', 'encrypted'),
}

_AZURE_MONITOR_METRICS: dict[str, dict[str, tuple[str, str]]] = {
    'microsoft.compute/virtualmachines': {
        'cpu_percent': ('Percentage CPU', 'Maximum'),
        'memory_free_bytes': ('Available Memory Bytes', 'Minimum'),
        'disk_iops': ('Disk Read Operations/Sec', 'Maximum'),
        'disk_queue': ('Disk Queue Depth', 'Maximum'),
        'network_bytes': ('Network In Total', 'Maximum'),
        'burst_credits': ('CPU Credits Remaining', 'Maximum'),
    },
    'microsoft.compute/virtualmachinescalesets': {
        'cpu_percent': ('Percentage CPU', 'Maximum'),
        'network_bytes': ('Network In Total', 'Maximum'),
    },
    'microsoft.compute/disks': {
        'iops': ('Composite Disk Read Operations/sec', 'Maximum'),
        'throughput': ('Composite Disk Read Bytes/sec', 'Maximum'),
        'burst_credits': ('Disk Paid Burst IO Percentage', 'Maximum'),
    },
    'microsoft.network/publicipaddresses': {'ingress_bytes': ('ByteCount', 'Maximum')},
    'microsoft.network/natgateways': {
        'network_bytes': ('ByteCount', 'Maximum'),
        'connections': ('SNATConnectionCount', 'Maximum'),
    },
    'microsoft.network/applicationgateways': {
        'requests': ('TotalRequests', 'Maximum'),
        'healthy_targets': ('HealthyHostCount', 'Maximum'),
        'capacity_units': ('CapacityUnits', 'Maximum'),
        'latency': ('BackendLastByteResponseTime', 'Maximum'),
    },
    'microsoft.network/loadbalancers': {
        'requests': ('ByteCount', 'Maximum'),
        'healthy_targets': ('DipAvailability', 'Average'),
    },
    'microsoft.web/serverfarms': {
        'cpu_percent': ('CpuPercentage', 'Maximum'),
        'memory_percent': ('MemoryPercentage', 'Maximum'),
        'http_queue': ('HttpQueueLength', 'Maximum'),
    },
    'microsoft.web/sites': {
        'cpu_percent': ('CpuTime', 'Total'),
        'memory_percent': ('MemoryWorkingSet', 'Average'),
        'requests': ('Requests', 'Total'),
    },
    'microsoft.dbforpostgresql/flexibleservers': {
        'cpu_percent': ('cpu_percent', 'Maximum'),
        'memory_percent': ('memory_percent', 'Maximum'),
        'connections': ('active_connections', 'Maximum'),
        'iops': ('iops', 'Maximum'),
    },
    'microsoft.dbformysql/flexibleservers': {
        'cpu_percent': ('cpu_percent', 'Maximum'),
        'memory_percent': ('memory_percent', 'Maximum'),
        'connections': ('active_connections', 'Maximum'),
    },
    'microsoft.sql/servers/databases': {
        'cpu_percent': ('cpu_percent', 'Maximum'),
        'connections': ('connection_successful', 'Maximum'),
    },
    'microsoft.documentdb/databaseaccounts': {
        'normalized_ru_consumption': ('NormalizedRUConsumption', 'Maximum'),
    },
    'microsoft.cache/redis': {
        'memory_percent': ('usedmemorypercentage', 'Maximum'),
        'cpu_percent': ('serverLoad', 'Maximum'),
        'connections': ('connectedclients', 'Maximum'),
        'evictions': ('evictedkeys', 'Maximum'),
    },
    'microsoft.storage/storageaccounts': {
        'bytes': ('UsedCapacity', 'Average'),
        'requests': ('Transactions', 'Total'),
    },
    'microsoft.cognitiveservices/accounts': {
        'ptu_utilization': ('ProvisionedManagedUtilizationV2', 'Maximum'),
        'invocations': ('AzureOpenAIRequests', 'Total'),
    },
    'microsoft.containerservice/managedclusters': {
        'cpu_percent': ('node_cpu_usage_percentage', 'Maximum'),
        'memory_percent': ('node_memory_rss_percentage', 'Maximum'),
    },
    'microsoft.containerinstance/containergroups': {
        'cpu_percent': ('CpuUsage', 'Average'),
        'memory_percent': ('MemoryUsage', 'Average'),
    },
    'microsoft.servicebus/namespaces': {
        'requests': ('IncomingRequests', 'Total'),
        'connections': ('ActiveConnections', 'Maximum'),
    },
    'microsoft.eventhub/namespaces': {
        'requests': ('IncomingMessages', 'Total'),
        'connections': ('ActiveConnections', 'Maximum'),
    },
    'microsoft.keyvault/vaults': {'requests': ('ServiceApiHit', 'Total')},
    'microsoft.logic/workflows': {'requests': ('RunsStarted', 'Total')},
    'microsoft.synapse/workspaces': {'requests': ('SQLStreamingInputEventBytes', 'Total')},
}

RULE_TELEMETRY_METRICS: dict[str, tuple[str, ...]] = {
    'AZURE_DISK_PROVISIONED_PERFORMANCE': ('iops', 'throughput'),
    'AZURE_PUBLIC_IP_ASSOCIATED_IDLE': ('ingress_bytes',),
    'AZURE_VM_RIGHTSIZING_UTILIZATION': ('cpu_percent',),
    'AZURE_VMSS_LOW_UTILIZATION_REVIEW': ('cpu_percent',),
    'AZURE_ASP_UNDERUTILIZED_SKU': ('cpu_percent', 'memory_percent'),
    'AZURE_NAT_GATEWAY_SERVICE_ENDPOINT_BYPASS': ('network_bytes',),
    'AZURE_NAT_GATEWAY_IDLE_LOW_TRAFFIC': ('connections', 'network_bytes'),
    'AZURE_APPGW_EMPTY_OR_HIGH_AUTOSCALE_FLOOR': ('requests', 'healthy_targets'),
    'AZURE_LB_EMPTY_OR_IDLE_BACKEND': ('requests', 'healthy_targets'),
    'AZURE_WEB_APP_IDLE_LOW_REQUESTS': ('requests',),
    'AZURE_AKS_CLUSTER_UTILIZATION_REVIEW': ('cpu_percent', 'memory_percent'),
    'AZURE_ACI_IDLE_LOW_UTILIZATION': ('cpu_percent', 'memory_percent'),
    'AZURE_SQL_PG_IDLE_AND_NONPROD_HA_REVIEW': ('cpu_percent', 'memory_percent'),
    'AZURE_COSMOSDB_MANUAL_RU_TO_AUTOSCALE': ('normalized_ru_consumption',),
    'AZURE_REDIS_UNDERUTILIZED_TIER_REVIEW': ('memory_percent', 'cpu_percent'),
    'AZURE_AI_FOUNDRY_PTU_VS_PAYG_ARBITRAGE': ('ptu_utilization', 'invocations'),
    'AZURE_MESSAGING_IDLE_NAMESPACE': ('requests', 'connections'),
    'AZURE_KEYVAULT_LOW_ACTIVITY': ('requests',),
    'AZURE_LOGIC_WORKFLOW_IDLE': ('requests',),
    'AZURE_SYNAPSE_IDLE_WORKSPACE': ('requests',),
}

_TYPE_FAMILY: dict[str, str] = {
    'microsoft.network/networkinterfaces': 'network-orphan',
    'microsoft.network/networksecuritygroups': 'network-orphan',
    'microsoft.containerservice/managedclusters': 'aks',
    'microsoft.containerinstance/containergroups': 'containers',
    'microsoft.dbformysql/flexibleservers': 'sql-postgres',
    'microsoft.compute/virtualmachinescalesets': 'virtual-machines',
    'microsoft.servicebus/namespaces': 'messaging',
    'microsoft.eventhub/namespaces': 'messaging',
    'microsoft.keyvault/vaults': 'platform',
    'microsoft.logic/workflows': 'integration',
    'microsoft.synapse/workspaces': 'analytics',
}

_PREFIX_FAMILY: tuple[tuple[str, str], ...] = (
    ('microsoft.compute/disks', 'managed-disks'),
    ('microsoft.compute/virtualmachines', 'virtual-machines'),
    ('microsoft.compute/', 'compute-other'),
    ('microsoft.network/publicipaddresses', 'ip-nat'),
    ('microsoft.network/natgateways', 'ip-nat'),
    ('microsoft.network/applicationgateways', 'gateways'),
    ('microsoft.network/loadbalancers', 'gateways'),
    ('microsoft.network/', 'network-other'),
    ('microsoft.web/serverfarms', 'app-service'),
    ('microsoft.web/sites', 'app-service'),
    ('microsoft.web/', 'application-other'),
    ('microsoft.dbforpostgresql/', 'sql-postgres'),
    ('microsoft.dbformysql/', 'sql-postgres'),
    ('microsoft.sql/', 'sql-postgres'),
    ('microsoft.documentdb/', 'cosmosdb'),
    ('microsoft.cache/', 'redis'),
    ('microsoft.storage/', 'blob-storage'),
    ('microsoft.cognitiveservices/', 'ai-foundry'),
    ('microsoft.containerservice/', 'aks'),
    ('microsoft.containerinstance/', 'containers'),
)

UTILIZATION_KEYS: dict[str, tuple[str, ...]] = {
    'managed-disks': ('iops', 'throughput'),
    'virtual-machines': ('cpu_percent', 'disk_iops', 'disk_queue', 'burst_credits'),
    'ip-nat': ('ingress_bytes', 'network_bytes', 'connections'),
    'gateways': ('requests', 'healthy_targets', 'capacity_units', 'latency'),
    'app-service': ('cpu_percent', 'memory_percent', 'http_queue'),
    'sql-postgres': ('cpu_percent', 'memory_percent', 'connections', 'iops'),
    'cosmosdb': ('normalized_ru_consumption',),
    'redis': ('memory_percent', 'cpu_percent', 'connections', 'evictions'),
    'blob-storage': ('bytes', 'requests'),
    'ai-foundry': ('ptu_utilization', 'invocations'),
    'network-orphan': (),
    'aks': ('cpu_percent', 'memory_percent'),
    'containers': ('cpu_percent', 'memory_percent'),
    'messaging': ('requests', 'connections'),
    'platform': ('requests',),
    'integration': ('requests',),
    'analytics': ('requests',),
    'compute-other': ('cpu_percent', 'network_bytes'),
    'network-other': ('ingress_bytes', 'network_bytes'),
    'application-other': ('cpu_percent', 'memory_percent', 'requests'),
}


def _finalize_catalog() -> None:
    for rtype, rules in _TYPE_ANALYSIS_RULES.items():
        entry = _CATALOG.setdefault(
            rtype,
            {'arm_api_version': '2021-04-01', 'normalized_fields': ()},
        )
        entry['analysis_rule_ids'] = rules
        entry['evidence_fields'] = _EVIDENCE_FIELDS.get(rtype, ())
        entry['monitor_metrics'] = _AZURE_MONITOR_METRICS.get(rtype, {})
    for rtype in _AZURE_MONITOR_METRICS:
        entry = _CATALOG.setdefault(
            rtype,
            {'arm_api_version': '2021-04-01', 'normalized_fields': ()},
        )
        entry.setdefault('analysis_rule_ids', ())
        entry.setdefault('evidence_fields', _EVIDENCE_FIELDS.get(rtype, ()))
        entry['monitor_metrics'] = _AZURE_MONITOR_METRICS[rtype]


_finalize_catalog()

_SECRET_PATTERN = re.compile(r'(password|secret|key|token|connectionstring|credential)', re.I)


def normalize_type(resource_type: str | None) -> str:
    return (resource_type or '').lower()


def catalog_entries():
    rows = []
    for rtype, meta in sorted(_CATALOG.items()):
        row = dict(provider='azure', resource_type=rtype, **meta)
        row['telemetry_rule_ids'] = telemetry_rule_ids_for_type(rtype)
        rows.append(row)
    return rows


def analysis_rule_ids_for(resource: dict) -> tuple[str, ...]:
    """Analysis rule ids that apply to this Azure inventory row."""
    if resource.get('cloud_provider', 'azure') != 'azure':
        return ()
    rtype = normalize_type(resource.get('resource_type'))
    rules = _TYPE_ANALYSIS_RULES.get(rtype)
    if rules is not None:
        return rules
    entry = _CATALOG.get(rtype) or {}
    cached = entry.get('analysis_rule_ids')
    if cached:
        return tuple(cached)
    family_id = resolve_family_id(resource)
    if not family_id:
        return ()
    from app.resource_catalog import FAMILIES

    for provider, fid, _cat, _types, family_rules in FAMILIES:
        if provider == 'azure' and fid == family_id:
            return tuple(family_rules)
    return ()


def evidence_fields_for_type(resource_type: str) -> tuple[str, ...]:
    rtype = normalize_type(resource_type)
    if rtype in _EVIDENCE_FIELDS:
        return _EVIDENCE_FIELDS[rtype]
    entry = _CATALOG.get(rtype) or {}
    return tuple(entry.get('evidence_fields') or ())


def telemetry_rule_ids_for_type(resource_type: str) -> tuple[str, ...]:
    return tuple(rid for rid in analysis_rule_ids_for({'cloud_provider': 'azure', 'resource_type': resource_type}) if rid in RULE_TELEMETRY_METRICS)


def telemetry_rules_for_resource(resource: dict) -> list[str]:
    return [rid for rid in analysis_rule_ids_for(resource) if rid in RULE_TELEMETRY_METRICS]


def telemetry_satisfied(rule_id: str, evidence: dict) -> bool:
    from app.evidence_metric_utilization import metric_has_sufficient

    keys = RULE_TELEMETRY_METRICS.get(rule_id)
    if not keys:
        return True
    if rule_id == 'AZURE_VM_RIGHTSIZING_UTILIZATION' or rule_id == 'AZURE_VMSS_LOW_UTILIZATION_REVIEW':
        return metric_has_sufficient(evidence, 'cpu_percent') and (
            metric_has_sufficient(evidence, 'memory_percent') or metric_has_sufficient(evidence, 'memory_free_bytes')
        )
    if rule_id == 'AZURE_AKS_CLUSTER_UTILIZATION_REVIEW' or rule_id == 'AZURE_ACI_IDLE_LOW_UTILIZATION':
        return metric_has_sufficient(evidence, 'cpu_percent') and metric_has_sufficient(evidence, 'memory_percent')
    return all(metric_has_sufficient(evidence, key) for key in keys)


def type_registry_summary(resource: dict) -> dict:
    rtype = normalize_type(resource.get('resource_type'))
    evidence = resource.get('evidence') or {}
    expected = evidence_fields_for_type(rtype)
    pending_fields = [key for key in expected if evidence.get(key) is None]
    pending_telemetry = [
        rid for rid in telemetry_rules_for_resource(resource) if not telemetry_satisfied(rid, evidence)
    ]
    return dict(
        resource_type=rtype,
        family_id=resolve_family_id(resource),
        analysis_rule_ids=analysis_rule_ids_for(resource),
        evidence_fields=expected,
        evidence_fields_pending=pending_fields,
        monitor_metrics=tuple(monitor_metrics_for_type(rtype).keys()),
        telemetry_rule_ids=tuple(pending_telemetry),
    )


def monitor_metrics_for_type(resource_type: str) -> dict[str, tuple[str, str]]:
    rtype = normalize_type(resource_type)
    if rtype in _AZURE_MONITOR_METRICS:
        return dict(_AZURE_MONITOR_METRICS[rtype])
    best: dict[str, tuple[str, str]] = {}
    best_len = -1
    for prefix, _family_id in _PREFIX_FAMILY:
        if rtype.startswith(prefix) and prefix in _AZURE_MONITOR_METRICS and len(prefix) > best_len:
            best_len = len(prefix)
            best = dict(_AZURE_MONITOR_METRICS[prefix])
    return best


def all_monitored_types() -> frozenset[str]:
    return frozenset(_AZURE_MONITOR_METRICS.keys())


def resolve_family_id(resource: dict) -> str | None:
    from app.resource_catalog import family

    fam = family(resource)
    if fam and fam[0] == 'azure':
        return fam[1]
    rtype = normalize_type(resource.get('resource_type'))
    if rtype in _TYPE_FAMILY:
        return _TYPE_FAMILY[rtype]
    for prefix, family_id in _PREFIX_FAMILY:
        if rtype.startswith(prefix):
            return family_id
    return None


def utilization_metrics_for(resource: dict) -> tuple[str, ...]:
    family_id = resolve_family_id(resource)
    if not family_id:
        return ()
    keys = UTILIZATION_KEYS.get(family_id)
    if keys:
        return keys
    collected = monitor_metrics_for_type(resource.get('resource_type', ''))
    return tuple(collected.keys()) if collected else ()


def azure_monitor_metrics_catalog() -> Mapping[str, dict[str, tuple[str, str]]]:
    return _AZURE_MONITOR_METRICS


def all_registry_types() -> frozenset[str]:
    return frozenset(_CATALOG.keys())


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


def resource_type_from_arm_id(resource_id: str) -> str | None:
    """Return lowercase provider/type (e.g. microsoft.compute/virtualmachines) from an ARM resource ID."""
    if '/providers/' not in (resource_id or ''):
        return None
    tail = resource_id.split('/providers/', 1)[-1].lower()
    parts = tail.split('/')
    if len(parts) >= 2:
        return f'{parts[0]}/{parts[1]}'
    return None


def api_version_for_arm_resource_id(resource_id: str, *, fallback: str = '2021-04-01') -> str:
    """Resolve a stable api-version from the read-only catalog (no live provider metadata)."""
    rtype = resource_type_from_arm_id(resource_id)
    if rtype:
        version = arm_api_version(rtype)
        if version:
            return version
    return fallback


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
            provider_metadata_params(),
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
