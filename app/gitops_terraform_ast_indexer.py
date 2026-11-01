"""Parse Terraform HCL resource blocks and infer cloud resource IDs for AST indexing."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.agent_gitops_sync import TERRAFORM_RESOURCE_MAP

_ARM_FROM_AZURERM = {
    "azurerm_managed_disk": "Microsoft.Compute/disks",
    "azurerm_linux_virtual_machine": "Microsoft.Compute/virtualMachines",
    "azurerm_windows_virtual_machine": "Microsoft.Compute/virtualMachines",
    "azurerm_virtual_machine": "Microsoft.Compute/virtualMachines",
    "azurerm_public_ip": "Microsoft.Network/publicIPAddresses",
    "azurerm_network_interface": "Microsoft.Network/networkInterfaces",
    "azurerm_storage_account": "Microsoft.Storage/storageAccounts",
    "azurerm_service_plan": "Microsoft.Web/serverFarms",
}

_AWS_FROM_TF = {value: key for key, value in TERRAFORM_RESOURCE_MAP.items() if key.startswith("aws:")}

_RESOURCE_START = re.compile(r'^\s*resource\s+"([^"]+)"\s+"([^"]+)"\s*\{')
_STRING_ATTR = re.compile(r'^\s*([A-Za-z0-9_.-]+)\s*=\s*"([^"]*)"\s*$', re.MULTILINE)


@dataclass(frozen=True)
class HclResourceBlock:
    resource_type: str
    resource_name: str
    start_line: int
    end_line: int
    text: str
    attributes: dict[str, str]


def iter_hcl_resource_blocks(source: str) -> list[HclResourceBlock]:
    lines = source.splitlines()
    blocks: list[HclResourceBlock] = []
    index = 0
    while index < len(lines):
        match = _RESOURCE_START.match(lines[index])
        if not match:
            index += 1
            continue
        resource_type, resource_name = match.group(1), match.group(2)
        start_line = index + 1
        depth = 1
        index += 1
        while index < len(lines) and depth > 0:
            depth += lines[index].count("{") - lines[index].count("}")
            index += 1
        end_line = index
        text = "\n".join(lines[start_line - 1 : end_line])
        attrs = {key: value for key, value in _STRING_ATTR.findall(text)}
        blocks.append(
            HclResourceBlock(
                resource_type=resource_type,
                resource_name=resource_name,
                start_line=start_line,
                end_line=end_line,
                text=text,
                attributes=attrs,
            )
        )
    return blocks


def _azure_arm_id(subscription_id: str, resource_group: str, provider_type: str, name: str) -> str:
    return (
        f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}/"
        f"providers/{provider_type}/{name}"
    ).lower()


def infer_cloud_resource_ids(block: HclResourceBlock, *, scope: dict[str, Any]) -> list[str]:
    attrs = block.attributes
    ids: list[str] = []
    explicit = attrs.get("id") or attrs.get("resource_id")
    if isinstance(explicit, str) and len(explicit) > 10:
        ids.append(explicit.lower())
    arm_type = _ARM_FROM_AZURERM.get(block.resource_type)
    subscription = scope.get("azure_subscription_id")
    if arm_type and subscription:
        group = attrs.get("resource_group_name") or scope.get("default_resource_group")
        name = attrs.get("name")
        if group and name:
            if arm_type == "Microsoft.Compute/disks":
                ids.append(_azure_arm_id(subscription, group, arm_type, name))
            elif arm_type == "Microsoft.Compute/virtualMachines":
                ids.append(_azure_arm_id(subscription, group, arm_type, name))
            elif arm_type == "Microsoft.Storage/storageAccounts":
                ids.append(_azure_arm_id(subscription, group, arm_type, name))
            else:
                ids.append(_azure_arm_id(subscription, group, arm_type, name))
    aws_family = _AWS_FROM_TF.get(block.resource_type)
    account = scope.get("aws_account_id")
    region = attrs.get("region") or scope.get("aws_region") or "us-east-1"
    if aws_family and account:
        if aws_family == "aws:ec2:instance":
            instance_id = attrs.get("id") or attrs.get("instance_id")
            if instance_id and instance_id.startswith("i-"):
                ids.append(f"arn:aws:ec2:{region}:{account}:instance/{instance_id}")
        if aws_family == "aws:ec2:volume":
            volume_id = attrs.get("id")
            if volume_id and volume_id.startswith("vol-"):
                ids.append(f"arn:aws:ec2:{region}:{account}:volume/{volume_id}")
    if block.resource_type.startswith("google_"):
        project = scope.get("gcp_project_id")
        zone = attrs.get("zone") or scope.get("gcp_zone")
        name = attrs.get("name")
        if project and zone and name:
            if block.resource_type == "google_compute_instance":
                ids.append(f"//compute.googleapis.com/projects/{project}/zones/{zone}/instances/{name}".lower())
            if block.resource_type == "google_compute_disk":
                ids.append(f"//compute.googleapis.com/projects/{project}/zones/{zone}/disks/{name}".lower())
    deduped: list[str] = []
    seen = set()
    for item in ids:
        if item not in seen:
            seen.add(item)
            deduped.append(item)
    return deduped


def index_terraform_file(*, file_path: str, source: str, scope: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for block in iter_hcl_resource_blocks(source):
        cloud_ids = infer_cloud_resource_ids(block, scope=scope)
        if not cloud_ids:
            continue
        address = f"{block.resource_type}.{block.resource_name}"
        for cloud_id in cloud_ids:
            rows.append(
                dict(
                    cloud_resource_id=cloud_id,
                    file_path=file_path,
                    address=address,
                    resource_name=block.resource_name,
                    start_line=block.start_line,
                    end_line=block.end_line,
                    indexed_block=block.text,
                    iac_kind="terraform",
                    match_tier="repository_ast",
                )
            )
    return rows
