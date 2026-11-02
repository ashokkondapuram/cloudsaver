#!/usr/bin/env python3
"""Generate docs/ANALYSIS_RULES_MASTER.md — evidence, pillars, and action paths for all catalog rules."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.agent_workflow_routing import (  # noqa: E402
    BASH_REMEDIATION_RULES,
    FINOPS_RULE_TO_ACTION,
    KUBERNETES_PATCH_PREVIEW_RULES,
    TERRAFORM_IMPORT_RULES,
    route_for_rule,
)
from app.resource_catalog import FAMILIES, RULE_DISPLAY_NAMES, definitions  # noqa: E402

# What each rule needs to reach condition_detected (operator-facing, derived from engine contracts).
EVIDENCE_GUIDE: dict[str, str] = {
    "AZURE_DISK_UNATTACHED_RETENTION": "Continuous unattached disk state history for minimum_days; fresh observation (<24h).",
    "AZURE_DISK_PROVISIONED_PERFORMANCE": "Attached disk: IOPS/throughput series, target disk headroom, throttling flags; snapshot path for unattached.",
    "AZURE_PUBLIC_IP_UNASSOCIATED": "Association verified false + continuous Unassociated state for minimum_days.",
    "AZURE_PUBLIC_IP_ASSOCIATED_IDLE": "Associated IP with ingress/egress byte series max ≤ maximum_bytes.",
    "AZURE_VM_STOPPED_RESIDUAL_COST": "Power stopped/deallocated with duration history where applicable.",
    "AZURE_VM_RIGHTSIZING_UTILIZATION": "30d CPU/memory P95 below thresholds; disk IOPS & network series; burst credits; SLO gate pass.",
    "AZURE_ASP_EMPTY_PAID_PLAN": "Paid SKU with zero apps/slots + Empty state history.",
    "AZURE_ASP_UNDERUTILIZED_SKU": "30d CPU/memory P95 below thresholds; SLO gate pass.",
    "AZURE_NAT_GATEWAY_SERVICE_ENDPOINT_BYPASS": "routing_verified, flow_log_coverage_ratio ≥95%, endpoint_eligible_bytes max > 0.",
    "AZURE_APPGW_EMPTY_OR_HIGH_AUTOSCALE_FLOOR": "dependencies_verified; request/healthy_target metrics; Empty state history (7d default).",
    "AZURE_SQL_PG_IDLE_AND_NONPROD_HA_REVIEW": "Low CPU/memory utilization + SLO gate + target_compatible.",
    "AZURE_COSMOSDB_MANUAL_RU_TO_AUTOSCALE": "Manual RU with low normalized RU consumption spread vs average.",
    "AZURE_REDIS_UNDERUTILIZED_TIER_REVIEW": "Memory/CPU P99 low, evictions low, target_compatible.",
    "AZURE_STORAGE_LIFECYCLE_AND_ORPHANED_VHD": "Lifecycle verified without multipart abort rules, or orphaned VHD signals.",
    "AZURE_AI_FOUNDRY_PTU_VS_PAYG_ARBITRAGE": "PTU utilization review via ai_capacity.ptu_review.",
    "AWS_UNATTACHED_EBS": "Unattached volume state + snapshot verification within 24h when required.",
    "AWS_EBS_GP2_TO_GP3_AND_IOPS_TUNING": "IOPS/throughput P99 vs target disk headroom; no throttling.",
    "AWS_EC2_STOPPED_EBS_RESIDUAL": "Stopped instance state history.",
    "AWS_EC2_GRAVITON_AND_SLO_RIGHTSIZING": "Low CPU/memory P95 + SLO gate + target_compatible.",
    "AWS_UNASSOCIATED_EIP": "Unassociated address state history (7d default).",
    "AWS_NAT_GW_ENDPOINT_BYPASS_AND_IDLE": "routing_verified, flow coverage ≥95%, endpoint_eligible_bytes max > 0.",
    "AWS_ELB_ORPHANED_AND_INGRESS_CONSOLIDATION": "Empty/orphan backend pattern (same as AppGW empty backend family).",
    "AWS_IDLE_RDS": "Stopped DB or non-prod with near-zero connections/CPU.",
    "AWS_RDS_AURORA_RIGHTSIZING_AND_GP3": "Low utilization + SLO gate + target_compatible.",
    "AWS_DYNAMODB_BILLING_MODE_AND_UNUSED_GSI": "Low read/write utilization, low throttles, spiky traffic verified.",
    "AWS_ELASTICACHE_GRAVITON_AND_VALKEY_UPGRADE": "Low memory/CPU + target_compatible.",
    "AWS_LAMBDA_ARM64_AND_PROVISIONED_CONCURRENCY": "Low provisioned concurrency utilization + SLO + target_compatible.",
    "AWS_S3_INTELLIGENT_TIERING_AND_MULTIPART_CLEANUP": "Multipart abort policy gaps or lifecycle gaps.",
    "AWS_BEDROCK_PT_AND_SAGEMAKER_IDLE_ENDPOINT": "Idle inference endpoints or low PT utilization.",
    "GCP_UNATTACHED_DISK": "Unattached disk + snapshot verification when required.",
    "GCP_DISK_HYPERDISK_IOPS_TUNING": "IOPS/throughput vs target headroom.",
    "GCP_GCE_STOPPED_DISK_TAX": "Stopped VM disk charge history.",
    "GCP_GCE_AXION_AND_CUSTOM_RIGHTSIZING": "Low CPU/memory + SLO gate + target_compatible.",
    "GCP_UNASSIGNED_ADDRESS": "Unassigned address retention history.",
    "GCP_CLOUD_NAT_PRIVATE_GOOGLE_ACCESS": "routing_verified, flow coverage ≥95%, endpoint_eligible_bytes max > 0.",
    "GCP_LB_EMPTY_BACKEND_FORWARDING_RULE": "Empty backend forwarding rule pattern.",
    "GCP_IDLE_CLOUD_SQL": "Aligned hours and zero max connections when present.",
    "GCP_CLOUDSQL_ALLOYDB_RIGHTSIZING_AND_HA": "Low utilization + SLO gate + target_compatible.",
    "GCP_BIGQUERY_SLOT_AUTOSCALE_AND_STORAGE": "Low slot utilization + target_compatible + no commitment conflict.",
    "GCP_CLOUDRUN_MIN_INSTANCE_AND_MEMORYSTORE": "Zero requests with min instances > 0 on non-prod signals.",
    "GCP_VERTEX_AI_IDLE_ENDPOINT_AND_REPLICA_FLOOR": "Idle endpoint invocations or low replica floor utilization.",
    "K8S_CONTAINER_CPU_OVERREQUEST": "Mature workload CPU P95 vs request headroom; patch recommendation when detected.",
    "K8S_CONTAINER_MEMORY_OVERREQUEST": "Memory working-set P95 vs request; OOM guards.",
    "K8S_CONTAINER_UNDERPROVISIONED_RISK": "Throttling/OOM/restart telemetry (reliability, not downsizing).",
    "K8S_HPA_PDB_CONFLICT_OR_IDLE_FLOOR": "HPA min replicas vs PDB constraints or idle floor.",
    "K8S_NODE_POOL_FRAGMENTATION_WASTE": "Node allocatable vs requested slack.",
    "K8S_ABANDONED_WORKLOAD_OR_NAMESPACE": "Zero-traffic workload/namespace history.",
    "K8S_PVC_UNMOUNTED_OR_LOW_OCCUPANCY": "PVC mount status and occupancy.",
    "K8S_STATEFULSET_SIZING_AND_VOLUME_TEMPLATE": "StatefulSet memory buffer and volume template sizing.",
    "K8S_DAEMONSET_CLUSTER_WIDE_OVERHEAD_TAX": "DaemonSet aggregate allocation overhead.",
    "K8S_ORPHANED_LOADBALANCER_SERVICE": "LoadBalancer service with empty endpoints.",
}


def action_channel(rule_id: str) -> str:
    try:
        return route_for_rule(rule_id).primary
    except KeyError:
        return "legacy_remediation"


def tier(rule_id: str, channel: str) -> str:
    if rule_id in FINOPS_RULE_TO_ACTION:
        return "A — FinOps resize (telemetry + SLO)"
    if rule_id in KUBERNETES_PATCH_PREVIEW_RULES:
        return "A — K8 patch preview"
    if channel == "engineering_review_plan":
        return "B — Engineering zero-downtime review"
    if channel in ("remediation_terraform_import", "remediation_bash_review"):
        return "B — Import / bash review artifact"
    if "RIGHTSIZING" in rule_id or "UNDERUTILIZED" in rule_id or "TUNING" in rule_id:
        return "B — Capacity / tier review (manual)"
    if "NAT" in rule_id or "BYPASS" in rule_id or "ENDPOINT" in rule_id or "APPGW" in rule_id or "ELB" in rule_id:
        return "C — Network / architecture"
    if rule_id.startswith("K8S_"):
        return "B — Kubernetes assessment"
    return "B — General manual assessment"


def main() -> None:
    defs = {row[0]: row for row in definitions()}
    lines = [
        "# Analysis rules master reference (all points considered)",
        "",
        "CloudSaver evaluates **51 published catalog rules** across Azure, AWS, GCP, and Kubernetes. ",
        "This document is the operator-facing view of **what each rule checks**, **what evidence must exist**, ",
        "**which pillar it primarily supports**, and **which action path applies** after `condition_detected`.",
        "",
        "Regenerate after catalog changes:",
        "",
        "```bash",
        "PYTHONPATH=. python3 scripts/generate_analysis_rules_master.py",
        "```",
        "",
        "Related: [RESOURCE_ANALYSIS_RULES.md](RESOURCE_ANALYSIS_RULES.md) (per resource type), ",
        "[FINOPS_ANALYSIS_VERIFICATION.md](FINOPS_ANALYSIS_VERIFICATION.md), ",
        "[FINOPS_RESIZE_METRICS.md](FINOPS_RESIZE_METRICS.md).",
        "",
        "---",
        "",
        "## How “best” analysis works here (all points considered)",
        "",
        "Every rule evaluation records exactly one of **eight outcomes** — never silent approval:",
        "",
        "`condition_detected` · `condition_not_detected` · `insufficient_evidence` · `not_applicable` · ",
        "`disabled_by_policy` · `excluded_by_exception` · `unsupported_by_collector` · `evaluation_failed`",
        "",
        "**Cross-cutting gates (always applied):**",
        "",
        "| Dimension | Behavior |",
        "| --- | --- |",
        "| **Five pillars** | Each finding merges into cost, reliability, performance, security, operations checks in assessment (`app/assessment.py`). |",
        "| **Protection** | Tags, locks, backup/replication, DR roles → `protected_reasons`; blocks destructive recommendations. |",
        "| **Observation freshness** | Evaluations require observation within **24 hours** unless rule says otherwise. |",
        "| **Telemetry contract** | 30-day / 5-minute series where used: **≥95% coverage**, no gap **>60 minutes**, no zero-fill. |",
        "| **SLO / rightsizing** | VM/EC2/GCE/RDS/App Service rules use `slo_gate` — error budget, latency correlation, OOM/throttle guards. |",
        "| **Financial overlap** | Same resource + multiple rules → opportunity groups; do not sum savings blindly. |",
        "| **Automatic execution** | **`automatic_execution: false`** on all rule rows; actions are explicit APIs with human gates. |",
        "| **Scoped workspaces** | Provider/scope keys filter scans, findings, and evaluations consistently. |",
        "",
        "```mermaid",
        "flowchart TD",
        "  scan[Completed scan inventory] --> eval[Rule evaluation per family]",
        "  eval --> outcome{Outcome}",
        "  outcome -->|insufficient_evidence| gather[Collect metrics history flow logs]",
        "  outcome -->|condition_detected| assess[Five-pillar assessment]",
        "  assess --> route[Workflow channel]",
        "  route --> finops[FinOps autopilot resize]",
        "  route --> eng[Engineering plan]",
        "  route --> k8[K8 patch preview]",
        "  route --> tf[Terraform/bash review]",
        "  route --> manual[Manual review decision]",
        "```",
        "",
        "---",
        "",
        "## Recommended production sets",
        "",
        "| Set | Enable when | Rules (count) |",
        "| --- | --- | --- |",
        "| **FinOps compute resize** | Live metrics + identity connectors with `compute.resize` | 5 autopilot-mapped rightsizing rules |",
        "| **Storage hygiene** | Snapshot/history collectors healthy | Unattached disk/EBS/GCP disk + performance/tuning rules |",
        "| **Network cost** | Flow logs + routing verification wired | NAT bypass, AppGW/LB empty backend, idle IP rules |",
        "| **Kubernetes efficiency** | Prometheus/AMP metrics on clusters | CPU/memory overrequest + PVC/service rules |",
        "| **Full catalog** | Mature observability on all families | All **51** rules (default identity catalog) |",
        "",
        "**Best single rule quality bar:** prefer rules that reached **`condition_detected`** with **sufficient telemetry** ",
        "and **no `safety_blocks`** over legacy ARG-only findings without `rule_evaluations`.",
        "",
        "---",
        "",
        "## Complete rule catalog",
        "",
        "| Tier | Provider | Category | rule_id | Display name | Pillar | Action channel | Evidence / condition summary | Parameters |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]

    for rule_id in sorted(defs):
        row = defs[rule_id]
        _rid, provider, category, _kind, name, pillar, bounds = row
        channel = action_channel(rule_id)
        t = tier(rule_id, channel)
        params = ", ".join(f"{k}={v[0]}" for k, v in bounds.items()) if bounds else "—"
        evidence = EVIDENCE_GUIDE.get(rule_id, "Complete fresh history, telemetry, and target proof per family contract.")
        lines.append(
            f"| {t} | {provider} | {category} | `{rule_id}` | {name} | {pillar} | `{channel}` | {evidence} | {params} |"
        )

    examples = [
        (
            "`AZURE_VM_RIGHTSIZING_UTILIZATION`",
            "Scan lists `Microsoft.Compute/virtualMachines` → metrics show 30d CPU P95 4%, memory P95 22%, disk/network series pass contract, `slo_gate` clear, no protection tags.",
            "`condition_detected` → assessment (cost + performance) → `finops_autopilot_resize` → `GET .../resize-metrics` eligible → `compute.resize` playbook `azure.vm.rightsize` with human approval.",
        ),
        (
            "`AWS_NAT_GW_ENDPOINT_BYPASS_AND_IDLE`",
            "NAT gateway inventory row → flow logs prove ≥95% coverage, `routing_verified`, eligible bytes to S3/Dynamo via VPC endpoints > 0.",
            "`condition_detected` → manual_assessment_only — architect endpoint routing; **no** autopilot resize or Terraform import.",
        ),
        (
            "`K8S_CONTAINER_CPU_OVERREQUEST`",
            "Deployment pod metrics: CPU P95 80m vs request 2000m over mature window; no throttling risk flags.",
            "`condition_detected` → `kubernetes_patch_preview` → YAML patch lowering requests; operator applies after dry-run.",
        ),
        (
            "`AZURE_DISK_UNATTACHED_RETENTION`",
            "Managed disk unattached 21 days, snapshot verified, no legal-hold tags.",
            "`condition_detected` → `engineering_review_plan` for detach/delete sequencing (execution disabled until readiness gates pass).",
        ),
        (
            "`AWS_UNATTACHED_EBS`",
            "Volume `available` 30 days, recent snapshot on file.",
            "`condition_detected` → `remediation_terraform_import` review package — operator confirms delete or attach; not auto-deleted.",
        ),
    ]
    lines.extend(["", "---", "", "## Worked examples (check → analyze → action)", ""])
    for rule, check, action in examples:
        lines.extend([f"### {rule}", "", f"1. **Check:** {check}", f"2. **Analyze & action:** {action}", ""])

    lines.extend(
        [
            "",
            "---",
            "",
            "## Legacy scan findings (Azure ARG — parallel to catalog)",
            "",
            "These **`rule_id`** values may appear in `scan.findings` without catalog `rule_evaluations`:",
            "",
            "| rule_id | Display name | Typical action |",
            "| --- | --- | --- |",
            "| `ORPHANED_DISK` | Unattached managed disk | Terraform import / bash review |",
            "| `UNASSOCIATED_PUBLIC_IP` | Unassociated public IP | Terraform import / bash review |",
            "| `ORPHANED_NIC` / `ORPHANED_NSG` | Orphan NIC/NSG | Bash + Terraform review |",
            "| `IDLE_APP_GATEWAY` | Idle Application Gateway | Terraform import only |",
            "| `STOPPED_VM` / `EMPTY_APP_SERVICE_PLAN` | Stopped VM / empty plan | Manual + catalog rules when live evidence exists |",
            "",
            "Prefer **catalog outcomes** on inventory rows when both exist; legacy rows are review **signals**, not savings proof.",
            "",
        ]
    )

    out = ROOT / "docs" / "ANALYSIS_RULES_MASTER.md"
    out.write_text("\n".join(lines) + "\n")
    print(f"Wrote {out.relative_to(ROOT)} ({len(lines)} lines)")


if __name__ == "__main__":
    main()
