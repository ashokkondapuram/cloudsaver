"""Per-resource rule detail, evaluation scoping, and finding/evaluation conflicts."""
from app.rule_detail import (
    build_resource_rule_detail,
    evaluations_for_resource,
    rule_conflicts,
)


def test_evaluations_for_resource_azure_case_insensitive():
    rid = "/subscriptions/S/resourceGroups/rg/providers/Microsoft.Compute/disks/d1"
    scan_evaluations = [
        dict(
            cloud_provider="azure",
            resource_id=rid.lower(),
            rule_id="AZURE_DISK_UNATTACHED_RETENTION",
            outcome="condition_detected",
        ),
        dict(
            cloud_provider="azure",
            resource_id="/subscriptions/S/resourceGroups/rg/providers/Microsoft.Compute/disks/other",
            rule_id="AZURE_DISK_UNATTACHED_RETENTION",
            outcome="condition_detected",
        ),
    ]
    rows = evaluations_for_resource(scan_evaluations, provider="azure", resource_id=rid)
    assert len(rows) == 1
    assert rows[0]["rule_id"] == "AZURE_DISK_UNATTACHED_RETENTION"


def test_rule_conflicts_source_reconciliation():
    conflicts = rule_conflicts(
        reconciliation_status="source_conflict",
        findings=[],
        evaluations=[],
    )
    assert any(c["kind"] == "source_reconciliation" and c["severity"] == "block" for c in conflicts)


def test_rule_conflicts_outcome_mismatch():
    conflicts = rule_conflicts(
        reconciliation_status=None,
        findings=[dict(rule_id="ORPHANED_DISK")],
        evaluations=[
            dict(rule_id="ORPHANED_DISK", outcome="condition_not_detected"),
        ],
    )
    assert any(c["kind"] == "outcome_mismatch" for c in conflicts)


def test_rule_conflicts_evaluation_without_finding():
    conflicts = rule_conflicts(
        reconciliation_status=None,
        findings=[],
        evaluations=[
            dict(rule_id="AWS_UNATTACHED_EBS", outcome="condition_detected"),
        ],
    )
    assert any(c["kind"] == "evaluation_without_finding" for c in conflicts)


def test_build_resource_rule_detail_primary_and_conflicts():
    rid = "/subscriptions/s/resourceGroups/r/providers/Microsoft.Compute/disks/d1"
    assessment = dict(provider="azure", resource_id=rid, resource_type="Microsoft.Compute/disks")
    evaluations = [
        dict(
            cloud_provider="azure",
            resource_id=rid,
            rule_id="AZURE_DISK_PROVISIONED_PERFORMANCE",
            outcome="condition_detected",
        ),
        dict(
            cloud_provider="azure",
            resource_id=rid,
            rule_id="AZURE_DISK_UNATTACHED_RETENTION",
            outcome="condition_detected",
        ),
    ]
    findings = [dict(rule_id="AZURE_DISK_UNATTACHED_RETENTION", opportunity_group_id="g1")]
    detail = build_resource_rule_detail(
        assessment,
        findings,
        evaluations,
        dict(reconciliation_status="matched", evidence={}),
    )
    assert detail["rule_matches"]["primary_match"]["rule_id"] == "AZURE_DISK_UNATTACHED_RETENTION"
    assert len(detail["rule_matches"]["alternate_matches"]) == 1
    assert not any(c["kind"] == "outcome_mismatch" for c in detail["rule_conflicts"])
