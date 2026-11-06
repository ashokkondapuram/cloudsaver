from datetime import datetime, timedelta, timezone

from app.collectors.live_common import metrics_utilization_complete, monitor_series, summary
from app.telemetry_contract import TimeSeriesEvidenceContract, evaluate_series

NOW = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)


def test_monitor_series_snaps_azure_timestamps():
    start = NOW - timedelta(days=30)
    points = [
        (start + timedelta(minutes=7), 12.0),
        (start + timedelta(minutes=7, seconds=30), 99.0),
        (start + timedelta(minutes=12), 4.0),
    ]
    built = monitor_series(points, NOW)
    assert built is not None
    assert len(built['points']) == 2
    result = evaluate_series(
        built,
        TimeSeriesEvidenceContract('cpu_percent'),
        now=NOW,
        require_resource_age=False,
    )
    assert result.valid_samples == 2
    assert result.gap_reason in ('insufficient_sample_coverage', 'unexplained_telemetry_gap', None)


def test_metrics_utilization_complete_uses_summary():
    start = NOW - timedelta(days=30)
    series = dict(
        window_start=start.isoformat(),
        window_end=NOW.isoformat(),
        points=[{'at': (start + timedelta(minutes=5 * i)).isoformat(), 'value': 3.0} for i in range(1, 8641)],
    )
    evidence = {
        'metrics': {'cpu_percent': series},
        'metric_summaries': {'cpu_percent': summary(series, 'cpu_percent', NOW)},
    }
    assert metrics_utilization_complete(evidence, ('cpu_percent',), now=NOW) is True
