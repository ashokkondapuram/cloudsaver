"""Tests for legacy → catalog rule_id normalization."""
from app.rule_id_canonical import (
    canonical_rule_id,
    normalize_enabled_rule_ids,
    normalize_scan,
    rule_enabled,
)


def test_legacy_scan_finding_maps_to_catalog():
    assert canonical_rule_id("ORPHANED_DISK") == "AZURE_DISK_UNATTACHED_RETENTION"
    assert canonical_rule_id("K8S_CPU_OVERSIZED") == "K8S_CONTAINER_CPU_OVERREQUEST"


def test_normalize_scan_deduplicates_alias_findings():
    scan = dict(
        findings=[
            dict(resource_id="/subscriptions/s/rg/d/providers/Microsoft.Compute/disks/d1", rule_id="ORPHANED_DISK"),
            dict(resource_id="/subscriptions/s/rg/d/providers/Microsoft.Compute/disks/d1", rule_id="ORPHANED_DISKS"),
        ]
    )
    normalized = normalize_scan(scan)
    assert len(normalized["findings"]) == 1
    assert normalized["findings"][0]["rule_id"] == "AZURE_DISK_UNATTACHED_RETENTION"


def test_enabled_policy_accepts_legacy_and_catalog():
    enabled = normalize_enabled_rule_ids({"ORPHANED_DISK", "AZURE_VM_STOPPED_RESIDUAL_COST"})
    assert "AZURE_DISK_UNATTACHED_RETENTION" in enabled
    assert rule_enabled("ORPHANED_DISK", enabled)
    assert rule_enabled("AZURE_DISK_UNATTACHED_RETENTION", enabled)
