"""Deterministic review action items from saved evidence — no model required."""

from app.resource_action_items.evidence import collect_evidence_items
from app.resource_action_items.findings import collect_finding_items
from app.resource_action_items.guardrails import collect_guardrail_items, collect_priority_items
from app.resource_action_items.risk import collect_risk_items

_CATEGORY_ORDER = ('priority', 'risk', 'finding', 'evidence', 'guardrail')


def derive_action_items(assessment, findings=None, rule_evaluations=None, *, limit=12):
    """Return ordered, deduplicated action items for one resource assessment."""
    if not assessment or not isinstance(assessment, dict):
        return []
    items = []
    seen = set()

    def add(action):
        if not action:
            return
        key = (action['title'], action['kind'], action.get('category'))
        if key in seen or len(items) >= limit:
            return
        seen.add(key)
        items.append(action)

    protected = assessment.get('disposition') == 'protected' or bool(assessment.get('protected_reasons'))
    collect_risk_items(assessment, add=add, protected=protected)
    collect_finding_items(assessment, findings, rule_evaluations, add=add, protected=protected)
    collect_evidence_items(assessment, add=add)
    collect_guardrail_items(assessment, add=add)
    collect_priority_items(assessment, add=add, protected=protected, items=items)

    rank = {name: index for index, name in enumerate(_CATEGORY_ORDER)}
    items.sort(key=lambda row: (rank.get(row.get('category'), 99), row['title']))
    return items[:limit]
