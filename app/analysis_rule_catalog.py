"""Analysis rule metadata: Well-Architected pillar and exact resource-type bindings (VM ≠ VMSS)."""
from __future__ import annotations

from app.assessment import PILLARS

# Azure: (rule_id, pillar, exact ARM resource types). Authoritative for evaluate_inventory type routing.
_AZURE_RULE_BINDINGS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ('AZURE_DISK_UNATTACHED_RETENTION', 'cost', ('microsoft.compute/disks',)),
    ('AZURE_DISK_PROVISIONED_PERFORMANCE', 'performance', ('microsoft.compute/disks',)),
    ('AZURE_VM_STOPPED_RESIDUAL_COST', 'cost', ('microsoft.compute/virtualmachines',)),
    ('AZURE_VM_RIGHTSIZING_UTILIZATION', 'performance', ('microsoft.compute/virtualmachines',)),
    ('AZURE_VMSS_LOW_UTILIZATION_REVIEW', 'performance', ('microsoft.compute/virtualmachinescalesets',)),
    ('AZURE_PUBLIC_IP_UNASSOCIATED', 'cost', ('microsoft.network/publicipaddresses',)),
    ('AZURE_PUBLIC_IP_ASSOCIATED_IDLE', 'cost', ('microsoft.network/publicipaddresses',)),
    ('AZURE_NAT_GATEWAY_SERVICE_ENDPOINT_BYPASS', 'cost', ('microsoft.network/natgateways',)),
    ('AZURE_NAT_GATEWAY_IDLE_LOW_TRAFFIC', 'cost', ('microsoft.network/natgateways',)),
    ('AZURE_APPGW_EMPTY_OR_HIGH_AUTOSCALE_FLOOR', 'cost', ('microsoft.network/applicationgateways',)),
    ('AZURE_LB_EMPTY_OR_IDLE_BACKEND', 'cost', ('microsoft.network/loadbalancers',)),
    ('ORPHANED_NIC', 'cost', ('microsoft.network/networkinterfaces',)),
    ('ORPHANED_NSG', 'cost', ('microsoft.network/networksecuritygroups',)),
    ('AZURE_ASP_EMPTY_PAID_PLAN', 'cost', ('microsoft.web/serverfarms',)),
    ('AZURE_ASP_UNDERUTILIZED_SKU', 'performance', ('microsoft.web/serverfarms',)),
    ('AZURE_WEB_APP_IDLE_LOW_REQUESTS', 'cost', ('microsoft.web/sites',)),
    ('AZURE_AKS_CLUSTER_UTILIZATION_REVIEW', 'performance', ('microsoft.containerservice/managedclusters',)),
    ('AZURE_ACI_IDLE_LOW_UTILIZATION', 'performance', ('microsoft.containerinstance/containergroups',)),
    ('AZURE_SQL_PG_IDLE_AND_NONPROD_HA_REVIEW', 'cost', ('microsoft.dbforpostgresql/flexibleservers', 'microsoft.dbformysql/flexibleservers', 'microsoft.sql/servers/databases')),
    ('AZURE_DATABASE_PUBLIC_NETWORK_REVIEW', 'security', ('microsoft.dbforpostgresql/flexibleservers', 'microsoft.dbformysql/flexibleservers', 'microsoft.sql/servers/databases', 'microsoft.synapse/workspaces')),
    ('AZURE_COSMOSDB_MANUAL_RU_TO_AUTOSCALE', 'cost', ('microsoft.documentdb/databaseaccounts',)),
    ('AZURE_REDIS_UNDERUTILIZED_TIER_REVIEW', 'performance', ('microsoft.cache/redis',)),
    ('AZURE_REDIS_LEGACY_TLS_REVIEW', 'security', ('microsoft.cache/redis',)),
    ('AZURE_STORAGE_LIFECYCLE_AND_ORPHANED_VHD', 'cost', ('microsoft.storage/storageaccounts',)),
    ('AZURE_STORAGE_PUBLIC_BLOB_ACCESS_REVIEW', 'security', ('microsoft.storage/storageaccounts',)),
    ('AZURE_AI_FOUNDRY_PTU_VS_PAYG_ARBITRAGE', 'cost', ('microsoft.cognitiveservices/accounts',)),
    ('AZURE_MESSAGING_IDLE_NAMESPACE', 'cost', ('microsoft.servicebus/namespaces', 'microsoft.eventhub/namespaces')),
    ('AZURE_KEYVAULT_LOW_ACTIVITY', 'operations', ('microsoft.keyvault/vaults',)),
    ('AZURE_LOGIC_WORKFLOW_IDLE', 'cost', ('microsoft.logic/workflows',)),
    ('AZURE_SYNAPSE_IDLE_WORKSPACE', 'cost', ('microsoft.synapse/workspaces',)),
)

_AZURE_RULE_PILLAR = {rule_id: pillar for rule_id, pillar, _types in _AZURE_RULE_BINDINGS}
_AZURE_RULE_TYPES = {rule_id: types for rule_id, _pillar, types in _AZURE_RULE_BINDINGS}

# Non-Azure catalog rules (family-level; no per-ARM split in v1.4).
_OTHER_RULE_PILLAR: dict[str, str] = {
    'AWS_UNATTACHED_EBS': 'cost',
    'AWS_EBS_GP2_TO_GP3_AND_IOPS_TUNING': 'performance',
    'AWS_EC2_STOPPED_EBS_RESIDUAL': 'cost',
    'AWS_EC2_GRAVITON_AND_SLO_RIGHTSIZING': 'performance',
    'AWS_UNASSOCIATED_EIP': 'cost',
    'AWS_NAT_GW_ENDPOINT_BYPASS_AND_IDLE': 'cost',
    'AWS_ELB_ORPHANED_AND_INGRESS_CONSOLIDATION': 'cost',
    'AWS_IDLE_RDS': 'cost',
    'AWS_RDS_AURORA_RIGHTSIZING_AND_GP3': 'performance',
    'AWS_DYNAMODB_BILLING_MODE_AND_UNUSED_GSI': 'cost',
    'AWS_ELASTICACHE_GRAVITON_AND_VALKEY_UPGRADE': 'performance',
    'AWS_LAMBDA_ARM64_AND_PROVISIONED_CONCURRENCY': 'performance',
    'AWS_S3_INTELLIGENT_TIERING_AND_MULTIPART_CLEANUP': 'cost',
    'AWS_BEDROCK_PT_AND_SAGEMAKER_IDLE_ENDPOINT': 'cost',
    'GCP_UNATTACHED_DISK': 'cost',
    'GCP_DISK_HYPERDISK_IOPS_TUNING': 'performance',
    'GCP_GCE_STOPPED_DISK_TAX': 'cost',
    'GCP_GCE_AXION_AND_CUSTOM_RIGHTSIZING': 'performance',
    'GCP_UNASSIGNED_ADDRESS': 'cost',
    'GCP_CLOUD_NAT_PRIVATE_GOOGLE_ACCESS': 'cost',
    'GCP_LB_EMPTY_BACKEND_FORWARDING_RULE': 'cost',
    'GCP_IDLE_CLOUD_SQL': 'cost',
    'GCP_CLOUDSQL_ALLOYDB_RIGHTSIZING_AND_HA': 'performance',
    'GCP_BIGQUERY_SLOT_AUTOSCALE_AND_STORAGE': 'cost',
    'GCP_CLOUDRUN_MIN_INSTANCE_AND_MEMORYSTORE': 'cost',
    'GCP_VERTEX_AI_IDLE_ENDPOINT_AND_REPLICA_FLOOR': 'cost',
    'K8S_CONTAINER_CPU_OVERREQUEST': 'performance',
    'K8S_CONTAINER_MEMORY_OVERREQUEST': 'performance',
    'K8S_CONTAINER_UNDERPROVISIONED_RISK': 'reliability',
    'K8S_HPA_PDB_CONFLICT_OR_IDLE_FLOOR': 'reliability',
    'K8S_NODE_POOL_FRAGMENTATION_WASTE': 'cost',
    'K8S_ABANDONED_WORKLOAD_OR_NAMESPACE': 'operations',
    'K8S_PVC_UNMOUNTED_OR_LOW_OCCUPANCY': 'cost',
    'K8S_STATEFULSET_SIZING_AND_VOLUME_TEMPLATE': 'reliability',
    'K8S_DAEMONSET_CLUSTER_WIDE_OVERHEAD_TAX': 'cost',
    'K8S_ORPHANED_LOADBALANCER_SERVICE': 'cost',
}

PILLAR_LABELS = {
    'cost': 'Cost',
    'reliability': 'Reliability',
    'performance': 'Performance',
    'security': 'Security',
    'operations': 'Operations',
}

AZURE_RESOURCE_TYPE_LABELS: dict[str, str] = {
    'microsoft.compute/virtualmachines': 'Virtual machine',
    'microsoft.compute/virtualmachinescalesets': 'Virtual machine scale set',
    'microsoft.compute/disks': 'Managed disk',
    'microsoft.containerservice/managedclusters': 'AKS cluster',
    'microsoft.containerinstance/containergroups': 'Container instance',
    'microsoft.web/serverfarms': 'App Service plan',
    'microsoft.web/sites': 'Web app',
    'microsoft.network/publicipaddresses': 'Public IP address',
    'microsoft.network/natgateways': 'NAT gateway',
    'microsoft.network/applicationgateways': 'Application Gateway',
    'microsoft.network/loadbalancers': 'Load balancer',
    'microsoft.network/networkinterfaces': 'Network interface',
    'microsoft.network/networksecuritygroups': 'Network security group',
    'microsoft.storage/storageaccounts': 'Storage account',
    'microsoft.dbforpostgresql/flexibleservers': 'PostgreSQL flexible server',
    'microsoft.dbformysql/flexibleservers': 'MySQL flexible server',
    'microsoft.sql/servers/databases': 'SQL database',
    'microsoft.documentdb/databaseaccounts': 'Cosmos DB account',
    'microsoft.cache/redis': 'Azure Cache for Redis',
    'microsoft.cognitiveservices/accounts': 'Azure AI / Cognitive Services',
    'microsoft.servicebus/namespaces': 'Service Bus namespace',
    'microsoft.eventhub/namespaces': 'Event Hubs namespace',
    'microsoft.keyvault/vaults': 'Key Vault',
    'microsoft.logic/workflows': 'Logic App workflow',
    'microsoft.synapse/workspaces': 'Synapse workspace',
}


def azure_rules_by_resource_type() -> dict[str, tuple[str, ...]]:
    grouped: dict[str, list[str]] = {}
    for rule_id, _pillar, types in _AZURE_RULE_BINDINGS:
        for rtype in types:
            grouped.setdefault(rtype, []).append(rule_id)
    return {rtype: tuple(rules) for rtype, rules in grouped.items()}


def rule_pillar(rule_id: str) -> str:
    from app.rule_id_canonical import canonical_rule_id

    rid = canonical_rule_id(rule_id)
    if rid in _AZURE_RULE_PILLAR:
        return _AZURE_RULE_PILLAR[rid]
    if rid in _OTHER_RULE_PILLAR:
        return _OTHER_RULE_PILLAR[rid]
    if 'STATEFULSET' in rid:
        return 'reliability'
    if 'ABANDONED' in rid or rid == 'K8S_ABANDONED_WORKLOAD_OR_NAMESPACE':
        return 'operations'
    if 'TLS' in rid or 'PUBLIC' in rid and 'NETWORK' in rid or 'BLOB_ACCESS' in rid:
        return 'security'
    if 'RIGHTSIZING' in rid or 'UTILIZATION' in rid or 'PERFORMANCE' in rid or 'THROTTLING' in rid:
        return 'performance'
    return 'cost'


def azure_resource_types_for_rule(rule_id: str) -> tuple[str, ...]:
    from app.rule_id_canonical import canonical_rule_id

    rid = canonical_rule_id(rule_id)
    return _AZURE_RULE_TYPES.get(rid, ())


def resource_types_for_rule(rule_id: str, provider: str, *, family_types: tuple[str, ...] = ()) -> tuple[str, ...]:
    if provider == 'azure':
        bound = azure_resource_types_for_rule(rule_id)
        if bound:
            return bound
    return family_types


def catalog_by_pillar(*, provider: str | None = None) -> dict:
    """Rules grouped under the five assessment pillars (matches drawer pillar model)."""
    from app.resource_catalog import RULE_DISPLAY_NAMES, definitions

    rows = [row for row in definitions() if not provider or row[1] == provider]
    by_pillar: dict[str, list[dict]] = {p: [] for p in PILLARS}
    for rule_id, prov, category, canonical_type, name, _legacy_pillar, bounds in rows:
        types = resource_types_for_rule(rule_id, prov, family_types=(canonical_type,))
        item = dict(
            id=rule_id,
            name=name or RULE_DISPLAY_NAMES.get(rule_id, rule_id),
            provider=prov,
            service_category=category,
            pillar=rule_pillar(rule_id),
            resource_types=list(types),
            parameter_bounds={k: dict(default=v[0], minimum=v[1], maximum=v[2]) for k, v in bounds.items()},
        )
        if prov == 'azure':
            item['resource_type_labels'] = [
                AZURE_RESOURCE_TYPE_LABELS.get(t, t.rsplit('/', 1)[-1]) for t in types
            ]
        by_pillar[item['pillar']].append(item)
    pillars = [
        dict(
            pillar=p,
            label=PILLAR_LABELS[p],
            rules=sorted(by_pillar[p], key=lambda row: row['name'].lower()),
        )
        for p in PILLARS
    ]
    return dict(pillars=pillars, provider=provider, pillar_order=list(PILLARS))


def azure_compute_rule_matrix() -> list[dict]:
    """Explicit VM vs VMSS (and related compute) analysis coverage."""
    compute_types = (
        'microsoft.compute/virtualmachines',
        'microsoft.compute/virtualmachinescalesets',
        'microsoft.containerservice/managedclusters',
        'microsoft.containerinstance/containergroups',
    )
    out = []
    for rtype in compute_types:
        rules = azure_rules_by_resource_type().get(rtype, ())
        out.append(
            dict(
                resource_type=rtype,
                label=AZURE_RESOURCE_TYPE_LABELS.get(rtype, rtype),
                analysis_rule_ids=list(rules),
                by_pillar={
                    p: [rid for rid in rules if rule_pillar(rid) == p] for p in PILLARS
                },
            )
        )
    return out
