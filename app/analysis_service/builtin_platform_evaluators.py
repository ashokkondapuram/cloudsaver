"""Built-in platform pillar checks (tags, prod encryption) — pure, no I/O."""
from __future__ import annotations

from app.analysis_service.context import UnifiedResourceContext
from app.analysis_service.finding import Pillar, PillarFinding, Severity, deterministic_finding_id


def evaluate_builtin_platform_rules(ctx: UnifiedResourceContext) -> list[PillarFinding]:
    findings: list[PillarFinding] = []
    env = ctx.env_label() or ''
    is_prod = env in ('prod', 'production')
    has_owner = ctx.tag('owner') is not None
    has_cost = ctx.tag('cost_center') is not None or ctx.tag('CostCenter') is not None
    has_env_tag = ctx.env_label() is not None

    missing_owner = not has_owner
    missing_cost = not has_cost
    missing_env = not has_env_tag
    if missing_owner or missing_cost or missing_env:
        if missing_owner and is_prod:
            sev = Severity.HIGH
        elif missing_owner or missing_cost or missing_env:
            sev = Severity.MEDIUM
        else:
            sev = Severity.LOW
        findings.append(
            PillarFinding(
                finding_id=deterministic_finding_id(
                    canonical_id=ctx.canonical_id, pillar=Pillar.OPERATIONAL_EXCELLENCE, rule_id='PLATFORM_DEFAULT_TAGS'
                ),
                pillar=Pillar.OPERATIONAL_EXCELLENCE,
                rule_id='PLATFORM_DEFAULT_TAGS',
                severity=sev,
                canonical_id=ctx.canonical_id,
                provider=ctx.provider,
                region=ctx.region,
                resource_type=ctx.resource_type,
                current_sku=ctx.current_sku,
                evidence={
                    'source': 'builtin_platform',
                    'missing_owner': missing_owner,
                    'missing_cost_center': missing_cost,
                    'missing_env': missing_env,
                },
                remediation_action='Add owner, cost center, and environment tags or labels per FinOps policy',
            )
        )

    enc = ctx.config.encrypted_at_rest
    if is_prod and enc is False:
        findings.append(
            PillarFinding(
                finding_id=deterministic_finding_id(
                    canonical_id=ctx.canonical_id, pillar=Pillar.SECURITY, rule_id='PLATFORM_PROD_ENCRYPTION_EXPECTATION'
                ),
                pillar=Pillar.SECURITY,
                rule_id='PLATFORM_PROD_ENCRYPTION_EXPECTATION',
                severity=Severity.HIGH,
                canonical_id=ctx.canonical_id,
                provider=ctx.provider,
                region=ctx.region,
                resource_type=ctx.resource_type,
                current_sku=ctx.current_sku,
                evidence={'source': 'builtin_platform', 'encrypted_at_rest': False},
                remediation_action='Enable encryption at rest for production data paths',
            )
        )

    return findings
