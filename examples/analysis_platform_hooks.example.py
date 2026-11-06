# Example: copy to app/analysis_platform_hooks.py on PYTHONPATH or load via
# CLOUDSAVER_ANALYSIS_PLATFORM_EVALUATORS=my_org.cloudsaver_rules
#
# Platform evaluators must be pure (read UnifiedResourceContext only). Do not
# perform network I/O here. See docs/ANALYSIS_SERVICE.md.

from __future__ import annotations

from app.analysis_service.context import UnifiedResourceContext
from app.analysis_service.finding import Pillar, PillarFinding, Severity, deterministic_finding_id


def evaluate_platform(ctx: UnifiedResourceContext) -> list[PillarFinding]:
    """Example: flag resources missing a cost_center tag in non-prod (illustrative)."""
    tags = ctx.tags or {}
    if tags.get('cost_center') or tags.get('CostCenter'):
        return []
    env = ctx.env_label() or ''
    if env in ('prod', 'production'):
        return []
    return [
        PillarFinding(
            finding_id=deterministic_finding_id(
                canonical_id=ctx.canonical_id,
                pillar=Pillar.OPERATIONAL_EXCELLENCE,
                rule_id='PLATFORM_EXAMPLE_MISSING_COST_CENTER',
            ),
            pillar=Pillar.OPERATIONAL_EXCELLENCE,
            rule_id='PLATFORM_EXAMPLE_MISSING_COST_CENTER',
            severity=Severity.LOW,
            canonical_id=ctx.canonical_id,
            provider=ctx.provider,
            region=ctx.region,
            resource_type=ctx.resource_type,
            current_sku=ctx.current_sku,
            evidence={'tags': dict(tags)},
            remediation_action='Add cost_center label or tag for chargeback',
        )
    ]
