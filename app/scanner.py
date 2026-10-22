"""Read-only Azure inventory findings. A finding is a review signal, not savings."""
from __future__ import annotations

import os
from typing import Any
from uuid import UUID


class ScanError(RuntimeError):
    """The scan could not produce a complete, authorized result."""


_PROJECTION = "| project id, name, type, resourceGroup, subscriptionId"
RULES = (
    ("ORPHANED_DISK", "HIGH", """Resources
| where type =~ 'microsoft.compute/disks'
| where tostring(properties.diskState) == 'Unattached'
""" + _PROJECTION + ", sizeGB=toint(properties.diskSizeGB), skuName=tostring(sku.name)",
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
""" + _PROJECTION + ", skuName=tostring(sku.name)",
     "App Service plan currently reports no hosted sites. Confirm intended capacity and dependencies before changes."),
)


def execute_pages(client: Any, query: str, subscriptions: list[str]) -> list[dict]:
    """Fetch every ARG page or fail. Never return a silently incomplete inventory.

    SDK contract: QueryRequestOptions(top=1000, skip_token=..., result_format='objectArray').
    See https://learn.microsoft.com/python/api/azure-mgmt-resourcegraph/azure.mgmt.resourcegraph.models.queryrequestoptions
    """
    from azure.mgmt.resourcegraph.models import QueryRequest, QueryRequestOptions

    if not subscriptions:
        raise ScanError("At least one authorized subscription is required.")
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
                raise ScanError("Inventory exceeds this MVP scan limit; split the workspace subscriptions.")
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


def _findings(client: Any, subscriptions: list[str]) -> list[dict]:
    findings = []
    for rule_id, severity, query, explanation in RULES:
        for row in execute_pages(client, query, subscriptions):
            evidence = []
            for field in ("sizeGB", "skuName", "powerState"):
                if row.get(field) is not None:
                    evidence.append(f"{field}: {str(row[field])[:128]}")
            findings.append({
                "rule_id": rule_id, "severity": severity,
                "resource_name": row["name"], "resource_type": row["type"],
                "resource_group": row["resourceGroup"],
                "subscription_id": row["subscriptionId"], "resource_id": row["id"],
                "estimated_monthly_waste_usd": None,
                "details": explanation + (" Evidence: " + "; ".join(evidence) if evidence else ""),
            })
    return findings


def scan_live(tenant: dict) -> list[dict]:
    """Scan only operator-authorized subscriptions using the explicit customer tenant.

    Service-principal RBAC scope must be verified by the operator on onboarding.
    A mid-scan error raises; no partial findings escape or get persisted as complete.
    """
    from azure.identity import ClientSecretCredential
    from azure.mgmt.resourcegraph import ResourceGraphClient

    client_id = os.getenv("AZURE_CLIENT_ID", "")
    client_secret = os.getenv("AZURE_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        raise ScanError("Azure credentials are not configured.")
    tenant_id = str(UUID(tenant["tenant_id"]))
    subscriptions = [str(UUID(s)) for s in tenant["subscription_ids"]]
    if not subscriptions:
        raise ScanError("No authorized subscriptions configured.")
    with ClientSecretCredential(tenant_id=tenant_id, client_id=client_id,
                                client_secret=client_secret, retry_total=3,
                                connection_timeout=10, read_timeout=45) as credential:
        with ResourceGraphClient(credential, retry_total=3, retry_backoff_factor=1,
                                 connection_timeout=10, read_timeout=45) as client:
            return _findings(client, subscriptions)


def demo_findings() -> list[dict]:
    """Illustrative local fixtures; dollar values are invented for UI demonstration."""
    subscription = "00000000-0000-0000-0000-000000000001"
    fixtures = [
        (0, "archive-export-disk", 76.80), (0, "old-build-cache", 38.40),
        (0, "migration-snapshot-disk", 153.60), (1, "unused-edge-ip", 3.65),
        (1, "legacy-api-ip", 3.65), (2, "retired-build-agent", 12.80),
        (3, "staging-app-plan", 73.00), (3, "legacy-web-plan", 146.00),
    ]
    results = []
    types = ["microsoft.compute/disks", "microsoft.network/publicipaddresses",
             "microsoft.compute/virtualmachines", "microsoft.web/serverfarms"]
    for index, name, amount in fixtures:
        rule_id, severity, _, description = RULES[index]
        resource_type = types[index]
        results.append({"rule_id": rule_id, "severity": severity,
                        "resource_name": name, "resource_type": resource_type,
                        "resource_group": "demo-platform", "subscription_id": subscription,
                        "resource_id": f"/subscriptions/{subscription}/resourceGroups/demo-platform/providers/{resource_type}/{name}",
                        "estimated_monthly_waste_usd": amount,
                        "details": "DEMO: illustrative cost, not Azure billing data. " + description})
    return results
