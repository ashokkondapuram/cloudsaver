"""Azure ARM resource type → dedicated PostgreSQL table and column definitions.

Column names follow Azure Resource Manager property paths (snake_case), aligned with
Microsoft REST reference docs for each resource type.
"""
from __future__ import annotations

from typing import Any

# Shared cost columns appended to every typed resource table (all providers).
COST_COLUMNS_SQL = """
    reporting_currency CHAR(3) NOT NULL,
    cost_period_start DATE,
    cost_period_end DATE,
    azure_billed NUMERIC(24,8),
    azure_effective NUMERIC(24,8),
    azure_list NUMERIC(24,8),
    cost_center_billed NUMERIC(24,8),
    cost_center_effective NUMERIC(24,8),
    cost_center_list NUMERIC(24,8),
    azure_charge_count INTEGER NOT NULL DEFAULT 0,
    cost_center_charge_count INTEGER NOT NULL DEFAULT 0
"""

IDENTITY_COLUMNS_SQL = """
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    scan_id UUID NOT NULL,
    resource_id TEXT NOT NULL,
    subscription_id UUID NOT NULL,
    resource_group TEXT NOT NULL,
    name TEXT NOT NULL,
    location TEXT,
    tags JSONB NOT NULL DEFAULT '{}'::jsonb,
    observed_at TIMESTAMPTZ NOT NULL,
    arm_api_version TEXT,
    provisioning_state TEXT,
"""

# microsoft.compute/disks — https://learn.microsoft.com/en-us/rest/api/compute/disks/get
AZURE_COMPUTE_DISKS = {
    'arm_type': 'microsoft.compute/disks',
    'table': 'azure_compute_disks',
    'provider': 'azure',
    'specific_sql': """
        disk_size_gb INTEGER,
        disk_iops_read_write INTEGER,
        disk_mbps_read_write INTEGER,
        disk_state TEXT,
        os_type TEXT,
        sku_name TEXT,
        sku_tier TEXT,
        encryption_type TEXT,
        network_access_policy TEXT,
        creation_data_type TEXT,
        max_shares INTEGER,
        bursting_enabled BOOLEAN
    """,
    'field_map': {
        'disk_size_gb': ('typed_configuration', 'diskSizeGB'),
        'disk_iops_read_write': ('typed_configuration', 'diskIOPSReadWrite'),
        'disk_mbps_read_write': ('typed_configuration', 'diskMBpsReadWrite'),
        'disk_state': ('typed_configuration', 'diskState'),
        'os_type': ('typed_configuration', 'osType'),
        'sku_name': ('arm_sku', 'name'),
        'sku_tier': ('arm_sku', 'tier'),
        'encryption_type': ('typed_configuration', 'encryption', 'type'),
        'network_access_policy': ('typed_configuration', 'networkAccessPolicy'),
        'creation_data_type': ('typed_configuration', 'creationData', 'createOption'),
        'max_shares': ('typed_configuration', 'maxShares'),
        'bursting_enabled': ('typed_configuration', 'burstingEnabled'),
    },
}

AZURE_COMPUTE_VIRTUAL_MACHINES = {
    'arm_type': 'microsoft.compute/virtualmachines',
    'table': 'azure_compute_virtual_machines',
    'provider': 'azure',
    'specific_sql': """
        vm_size TEXT,
        os_type TEXT,
        power_state TEXT,
        priority TEXT,
        zones JSONB,
        os_disk_id TEXT,
        data_disk_count INTEGER
    """,
    'field_map': {
        'vm_size': ('typed_configuration', 'hardwareProfile', 'vmSize'),
        'os_type': ('evidence', 'os_type'),
        'power_state': ('evidence', 'power_state'),
        'priority': ('typed_configuration', 'priority'),
        'zones': ('typed_configuration', 'zones'),
        'os_disk_id': ('typed_configuration', 'storageProfile', 'osDisk', 'managedDisk', 'id'),
        'data_disk_count': ('typed_configuration', 'storageProfile', 'dataDisks'),
    },
}

AZURE_STORAGE_STORAGE_ACCOUNTS = {
    'arm_type': 'microsoft.storage/storageaccounts',
    'table': 'azure_storage_storage_accounts',
    'provider': 'azure',
    'specific_sql': """
        sku_name TEXT,
        sku_tier TEXT,
        kind TEXT,
        access_tier TEXT,
        minimum_tls_version TEXT,
        allow_blob_public_access BOOLEAN,
        supports_https_traffic_only BOOLEAN,
        is_hns_enabled BOOLEAN
    """,
    'field_map': {
        'sku_name': ('typed_configuration', 'sku', 'name'),
        'sku_tier': ('typed_configuration', 'sku', 'tier'),
        'kind': ('typed_configuration', 'kind'),
        'access_tier': ('typed_configuration', 'accessTier'),
        'minimum_tls_version': ('typed_configuration', 'minimumTlsVersion'),
        'allow_blob_public_access': ('typed_configuration', 'allowBlobPublicAccess'),
        'supports_https_traffic_only': ('typed_configuration', 'supportsHttpsTrafficOnly'),
        'is_hns_enabled': ('typed_configuration', 'isHnsEnabled'),
    },
}

AZURE_NETWORK_PUBLIC_IP_ADDRESSES = {
    'arm_type': 'microsoft.network/publicipaddresses',
    'table': 'azure_network_public_ip_addresses',
    'provider': 'azure',
    'specific_sql': """
        public_ip_allocation_method TEXT,
        ip_address TEXT,
        idle_timeout_in_minutes INTEGER,
        sku_name TEXT,
        zones JSONB
    """,
    'field_map': {
        'public_ip_allocation_method': ('typed_configuration', 'publicIPAllocationMethod'),
        'ip_address': ('typed_configuration', 'ipAddress'),
        'idle_timeout_in_minutes': ('typed_configuration', 'idleTimeoutInMinutes'),
        'sku_name': ('typed_configuration', 'sku', 'name'),
        'zones': ('typed_configuration', 'zones'),
    },
}

AZURE_CONTAINERSERVICE_MANAGED_CLUSTERS = {
    'arm_type': 'microsoft.containerservice/managedclusters',
    'table': 'azure_containerservice_managed_clusters',
    'provider': 'azure',
    'specific_sql': """
        kubernetes_version TEXT,
        node_resource_group TEXT,
        fqdn TEXT,
        power_state TEXT,
        network_plugin TEXT,
        private_cluster BOOLEAN,
        agent_pool_count INTEGER,
        node_count INTEGER
    """,
    'field_map': {
        'kubernetes_version': ('typed_configuration', 'kubernetesVersion'),
        'node_resource_group': ('typed_configuration', 'nodeResourceGroup'),
        'fqdn': ('typed_configuration', 'fqdn'),
        'power_state': ('typed_configuration', 'powerState', 'code'),
        'network_plugin': ('typed_configuration', 'networkProfile', 'networkPlugin'),
        'private_cluster': ('typed_configuration', 'apiServerAccessProfile', 'enablePrivateCluster'),
        'agent_pool_count': ('typed_configuration', 'agentPoolProfiles'),
        'node_count': ('evidence', 'node_count'),
    },
}

# AWS pattern (same cost columns) — https://docs.aws.amazon.com/AWSEC2/latest/APIReference/API_Instance.html
AWS_EC2_INSTANCES = {
    'arm_type': 'aws:ec2:instance',
    'table': 'aws_ec2_instances',
    'provider': 'aws',
    'specific_sql': """
        account_id TEXT NOT NULL,
        region TEXT NOT NULL,
        instance_type TEXT,
        state_name TEXT,
        platform TEXT,
        architecture TEXT,
        vpc_id TEXT,
        subnet_id TEXT
    """,
    'field_map': {},
}

AZURE_TABLES = [
    AZURE_COMPUTE_DISKS,
    AZURE_COMPUTE_VIRTUAL_MACHINES,
    AZURE_STORAGE_STORAGE_ACCOUNTS,
    AZURE_NETWORK_PUBLIC_IP_ADDRESSES,
    AZURE_CONTAINERSERVICE_MANAGED_CLUSTERS,
]

ALL_TYPED_TABLES = AZURE_TABLES + [AWS_EC2_INSTANCES]

TYPE_TO_SPEC = {spec['arm_type']: spec for spec in AZURE_TABLES}


def _dig(data: dict, path: tuple[str, ...]):
    cur: Any = data
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    if path[0] == 'typed_configuration' and path[-1] == 'dataDisks' and isinstance(cur, list):
        return len(cur)
    if path[0] == 'typed_configuration' and path[-1] == 'agentPoolProfiles' and isinstance(cur, list):
        return len(cur)
    if path[0] == 'typed_configuration' and path[-1] == 'zones' and isinstance(cur, list):
        return cur
    return cur


def extract_row_fields(observation: dict, spec: dict) -> dict:
    evidence = observation.get('evidence') or {}
    typed = evidence.get('typed_configuration') or {}
    arm_sku = evidence.get('arm_sku') or {}
    bundle = {'evidence': evidence, 'typed_configuration': typed, 'arm_sku': arm_sku}
    row = {}
    for column, path in spec.get('field_map', {}).items():
        row[column] = _dig(bundle, path)
    return row
