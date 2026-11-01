import hashlib

import pytest

from app.agent_contract import validate_plan
from app.finops_autopilot_planner import build_resize_agent_plan
from app.finops_resize_playbooks import list_playbooks, resolve_playbook


TENANT = "11111111-1111-4111-8111-111111111111"
SUB = "33333333-3333-4333-8333-333333333333"


def test_playbooks_cover_three_clouds():
    items = list_playbooks()
    providers = {row["cloud_provider"] for row in items}
    assert providers == {"azure", "aws", "gcp"}


def test_build_azure_resize_plan():
    resource = dict(
        cloud_provider="azure",
        resource_type="Microsoft.Compute/virtualMachines",
        resource_id=f"/subscriptions/{SUB}/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm",
        evidence=dict(power_state="PowerState/running", vm_size="Standard_D8s_v5"),
    )
    plan = build_resize_agent_plan(resource=resource, connector_id="azure-compute", target_size="Standard_D4s_v5")
    assert len(plan["steps"]) == 2
    assert plan["steps"][0]["operation"] == "resource.inspect"
    assert plan["steps"][1]["operation"] == "compute.resize"
    assert plan["steps"][1]["arguments"]["target_size"] == "Standard_D4s_v5"


def test_validate_plan_accepts_finops_resize_plan():
    from app.agent_contract import Connector

    resource = dict(
        cloud_provider="azure",
        resource_type="Microsoft.Compute/virtualMachines",
        resource_id=f"/subscriptions/{SUB}/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm",
        evidence=dict(power_state="PowerState/running", vm_size="Standard_D8s_v5"),
    )
    plan = build_resize_agent_plan(resource=resource, connector_id="azure-compute", target_size="Standard_D4s_v5")
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
    assert validated["steps"][1]["operation"] == "compute.resize"


def test_resolve_playbook_by_action():
    book = resolve_playbook(cloud_provider="aws", resource_type="aws:ec2:instance", finops_action="aws.ec2.rightsize")
    assert book["size_field"] == "instance_type"


def test_pick_resize_connector():
    from app.agent_contract import Connector
    from app.finops_resize_playbooks import pick_resize_connector

    resource_id = f"/subscriptions/{SUB}/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm"
    book = resolve_playbook(cloud_provider="azure", resource_type="Microsoft.Compute/virtualMachines")
    catalog = [
        Connector(
            id="azure-tags",
            tenant_id=TENANT,
            provider="azure",
            scope_id=SUB,
            kind="azure_arm",
            operations=["resource.inspect", "tags.merge"],
            endpoint=None,
            token_env=None,
        ),
        Connector(
            id="azure-compute",
            tenant_id=TENANT,
            provider="azure",
            scope_id=SUB,
            kind="azure_arm",
            operations=["resource.inspect", "compute.resize"],
            endpoint=None,
            token_env=None,
        ),
    ]
    picked = pick_resize_connector(catalog, TENANT, book, resource_id)
    assert picked.id == "azure-compute"
