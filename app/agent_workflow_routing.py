"""Map FinOps analysis rule IDs to review/agent workflow channels (declarative, no cloud I/O)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.finops_resize_playbooks import PLAYBOOKS
from app.resource_catalog import FAMILIES

WorkflowChannel = Literal[
    "finops_autopilot_resize",
    "engineering_review_plan",
    "remediation_bash_review",
    "remediation_terraform_import",
    "kubernetes_patch_preview",
    "manual_assessment_only",
]

# Rightsizing rules that may produce a deterministic FinOps agent plan (inspect → compute.resize).
FINOPS_RULE_TO_ACTION: dict[str, str] = {
    "AZURE_VM_RIGHTSIZING_UTILIZATION": "azure.vm.rightsize",
    "AZURE_ASP_UNDERUTILIZED_SKU": "azure.appservice.rightsize",
    "AWS_EC2_GRAVITON_AND_SLO_RIGHTSIZING": "aws.ec2.rightsize",
    "AWS_RDS_AURORA_RIGHTSIZING_AND_GP3": "aws.rds.rightsize",
    "GCP_GCE_AXION_AND_CUSTOM_RIGHTSIZING": "gcp.compute.rightsize",
}

# Azure engineering pilot plans (evidence gates; execution_enabled=False in API).
ENGINEERING_ACTION_BY_RULE: dict[str, str] = {
    "AZURE_VM_RIGHTSIZING_UTILIZATION": "azure.vm.rightsize",
    "AZURE_DISK_UNATTACHED_RETENTION": "azure.disk.review",
    "AZURE_STORAGE_LIFECYCLE_AND_ORPHANED_VHD": "azure.storage.lifecycle.review",
}

KUBERNETES_PATCH_PREVIEW_RULES = frozenset(
    {"K8S_CONTAINER_CPU_OVERREQUEST", "K8S_CONTAINER_MEMORY_OVERREQUEST"}
)

# Bash review for public IP and orphaned NIC/NSG scan signals (disk uses engineering plan).
BASH_REMEDIATION_RULES = frozenset(
    {"AZURE_PUBLIC_IP_UNASSOCIATED", "ORPHANED_NIC", "ORPHANED_NSG"}
)
TERRAFORM_IMPORT_RULES = frozenset(
    {
        *BASH_REMEDIATION_RULES,
        "AZURE_APPGW_EMPTY_OR_HIGH_AUTOSCALE_FLOOR",
        "AZURE_STORAGE_LIFECYCLE_AND_ORPHANED_VHD",
        "AWS_UNATTACHED_EBS",
        "AWS_UNASSOCIATED_EIP",
        "AWS_IDLE_RDS",
        "GCP_UNATTACHED_DISK",
        "GCP_UNASSIGNED_ADDRESS",
        "GCP_IDLE_CLOUD_SQL",
    }
)

AgentOperation = Literal[
    "resource.inspect",
    "compute.resize",
    "gitops.terraform.sync",
    "workload.inspect",
    "manual_review",
]


@dataclass(frozen=True, slots=True)
class AgentWorkflowRoute:
    """Primary workflow channel for operators/agents after condition_detected."""

    primary: WorkflowChannel
    secondary: tuple[WorkflowChannel, ...] = ()
    finops_action: str | None = None
    engineering_action: str | None = None
    agent_operations: tuple[str, ...] = ()
    zero_downtime: bool | None = None


def _catalog_rule_ids() -> frozenset[str]:
    return frozenset(rule_id for _p, _f, _c, _t, rules in FAMILIES for rule_id in rules)


def route_for_rule(rule_id: str) -> AgentWorkflowRoute:
    if rule_id.startswith('PLATFORM_'):
        return AgentWorkflowRoute(
            primary="manual_assessment_only",
            agent_operations=("manual_review",),
        )
    if rule_id not in _catalog_rule_ids() and rule_id not in TERRAFORM_IMPORT_RULES | BASH_REMEDIATION_RULES:
        raise KeyError(f"Unknown rule_id for workflow routing: {rule_id}")

    if rule_id in FINOPS_RULE_TO_ACTION:
        action = FINOPS_RULE_TO_ACTION[rule_id]
        ops: tuple[str, ...] = ("resource.inspect", "compute.resize")
        secondary: list[WorkflowChannel] = []
        eng = ENGINEERING_ACTION_BY_RULE.get(rule_id)
        if eng:
            secondary.append("engineering_review_plan")
        return AgentWorkflowRoute(
            primary="finops_autopilot_resize",
            secondary=tuple(secondary),
            finops_action=action,
            engineering_action=eng,
            agent_operations=ops,
        )

    if rule_id in ENGINEERING_ACTION_BY_RULE:
        return AgentWorkflowRoute(
            primary="engineering_review_plan",
            engineering_action=ENGINEERING_ACTION_BY_RULE[rule_id],
            agent_operations=("manual_review",),
        )

    if rule_id in KUBERNETES_PATCH_PREVIEW_RULES:
        return AgentWorkflowRoute(
            primary="kubernetes_patch_preview",
            agent_operations=("workload.inspect", "manual_review"),
        )

    if rule_id.startswith("K8S_"):
        return AgentWorkflowRoute(
            primary="manual_assessment_only",
            agent_operations=("manual_review",),
        )

    if rule_id in BASH_REMEDIATION_RULES:
        return AgentWorkflowRoute(
            primary="remediation_bash_review",
            secondary=("remediation_terraform_import",),
            agent_operations=("manual_review",),
        )

    if rule_id in TERRAFORM_IMPORT_RULES:
        return AgentWorkflowRoute(
            primary="remediation_terraform_import",
            agent_operations=("manual_review",),
        )

    return AgentWorkflowRoute(
        primary="manual_assessment_only",
        agent_operations=("manual_review",),
    )


def catalog_routes() -> dict[str, AgentWorkflowRoute]:
    return {rule_id: route_for_rule(rule_id) for rule_id in sorted(_catalog_rule_ids())}


def finops_plan_step_operations(*, sync_iac: bool = False) -> tuple[str, ...]:
    steps = ("resource.inspect", "compute.resize")
    if sync_iac:
        return (*steps, "gitops.terraform.sync")
    return steps
