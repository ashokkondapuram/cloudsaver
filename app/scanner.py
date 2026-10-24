"""Read-only Azure inventory findings. A finding is a review signal, not savings."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID


class ScanError(RuntimeError):
    """The scan could not produce a complete, authorized result."""


_PROJECTION = "| project id, name, type, resourceGroup, subscriptionId, tags, location"
RULES = (
    ("ORPHANED_DISK", "HIGH", """Resources
| where type =~ 'microsoft.compute/disks'
| where tostring(properties.diskState) == 'Unattached'
""" + _PROJECTION + ", sizeGB=toint(properties.diskSizeGB), skuName=tostring(sku.name), encryptionType=tostring(properties.encryption.type)",
     "Unattached managed disk. Confirm retention, backup, and recovery requirements before removal."),
    ("UNASSOCIATED_PUBLIC_IP", "MEDIUM", """Resources
| where type =~ 'microsoft.network/publicipaddresses'
| where isempty(properties.ipConfiguration.id) and isempty(properties.natGateway.id)
""" + _PROJECTION + ", skuName=tostring(sku.name)",
     "Public IP has no indexed NIC/gateway or NAT gateway association. Verify current dependencies and reservations."),
    ("STOPPED_VM", "LOW", """Resources
| where type =~ 'microsoft.compute/virtualmachines'
| extend powerState=tostring(properties.extended.instanceView.powerState.code)
| where powerState in ('PowerState/stopped', 'PowerState/deallocated')
""" + _PROJECTION + ", powerState",
     "Stopped/deallocated VM review signal. Storage can remain billable; this does not establish idle duration or savings."),
    ("EMPTY_APP_SERVICE_PLAN", "MEDIUM", """Resources
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
    ("IDLE_APP_GATEWAY", "HIGH", """Resources
| where type =~ 'microsoft.network/applicationgateways'
| extend pools=properties.backendAddressPools
| where properties.operationalState =~ 'Stopped' or coalesce(array_length(pools), 0) == 0
""" + _PROJECTION + ", skuName=tostring(sku.name)",
     "Application Gateway is stopped or has no configured backend pools. Validate routing intent and billing; this signal does not establish idle duration or savings."),
)


def execute_pages(client: Any, query: str, subscriptions: list[str]) -> list[dict]:
    """Fetch every ARG page or fail. Never return a silently incomplete inventory.

    SDK contract: QueryRequestOptions(top=1000, skip_token=..., result_format='objectArray').
    See https://learn.microsoft.com/python/api/azure-mgmt-resourcegraph/azure.mgmt.resourcegraph.models.queryrequestoptions
    """
    from azure.mgmt.resourcegraph.models import QueryRequest, QueryRequestOptions

    if not subscriptions:
        raise ScanError("At least one authorized Azure subscription is required.")
    allowed = {str(UUID(s)).lower() for s in subscriptions}
    token = None
    seen_tokens: set[str] = set()
    by_id: dict[str, dict] = {}
    for _ in range(1000):
        request = QueryRequest(
            subscriptions=sorted(allowed), query=query,
            options=QueryRequestOptions(top=1000, skip_token=token,
                                        result_format="objectArray", allow_partial_scopes=False),
        )
        response = client.resources(request, connection_timeout=10, read_timeout=45)
        rows = response.data
        if not isinstance(rows, list):
            raise ScanError("Azure returned an unexpected inventory format.")
        for row in rows:
            if not isinstance(row, dict):
                raise ScanError("Azure returned a malformed inventory row.")
            subscription = str(row.get("subscriptionId", "")).lower()
            resource_id = row.get("id")
            if subscription not in allowed or not isinstance(resource_id, str):
                raise ScanError("Azure returned a resource outside the authorized scope.")
            if not resource_id.lower().startswith(f"/subscriptions/{subscription}/"):
                raise ScanError("Azure returned an inconsistent resource identifier.")
            for field in ("name", "type", "resourceGroup"):
                if not isinstance(row.get(field), str) or not row[field]:
                    raise ScanError("Azure returned a malformed resource identity.")
            by_id[resource_id.lower()] = row
            if len(by_id) > 100_000:
                raise ScanError("Inventory exceeds this MVP scan limit; split the workspace Azure subscriptions.")
        next_token = getattr(response, "skip_token", None)
        truncated = str(getattr(response, "result_truncated", "false")).lower()
        is_truncated = truncated in ("true", "resulttruncated.true")
        if not next_token:
            if is_truncated:
                raise ScanError("Azure truncated the result without a continuation token.")
            return list(by_id.values())
        if not isinstance(next_token, str) or next_token in seen_tokens:
            raise ScanError("Azure returned an invalid or repeated continuation token.")
        seen_tokens.add(next_token)
        token = next_token
    raise ScanError("Azure inventory exceeded the pagination limit.")


INVENTORY_QUERY = ("Resources | where isnotempty(id)" + _PROJECTION +
    ', diskState=tostring(properties.diskState), powerState=tostring(properties.extended.instanceView.powerState.code)'
    ', hostedAppCount=toint(properties.numberOfSites), skuTier=tostring(sku.tier), createdAt=tostring(properties.timeCreated)'
    ', resourceLocation=location, managedBy=tostring(managedBy), osDiskId=tostring(properties.storageProfile.osDisk.managedDisk.id)'
    ', dataDisks=properties.storageProfile.dataDisks, networkInterfaces=properties.networkProfile.networkInterfaces'
    ', nicIpConfigurations=properties.ipConfigurations, serverFarmId=tostring(properties.serverFarmId)'
    ', sizeGB=toint(properties.diskSizeGB), provisionedIops=toint(properties.diskIOPSReadWrite)'
    ', encryptionType=tostring(properties.encryption.type), minimumTlsVersion=tostring(properties.minimumTlsVersion)'
    ', backupRetentionDays=toint(properties.backupRetentionDays), highAvailability=properties.highAvailability.mode'
    ', disableLocalAuth=properties.disableLocalAuth, allowBlobPublicAccess=properties.allowBlobPublicAccess'
    ', zoneRedundant=properties.zoneRedundant, zones=zones')


def scan_inventory_observations(client: Any, subscriptions: list[str]) -> list[dict]:
    """All scoped resources observed in Azure Resource Graph (not limited to finding rules)."""
    rows = []
    observed_at = datetime.now(timezone.utc).isoformat()
    for row in execute_pages(client, INVENTORY_QUERY, subscriptions):
        evidence = {'source': 'Azure Resource Graph', 'tags': row.get('tags') or {}}
        for source, target in (('diskState', 'disk_state'), ('powerState', 'power_state'), ('skuTier', 'sku_tier'), ('createdAt', 'created_at')):
            if isinstance(row.get(source), str) and row[source]:
                evidence[target] = row[source]
        if type(row.get('hostedAppCount')) is int and row['hostedAppCount'] >= 0:
            evidence['hosted_app_count'] = row['hostedAppCount']
        for source,target in (('sizeGB','size_gb'),('provisionedIops','provisioned_iops'),('backupRetentionDays','backup_retention_days')):
            if type(row.get(source)) is int and row[source]>=0:evidence[target]=row[source]
        if row.get('encryptionType') in ('EncryptionAtRestWithPlatformKey','EncryptionAtRestWithCustomerKey','EncryptionAtRestWithPlatformAndCustomerKeys'):evidence['encrypted']=True
        for source,target in (('zoneRedundant','multi_az'),('disableLocalAuth','managed_secrets'),('allowBlobPublicAccess','publicly_accessible')):
            if type(row.get(source)) is bool:evidence[target]=row[source]
        if row.get('minimumTlsVersion') in ('1.2','1.3','TLS1_2','TLS1_3'):evidence['tls_required']=True
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
            'unsupported_rule_ids': ['AZURE_DISK_PROVISIONED_PERFORMANCE', 'AZURE_PUBLIC_IP_ASSOCIATED_IDLE',
                                     'AZURE_VM_RIGHTSIZING_UTILIZATION', 'AZURE_ASP_UNDERUTILIZED_SKU'],
        })
    return rows


def _findings(client: Any, subscriptions: list[str], enabled_rule_ids: set[str] | None = None) -> list[dict]:
    findings = []
    rules = RULES if not enabled_rule_ids else tuple(r for r in RULES if r[0] in enabled_rule_ids)
    for rule_id, severity, query, explanation in rules:
        for row in execute_pages(client, query, subscriptions):
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
                "resource_name": row["name"], "resource_type": row["type"],
                "resource_group": row["resourceGroup"],
                "subscription_id": row["subscriptionId"], "resource_id": row["id"],
                "estimated_monthly_waste_usd": None,
                "evidence": {"source": "Azure Resource Graph", "tags": row.get("tags") or {}, **controls,
                             **({"size_gb": row["sizeGB"]} if type(row.get("sizeGB")) is int else {})},
                "details": explanation + (" Evidence: " + "; ".join(evidence) if evidence else ""),
            })
    return findings


def scan_live(tenant: dict, *, enabled_rule_ids: set[str] | None = None) -> tuple[list[dict], list[dict]]:
    """Scan only authorized subscriptions with a keyless credential for the customer tenant.

    Reader RBAC on each subscription is granted by the customer during onboarding.
    A mid-scan error raises; no partial findings escape or get persisted as complete.
    """
    from azure.mgmt.resourcegraph import ResourceGraphClient
    from app.cloud_identity import CredentialError, azure_credential
    subscriptions = [str(UUID(s)) for s in tenant["subscription_ids"]]
    if not subscriptions:
        raise ScanError("No authorized Azure subscriptions are configured.")
    try:
        credential = azure_credential(tenant)
    except CredentialError as exc:
        raise ScanError(str(exc) or "The customer Azure credential is unavailable.") from None
    with credential:
        with ResourceGraphClient(credential, retry_total=3, retry_backoff_factor=1,
                                 connection_timeout=10, read_timeout=45) as client:
            inventory = scan_inventory_observations(client, subscriptions)
            from app.collectors.live_common import enabled
            if enabled():
                from app.collectors.azure_live import enrich
                from app.cloud_http import JSONReader
                reader=JSONReader(headers_factory=lambda _: {'Authorization':'Bearer '+credential.get_token('https://management.azure.com/.default').token})
                try:inventory=enrich(reader,inventory)
                finally:reader.close()
            return _findings(client, subscriptions, enabled_rule_ids), inventory
