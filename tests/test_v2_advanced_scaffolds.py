from app.ai_workload_optimizer import routing_savings_usd
from app.autopilot_commitments import commitment_ladder
from app.k8s_karpenter_sync import draft_node_pool
from app.scanner_ai_gpu import idle_gpu_candidates, validate_dcgm_sample


def test_validate_dcgm_sample_accepts_idle_gpu():
    result = validate_dcgm_sample(
        {"gpu_utilization": 2.0, "memory_used_mb": 100, "memory_total_mb": 16000}
    )
    assert result["idle"] is True


def test_validate_dcgm_sample_rejects_invalid_utilization():
    try:
        validate_dcgm_sample(
            {"gpu_utilization": 120, "memory_used_mb": 1, "memory_total_mb": 2}
        )
    except ValueError as error:
        assert "gpu_utilization" in str(error)
    else:
        raise AssertionError("expected ValueError")


def test_idle_gpu_candidates_filters_active_gpus():
    samples = [
        {"gpu_utilization": 1.0, "memory_used_mb": 1, "memory_total_mb": 10},
        {"gpu_utilization": 40.0, "memory_used_mb": 1, "memory_total_mb": 10},
    ]
    assert len(idle_gpu_candidates(samples)) == 1


def test_commitment_ladder_never_authorizes_purchase():
    steps = commitment_ladder("10.0000", "2.0000", "1.0000")
    assert len(steps) == 3
    assert all(step["purchase_authorized"] is False for step in steps)


def test_draft_node_pool_requires_instance_types():
    manifest = draft_node_pool("batch", ["m6i.large"], "100")
    assert manifest["kind"] == "NodePool"
    assert manifest["spec"]["template"]["spec"]["limits"]["cpu"] == "100"


def test_draft_node_pool_rejects_empty_name():
    try:
        draft_node_pool("", ["m6i.large"], "10")
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_routing_savings_is_nonnegative():
    result = routing_savings_usd(1000, "3.00", "0.50", "0.5")
    assert float(result["estimated_savings_usd"]) >= 0
    assert result["advisory_only"] is True


def test_routing_savings_rejects_invalid_fraction():
    try:
        routing_savings_usd(10, "1", "1", "1.5")
    except ValueError:
        return
    raise AssertionError("expected ValueError")
