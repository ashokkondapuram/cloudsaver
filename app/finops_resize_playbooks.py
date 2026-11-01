"""FinOps resize playbooks: resource-type-specific targets and agent step templates."""
from __future__ import annotations

from typing import Any, Literal

FinOpsResizeAction = Literal[
    "azure.vm.rightsize",
    "azure.appservice.rightsize",
    "azure.disk.rightsize",
    "aws.ec2.rightsize",
    "aws.rds.rightsize",
    "gcp.compute.rightsize",
]


PLAYBOOKS: dict[str, dict[str, Any]] = {
    "azure.vm.rightsize": {
        "finops_action": "azure.vm.rightsize",
        "cloud_provider": "azure",
        "resource_type": "microsoft.compute/virtualmachines",
        "connector_kind": "azure_arm",
        "size_field": "vm_size",
        "terraform_attribute": "vm_size",
        "resize_operation": "compute.resize",
        "inspect_fields": ("powerState", "vm_size"),
        "summary_template": "Right-size Azure VM to {target_size} after live inspection",
    },
    "azure.appservice.rightsize": {
        "finops_action": "azure.appservice.rightsize",
        "cloud_provider": "azure",
        "resource_type": "microsoft.web/serverfarms",
        "connector_kind": "azure_arm",
        "size_field": "sku_name",
        "terraform_attribute": "size",
        "resize_operation": "compute.resize",
        "inspect_fields": ("numberOfSites", "sku_name"),
        "summary_template": "Right-size App Service plan SKU to {target_size} after live inspection",
    },
    "azure.disk.rightsize": {
        "finops_action": "azure.disk.rightsize",
        "cloud_provider": "azure",
        "resource_type": "microsoft.compute/disks",
        "connector_kind": "azure_arm",
        "size_field": "disk_size_gb",
        "terraform_attribute": "disk_size_gb",
        "resize_operation": "compute.resize",
        "inspect_fields": ("diskState", "disk_size_gb"),
        "summary_template": "Resize Azure managed disk to {target_size} GiB after live inspection",
    },
    "aws.ec2.rightsize": {
        "finops_action": "aws.ec2.rightsize",
        "cloud_provider": "aws",
        "resource_type": "aws:ec2:instance",
        "connector_kind": "aws_sdk",
        "size_field": "instance_type",
        "terraform_attribute": "instance_type",
        "resize_operation": "compute.resize",
        "inspect_fields": ("State", "instance_type"),
        "summary_template": "Right-size EC2 instance to {target_size} after live inspection",
    },
    "aws.rds.rightsize": {
        "finops_action": "aws.rds.rightsize",
        "cloud_provider": "aws",
        "resource_type": "aws:rds:db",
        "connector_kind": "aws_sdk",
        "size_field": "instance_class",
        "terraform_attribute": "instance_class",
        "resize_operation": "compute.resize",
        "inspect_fields": ("DBInstanceStatus", "instance_class"),
        "summary_template": "Right-size RDS instance class to {target_size} after live inspection",
    },
    "gcp.compute.rightsize": {
        "finops_action": "gcp.compute.rightsize",
        "cloud_provider": "gcp",
        "resource_type": "compute.googleapis.com/instance",
        "connector_kind": "gcp_rest",
        "size_field": "machine_type",
        "terraform_attribute": "machine_type",
        "resize_operation": "compute.resize",
        "inspect_fields": ("status", "machine_type"),
        "summary_template": "Right-size GCE instance to {target_size} after live inspection",
    },
}


def resolve_playbook(*, cloud_provider: str, resource_type: str, finops_action: str | None = None) -> dict[str, Any]:
    if finops_action:
        book = PLAYBOOKS.get(finops_action)
        if not book:
            raise ValueError("Unknown FinOps resize action")
        return book
    kind = resource_type.lower()
    for book in PLAYBOOKS.values():
        if book["cloud_provider"] == cloud_provider and book["resource_type"] in kind:
            return book
    raise ValueError("No FinOps resize playbook for this resource type")


def list_playbooks() -> list[dict[str, str]]:
    return [
        dict(
            finops_action=key,
            cloud_provider=book["cloud_provider"],
            resource_type=book["resource_type"],
            size_field=book["size_field"],
            terraform_attribute=book["terraform_attribute"],
            connector_kind=book["connector_kind"],
            resize_operation=book["resize_operation"],
            agent_steps="resource.inspect,compute.resize",
        )
        for key, book in PLAYBOOKS.items()
    ]


def candidate_size_from_resource(resource: dict[str, Any], book: dict[str, Any]) -> str | None:
    """Use scan evidence or recommendation metadata when caller did not supply target_size."""
    evidence = resource.get("evidence") or {}
    size_field = book["size_field"]
    for key in (
        "recommended_vm_size",
        "recommended_instance_type",
        "recommended_machine_type",
        "recommended_instance_class",
        "recommended_sku",
        "candidate_sku",
        f"recommended_{size_field}",
    ):
        value = evidence.get(key) or resource.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, int) and size_field == "disk_size_gb":
            return str(value)
    metrics = evidence.get("metrics") or {}
    for bucket in metrics.values():
        if isinstance(bucket, dict) and isinstance(bucket.get("recommended_size"), str):
            return bucket["recommended_size"]
    return None


def pick_resize_connector(catalog, tenant_id: str, book: dict[str, Any], resource_id: str):
    """Choose the first tenant connector that can execute this resize playbook without manual wiring."""
    from app.agent_contract import supports_resource

    resize_op = book["resize_operation"]
    matches = [
        c
        for c in catalog
        if c.tenant_id == tenant_id
        and c.kind == book["connector_kind"]
        and resize_op in c.operations
        and supports_resource(c, resource_id)
    ]
    if not matches:
        raise ValueError(
            "No connector allows compute.resize for this resource; grant compute.resize in CLOUDSAVER_AGENT_CONNECTORS"
        )
    if len(matches) > 1:
        matches.sort(key=lambda item: item.id)
    return matches[0]


def pick_gitops_connector(catalog, tenant_id: str, target_id: str):
    matches = [
        c
        for c in catalog
        if c.tenant_id == tenant_id
        and c.kind == "gitops_terraform"
        and c.target_id == target_id
        and "gitops.terraform.sync" in c.operations
    ]
    if not matches:
        raise ValueError("GitOps connector not found for target_id")
    return matches[0]
