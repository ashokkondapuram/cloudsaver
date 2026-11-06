"""Attach deterministic pillar analysis to completed scan payloads (ingestion → analysis decoupling)."""
from __future__ import annotations

from app.analysis_service.finding import Pillar
from app.analysis_service.loader import contexts_from_scan
from app.analysis_service.service import AnalysisService

ENGINE_VERSION = '1.0.0'
_EMPTY_SCORES = {pillar.value: 100.0 for pillar in Pillar}


def run_pillar_analysis(scan: dict) -> dict:
    """Return serializable pillar analysis block; never performs cloud HTTP."""
    inventory = scan.get('inventory') or []
    if not inventory:
        return {
            'version': ENGINE_VERSION,
            'engine': 'analysis-service',
            'account_pillar_scores': dict(_EMPTY_SCORES),
            'finding_count': 0,
            'resources': [],
        }
    result = AnalysisService().analyze_account(contexts_from_scan(scan))
    return {
        'version': ENGINE_VERSION,
        'engine': 'analysis-service',
        'account_pillar_scores': result.account_pillar_scores,
        'finding_count': result.finding_count,
        'resources': [item.model_dump(mode='json') for item in result.resources],
    }


def attach_pillar_analysis(scan: dict) -> dict:
    """Mutate scan dict in place and return it."""
    scan['pillar_analysis'] = run_pillar_analysis(scan)
    return scan
