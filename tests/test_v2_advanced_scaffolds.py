from app.ai_workload_optimizer import routing_savings_usd
from app.autopilot_commitments import commitment_ladder
from app.collectors.event_stream import (
    EventStreamConsumer,
    InMemoryEventBuffer,
    drain_buffer_to_drift_outbox,
    drift_ingest_bridge_enabled,
)
from app.drift.outbox_store import PlatformOutboxStore
from app.k8s_karpenter_sync import draft_node_pool
from app.scanner_ai_gpu import idle_gpu_candidates, validate_dcgm_sample
from tests.test_drift_event_pipeline import AWS_EVENT, TENANT
from tests.test_platform_outbox_lease import _store


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
    assert idle_gpu_candidates(samples, min_idle_hours=1) == []
    assert len(idle_gpu_candidates([samples[0]], min_idle_hours=1)) == 1


def test_idle_gpu_candidates_honors_min_idle_hours():
    idle = {"gpu_utilization": 1.0, "memory_used_mb": 1, "memory_total_mb": 10}
    assert idle_gpu_candidates([idle] * 23, min_idle_hours=24) == []
    assert len(idle_gpu_candidates([idle] * 24, min_idle_hours=24)) == 24


def test_commitment_ladder_applies_step_percent():
    steps = commitment_ladder("10.0000", "2.0000", "1.0000")
    assert steps[0]["recommended_new_commitment_hr"] == "1.7500"
    assert steps[1]["recommended_new_commitment_hr"] == "3.5000"
    assert steps[2]["recommended_new_commitment_hr"] == "5.2500"


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


def test_draft_node_pool_rejects_invalid_consolidation():
    try:
        draft_node_pool("batch", ["m6i.large"], "10", consolidation="Always")
    except ValueError as error:
        assert "consolidation" in str(error)
    else:
        raise AssertionError("expected ValueError")


def test_draft_node_pool_rejects_non_positive_cpu_limit():
    try:
        draft_node_pool("batch", ["m6i.large"], "0")
    except ValueError as error:
        assert "cpu_limit" in str(error)
    else:
        raise AssertionError("expected ValueError")


def test_idle_gpu_candidates_tracks_per_gpu_id():
    idle = {"gpu_utilization": 1.0, "memory_used_mb": 1, "memory_total_mb": 10, "gpu_id": "0"}
    busy = {**idle, "gpu_utilization": 50.0, "gpu_id": "1"}
    mixed = [idle, busy, idle]
    assert len(idle_gpu_candidates(mixed, min_idle_hours=2)) == 2
    interleaved = [
        {"gpu_utilization": 1.0, "memory_used_mb": 1, "memory_total_mb": 10},
        {"gpu_utilization": 50.0, "memory_used_mb": 1, "memory_total_mb": 10},
        {"gpu_utilization": 1.0, "memory_used_mb": 1, "memory_total_mb": 10},
    ]
    assert idle_gpu_candidates(interleaved, min_idle_hours=2) == []


def test_drain_buffer_to_outbox_requires_env(monkeypatch, tmp_path):
    monkeypatch.delenv("CLOUDSAVER_DRIFT_INGEST", raising=False)
    buffer = InMemoryEventBuffer()
    consumer = EventStreamConsumer(resolve_workspace=lambda _p, _a: TENANT)
    outbox = PlatformOutboxStore(_store(tmp_path))
    try:
        drain_buffer_to_drift_outbox(buffer, consumer=consumer, outbox=outbox)
    except ValueError as error:
        assert "CLOUDSAVER_DRIFT_INGEST" in str(error)
    else:
        raise AssertionError("expected ValueError")


def test_drain_buffer_to_outbox_enqueues_when_enabled(monkeypatch, tmp_path):
    monkeypatch.setenv("CLOUDSAVER_DRIFT_INGEST", "true")
    assert drift_ingest_bridge_enabled()
    consumer = EventStreamConsumer(resolve_workspace=lambda _p, acct: TENANT if acct == "123456789012" else None)
    parsed = consumer.parse_eventbridge(AWS_EVENT)
    buffer = InMemoryEventBuffer()
    buffer.push(parsed)
    outbox = PlatformOutboxStore(_store(tmp_path))
    result = drain_buffer_to_drift_outbox(buffer, consumer=consumer, outbox=outbox)
    assert result["accepted"] == 1
    assert len(buffer) == 0
    assert result["intents"][0][1] == "pending"


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
