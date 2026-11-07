"""Canonical catalog rule identifiers; legacy scan and policy ids normalize here."""
from __future__ import annotations

LEGACY_TO_CATALOG: dict[str, str] = {
    "ORPHANED_DISK": "AZURE_DISK_UNATTACHED_RETENTION",
    "ORPHANED_DISKS": "AZURE_DISK_UNATTACHED_RETENTION",
    "UNASSOCIATED_PUBLIC_IP": "AZURE_PUBLIC_IP_UNASSOCIATED",
    "UNASSOCIATED_PUBLIC_IPS": "AZURE_PUBLIC_IP_UNASSOCIATED",
    "STOPPED_VM": "AZURE_VM_STOPPED_RESIDUAL_COST",
    "STOPPED_VMS": "AZURE_VM_STOPPED_RESIDUAL_COST",
    "EMPTY_APP_SERVICE_PLAN": "AZURE_ASP_EMPTY_PAID_PLAN",
    "EMPTY_APP_SERVICE": "AZURE_ASP_EMPTY_PAID_PLAN",
    "UNDERUTILIZED_VM": "AZURE_VM_RIGHTSIZING_UTILIZATION",
    "UNDERUTILIZED_APP_SERVICE_PLAN": "AZURE_ASP_UNDERUTILIZED_SKU",
    "IDLE_APP_GATEWAY": "AZURE_APPGW_EMPTY_OR_HIGH_AUTOSCALE_FLOOR",
    "K8S_CPU_OVERSIZED": "K8S_CONTAINER_CPU_OVERREQUEST",
    "K8S_MEMORY_OVERSIZED": "K8S_CONTAINER_MEMORY_OVERREQUEST",
}

# Azure ARG scan signals with bash/terraform review but no FAMILIES catalog twin.
REMEDIATION_SCAN_RULE_IDS = frozenset({"ORPHANED_NIC", "ORPHANED_NSG"})

LEGACY_RULE_IDS = frozenset(LEGACY_TO_CATALOG) | REMEDIATION_SCAN_RULE_IDS


def canonical_rule_id(rule_id: str | None) -> str:
    if not rule_id or not isinstance(rule_id, str):
        return rule_id or ""
    return LEGACY_TO_CATALOG.get(rule_id, rule_id)


def normalize_enabled_rule_ids(rule_ids: set[str]) -> set[str]:
    return {canonical_rule_id(value) for value in rule_ids} | {
        value for value in rule_ids if value in REMEDIATION_SCAN_RULE_IDS
    }


def rule_enabled(rule_id: str, enabled: set[str]) -> bool:
    canonical = canonical_rule_id(rule_id)
    return canonical in enabled or rule_id in enabled


def normalize_finding(finding: dict) -> dict:
    rule_id = finding.get("rule_id")
    if not isinstance(rule_id, str):
        return finding
    return dict(finding, rule_id=canonical_rule_id(rule_id))


def normalize_scan(scan: dict) -> dict:
    if not isinstance(scan, dict):
        return scan
    result = dict(scan)
    seen: set[tuple] = set()
    findings = []
    for row in scan.get("findings") or []:
        if not isinstance(row, dict):
            continue
        finding = normalize_finding(row)
        key = (
            finding.get("cloud_provider", "azure"),
            finding.get("resource_id"),
            finding.get("rule_id"),
        )
        if key in seen:
            continue
        seen.add(key)
        findings.append(finding)
    result["findings"] = findings
    evaluations = []
    for row in scan.get("rule_evaluations") or []:
        if isinstance(row, dict) and isinstance(row.get("rule_id"), str):
            evaluations.append(dict(row, rule_id=canonical_rule_id(row["rule_id"])))
        else:
            evaluations.append(row)
    if "rule_evaluations" in scan:
        result["rule_evaluations"] = evaluations
    manifest = scan.get("rule_manifest")
    if isinstance(manifest, dict) and isinstance(manifest.get("enabled_rule_ids"), list):
        enabled = normalize_enabled_rule_ids({value for value in manifest["enabled_rule_ids"] if isinstance(value, str)})
        result["rule_manifest"] = dict(manifest, enabled_rule_ids=sorted(enabled))
    return result
