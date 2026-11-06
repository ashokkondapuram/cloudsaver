from datetime import datetime, timedelta, timezone

from app.resource_timestamps import (
    STALE_ANALYSIS_MINUTES,
    analysis_is_stale,
    observation_row_fields,
    touch_last_analyzed,
)


def test_analysis_is_stale_when_missing():
    assert analysis_is_stale({}) is True
    assert analysis_is_stale(None) is True


def test_analysis_is_stale_within_window():
    now = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)
    evidence = {}
    touch_last_analyzed(evidence, now=now - timedelta(minutes=STALE_ANALYSIS_MINUTES))
    assert analysis_is_stale(evidence, now=now) is False


def test_analysis_is_stale_after_window():
    now = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)
    evidence = {}
    touch_last_analyzed(evidence, now=now - timedelta(minutes=STALE_ANALYSIS_MINUTES + 1))
    assert analysis_is_stale(evidence, now=now) is True


def test_observation_row_fields():
    obs = {'evidence': {'last_analyzed_at': '2026-11-05T10:00:00Z', 'azure_status_fetched_at': '2026-11-05T10:05:00Z'}}
    fields = observation_row_fields(obs)
    assert fields['last_analyzed_at'] == '2026-11-05T10:00:00Z'
    assert fields['azure_status_fetched_at'] == '2026-11-05T10:05:00Z'
    assert fields['analysis_stale'] is True
