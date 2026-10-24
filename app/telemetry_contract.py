"""Explainable validation of source aggregates. Missing samples are never zero-filled."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math
from typing import Literal


def moment(value):
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00')) if isinstance(value, str) else value
        return parsed.astimezone(timezone.utc) if isinstance(parsed, datetime) and parsed.tzinfo else None
    except (ValueError, TypeError, OverflowError):
        return None


@dataclass(frozen=True)
class TimeSeriesEvidenceContract:
    metric_name: str
    aggregation: Literal['P95', 'P99', 'MAX', 'SUM'] = 'P95'
    interval_minutes: int = 5
    window_days: int = 30
    min_resource_age_days: int = 30
    min_coverage_ratio: float = .95
    max_gap_minutes: int = 60

    def __post_init__(self):
        if (self.aggregation not in ('P95', 'P99', 'MAX', 'SUM') or self.interval_minutes != 5
                or self.window_days != 30 or not .95 <= self.min_coverage_ratio <= 1
                or not 5 <= self.max_gap_minutes <= 60 or self.min_resource_age_days < 30):
            raise ValueError('Unsupported telemetry contract')


@dataclass(frozen=True)
class TimeSeriesEvaluationResult:
    contract: TimeSeriesEvidenceContract
    expected_samples: int
    valid_samples: int
    max_observed_gap_minutes: float | None
    window_start: datetime | None
    window_end: datetime | None
    observed_value: float | None
    is_sufficient: bool
    gap_reason: str | None
    coverage_ratio: float


def evaluate_series(values, contract, *, now=None, resource_created_at=None, require_resource_age=True):
    now = now or datetime.now(timezone.utc)
    expected = contract.window_days * 1440 // contract.interval_minutes
    start = end = gap = None
    parsed = {}

    def result(reason=None, observed=None):
        return TimeSeriesEvaluationResult(contract, expected, len(parsed), gap, start, end,
                                          observed, reason is None, reason, len(parsed) / expected)

    if not isinstance(values, dict):
        return result('metric_unavailable')
    start, end = moment(values.get('window_start')), moment(values.get('window_end'))
    if not start or not end or end - start != timedelta(days=contract.window_days):
        return result('invalid_observation_window')
    if not 0 <= (now - end).total_seconds() < 86400:
        return result('stale_or_future_window')
    created = moment(resource_created_at)
    if require_resource_age and (not created or created > start or now - created < timedelta(days=contract.min_resource_age_days)):
        return result('resource_age_unverified_or_too_short')
    points = values.get('points')
    if not isinstance(points, list) or len(points) > expected:
        return result('invalid_sample_count')
    for point in points:
        if not isinstance(point, dict):
            return result('invalid_sample')
        at, value = moment(point.get('at')), point.get('value')
        if (not at or not start < at <= end or (at - start).total_seconds() % (contract.interval_minutes * 60)
                or at in parsed or type(value) not in (int, float) or not math.isfinite(value) or value < 0):
            return result('invalid_duplicate_or_unaligned_sample')
        parsed[at] = value
    times = [start, *sorted(parsed), end]
    gap = max((b - a).total_seconds() / 60 for a, b in zip(times, times[1:]))
    if len(parsed) < math.ceil(expected * contract.min_coverage_ratio):
        return result('insufficient_sample_coverage')
    if gap > contract.max_gap_minutes:
        return result('unexplained_telemetry_gap')
    ordered = sorted(parsed.values())
    observed = {'P95': lambda: ordered[math.ceil(len(ordered) * .95) - 1],
                'P99': lambda: ordered[math.ceil(len(ordered) * .99) - 1],
                'MAX': lambda: ordered[-1], 'SUM': lambda: sum(ordered)}[contract.aggregation]()
    return result(observed=observed) if math.isfinite(observed) else result('aggregate_out_of_range')
