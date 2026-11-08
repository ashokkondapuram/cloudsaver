"""Attach deterministic pillar analysis to completed scan payloads (ingestion → analysis decoupling)."""
from __future__ import annotations

from app.analysis_service.loader import contexts_from_scan
from app.analysis_service.service import AnalysisService

ENGINE_VERSION = '1.0.0'


def run_pillar_analysis(scan: dict) -> dict:
    """Return serializable pillar analysis block; never performs cloud HTTP."""
    inventory = scan.get('inventory') or []
    if not inventory:
        # No inventory means nothing was assessed: an empty account_pillar_scores (not a numeric
        # 100 per pillar) is the honest "unassessed" result.
        return {
            'version': ENGINE_VERSION,
            'engine': 'analysis-service',
            'account_pillar_scores': {},
            'finding_count': 0,
            'resources': [],
            'assessment_status': 'unassessed',
            'assessed_resource_count': 0,
        }
    result = AnalysisService().analyze_account(contexts_from_scan(scan))
    return {
        'version': ENGINE_VERSION,
        'engine': 'analysis-service',
        'account_pillar_scores': result.account_pillar_scores,
        'finding_count': result.finding_count,
        'resources': [item.model_dump(mode='json') for item in result.resources],
        'assessment_status': result.assessment_status,
        'assessed_resource_count': result.assessed_resource_count,
    }


def attach_pillar_analysis(scan: dict) -> dict:
    """Mutate scan dict in place and return it."""
    scan['pillar_analysis'] = run_pillar_analysis(scan)
    return scan
