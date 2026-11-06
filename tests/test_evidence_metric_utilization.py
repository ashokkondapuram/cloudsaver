from datetime import datetime, timezone

from app.evidence_metric_utilization import apply_metrics_to_evidence_fields, metric_has_sufficient, metric_stat, metric_window


def test_metric_window_from_summary():
    evidence = {
        'metric_summaries': {
            'requests': dict(sufficient=True, p95=2.0, p99=3.0, maximum=5.0, coverage_ratio=0.96),
        },
    }
    window = metric_window(evidence, 'requests')
    assert window['p95'] == 2.0
    assert metric_stat(evidence, 'requests', 'maximum') == 5.0
    assert metric_has_sufficient(evidence, 'requests') is True


def test_apply_metrics_sets_ru_and_dependencies():
    evidence = dict(
        manual_throughput=True,
        backend_pool_count=2,
        metric_summaries=dict(
            normalized_ru_consumption=dict(sufficient=True, p95=12.0, maximum=40.0),
            healthy_targets=dict(sufficient=True, maximum=0.0),
        ),
    )
    apply_metrics_to_evidence_fields(evidence)
    assert evidence['ru_average_percent'] == 12.0
    assert evidence['dependencies_verified'] is False
    assert evidence['metric_rollups']['healthy_targets']['maximum'] == 0.0


def test_project_configuration_load_balancer():
    from app.evidence_autofill import project_configuration_properties

    resource = dict(
        resource_type='Microsoft.Network/loadBalancers',
        evidence={},
    )
    project_configuration_properties(resource, dict(backendAddressPools=[{}, {}]))
    assert resource['evidence']['backend_pool_count'] == 2
    assert resource['evidence']['dependencies_verified'] is True
