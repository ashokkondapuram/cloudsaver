"""Tests for Turbonomic-style primary rule match resolution."""
from app.rule_match_strategy import match_confidence, resolve_resource_matches


def _eval(resource_id, rule_id, **extra):
    return dict(
        resource_id=resource_id,
        rule_id=rule_id,
        outcome="condition_detected",
        automatic_execution=False,
        **extra,
    )


def test_stopped_vm_wins_over_rightsize_when_both_detected():
    resource = dict(
        resource_id="/subscriptions/s/resourceGroups/r/providers/Microsoft.Compute/virtualMachines/vm1",
        resource_type="Microsoft.Compute/virtualMachines",
        cloud_provider="azure",
        evidence={},
    )
    evaluations = [
        _eval(resource["resource_id"], "AZURE_VM_STOPPED_RESIDUAL_COST"),
        _eval(resource["resource_id"], "AZURE_VM_RIGHTSIZING_UTILIZATION"),
    ]
    result = resolve_resource_matches(resource, evaluations)
    assert result["primary_match"]["rule_id"] == "AZURE_VM_STOPPED_RESIDUAL_COST"
    assert len(result["alternate_matches"]) == 1
    assert result["alternate_matches"][0]["rule_id"] == "AZURE_VM_RIGHTSIZING_UTILIZATION"


def test_unattached_disk_wins_over_performance_tuning():
    resource = dict(
        resource_id="/subscriptions/s/resourceGroups/r/providers/Microsoft.Compute/disks/d1",
        resource_type="Microsoft.Compute/disks",
        cloud_provider="azure",
        evidence={},
    )
    evaluations = [
        _eval(resource["resource_id"], "AZURE_DISK_PROVISIONED_PERFORMANCE"),
        _eval(resource["resource_id"], "AZURE_DISK_UNATTACHED_RETENTION"),
    ]
    result = resolve_resource_matches(resource, evaluations)
    assert result["primary_match"]["rule_id"] == "AZURE_DISK_UNATTACHED_RETENTION"


def test_finops_resize_primary_when_only_rightsizing_fires():
    resource = dict(
        resource_id="i-abc",
        resource_type="aws:ec2:instance",
        cloud_provider="aws",
        evidence={},
    )
    evaluations = [_eval("i-abc", "AWS_EC2_GRAVITON_AND_SLO_RIGHTSIZING")]
    result = resolve_resource_matches(resource, evaluations)
    assert result["primary_match"]["display_channel"] == "finops_autopilot_resize"
    assert result["primary_match"]["action_class"] == "resize"
    assert match_confidence(evaluations[0]) == "high"


def test_safety_blocks_lower_confidence_not_blocked_outcome():
    resource = dict(resource_id="i-1", resource_type="aws:ec2:instance", cloud_provider="aws", evidence={})
    row = _eval("i-1", "AWS_EC2_GRAVITON_AND_SLO_RIGHTSIZING", safety_blocks=["SLO_ERROR_BUDGET_RISK"])
    assert match_confidence(row) == "medium"
