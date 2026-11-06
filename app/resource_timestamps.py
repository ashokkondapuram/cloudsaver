"""Per-resource analysis and Azure fetch timestamps."""
from __future__ import annotations

import os
from datetime import datetime, timezone

from app.assessment_policy import timestamp

STALE_ANALYSIS_MINUTES = int(os.getenv('CLOUDSAVER_RESOURCE_ANALYSIS_STALE_MINUTES', '30'))


def _iso(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    return now.isoformat().replace('+00:00', 'Z')


def touch_last_analyzed(evidence: dict, *, now: datetime | None = None) -> None:
    evidence['last_analyzed_at'] = _iso(now)


def touch_azure_status_fetched(evidence: dict, *, now: datetime | None = None) -> None:
    evidence['azure_status_fetched_at'] = _iso(now)


def last_analyzed_at(evidence: dict | None) -> datetime | None:
    if not evidence:
        return None
    return timestamp(evidence.get('last_analyzed_at'))


def azure_status_fetched_at(evidence: dict | None) -> datetime | None:
    if not evidence:
        return None
    return timestamp(evidence.get('azure_status_fetched_at'))


def analysis_is_stale(evidence: dict | None, *, now: datetime | None = None) -> bool:
    """True when analysis is missing or older than the configured window."""
    now = timestamp(now) or datetime.now(timezone.utc)
    analyzed = last_analyzed_at(evidence or {})
    if analyzed is None:
        return True
    age_minutes = (now - analyzed).total_seconds() / 60
    return age_minutes > STALE_ANALYSIS_MINUTES


def evidence_needs_refresh(evidence: dict | None) -> bool:
    """True when analysis is stale or registry/readiness still owes collection."""
    ev = evidence or {}
    if analysis_is_stale(ev):
        return True
    readiness = ev.get('analysis_readiness') or {}
    if readiness.get('configuration') != 'complete':
        return True
    if readiness.get('telemetry_pending_rule_ids'):
        return True
    registry = ev.get('type_registry') or {}
    if registry.get('evidence_fields_pending'):
        return True
    live = (ev.get('live_sources') or {}).get('telemetry')
    if live == 'resource_budget_exceeded':
        return True
    return False


def observation_row_fields(observation: dict | None) -> dict:
    """List/detail projection for per-resource freshness."""
    ev = (observation or {}).get('evidence') or {}
    stages = ev.get('fetch_stages') or {}
    refresh_in_progress = stages.get('analysis') == 'running'
    stale = evidence_needs_refresh(ev) and not refresh_in_progress
    return {
        'last_analyzed_at': ev.get('last_analyzed_at'),
        'azure_status_fetched_at': ev.get('azure_status_fetched_at'),
        'analysis_stale': stale,
        'refresh_in_progress': refresh_in_progress,
        'evidence_incomplete': stale,
    }
