from __future__ import annotations

from app.analysis_service.context import UnifiedResourceContext
from app.analysis_service.evaluators import _helpers as h
from app.analysis_service.finding import Pillar, PillarFinding, Severity, deterministic_finding_id


def evaluate(ctx: UnifiedResourceContext) -> list[PillarFinding]:
    findings: list[PillarFinding] = []
    monthly = h.monthly_cost(ctx)
    env = ctx.env_label()

    if env == 'prod' and ctx.config.multi_az_or_ha is False:
        findings.append(
            PillarFinding(
                finding_id=deterministic_finding_id(
                    canonical_id=ctx.canonical_id, pillar=Pillar.RELIABILITY, rule_id='REL_SPOF_PROD'
                ),
                pillar=Pillar.RELIABILITY,
                rule_id='REL_SPOF_PROD',
                severity=Severity.CRITICAL,
                canonical_id=ctx.canonical_id,
                provider=ctx.provider,
                region=ctx.region,
                resource_type=ctx.resource_type,
                current_sku=ctx.current_sku,
                evidence={'env': env, 'multi_az_or_ha': False, 'tags': ctx.tags},
                financial_impact=h.financial(monthly, projected=(monthly * 1.8) if monthly else None),
                remediation_action='ENABLE_MULTI_AZ',
            )
        )

    if ctx.config.backup_retention_days is not None and ctx.config.backup_retention_days <= 0:
        findings.append(
            PillarFinding(
                finding_id=deterministic_finding_id(
                    canonical_id=ctx.canonical_id, pillar=Pillar.RELIABILITY, rule_id='REL_NO_BACKUP'
                ),
                pillar=Pillar.RELIABILITY,
                rule_id='REL_NO_BACKUP',
                severity=Severity.HIGH,
                canonical_id=ctx.canonical_id,
                provider=ctx.provider,
                region=ctx.region,
                resource_type=ctx.resource_type,
                current_sku=ctx.current_sku,
                evidence={'backup_retention_days': ctx.config.backup_retention_days},
                financial_impact=h.financial(monthly, projected=(monthly * 1.05) if monthly else None),
                remediation_action='ENABLE_BACKUP',
            )
        )

    if ctx.config.deletion_protection is False and 'database' in ctx.resource_type.lower():
        findings.append(
            PillarFinding(
                finding_id=deterministic_finding_id(
                    canonical_id=ctx.canonical_id, pillar=Pillar.RELIABILITY, rule_id='REL_NO_DELETE_PROTECTION'
                ),
                pillar=Pillar.RELIABILITY,
                rule_id='REL_NO_DELETE_PROTECTION',
                severity=Severity.MEDIUM,
                canonical_id=ctx.canonical_id,
                provider=ctx.provider,
                region=ctx.region,
                resource_type=ctx.resource_type,
                current_sku=ctx.current_sku,
                evidence={'deletion_protection': False},
                financial_impact=h.financial(monthly),
                remediation_action='ENABLE_DELETE_PROTECTION',
            )
        )

    m = ctx.metrics
    if (
        m.cpu_max_pct
        and m.cpu_avg_pct
        and m.cpu_avg_pct > 0
        and (m.cpu_max_pct / m.cpu_avg_pct) > 4.0
        and ctx.config.auto_scaling_enabled is False
    ):
        findings.append(
            PillarFinding(
                finding_id=deterministic_finding_id(
                    canonical_id=ctx.canonical_id, pillar=Pillar.RELIABILITY, rule_id='REL_NO_AUTOSCALE'
                ),
                pillar=Pillar.RELIABILITY,
                rule_id='REL_NO_AUTOSCALE',
                severity=Severity.MEDIUM,
                canonical_id=ctx.canonical_id,
                provider=ctx.provider,
                region=ctx.region,
                resource_type=ctx.resource_type,
                current_sku=ctx.current_sku,
                evidence={
                    'cpu_max_pct': m.cpu_max_pct,
                    'cpu_avg_pct': m.cpu_avg_pct,
                    'auto_scaling_enabled': False,
                },
                financial_impact=h.financial(monthly),
                remediation_action='ENABLE_AUTOSCALING',
            )
        )

    destructive = [e for e in ctx.activity if any(x in e.event_name for x in ('Delete', 'Reboot', 'Stop'))]
    if destructive and (m.error_5xx_rate_pct or 0) > 1.0:
        event = destructive[0]
        findings.append(
            PillarFinding(
                finding_id=deterministic_finding_id(
                    canonical_id=ctx.canonical_id, pillar=Pillar.RELIABILITY, rule_id='REL_DESTRUCTIVE_VOLATILITY'
                ),
                pillar=Pillar.RELIABILITY,
                rule_id='REL_DESTRUCTIVE_VOLATILITY',
                severity=Severity.HIGH,
                canonical_id=ctx.canonical_id,
                provider=ctx.provider,
                region=ctx.region,
                resource_type=ctx.resource_type,
                current_sku=ctx.current_sku,
                evidence={
                    'event_id': event.event_id,
                    'event_name': event.event_name,
                    'error_5xx_rate_pct': m.error_5xx_rate_pct,
                },
                financial_impact=h.financial(monthly),
                remediation_action='REVIEW_CHANGE',
            )
        )

    policy = ctx.config.snapshot_retention_policy_days
    age = ctx.config.snapshot_age_days
    if policy and age and age > policy:
        findings.append(
            PillarFinding(
                finding_id=deterministic_finding_id(
                    canonical_id=ctx.canonical_id, pillar=Pillar.RELIABILITY, rule_id='REL_STALE_SNAPSHOT'
                ),
                pillar=Pillar.RELIABILITY,
                rule_id='REL_STALE_SNAPSHOT',
                severity=Severity.LOW,
                canonical_id=ctx.canonical_id,
                provider=ctx.provider,
                region=ctx.region,
                resource_type=ctx.resource_type,
                current_sku=ctx.current_sku,
                evidence={'snapshot_age_days': age, 'snapshot_retention_policy_days': policy},
                financial_impact=h.financial(monthly, savings=monthly * 0.05 if monthly else None),
                remediation_action='DELETE_ORPHAN',
            )
        )

    return findings
