from datetime import datetime, timedelta, timezone

import pytest

from app.finops_resize_metrics import build_resize_metrics
from app.analysis_rules import evaluate_inventory

NOW = datetime(2026, 11, 1, 18, tzinfo=timezone.utc)
SUB = "33333333-3333-4333-8333-333333333333"


def metric(value=4.0):
    start = NOW - timedelta(days=30)
    return dict(
        window_start=start.isoformat(),
        window_end=NOW.isoformat(),
        points=[
            dict(at=(start + timedelta(seconds=300 * i)).isoformat(), value=value)
            for i in range(1, 8641)
        ],
    )


def vm_resource(**extra):
    evidence = dict(
        power_state="PowerState/running",
        vm_size="Standard_D8s_v5",
        created_at=(NOW - timedelta(days=45)).isoformat(),
        metrics=dict(
            cpu_percent=metric(4),
            memory_percent=metric(12),
            disk_iops=metric(100),
            network_bytes=metric(1_000_000),
        ),
        slo_burn_rate=0.3,
        cpu_latency_correlation_r=0.2,
        slo_observed_at=NOW.isoformat(),
        burst_credits_depleted=False,
        target_compatible=True,
        **extra.pop("evidence", {}),
    )
    evidence.update(extra.get("evidence_patch", {}))
    return dict(
        cloud_provider="azure",
        resource_type="Microsoft.Compute/virtualMachines",
        resource_id=f"/subscriptions/{SUB}/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/app",
        resource_name="app",
        subscription_id=SUB,
        evidence=evidence,
        observed_at=NOW.isoformat(),
        **extra,
    )


def test_resize_metrics_reports_telemetry_contract_fields():
    resource = vm_resource()
    evaluations = evaluate_inventory([resource], observed_at=NOW.isoformat(), now=NOW)
    scan = dict(
        scan_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        status="completed",
        timestamp=NOW.isoformat(),
        inventory=[resource],
        rule_evaluations=evaluations,
        findings=[],
    )
    payload = build_resize_metrics(scan, now=NOW)
    assert payload["eligible_count"] >= 0
    assert len(payload["items"]) == 1
    row = payload["items"][0]
    assert row["finops_action"] == "azure.vm.rightsize"
    assert row["rule_name"] == "Evidence-based VM rightsizing review"
    cpu = next(m for m in row["metrics"] if m["metric"] == "cpu_percent")
    assert cpu["sufficient"] is True
    assert cpu["coverage_ratio"] >= 0.95
    assert cpu["contract"]["window_days"] == 30
    assert row["slo"]["status"] == "pass"


def test_resize_metrics_marks_ineligible_without_condition_detected():
    resource = vm_resource()
    evaluations = evaluate_inventory([resource], observed_at=NOW.isoformat(), now=NOW)
    for ev in evaluations:
        if ev["rule_id"] == "AZURE_VM_RIGHTSIZING_UTILIZATION":
            ev["outcome"] = "insufficient_evidence"
    scan = dict(
        scan_id="scan-1",
        status="completed",
        timestamp=NOW.isoformat(),
        inventory=[resource],
        rule_evaluations=evaluations,
        findings=[],
    )
    row = build_resize_metrics(scan, now=NOW)["items"][0]
    assert row["resize_eligible"] is False
    assert "rule_outcome_insufficient_evidence" in row["eligibility_reasons"]


def test_eligible_only_filter():
    resource = vm_resource()
    evaluations = evaluate_inventory([resource], observed_at=NOW.isoformat(), now=NOW)
    scan = dict(
        scan_id="scan-2",
        status="completed",
        timestamp=NOW.isoformat(),
        inventory=[resource],
        rule_evaluations=evaluations,
        findings=[],
    )
    all_rows = build_resize_metrics(scan, now=NOW)
    filtered = build_resize_metrics(scan, now=NOW, eligible_only=True)
    assert filtered["total"] <= all_rows["total"]
