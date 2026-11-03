"""Engineering + FinOps agent workflow routing matches analysis catalog and contracts."""
import pytest

from app.agent_contract import ALLOWED_OPERATIONS_BY_KIND
from app.agent_workflow_routing import (
    FINOPS_RULE_TO_ACTION,
    KUBERNETES_PATCH_PREVIEW_RULES,
    TERRAFORM_IMPORT_RULES,
    catalog_routes,
    finops_plan_step_operations,
    route_for_rule,
)
from app.engineering.readiness import RULES as ENGINEERING_READINESS_RULES
from app.finops_autopilot_planner import build_resize_agent_plan
from app.finops_resize_playbooks import PLAYBOOKS, resolve_playbook
from app.resource_catalog import FAMILIES


CATALOG_RULES = frozenset(rule_id for _p, _f, _c, _t, rules in FAMILIES for rule_id in rules)
SUB = "33333333-3333-4333-8333-333333333333"


def test_every_catalog_rule_has_a_workflow_route():
    routes = catalog_routes()
    assert set(routes) == CATALOG_RULES
    for rule_id, route in routes.items():
        assert route.primary
        assert route.agent_operations
        if route.finops_action:
            assert route.finops_action in PLAYBOOKS
            assert route.finops_action == FINOPS_RULE_TO_ACTION[rule_id]
        if route.engineering_action:
            assert route.engineering_action in ENGINEERING_READINESS_RULES


def test_engineering_capabilities_actions_align_with_readiness():
    from app.engineering.readiness import RULES

    assert set(RULES) == {"azure.vm.rightsize", "azure.disk.review", "azure.storage.lifecycle.review"}
    rule_by_action = {
        "azure.vm.rightsize": "AZURE_VM_RIGHTSIZING_UTILIZATION",
        "azure.disk.review": "AZURE_DISK_UNATTACHED_RETENTION",
        "azure.storage.lifecycle.review": "AZURE_STORAGE_LIFECYCLE_AND_ORPHANED_VHD",
    }
    for action, rule_code in RULES.items():
        assert action in rule_by_action
        assert rule_code.startswith("CS-AZ-")
        route = route_for_rule(rule_by_action[action])
        if route.engineering_action == action:
            assert route.zero_downtime is True


@pytest.mark.parametrize("rule_id,finops_action", list(FINOPS_RULE_TO_ACTION.items()))
def test_finops_routes_emit_validate_plan_operations(rule_id, finops_action):
    book = PLAYBOOKS[finops_action]
    resource = _sample_resource(book["cloud_provider"], book["resource_type"])
    plan = build_resize_agent_plan(
        resource=resource,
        connector_id="resize-connector",
        target_size=_smaller_target(book, resource),
        finops_action=finops_action,
    )
    ops = tuple(step["operation"] for step in plan["steps"])
    assert ops == finops_plan_step_operations(sync_iac=False)
    assert plan["finops_action"] == finops_action
    assert book["resize_operation"] in ALLOWED_OPERATIONS_BY_KIND[book["connector_kind"]]


def test_finops_gitops_route_adds_terraform_sync():
    resource = dict(
        cloud_provider="azure",
        resource_type="Microsoft.Compute/virtualMachines",
        resource_id=f"/subscriptions/{SUB}/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm",
        evidence=dict(power_state="PowerState/running", vm_size="Standard_D8s_v5"),
    )
    plan = build_resize_agent_plan(
        resource=resource,
        connector_id="azure-compute",
        target_size="Standard_D4s_v5",
        gitops_connector_id="repo-sync",
        gitops_target_id="infra",
    )
    ops = tuple(step["operation"] for step in plan["steps"])
    assert ops == finops_plan_step_operations(sync_iac=True)
    assert plan["steps"][-1]["arguments"]["patch_mode"] == "rightsize_sku"


def test_kubernetes_overrequest_routes_to_patch_preview_not_resize():
    for rule_id in KUBERNETES_PATCH_PREVIEW_RULES:
        route = route_for_rule(rule_id)
        assert route.primary == "kubernetes_patch_preview"
        assert "compute.resize" not in route.agent_operations


def test_k8_reliability_rule_stays_assessment_only():
    route = route_for_rule("K8S_CONTAINER_UNDERPROVISIONED_RISK")
    assert route.primary == "manual_assessment_only"
    assert route.finops_action is None


def test_terraform_import_rules_are_declared():
    for rule_id in (
        "AWS_UNATTACHED_EBS",
        "GCP_UNATTACHED_DISK",
        "AZURE_PUBLIC_IP_UNASSOCIATED",
    ):
        assert rule_id in TERRAFORM_IMPORT_RULES
        assert route_for_rule(rule_id).primary in (
            "remediation_terraform_import",
            "remediation_bash_review",
        )


def test_idle_rds_routes_to_terraform_import_review():
    route = route_for_rule("AWS_IDLE_RDS")
    assert route.primary == "remediation_terraform_import"


def _sample_resource(cloud_provider: str, resource_type: str) -> dict:
    if cloud_provider == "azure":
        if "virtualmachines" in resource_type.lower():
            return dict(
                cloud_provider="azure",
                resource_type=resource_type,
                resource_id=f"/subscriptions/{SUB}/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm",
                evidence=dict(power_state="PowerState/running", vm_size="Standard_D8s_v5"),
            )
        if "serverfarms" in resource_type.lower():
            return dict(
                cloud_provider="azure",
                resource_type=resource_type,
                resource_id=f"/subscriptions/{SUB}/resourceGroups/rg/providers/Microsoft.Web/serverFarms/plan",
                evidence=dict(sku_name="P1v3", hosted_app_count=2),
            )
        if "disks" in resource_type.lower():
            return dict(
                cloud_provider="azure",
                resource_type=resource_type,
                resource_id=f"/subscriptions/{SUB}/resourceGroups/rg/providers/Microsoft.Compute/disks/d1",
                evidence=dict(disk_state="Attached", disk_size_gb=128),
            )
    if cloud_provider == "aws":
        if ":instance" in resource_type:
            return dict(
                cloud_provider="aws",
                resource_type=resource_type,
                resource_id=f"arn:aws:ec2:us-east-1:123456789012:instance/i-0123456789abcdef0",
                evidence=dict(power_state="running", instance_type="m5.xlarge"),
            )
        return dict(
            cloud_provider="aws",
            resource_type=resource_type,
            resource_id="arn:aws:rds:us-east-1:123456789012:db:app",
            evidence=dict(power_state="available", instance_class="db.r5.large"),
        )
    return dict(
        cloud_provider="gcp",
        resource_type=resource_type,
        resource_id="//compute.googleapis.com/projects/demo/zones/us-central1-a/instances/web",
        evidence=dict(state="RUNNING", machine_type="n2-standard-8"),
    )


def _smaller_target(book: dict, resource: dict) -> str:
    field = book["size_field"]
    current = (resource.get("evidence") or {}).get(field) or resource.get(field)
    if not isinstance(current, str) or not current:
        return "target-size-smaller"
    if field == "instance_class":
        return current.replace(".large", ".medium")
    if field == "sku_name":
        return "P1v2" if current != "P1v2" else "S1"
    if field == "instance_type":
        return current.replace("xlarge", "large").replace(".8", ".4")
    if field == "machine_type":
        return current.replace("8", "4")
    return current.replace("D8", "D4").replace("8", "4")
