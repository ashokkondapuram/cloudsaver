"""Shared action-item shape and helpers."""

from __future__ import annotations

_CATEGORIES = frozenset({'risk', 'finding', 'evidence', 'guardrail', 'priority'})
_KIND = ('verify', 'investigate', 'configure', 'rightsize', 'retain', 'decommission')


def action(
    *,
    title,
    rationale,
    kind,
    pillar,
    evidence_codes,
    category,
    effort='medium',
    change_risk='medium',
    confidence='high',
    prerequisites=None,
):
    if kind not in _KIND:
        kind = 'investigate'
    if category not in _CATEGORIES:
        raise ValueError(f'Unknown action category: {category}')
    return dict(
        title=title,
        rationale=rationale,
        kind=kind,
        pillar=pillar,
        category=category,
        effort=effort,
        change_risk=change_risk,
        confidence=confidence,
        evidence_codes=list(evidence_codes or []),
        prerequisites=list(prerequisites or []),
    )


def check_lookup(assessment):
    by_code = {}
    for pillar in assessment.get('pillars') or []:
        for check in pillar.get('checks') or []:
            by_code[check['code']] = dict(check, pillar=pillar.get('pillar', 'operations'))
    return by_code
