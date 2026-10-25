"""DCGM-style GPU metric contract validation (v2 scaffold; no live collection)."""

REQUIRED_FIELDS = frozenset({"gpu_utilization", "memory_used_mb", "memory_total_mb"})


def validate_dcgm_sample(sample: dict) -> dict:
    if not isinstance(sample, dict):
        raise ValueError("GPU sample must be a mapping")
    missing = REQUIRED_FIELDS - sample.keys()
    if missing:
        raise ValueError(f"Missing GPU fields: {', '.join(sorted(missing))}")
    util = float(sample["gpu_utilization"])
    if not 0 <= util <= 100:
        raise ValueError("gpu_utilization must be between 0 and 100")
    return {"valid": True, "idle": util < 5.0, "utilization": util}


def idle_gpu_candidates(samples: list[dict], min_idle_hours: float = 24.0) -> list[dict]:
    """Heuristic: sustained low utilization over the supplied hourly samples."""
    if min_idle_hours <= 0:
        raise ValueError("min_idle_hours must be positive")
    out = []
    for sample in samples:
        checked = validate_dcgm_sample(sample)
        if checked["idle"]:
            out.append({**sample, "recommendation": "review_hibernation"})
    return out
