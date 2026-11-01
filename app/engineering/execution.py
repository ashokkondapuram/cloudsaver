"""Deterministic zero-downtime agent plans for approved engineering actions."""
from __future__ import annotations

from typing import Any

from app.agent_contract import expected_state
from app.engineering.actions import resize_arguments
from app.finops_resize_playbooks import resolve_playbook


def build_engineering_resize_agent_plan(
    *,
    action_id: str,
    resource: dict[str, Any],
    connector_id: str,
    target_size: str,
    gitops_connector_id: str | None = None,
    gitops_target_id: str | None = None,
) -> dict[str, Any]:
    book = resolve_playbook(
        cloud_provider=resource.get("cloud_provider", "azure"),
        resource_type=resource.get("resource_type", ""),
        finops_action="azure.vm.rightsize",
    )
    resize_args = resize_arguments(action_id=action_id, target_size=target_size)
    baseline = expected_state(resource)
    inspect_expected = {}
    for field in book["inspect_fields"]:
        if field in baseline:
            inspect_expected[field] = baseline[field]
    size_field = book["size_field"]
    if size_field not in inspect_expected:
        current = (resource.get("evidence") or {}).get(size_field) or resource.get(size_field)
        if isinstance(current, str) and current:
            inspect_expected[size_field] = current
    if not inspect_expected:
        raise ValueError("Scan observation is missing live size metadata required for resize")
    if inspect_expected.get(size_field) == target_size:
        raise ValueError("Target size matches current observation; no resize required")
    steps = [
        dict(
            connector_id=connector_id,
            operation="resource.inspect",
            arguments=dict(expected_state=inspect_expected),
            purpose="Verify live power/state and current size before a zero-downtime resize",
            verification="Gateway permit binds to saved expected_state on the task",
            rollback="Read-only; abort if live state drifted",
        ),
        dict(
            connector_id=connector_id,
            operation=book["resize_operation"],
            arguments=resize_args,
            purpose=f"Apply engineering {action_id} to {target_size} without deallocate/stop",
            verification="Re-read resource metadata and confirm size field matches target",
            rollback="Restore prior SKU manually using provider console or IaC; snapshot not automatic",
        ),
    ]
    if gitops_connector_id and gitops_target_id:
        steps.append(
            dict(
                connector_id=gitops_connector_id,
                operation="gitops.terraform.sync",
                arguments=dict(
                    target_id=gitops_target_id,
                    patch_mode="rightsize_sku",
                    attributes=dict(
                        target_size=target_size,
                        terraform_attribute=book["terraform_attribute"],
                    ),
                ),
                purpose="Open a repository PR updating Terraform SKU to match approved zero-downtime resize",
                verification="Verify draft PR patches the indexed AST block attribute only",
                rollback="Close PR without merge; cloud resize already applied",
            )
        )
    return dict(
        summary=f"Zero-downtime engineering resize to {target_size} after live inspection",
        steps=steps,
        finops_action=book["finops_action"],
        target_size=target_size,
        engineering_action=action_id,
        resize_mode="zero_downtime",
    )
