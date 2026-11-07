"""Build saved-scan SLO packets from Prometheus container series (read-only)."""

from datetime import datetime, timezone

from app.kubernetes_latency_evidence import PROXY_BASIS, proxy_latency_series, resolve_latency_p99_series

# Backward-compatible alias for tests and docs that reference the private helper.
_proxy_latency_series = proxy_latency_series


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
    slo_target = evidence.get("slo_latency_target_ms")
    if not isinstance(slo_target, (int, float)) or slo_target <= 0:
        slo_target = 100.0
    latency_series = resolve_latency_p99_series(cpu_series, evidence, slo_target_ms=float(slo_target))
    burn = None
    for key in ("error_budget_burn_rate_30d", "slo_burn_rate"):
        value = evidence.get(key)
        if isinstance(value, (int, float)) and value >= 0:
            burn = float(value)
            break
    return {
        "cpu_series": cpu_series,
        "latency_p99_series": latency_series,
        "error_budget_burn_rate_30d": burn,
        "slo_latency_target_ms": float(slo_target),
        "observed_at": observed_at or cpu.get("window_end") or datetime.now(timezone.utc).isoformat(),
        "oom_kill_count_30d": oom_count,
        "p95_cfs_throttled_ratio": throttle.get("p95"),
        "fixed_heap_configured": bool(evidence.get("fixed_heap_configured")),
        "hpa_coordination_required": bool(evidence.get("hpa_present")),
    }


def attach_container_slo_evidence(evidence: dict, *, observed_at: str | None = None) -> None:
    built = build_container_slo_evidence(evidence, observed_at=observed_at)
    if built is not None:
        basis = built.get("latency_p99_series", {}).get("basis", PROXY_BASIS)
        evidence["latency_basis"] = basis
        evidence["slo_evidence"] = built
        cpu = (evidence.get("metrics") or {}).get("cpu") or {}
        if isinstance(cpu.get("points"), list):
            cpu.pop("points", None)
        latency = (evidence.get("metrics") or {}).get("latency") or {}
        if isinstance(latency.get("points"), list):
            latency.pop("points", None)
