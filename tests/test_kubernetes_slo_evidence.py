from datetime import datetime, timedelta, timezone

from app.causal_topology_simulator import evaluate_slo_bounded_rightsizing
from app.kubernetes_slo_evidence import attach_container_slo_evidence

NOW = datetime.now(timezone.utc).replace(second=0, microsecond=0)


def _points(value, n=8640):
    start = NOW - timedelta(days=30)
    return [{"at": (start + timedelta(minutes=5 * (i + 1))).isoformat(), "value": value * (1 + 0.01 * (i % 7))} for i in range(n)]


def test_attach_slo_when_cpu_and_throttling_are_sufficient():
    evidence = {
        "metrics": {
            "cpu": {
                "sufficient": True,
                "p95": 0.2,
                "window_start": (NOW - timedelta(days=30)).isoformat(),
                "window_end": NOW.isoformat(),
                "points": _points(0.2),
            },
            "throttling": {"sufficient": True, "p95": 0.001},
            "oom": {"sufficient": True, "maximum": 0.0},
        },
        "fixed_heap_configured": False,
        "hpa_present": False,
    }
    attach_container_slo_evidence(evidence, observed_at=NOW.isoformat())
    assert "slo_evidence" in evidence
    assert "points" not in evidence["metrics"]["cpu"]
    gate = evaluate_slo_bounded_rightsizing(evidence["slo_evidence"], now=NOW)
    assert gate["status"] == "review_eligible"


def test_attach_skips_incomplete_telemetry():
    evidence = {"metrics": {"cpu": {"sufficient": False}, "throttling": {"sufficient": True, "p95": 0.001}}}
    attach_container_slo_evidence(evidence, observed_at=NOW.isoformat())
    assert "slo_evidence" not in evidence
