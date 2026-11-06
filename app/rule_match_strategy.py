"""Industry-style rule match resolution (Turbonomic-aligned action market).

When multiple catalog rules reach ``condition_detected`` on one resource, operators need a
single primary recommendation plus explicit alternates — not an undifferentiated list.

This module does not execute changes; it ranks matches using evidence completeness, workflow
channel, and family-specific exclusivity (same pattern IBM Turbonomic uses for competing actions).
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from app.agent_workflow_routing import route_for_rule
from app.resource_catalog import FAMILIES, family

# Turbonomic-style action taxonomy (Configure / Resize / Move / Delete / Suspend / Scale).
class ActionClass(str, Enum):
    DELETE = "delete"
    SUSPEND = "suspend"
    RESIZE = "resize"
    CONFIGURE = "configure"
    MOVE = "move"
    SCALE = "scale"
    ARCHITECT = "architect_review"


ACTION_CLASS_BY_RULE: dict[str, ActionClass] = {
    "AZURE_DISK_UNATTACHED_RETENTION": ActionClass.DELETE,
    "AZURE_DISK_PROVISIONED_PERFORMANCE": ActionClass.CONFIGURE,
    "AZURE_PUBLIC_IP_UNASSOCIATED": ActionClass.DELETE,
    "AZURE_PUBLIC_IP_ASSOCIATED_IDLE": ActionClass.DELETE,
    "AZURE_VM_STOPPED_RESIDUAL_COST": ActionClass.SUSPEND,
    "AZURE_VM_RIGHTSIZING_UTILIZATION": ActionClass.RESIZE,
    "AZURE_ASP_EMPTY_PAID_PLAN": ActionClass.DELETE,
    "AZURE_ASP_UNDERUTILIZED_SKU": ActionClass.RESIZE,
    "AZURE_NAT_GATEWAY_SERVICE_ENDPOINT_BYPASS": ActionClass.ARCHITECT,
    "AZURE_APPGW_EMPTY_OR_HIGH_AUTOSCALE_FLOOR": ActionClass.ARCHITECT,
    "AWS_UNATTACHED_EBS": ActionClass.DELETE,
    "AWS_EBS_GP2_TO_GP3_AND_IOPS_TUNING": ActionClass.CONFIGURE,
    "AWS_EC2_STOPPED_EBS_RESIDUAL": ActionClass.SUSPEND,
    "AWS_EC2_GRAVITON_AND_SLO_RIGHTSIZING": ActionClass.RESIZE,
    "AWS_UNASSOCIATED_EIP": ActionClass.DELETE,
    "AWS_NAT_GW_ENDPOINT_BYPASS_AND_IDLE": ActionClass.ARCHITECT,
    "AWS_ELB_ORPHANED_AND_INGRESS_CONSOLIDATION": ActionClass.ARCHITECT,
    "AWS_IDLE_RDS": ActionClass.SUSPEND,
    "AWS_RDS_AURORA_RIGHTSIZING_AND_GP3": ActionClass.RESIZE,
    "GCP_UNATTACHED_DISK": ActionClass.DELETE,
    "GCP_DISK_HYPERDISK_IOPS_TUNING": ActionClass.CONFIGURE,
    "GCP_GCE_STOPPED_DISK_TAX": ActionClass.SUSPEND,
    "GCP_GCE_AXION_AND_CUSTOM_RIGHTSIZING": ActionClass.RESIZE,
    "GCP_UNASSIGNED_ADDRESS": ActionClass.DELETE,
    "GCP_CLOUD_NAT_PRIVATE_GOOGLE_ACCESS": ActionClass.ARCHITECT,
    "GCP_LB_EMPTY_BACKEND_FORWARDING_RULE": ActionClass.ARCHITECT,
    "GCP_IDLE_CLOUD_SQL": ActionClass.SUSPEND,
    "K8S_CONTAINER_CPU_OVERREQUEST": ActionClass.RESIZE,
    "K8S_CONTAINER_MEMORY_OVERREQUEST": ActionClass.RESIZE,
    "AWS_DYNAMODB_BILLING_MODE_AND_UNUSED_GSI": ActionClass.CONFIGURE,
    "AWS_ELASTICACHE_GRAVITON_AND_VALKEY_UPGRADE": ActionClass.MOVE,
    "AWS_LAMBDA_ARM64_AND_PROVISIONED_CONCURRENCY": ActionClass.RESIZE,
    "AWS_S3_INTELLIGENT_TIERING_AND_MULTIPART_CLEANUP": ActionClass.CONFIGURE,
    "AWS_BEDROCK_PT_AND_SAGEMAKER_IDLE_ENDPOINT": ActionClass.SUSPEND,
    "AZURE_AI_FOUNDRY_PTU_VS_PAYG_ARBITRAGE": ActionClass.CONFIGURE,
    "AZURE_COSMOSDB_MANUAL_RU_TO_AUTOSCALE": ActionClass.CONFIGURE,
    "AZURE_REDIS_UNDERUTILIZED_TIER_REVIEW": ActionClass.RESIZE,
    "AZURE_SQL_PG_IDLE_AND_NONPROD_HA_REVIEW": ActionClass.SUSPEND,
    "AZURE_STORAGE_LIFECYCLE_AND_ORPHANED_VHD": ActionClass.CONFIGURE,
    "GCP_BIGQUERY_SLOT_AUTOSCALE_AND_STORAGE": ActionClass.CONFIGURE,
    "GCP_CLOUDRUN_MIN_INSTANCE_AND_MEMORYSTORE": ActionClass.CONFIGURE,
    "GCP_CLOUDSQL_ALLOYDB_RIGHTSIZING_AND_HA": ActionClass.RESIZE,
    "GCP_VERTEX_AI_IDLE_ENDPOINT_AND_REPLICA_FLOOR": ActionClass.SUSPEND,
    "K8S_ABANDONED_WORKLOAD_OR_NAMESPACE": ActionClass.DELETE,
    "K8S_DAEMONSET_CLUSTER_WIDE_OVERHEAD_TAX": ActionClass.SCALE,
    "K8S_HPA_PDB_CONFLICT_OR_IDLE_FLOOR": ActionClass.CONFIGURE,
    "K8S_NODE_POOL_FRAGMENTATION_WASTE": ActionClass.SCALE,
    "K8S_ORPHANED_LOADBALANCER_SERVICE": ActionClass.DELETE,
    "K8S_PVC_UNMOUNTED_OR_LOW_OCCUPANCY": ActionClass.DELETE,
    "K8S_STATEFULSET_SIZING_AND_VOLUME_TEMPLATE": ActionClass.RESIZE,
    "K8S_CONTAINER_UNDERPROVISIONED_RISK": ActionClass.SCALE,
    "PLATFORM_DEFAULT_TAGS": ActionClass.CONFIGURE,
    "PLATFORM_PROD_ENCRYPTION_EXPECTATION": ActionClass.CONFIGURE,
}

# Lower number = higher priority channel when picking a primary match.
CHANNEL_RANK: dict[str, int] = {
    "finops_autopilot_resize": 10,
    "kubernetes_patch_preview": 20,
    "engineering_review_plan": 30,
    "remediation_terraform_import": 40,
    "remediation_bash_review": 50,
    "manual_assessment_only": 60,
}

# Within one resource family, earlier rule wins as primary when both fire (state should be mutually exclusive).
FAMILY_RULE_ORDER: dict[tuple[str, str], tuple[str, ...]] = {
    (provider, fam): tuple(rules)
    for provider, fam, _cat, _types, rules in FAMILIES
}

CONFIDENCE_ORDER = ("high", "medium", "low", "blocked")


def _action_class(rule_id: str) -> ActionClass:
    return ACTION_CLASS_BY_RULE.get(rule_id, ActionClass.ARCHITECT)


def _channel(rule_id: str) -> str:
    try:
        return route_for_rule(rule_id).primary
    except KeyError:
        return "manual_assessment_only"


def match_confidence(evaluation: dict) -> str:
    """Evidence-weighted confidence (Turbonomic data-health analogue)."""
    if evaluation.get("outcome") != "condition_detected":
        return "blocked"
    if evaluation.get("destructive_actions_blocked") or evaluation.get("protected_reasons"):
        return "blocked"
    if evaluation.get("safety_blocks"):
        return "medium"
    channel = _channel(evaluation["rule_id"])
    if channel == "finops_autopilot_resize":
        return "high"
    if channel in ("kubernetes_patch_preview", "engineering_review_plan"):
        return "high"
    if channel in ("remediation_terraform_import", "remediation_bash_review"):
        return "medium"
    return "medium"


def _family_order_key(resource: dict, rule_id: str) -> int:
    fam = family(resource)
    if not fam:
        return 999
    order = FAMILY_RULE_ORDER.get((fam[0], fam[1]), ())
    try:
        return order.index(rule_id)
    except ValueError:
        return 999


def _sort_key(resource: dict, evaluation: dict) -> tuple:
    conf = match_confidence(evaluation)
    conf_rank = CONFIDENCE_ORDER.index(conf) if conf in CONFIDENCE_ORDER else 99
    channel = _channel(evaluation["rule_id"])
    channel_rank = CHANNEL_RANK.get(channel, 99)
    family_rank = _family_order_key(resource, evaluation["rule_id"])
    # Prefer lower-risk action classes when channels tie (configure before delete).
    action_rank = {
        ActionClass.SCALE: 0,
        ActionClass.RESIZE: 1,
        ActionClass.CONFIGURE: 2,
        ActionClass.SUSPEND: 3,
        ActionClass.MOVE: 4,
        ActionClass.ARCHITECT: 5,
        ActionClass.DELETE: 6,
    }[_action_class(evaluation["rule_id"])]
    return (family_rank, conf_rank, channel_rank, action_rank, evaluation["rule_id"])


def _evaluation_targets_resource(resource: dict, evaluation: dict) -> bool:
    provider = resource.get("cloud_provider", "azure")
    rid = resource["resource_id"]
    eid = evaluation.get("resource_id") or rid
    if provider == "azure":
        return eid.lower() == rid.lower()
    return eid == rid


def resolve_resource_matches(
    resource: dict,
    evaluations: list[dict],
    *,
    opportunity_group_id: str | None = None,
) -> dict[str, Any]:
    """Pick primary + alternates for one inventory resource."""
    rid = resource["resource_id"]
    detected = [
        row
        for row in evaluations
        if _evaluation_targets_resource(resource, row) and row.get("outcome") == "condition_detected"
    ]
    if not detected:
        return dict(
            resource_id=rid,
            cloud_provider=resource.get("cloud_provider", "azure"),
            primary_match=None,
            alternate_matches=[],
            opportunity_group_id=opportunity_group_id,
            overlap_policy="max_one_primary_per_resource; financial rollup uses opportunity_group max",
        )
    ordered = sorted(detected, key=lambda row: _sort_key(resource, row))
    primary = ordered[0]
    alternates = ordered[1:]
    return dict(
        resource_id=rid,
        cloud_provider=resource.get("cloud_provider", "azure"),
        primary_match=dict(
            rule_id=primary["rule_id"],
            display_channel=_channel(primary["rule_id"]),
            action_class=_action_class(primary["rule_id"]).value,
            match_confidence=match_confidence(primary),
            safety_blocks=list(primary.get("safety_blocks") or []),
            protected_reasons=list(primary.get("protected_reasons") or []),
        ),
        alternate_matches=[
            dict(
                rule_id=row["rule_id"],
                display_channel=_channel(row["rule_id"]),
                action_class=_action_class(row["rule_id"]).value,
                match_confidence=match_confidence(row),
                suppressed_reason="lower_rank_in_action_market",
            )
            for row in alternates
        ],
        opportunity_group_id=opportunity_group_id,
        overlap_policy="max_one_primary_per_resource; financial rollup uses opportunity_group max",
        strategy_version="1.0.0",
    )


def resolve_scan_matches(scan: dict) -> list[dict[str, Any]]:
    """Resolve primary matches for every inventory row in a scan snapshot."""
    inventory = list(scan.get("inventory") or [])
    evaluations = list(scan.get("rule_evaluations") or [])
    group_by_resource: dict[tuple[str, str], str | None] = {}
    for finding in scan.get("findings") or []:
        if finding.get("opportunity_group_id") and finding.get("resource_id"):
            provider = finding.get("cloud_provider", "azure")
            key = provider, finding["resource_id"].lower() if provider == "azure" else finding["resource_id"]
            group_by_resource[key] = finding["opportunity_group_id"]
    rows = []
    for resource in inventory:
        provider = resource.get("cloud_provider", "azure")
        key = provider, resource["resource_id"].lower() if provider == "azure" else resource["resource_id"]
        rows.append(
            resolve_resource_matches(
                resource,
                evaluations,
                opportunity_group_id=group_by_resource.get(key),
            )
        )
    return rows
