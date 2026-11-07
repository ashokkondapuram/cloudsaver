from datetime import datetime, timedelta, timezone

import pytest

from app.collectors.grafana_telemetry import GrafanaSeriesError, coverage_ratio, series_from_frames, validate_query_payload


def test_duplicate_samples_do_not_inflate_coverage():
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    start = now - timedelta(days=7)
    dup_at = (start + timedelta(minutes=5)).isoformat()
    points = [{'at': dup_at, 'value': 0.1}, {'at': dup_at, 'value': 0.2}]
    ratio, gap = coverage_ratio(points, window_start=start, window_end=now, window_days=7, now=now)
    assert gap == 'DUPLICATE_OR_INVALID_SAMPLE'


def test_query_error_in_http_200_payload():
    with pytest.raises(GrafanaSeriesError) as error:
        validate_query_payload(dict(results=dict(A=dict(error='boom', frames=[]))))
    assert error.value.code == 'GRAFANA_QUERY_FAILED'


def test_series_preserves_cluster_in_key():
    payload = dict(
        results=dict(
            A=dict(
                frames=[
                    dict(
                        schema=dict(fields=[{}, dict(name='Value', labels=dict(cluster='c1', namespace='ns', pod='p', container='app'))]),
                        data=dict(values=[[1_700_000_000_000], [0.2]]),
                    )
                ]
            )
        )
    )
    series = series_from_frames(payload, cluster='c1', cluster_label='cluster')
    assert ('c1', 'ns', 'p', 'app') in series
