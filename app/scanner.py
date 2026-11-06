"""Read-only Azure inventory findings. A finding is a review signal, not savings."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID


from app.scan_errors import ScanError
from app.collectors.azure_resource_graph import execute_pages


_PROJECTION = "| project id, name, type, resourceGroup, subscriptionId, tags, location"
RULES = (
    ("AZURE_DISK_UNATTACHED_RETENTION", "HIGH", """Resources
| where type =~ 'microsoft.compute/disks'
| where tostring(properties.diskState) == 'Unattached'
""" + _PROJECTION + ", sizeGB=toint(properties.diskSizeGB), skuName=tostring(sku.name), encryptionType=tostring(properties.encryption.type)",
     "Unattached managed disk. Confirm retention, backup, and recovery requirements before removal."),
    ("AZURE_PUBLIC_IP_UNASSOCIATED", "MEDIUM", """Resources
| where type =~ 'microsoft.network/publicipaddresses'
| where isempty(properties.ipConfiguration.id) and isempty(properties.natGateway.id)
""" + _PROJECTION + ", skuName=tostring(sku.name)",
     "Public IP has no indexed NIC/gateway or NAT gateway association. Verify current dependencies and reservations."),
    ("AZURE_VM_STOPPED_RESIDUAL_COST", "LOW", """Resources
| where type =~ 'microsoft.compute/virtualmachines'
| extend powerState=tostring(properties.extended.instanceView.powerState.code)
| where powerState in ('PowerState/stopped', 'PowerState/deallocated')
""" + _PROJECTION + ", powerState",
     "Stopped/deallocated VM review signal. Storage can remain billable; this does not establish idle duration or savings."),
    ("AZURE_ASP_EMPTY_PAID_PLAN", "MEDIUM", """Resources
| where type =~ 'microsoft.web/serverfarms'
| where toint(properties.numberOfSites) == 0
""" + _PROJECTION + ", skuName=tostring(sku.name), hostedAppCount=toint(properties.numberOfSites), zoneRedundant=properties.zoneRedundant",
     "App Service plan currently reports no hosted sites. Confirm intended capacity and dependencies before changes."),
    ("ORPHANED_NIC", "LOW", """Resources
| where type =~ 'microsoft.network/networkinterfaces'
| where isempty(properties.virtualMachine.id) and isempty(properties.privateEndpoint.id)
""" + _PROJECTION + ", ipConfigs=tostring(properties.ipConfigurations)",
     "Network interface is not attached to any virtual machine or private endpoint. May retain unneeded IP allocations."),
    ("ORPHANED_NSG", "LOW", """Resources
| where type =~ 'microsoft.network/networksecuritygroups'
| where coalesce(array_length(properties.networkInterfaces), 0) == 0 and coalesce(array_length(properties.subnets), 0) == 0
""" + _PROJECTION,
     "Network security group has no associated subnets or network interfaces."),
    ("AZURE_APPGW_EMPTY_OR_HIGH_AUTOSCALE_FLOOR", "HIGH", """Resources
| where type =~ 'microsoft.network/applicationgateways'
| extend pools=properties.backendAddressPools
| where properties.operationalState =~ 'Stopped' or coalesce(array_length(pools), 0) == 0
""" + _PROJECTION + ", skuName=tostring(sku.name)",
     "Application Gateway is stopped or has no configured backend pools. Validate routing intent and billing; this signal does not establish idle duration or savings."),
)


def inventory_query_body() -> str:
    """Uncapped Azure Resource Graph inventory projection (no settings access)."""
    return (
        "Resources | where isnotempty(id)" + _PROJECTION
        + ', diskState=tostring(properties.diskState), powerState=tostring(properties.extended.instanceView.powerState.code)'
        + ', vmSize=tostring(properties.hardwareProfile.vmSize), skuName=tostring(sku.name)'
        + ', hostedAppCount=toint(properties.numberOfSites), skuTier=tostring(sku.tier), createdAt=tostring(properties.timeCreated)'
        + ', resourceLocation=location, managedBy=tostring(managedBy), osDiskId=tostring(properties.storageProfile.osDisk.managedDisk.id)'
        + ', dataDisks=properties.storageProfile.dataDisks, networkInterfaces=properties.networkProfile.networkInterfaces'
        + ', nicIpConfigurations=properties.ipConfigurations, serverFarmId=tostring(properties.serverFarmId)'
        + ', sizeGB=toint(properties.diskSizeGB), provisionedIops=toint(properties.diskIOPSReadWrite)'
        + ', encryptionType=tostring(properties.encryption.type), minimumTlsVersion=tostring(properties.minimumTlsVersion)'
        + ', backupRetentionDays=toint(properties.backupRetentionDays), highAvailability=properties.highAvailability.mode'
        + ', disableLocalAuth=properties.disableLocalAuth, allowBlobPublicAccess=properties.allowBlobPublicAccess'
        + ', zoneRedundant=properties.zoneRedundant, zones=zones'
        + ', kubernetesVersion=tostring(properties.kubernetesVersion), nodeResourceGroup=tostring(properties.nodeResourceGroup)'
        + ', aksPowerState=tostring(properties.powerState.code), fqdn=tostring(properties.fqdn)'
        + ', privateCluster=properties.apiServerAccessProfile.enablePrivateCluster'
        + ', networkPlugin=tostring(properties.networkProfile.networkPlugin), agentPoolProfiles=properties.agentPoolProfiles'
        + ', publicIpConfiguration=properties.ipConfiguration, publicNatGateway=properties.natGateway'
    )


def inventory_query(*, settings=None) -> str:
    """Full ARG inventory query, optionally capped for local pilot scans."""
    query = inventory_query_body()
    from app.cloudsaver_platform_settings import integration_int
    limit = integration_int(settings, 'azure_inventory_limit', 'CLOUDSAVER_AZURE_INVENTORY_LIMIT', default=0)
    if limit == 0:
        return query
    if not 1 <= limit <= 10_000:
        raise ScanError('Azure inventory limit must be 1–10000 when CLOUDSAVER_AZURE_INVENTORY_LIMIT is set.')
    return f'{query} | limit {limit}'


# Backward-compatible name for tests and docs that reference the uncapped query shape.
INVENTORY_QUERY = inventory_query_body()


def scan_inventory_observations(credential, subscriptions: list[str], *, settings=None) -> list[dict]:
    """All scoped resources observed in Azure Resource Graph (not limited to finding rules)."""
    rows = []
    now = datetime.now(timezone.utc)
    observed_at = now.isoformat()
    query = inventory_query(settings=settings)
    for row in execute_pages(credential, query, subscriptions):
        evidence = {'source': 'Azure Resource Graph', 'tags': row.get('tags') or {}}
        for source, target in (('vmSize', 'vm_size'), ('skuName', 'sku_name'), ('diskState', 'disk_state'), ('powerState', 'power_state'), ('skuTier', 'sku_tier'), ('createdAt', 'created_at')):
            if isinstance(row.get(source), str) and row[source]:
                evidence[target] = row[source]
        if type(row.get('hostedAppCount')) is int and row['hostedAppCount'] >= 0:
            evidence['hosted_app_count'] = row['hostedAppCount']
        for source,target in (('sizeGB','size_gb'),('provisionedIops','provisioned_iops'),('backupRetentionDays','backup_retention_days')):
            if type(row.get(source)) is int and row[source]>=0:evidence[target]=row[source]
        if row.get('encryptionType') in ('EncryptionAtRestWithPlatformKey','EncryptionAtRestWithCustomerKey','EncryptionAtRestWithPlatformAndCustomerKeys'):evidence['encrypted']=True
        for source,target in (('allowBlobPublicAccess','allow_blob_public_access'),('zoneRedundant','multi_az'),('disableLocalAuth','managed_secrets'),('allowBlobPublicAccess','publicly_accessible')):
            if type(row.get(source)) is bool:evidence[target]=row[source]
        if row.get('minimumTlsVersion') in ('1.2','1.3','TLS1_2','TLS1_3'):evidence['tls_required']=True
        if row['type'].lower() == 'microsoft.containerservice/managedclusters':
            for source, target in (('kubernetesVersion', 'kubernetes_version'), ('nodeResourceGroup', 'node_resource_group'),
                                    ('aksPowerState', 'power_state'), ('fqdn', 'fqdn'), ('networkPlugin', 'network_plugin')):
                if isinstance(row.get(source), str) and row[source]:
                    evidence[target] = row[source]
            if isinstance(row.get('privateCluster'), bool):
                evidence['private_cluster'] = row['privateCluster']
            pools = row.get('agentPoolProfiles')
            if isinstance(pools, list):
                evidence['node_pools'] = [dict(name=p.get('name'), vm_size=p.get('vmSize'), count=p.get('count'),
                    mode=p.get('mode'), os_type=p.get('osType')) for p in pools if isinstance(p, dict)]
                evidence['node_count'] = sum(p.get('count') or 0 for p in pools if isinstance(p, dict) and type(p.get('count')) is int)
        edges = []
        def edge(kind, source, target):
            if isinstance(source, str) and isinstance(target, str) and source and target:
                edges.append(dict(relationship=kind, from_resource_id=source, to_resource_id=target,
                                  verification_state='verified', observed_at=observed_at))
        kind = row['type'].lower()
        if kind == 'microsoft.compute/disks':
            edge('vm_to_disk', row.get('managedBy'), row['id'])
        elif kind == 'microsoft.compute/virtualmachines':
            edge('vm_to_disk', row['id'], row.get('osDiskId'))
            for item in row.get('dataDisks') or []:
                edge('vm_to_disk', row['id'], (item.get('managedDisk') or {}).get('id'))
            for item in row.get('networkInterfaces') or []:
                edge('vm_to_nic', row['id'], item.get('id'))
        elif kind == 'microsoft.network/networkinterfaces':
            for item in row.get('nicIpConfigurations') or []:
                edge('nic_to_ip', row['id'], ((item.get('properties') or {}).get('publicIPAddress') or {}).get('id'))
        elif kind == 'microsoft.web/sites':
            edge('app_service_to_plan', row['id'], row.get('serverFarmId'))
        elif kind == 'microsoft.network/publicipaddresses':
            ip_cfg = row.get('publicIpConfiguration') or row.get('ipConfiguration')
            nat = row.get('publicNatGateway') or row.get('natGateway')
            if isinstance(ip_cfg, dict) and ip_cfg.get('id'):
                evidence['association_verified'] = True
            elif isinstance(nat, dict) and nat.get('id'):
                evidence['association_verified'] = True
            elif ip_cfg is not None or nat is not None:
                evidence['association_verified'] = False
        rows.append({
            'cloud_provider': 'azure',
            'resource_id': row['id'],
            'resource_name': row['name'],
            'resource_type': row['type'],
            'resource_group': row['resourceGroup'],
            'subscription_id': row['subscriptionId'],
            'scope_id': row['subscriptionId'],
            'evidence': evidence,
            'region': row.get('resourceLocation'), 'dependency_refs': edges,
            'collector_version': 'azure-arg-2026-10-24',
        })
    from app.collectors.azure_configuration_evidence import enrich_inventory_configuration
    from app.resource_timestamps import touch_azure_status_fetched

    rows = enrich_inventory_configuration(rows)
    for resource in rows:
        touch_azure_status_fetched(resource.setdefault('evidence', {}), now=now)
    return rows


def _findings(credential, subscriptions: list[str], enabled_rule_ids: set[str] | None = None) -> list[dict]:
    from app.rule_id_canonical import rule_enabled

    findings = []
    rules = RULES if not enabled_rule_ids else tuple(r for r in RULES if rule_enabled(r[0], enabled_rule_ids))
    for rule_id, severity, query, explanation in rules:
        for row in execute_pages(credential, query, subscriptions):
            evidence = []
            for field in ("sizeGB", "skuName", "powerState", "ipConfigs"):
                if row.get(field) is not None:
                    evidence.append(f"{field}: {str(row[field])[:128]}")
            controls = {}
            if row.get('encryptionType') in ('EncryptionAtRestWithPlatformKey', 'EncryptionAtRestWithCustomerKey', 'EncryptionAtRestWithPlatformAndCustomerKeys'):
                controls['encrypted'] = True
            if type(row.get('hostedAppCount')) is int and row['hostedAppCount'] >= 0:
                controls['hosted_app_count'] = row['hostedAppCount']
            if type(row.get('zoneRedundant')) is bool:
                controls['multi_az'] = row['zoneRedundant']
            findings.append({
                "rule_id": rule_id, "severity": severity,
                "cloud_provider": "azure",
                "resource_name": row["name"], "resource_type": row["type"],
                "resource_group": row["resourceGroup"],
                "subscription_id": row["subscriptionId"], "resource_id": row["id"],
                "region": row.get("resourceLocation") or row.get("location"),
                "estimated_monthly_waste_usd": None,
                "evidence": {"source": "Azure Resource Graph", "tags": row.get("tags") or {}, **controls,
                             **({"size_gb": row["sizeGB"]} if type(row.get("sizeGB")) is int else {}),
                             **({"sku_name": row["skuName"]} if isinstance(row.get("skuName"), str) and row["skuName"] else {}),
                             **({"power_state": row["powerState"]} if isinstance(row.get("powerState"), str) and row["powerState"] else {}),
                             **({"disk_state": row.get("diskState")} if isinstance(row.get("diskState"), str) else {})},
                "details": explanation + (" Evidence: " + "; ".join(evidence) if evidence else ""),
            })
    return findings


def scan_live(
    tenant: dict,
    *,
    enabled_rule_ids: set[str] | None = None,
    progress=None,
    policies: dict | None = None,
    observed_at: str | None = None,
) -> tuple[list[dict], list[dict]]:
    """Scan only authorized subscriptions with a keyless credential for the customer tenant.

    Reader RBAC on each subscription is granted by the customer during onboarding.
    A mid-scan error raises; no partial findings escape or get persisted as complete.
    """
    from app.cloud_identity import CredentialError, azure_credential
    subscriptions = [str(UUID(s)) for s in tenant["subscription_ids"]]
    if not subscriptions:
        raise ScanError("No authorized Azure subscriptions are configured.")
    try:
        credential = azure_credential(tenant)
    except CredentialError as exc:
        raise ScanError(str(exc) or "The customer Azure credential is unavailable.") from None
    with credential:
        from app.config import Settings
        stack_settings = Settings.load()
        inventory = scan_inventory_observations(credential, subscriptions, settings=stack_settings)
        if progress is not None:
            progress.seed_inventory(inventory)
        from app.cloud_http import BearerTokenCache, JSONReader
        arm_auth = BearerTokenCache(credential, 'https://management.azure.com/.default')
        reader = JSONReader(headers_factory=arm_auth)
        arg_findings = _findings(credential, subscriptions, enabled_rule_ids)
        stamp = observed_at or datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        try:
            from app.collectors.azure_arm_detail import enrich_arm_details, enabled as arm_detail_enabled
            from app.collectors.azure_storage_policy import enrich_storage_management_policies
            from app.collectors.cloud_advisor import enrich_inventory_advisor_signals
            from app.collectors.resource_pipeline import enrich_inventory_pipeline
            from app.collectors.wiz_security import enrich_inventory_wiz_from_reader

            if arm_detail_enabled(stack_settings):
                inventory = enrich_arm_details(reader, inventory, settings=stack_settings, progress=progress)
            inventory = enrich_storage_management_policies(reader, inventory, settings=stack_settings)
            inventory = enrich_inventory_advisor_signals(
                reader,
                inventory,
                subscriptions=subscriptions,
                settings=stack_settings,
            )
            inventory = enrich_inventory_wiz_from_reader(reader, inventory, settings=stack_settings)
            inventory, pipeline_findings = enrich_inventory_pipeline(
                reader,
                inventory,
                settings=stack_settings,
                progress=progress,
                arg_findings=arg_findings,
                policies=policies,
                observed_at=stamp,
            )
        finally:
            reader.close()
        merged = list(arg_findings)
        seen = {(f.get('cloud_provider', 'azure'), (f.get('resource_id') or '').lower(), f.get('rule_id')) for f in merged}
        for f in pipeline_findings:
            key = (f.get('cloud_provider', 'azure'), (f.get('resource_id') or '').lower(), f.get('rule_id'))
            if key not in seen:
                seen.add(key)
                merged.append(f)
        return merged, inventory
