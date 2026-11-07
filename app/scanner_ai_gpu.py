"""DCGM-style GPU metric contract validation (v2; no zero-fill on missing samples)."""

REQUIRED_FIELDS = frozenset({"gpu_utilization", "memory_used_mb", "memory_total_mb"})
OPTIONAL_FIELDS = frozenset({"tensor_core_active_pct", "sm_occupancy_pct", "nvlink_bandwidth_gbps", "thermal_throttle"})


def validate_dcgm_sample(sample: dict) -> dict:
    if sample is None:
        raise ValueError("Missing GPU sample must not be zero-filled")
    if not isinstance(sample, dict):
        raise ValueError("GPU sample must be a mapping")
    missing = REQUIRED_FIELDS - sample.keys()
    if missing:
        raise ValueError(f"Missing GPU fields: {', '.join(sorted(missing))}")
    util = float(sample["gpu_utilization"])
    if not 0 <= util <= 100:
        raise ValueError("gpu_utilization must be between 0 and 100")
    extras = {k: sample[k] for k in OPTIONAL_FIELDS if k in sample}
    return {"valid": True, "idle": util < 5.0, "utilization": util, **extras}


def mig_partition_advisory(*, peak_vram_gb: str, slo_latency_p99_ms: str) -> dict:
    peak = float(peak_vram_gb)
    p99 = float(slo_latency_p99_ms)
    if peak <= 0 or p99 <= 0:
        raise ValueError("peak_vram_gb and slo_latency_p99_ms must be positive")
    eligible = peak <= 40 and p99 <= 200
    return dict(mig_partition_recommended=eligible, advisory_only=True, purchase_authorized=False)


def idle_gpu_candidates(samples: list[dict], min_idle_hours: float = 24.0) -> list[dict]:
    """Heuristic: sustained low utilization over trailing hourly samples."""
    import math

    if min_idle_hours <= 0:
        raise ValueError("min_idle_hours must be positive")
    required = max(1, math.ceil(min_idle_hours))
    streak = 0
    for sample in reversed(samples):
        if validate_dcgm_sample(sample)["idle"]:
            streak += 1
        else:
            break
    if streak < required:
        return []
    out = []
    for sample in reversed(samples):
        if not validate_dcgm_sample(sample)["idle"]:
            break
        out.append({**sample, "recommendation": "review_hibernation", "idle_hours_observed": streak})
        if len(out) >= streak:
            break
    out.reverse()
    return out
