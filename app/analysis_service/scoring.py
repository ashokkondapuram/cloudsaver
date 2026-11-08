"""Spend- and severity-weighted pillar health scores (0–100)."""
from __future__ import annotations

from app.analysis_service.finding import Pillar, PillarFinding, Severity

_SEVERITY_WEIGHT = {
    Severity.CRITICAL: 25.0,
    Severity.HIGH: 15.0,
    Severity.MEDIUM: 8.0,
    Severity.LOW: 3.0,
}


def score_pillar(findings: list[PillarFinding], *, pillar: Pillar, assessed: bool = True) -> float | None:
    """Lower score means more risk. Start at 100 and deduct weighted findings.

    None (not a numeric 100) when the resource was never assessed: no findings because nothing
    was evaluated reads as "healthy" otherwise, which is worse than reporting unknown.
    """
    if not assessed:
        return None
    relevant = [f for f in findings if f.pillar == pillar]
    if not relevant:
        return 100.0
    penalty = 0.0
    for item in relevant:
        base = _SEVERITY_WEIGHT.get(item.severity, 8.0)
        spend = item.financial_impact.current_monthly_cost_usd or 0.0
        spend_weight = min(1.5, 1.0 + (spend / 500.0) * 0.25)
        penalty += base * spend_weight
    return max(0.0, round(100.0 - penalty, 2))
