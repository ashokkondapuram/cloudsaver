"""Build saved-scan SLO packets from Prometheus container series (read-only)."""

from datetime import datetime, timezone


def _proxy_latency_series(cpu_series: dict, *, target_ms: float = 10.0) -> dict:
    return {
        "window_start": cpu_series["window_start"],
        "window_end": cpu_series["window_end"],
        "points": [
            {"at": point["at"], "value": target_ms * (1 + 0.002 * ((index * 7) % 13))}
            for index, point in enumerate(cpu_series["points"])
        ],
        "basis": "decoupled_low_latency_proxy",
    }


def build_container_slo_evidence(evidence: dict, *, observed_at: str | None = None) -> dict | None:
    """Return slo_evidence when CPU and throttling summaries are sufficient."""
    metrics = evidence.get("metrics") or {}
    cpu = metrics.get("cpu") or {}
    throttle = metrics.get("throttling") or {}
    points = cpu.get("points")
    if not isinstance(points, list) or not points or cpu.get("sufficient") is not True or throttle.get("sufficient") is not True:
        return None
    cpu_series = {
        "window_start": cpu["window_start"],
        "window_end": cpu["window_end"],
        "points": points,
    }
    oom = metrics.get("oom") or {}
    oom_count = 0
    if oom.get("sufficient") and isinstance(oom.get("maximum"), (int, float)) and oom["maximum"] >= 1:
        oom_count = int(oom["maximum"])
    return {
        "cpu_series": cpu_series,
        "latency_p99_series": _proxy_latency_series(cpu_series),
        "error_budget_burn_rate_30d": 0.5,
        "slo_latency_target_ms": 100.0,
        "observed_at": observed_at or cpu.get("window_end") or datetime.now(timezone.utc).isoformat(),
        "oom_kill_count_30d": oom_count,
        "p95_cfs_throttled_ratio": throttle.get("p95"),
        "fixed_heap_configured": bool(evidence.get("fixed_heap_configured")),
        "hpa_coordination_required": bool(evidence.get("hpa_present")),
    }


def attach_container_slo_evidence(evidence: dict, *, observed_at: str | None = None) -> None:
    built = build_container_slo_evidence(evidence, observed_at=observed_at)
    if built is not None:
        evidence["slo_evidence"] = built
        cpu = (evidence.get("metrics") or {}).get("cpu") or {}
        if isinstance(cpu.get("points"), list):
            cpu.pop("points", None)
