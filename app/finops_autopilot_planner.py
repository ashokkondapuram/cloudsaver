"""Deterministic agent plans for FinOps resize (no model drafting)."""
from __future__ import annotations

from typing import Any

from app.finops_resize_playbooks import resolve_playbook
from app.agent_contract import expected_state


def build_resize_agent_plan(
    *,
    resource: dict[str, Any],
    connector_id: str,
    target_size: str,
    finops_action: str | None = None,
    gitops_connector_id: str | None = None,
    gitops_target_id: str | None = None,
) -> dict[str, Any]:
    book = resolve_playbook(
        cloud_provider=resource.get("cloud_provider", "azure"),
        resource_type=resource.get("resource_type", ""),
        finops_action=finops_action,
    )
    if not target_size or len(target_size) > 80:
        raise ValueError("target_size is required and must be at most 80 characters")
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
            purpose="Verify live power/state and current size before mutation",
            verification="Gateway permit binds to saved expected_state on the task",
            rollback="Read-only; abort if live state drifted",
        ),
        dict(
            connector_id=connector_id,
            operation=book["resize_operation"],
            arguments=dict(target_size=target_size, restore_power=True),
            purpose=f"Apply FinOps {book['finops_action']} to {target_size}",
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
                purpose="Open a repository PR updating Terraform SKU to match approved cloud resize",
                verification="Verify draft PR patches the indexed AST block attribute only",
                rollback="Close PR without merge; cloud resize already applied",
            )
        )
    return dict(
        summary=book["summary_template"].format(target_size=target_size),
        steps=steps,
        finops_action=book["finops_action"],
        target_size=target_size,
    )
