"""Per-resource fetch stage status for scans and resource detail APIs."""
from __future__ import annotations

STAGES = ('costs', 'activity_log', 'retail', 'analysis', 'recommendations')
Terminal = frozenset({'completed', 'failed', 'skipped', 'pending', 'running'})


def init_fetch_stages(evidence: dict) -> dict:
    stages = dict.fromkeys(STAGES, 'pending')
    evidence['fetch_stages'] = stages
    return stages


def set_stage(evidence: dict, stage: str, status: str) -> None:
    if stage not in STAGES or status not in Terminal:
        raise ValueError('Invalid fetch stage transition')
    evidence.setdefault('fetch_stages', dict.fromkeys(STAGES, 'pending'))[stage] = status


def sync_fetch_stages(evidence: dict, *, findings: list[dict] | None = None) -> dict:
    """Derive stage completion from collected evidence and priced findings."""
    stages = evidence.setdefault('fetch_stages', dict.fromkeys(STAGES, 'pending'))
    live = evidence.get('live_sources') or {}
    if evidence.get('billed_cost_usd') is not None or evidence.get('effective_cost_usd') is not None:
        stages['costs'] = 'completed'
    elif stages['costs'] == 'pending':
        stages['costs'] = 'pending'

    if live.get('activity_log') == 'collected' or isinstance(evidence.get('state_history'), list):
        stages['activity_log'] = 'completed'
    elif live.get('activity_log') == 'unavailable_or_incomplete':
        stages['activity_log'] = 'failed'
    elif live.get('telemetry') == 'resource_budget_exceeded':
        stages['activity_log'] = 'skipped'

    retail = False
    for row in findings or []:
        if row.get('retail_estimate_usd') is not None or (row.get('evidence') or {}).get('pricing_evidence'):
            retail = True
            break
    if retail or (evidence.get('pricing_evidence')):
        stages['retail'] = 'completed'
    elif stages['retail'] == 'pending':
        stages['retail'] = 'pending'

    if evidence.get('analysis_readiness'):
        stages['analysis'] = 'completed'

    if findings is not None:
        stages['recommendations'] = 'completed' if findings else 'completed'

    return stages


def any_pending(stages: dict | None) -> bool:
    if not stages:
        return False
    return any(stages.get(key) in ('pending', 'running') for key in STAGES)
