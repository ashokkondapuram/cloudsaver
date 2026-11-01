"""Engineering actions must remain zero-downtime across API, readiness, and agent plans."""
from datetime import datetime, timezone

import pytest

from app.agent_contract import Connector, validate_plan
from app.engineering.actions import ACTIONS, downtime_class, resize_arguments
from app.engineering.execution import build_engineering_resize_agent_plan
from app.engineering.readiness import POLICY, evaluate

SUB = "33333333-3333-4333-8333-333333333333"
TENANT = "11111111-1111-4111-8111-111111111111"


def test_all_engineering_actions_are_zero_downtime():
    assert POLICY["downtime_policy"] == "zero_downtime"
    for action_id in ACTIONS:
        assert downtime_class(action_id) == "zero_downtime"


def test_disk_review_never_emits_resize_arguments():
    with pytest.raises(ValueError, match="evidence-only"):
        resize_arguments(action_id="azure.disk.review", target_size="P1v3")


def test_vm_resize_arguments_use_zero_downtime_mode():
    args = resize_arguments(action_id="azure.vm.rightsize", target_size="Standard_D4s_v5")
    assert args == dict(
        target_size="Standard_D4s_v5",
        resize_mode="zero_downtime",
        restore_power=False,
    )


def test_readiness_includes_zero_downtime_checks():
    resource = dict(
        cloud_provider="azure",
        subscription_id=SUB,
        resource_type="Microsoft.Compute/virtualMachines",
        resource_id=f"/subscriptions/{SUB}/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm",
        evidence=dict(vm_size="Standard_D4s_v5"),
    )
    scan = dict(scan_id="scan-1", timestamp=datetime.now(timezone.utc).isoformat())
    workload = dict(id="w1", version=1, owner="owner", requirements={})
    readiness = evaluate(resource, scan, workload, action="azure.vm.rightsize", candidate_sku="Standard_D2s_v5")
    codes = {check["code"] for check in readiness["checks"]}
    assert "ZERO_DOWNTIME_POLICY" in codes
    assert "ZERO_DOWNTIME_METHOD" in codes
    assert any("zero-downtime" in step.lower() for step in readiness["next_steps"])


def test_engineering_agent_plan_validates_zero_downtime_resize():
    resource = dict(
        cloud_provider="azure",
        resource_type="Microsoft.Compute/virtualMachines",
        resource_id=f"/subscriptions/{SUB}/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm",
        evidence=dict(power_state="PowerState/running", vm_size="Standard_D8s_v5"),
    )
    plan = build_engineering_resize_agent_plan(
        action_id="azure.vm.rightsize",
        resource=resource,
        connector_id="azure-compute",
        target_size="Standard_D4s_v5",
    )
    assert plan["resize_mode"] == "zero_downtime"
    assert plan["steps"][1]["arguments"]["resize_mode"] == "zero_downtime"
    task = dict(
        id="22222222-2222-4222-8222-222222222222",
        tenant_id=TENANT,
        provider="azure",
        scope_id=SUB,
        resource_id=resource["resource_id"],
        payload=dict(
            connector_ids=["azure-compute"],
            expected_state=dict(powerState="PowerState/running", vm_size="Standard_D8s_v5"),
        ),
    )
    catalog = [
        Connector(
            id="azure-compute",
            tenant_id=TENANT,
            provider="azure",
            scope_id=SUB,
            kind="azure_arm",
            operations=["resource.inspect", "compute.resize"],
            endpoint=None,
            token_env=None,
        )
    ]
    validated = validate_plan(plan, task, catalog)
    assert validated["steps"][1]["arguments"]["resize_mode"] == "zero_downtime"
