"""Safety gates aligned with scan-based Kubernetes CPU/memory rules (advisory)."""
from __future__ import annotations

CPU_MIN_EXCESS_CORES = 0.1
MEMORY_MIN_EXCESS_BYTES = 256 * 1024**2
CPU_HEADROOM = 1.5
MEMORY_HEADROOM = 1.35
THROTTLE_P95_LIMIT = 0.02
COVERAGE_MIN = 0.90


def cpu_safety_blocks(*, throttle_p95: float | None, hpa_managed: bool | None) -> list[str]:
    blocks = []
    if throttle_p95 is not None and throttle_p95 > THROTTLE_P95_LIMIT:
        blocks.append('CPU_THROTTLING_ABOVE_2_PERCENT')
    if hpa_managed is None:
        blocks.append('HPA_STATUS_NOT_OBSERVED')
    elif hpa_managed:
        blocks.append('COORDINATED_HPA_REVIEW_REQUIRED')
    return blocks


def memory_safety_blocks(*, oom_observed: bool, restart_spread: bool) -> list[str]:
    blocks = []
    if oom_observed:
        blocks.append('OOMKILL_OBSERVED')
    elif restart_spread:
        blocks.append('RESTART_HISTORY_REQUIRES_OOM_VERIFICATION')
    return blocks


def coverage_blocks(coverage_ratio: float | None) -> list[str]:
    if coverage_ratio is not None and coverage_ratio < COVERAGE_MIN:
        return ['INSUFFICIENT_TELEMETRY_COVERAGE']
    return []


def scan_aligned_cpu_target(p95: float | None) -> float | None:
    if p95 is None:
        return None
    return p95 * CPU_HEADROOM


def scan_aligned_memory_target(p99: float | None) -> float | None:
    if p99 is None:
        return None
    return p99 * MEMORY_HEADROOM


def cpu_overrequest_detected(current: float | None, p95: float | None) -> bool:
    if current is None or p95 is None or current <= 0:
        return False
    target = scan_aligned_cpu_target(p95)
    if target is None:
        return False
    return current > target and current - target > CPU_MIN_EXCESS_CORES


def memory_overrequest_detected(current: float | None, p99: float | None) -> bool:
    if current is None or p99 is None or current <= 0:
        return False
    target = scan_aligned_memory_target(p99)
    if target is None:
        return False
    return current > target and current - target > MEMORY_MIN_EXCESS_BYTES
