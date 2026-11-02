"""Resize eligibility metrics from saved scan evidence (telemetry contracts + rule outcomes)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.agent_workflow_routing import FINOPS_RULE_TO_ACTION
from app.finops_resize_playbooks import PLAYBOOKS, candidate_size_from_resource, resolve_playbook
from app.multicloud_rules import slo_gate
from app.resource_catalog import display_name
from app.telemetry_contract import TimeSeriesEvidenceContract, evaluate_series, moment

# Playbook → primary rightsizing rule used for evaluation linkage.
PLAYBOOK_RULE_ID: dict[str, str] = {
    **{action: rule_id for rule_id, action in FINOPS_RULE_TO_ACTION.items()},
    "azure.disk.rightsize": "AZURE_DISK_PROVISIONED_PERFORMANCE",
}

# Metrics required to support a resize review (aggregation per series).
PLAYBOOK_METRIC_SPECS: dict[str, tuple[tuple[str, str], ...]] = {
    "azure.vm.rightsize": (
        ("cpu_percent", "P95"),
        ("memory_percent", "P95"),
        ("disk_iops", "MAX"),
        ("network_bytes", "MAX"),
    ),
    "azure.appservice.rightsize": (("cpu_percent", "P95"), ("memory_percent", "P95")),
    "azure.disk.rightsize": (("iops", "P99"), ("throughput", "P99")),
    "aws.ec2.rightsize": (("cpu_percent", "P95"), ("memory_percent", "P95")),
    "aws.rds.rightsize": (("cpu_percent", "P95"), ("memory_percent", "P95")),
    "gcp.compute.rightsize": (("cpu_percent", "P95"), ("memory_percent", "P95")),
}

SLO_PLAYBOOKS = frozenset({"azure.vm.rightsize", "aws.ec2.rightsize", "gcp.compute.rightsize", "aws.rds.rightsize"})


def _metric_report(evidence: dict, name: str, aggregation: str, *, now: datetime, created_at) -> dict[str, Any]:
    raw = (evidence.get("metrics") or {}).get(name)
    contract = TimeSeriesEvidenceContract(name, aggregation)
    if not isinstance(raw, dict):
        return dict(
            metric=name,
            aggregation=aggregation,
            sufficient=False,
            gap_reason="metric_unavailable",
            coverage_ratio=None,
            observed_value=None,
            valid_samples=0,
            expected_samples=contract.window_days * 1440 // contract.interval_minutes,
            window_start=None,
            window_end=None,
        )
    result = evaluate_series(raw, contract, now=now, resource_created_at=created_at, require_resource_age=True)
    return dict(
        metric=name,
        aggregation=aggregation,
        sufficient=result.is_sufficient,
        gap_reason=result.gap_reason,
        coverage_ratio=round(result.coverage_ratio, 4) if result.coverage_ratio is not None else None,
        observed_value=result.observed_value,
        valid_samples=result.valid_samples,
        expected_samples=result.expected_samples,
        max_gap_minutes=result.max_observed_gap_minutes,
        window_start=result.window_start.isoformat() if result.window_start else raw.get("window_start"),
        window_end=result.window_end.isoformat() if result.window_end else raw.get("window_end"),
        contract=dict(
            window_days=contract.window_days,
            interval_minutes=contract.interval_minutes,
            min_coverage_ratio=contract.min_coverage_ratio,
            max_gap_minutes=contract.max_gap_minutes,
            min_resource_age_days=contract.min_resource_age_days,
        ),
    )


def _slo_report(evidence: dict, *, now: datetime) -> dict[str, Any]:
    gate = slo_gate(evidence, now)
    status = "pass" if gate is True else "fail" if gate is False else "unknown"
    return dict(
        status=status,
        burn_rate=evidence.get("slo_burn_rate"),
        cpu_latency_correlation_r=evidence.get("cpu_latency_correlation_r"),
        slo_observed_at=evidence.get("slo_observed_at"),
        oom_kill_count_30d=evidence.get("oom_kill_count_30d"),
        cfs_throttling_p95_pct=evidence.get("cfs_throttling_p95_pct"),
        target_compatible=evidence.get("target_compatible"),
        burst_credits_depleted=evidence.get("burst_credits_depleted"),
    )


def _evaluation_for(resource_id: str, rule_id: str, evaluations: list[dict]) -> dict | None:
    matches = [
        row
        for row in evaluations
        if row.get("resource_id") == resource_id and row.get("rule_id") == rule_id
    ]
    return matches[0] if len(matches) == 1 else (matches[0] if matches else None)


def build_resize_metrics(
    scan: dict,
    *,
    now: datetime | None = None,
    eligible_only: bool = False,
    cloud_provider: str | None = None,
) -> dict[str, Any]:
    """Build per-resource resize metric rows from a completed scan snapshot."""
    now = now or datetime.now(timezone.utc)
    observed_at = scan.get("timestamp")
    evaluations = list(scan.get("rule_evaluations") or [])
    inventory = list(scan.get("inventory") or [])
    items: list[dict[str, Any]] = []

    for resource in inventory:
        provider = resource.get("cloud_provider", "azure")
        if cloud_provider and provider != cloud_provider:
            continue
        try:
            book = resolve_playbook(cloud_provider=provider, resource_type=resource.get("resource_type", ""))
        except ValueError:
            continue
        action = book["finops_action"]
        rule_id = PLAYBOOK_RULE_ID.get(action)
        if not rule_id:
            continue
        evidence = resource.get("evidence") if isinstance(resource.get("evidence"), dict) else {}
        created_at = evidence.get("created_at")
        metrics = [
            _metric_report(evidence, name, agg, now=now, created_at=created_at)
            for name, agg in PLAYBOOK_METRIC_SPECS.get(action, ())
        ]
        evaluation = _evaluation_for(resource["resource_id"], rule_id, evaluations)
        slo = _slo_report(evidence, now=now) if action in SLO_PLAYBOOKS else None
        size_field = book["size_field"]
        current_size = evidence.get(size_field) or resource.get(size_field)
        recommended = candidate_size_from_resource(resource, book)
        required_metrics = [m for m in metrics if m["metric"] in {n for n, _ in PLAYBOOK_METRIC_SPECS.get(action, ())}]
        metrics_ok = bool(required_metrics) and all(m["sufficient"] for m in required_metrics)
        slo_ok = slo is None or slo["status"] == "pass"
        eval_ok = evaluation is not None and evaluation.get("outcome") == "condition_detected"
        protected = bool(evaluation and evaluation.get("destructive_actions_blocked"))
        safety = list(evaluation.get("safety_blocks") or []) if evaluation else []
        eligible = eval_ok and metrics_ok and slo_ok and not protected and not safety
        reasons: list[str] = []
        if not evaluation:
            reasons.append("missing_rule_evaluation")
        elif evaluation.get("outcome") != "condition_detected":
            reasons.append(f"rule_outcome_{evaluation.get('outcome', 'unknown')}")
        if not metrics_ok:
            reasons.append("insufficient_telemetry")
        if slo and slo["status"] != "pass":
            reasons.append(f"slo_gate_{slo['status']}")
        if protected:
            reasons.append("destructive_actions_blocked")
        if safety:
            reasons.append("safety_blocks_present")
        if current_size in (None, ""):
            reasons.append("current_size_unknown")

        row = dict(
            resource_id=resource["resource_id"],
            resource_name=resource.get("resource_name"),
            resource_type=resource.get("resource_type"),
            cloud_provider=provider,
            scope_id=resource.get("scope_id") or resource.get("subscription_id"),
            finops_action=action,
            rule_id=rule_id,
            rule_name=display_name(rule_id),
            current_size=dict(field=size_field, value=current_size),
            recommended_size=recommended,
            resize_eligible=eligible,
            eligibility_reasons=reasons,
            evaluation=(
                None
                if not evaluation
                else dict(
                    outcome=evaluation.get("outcome"),
                    reason=evaluation.get("reason"),
                    rule_version=evaluation.get("rule_version"),
                    safety_blocks=safety,
                    destructive_actions_blocked=protected,
                )
            ),
            metrics=metrics,
            slo=slo,
            observation=dict(observed_at=observed_at, scan_id=scan.get("scan_id")),
        )
        if eligible_only and not eligible:
            continue
        items.append(row)

    return dict(
        schema_version=1,
        scan_id=scan.get("scan_id"),
        observed_at=observed_at,
        generated_at=now.isoformat(),
        contract_note=(
            "Metrics use 30-day five-minute series with ≥95% coverage, no gap over 60 minutes, "
            "and verified resource age unless noted. Missing data never implies safe downsizing."
        ),
        total=len(items),
        eligible_count=sum(1 for row in items if row["resize_eligible"]),
        items=items,
    )
