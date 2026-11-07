from app.collectors.grafana_k8s_policy import (
    cpu_overrequest_detected, cpu_safety_blocks, memory_overrequest_detected, memory_safety_blocks,
)


def test_cpu_safety_blocks():
    assert 'CPU_THROTTLING_ABOVE_2_PERCENT' in cpu_safety_blocks(throttle_p95=0.05, hpa_managed=False)
    assert 'COORDINATED_HPA_REVIEW_REQUIRED' in cpu_safety_blocks(throttle_p95=0, hpa_managed=True)


def test_memory_safety_blocks():
    assert 'OOMKILL_OBSERVED' in memory_safety_blocks(oom_observed=True, restart_spread=False)


def test_overrequest_parity_with_scan_rules():
    assert cpu_overrequest_detected(0.5, 0.1)
    assert not cpu_overrequest_detected(0.2, 0.1)
    assert memory_overrequest_detected(1 * 1024**3, 0.4 * 1024**3)
