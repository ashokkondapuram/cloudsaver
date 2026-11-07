from datetime import datetime, timedelta, timezone

from app.kubernetes_latency_evidence import (
    OBSERVABILITY_LATENCY_BASIS,
    latency_series_from_metric,
    resolve_latency_p99_series,
    validate_latency_query,
)

NOW = datetime.now(timezone.utc).replace(second=0, microsecond=0)


def _cpu():
    start = NOW - timedelta(days=30)
    points = [{"at": (start + timedelta(minutes=5 * (i + 1))).isoformat(), "value": 0.2 * (1 + 0.01 * (i % 7))} for i in range(8640)]
    return {"window_start": start.isoformat(), "window_end": NOW.isoformat(), "points": points}


def test_validate_latency_query_rejects_multiline():
    try:
        validate_latency_query("histogram_quantile(0.99,\nrate(x[5m]))")
    except ValueError as err:
        assert "single-line" in str(err)
    else:
        raise AssertionError("expected ValueError")


def test_resolve_uses_observability_latency_when_sufficient():
    cpu = _cpu()
    lat_points = [{"at": p["at"], "value": 12.5} for p in cpu["points"]]
    evidence = {
        "metrics": {
            "latency": {
                "sufficient": True,
                "window_start": cpu["window_start"],
                "window_end": cpu["window_end"],
                "points": lat_points,
                "basis": OBSERVABILITY_LATENCY_BASIS,
                "unit": "milliseconds",
            }
        }
    }
    series = resolve_latency_p99_series(cpu, evidence)
    assert series["basis"] == OBSERVABILITY_LATENCY_BASIS
    assert len(series["points"]) == len(cpu["points"])


def test_latency_series_from_metric_rejects_mismatched_window():
    cpu = _cpu()
    latency = {
        "sufficient": True,
        "window_start": cpu["window_start"],
        "window_end": (NOW - timedelta(days=1)).isoformat(),
        "points": [{"at": cpu["points"][0]["at"], "value": 1.0}],
    }
    assert latency_series_from_metric(latency, cpu) is None
