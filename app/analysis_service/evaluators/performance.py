from __future__ import annotations

from app.analysis_service.context import UnifiedResourceContext
from app.analysis_service.evaluators import _helpers as h
from app.analysis_service.finding import Pillar, PillarFinding, Severity, deterministic_finding_id


def evaluate(ctx: UnifiedResourceContext) -> list[PillarFinding]:
    findings: list[PillarFinding] = []
    monthly = h.monthly_cost(ctx)
    m = ctx.metrics

    saturated = (
        (m.cpu_p95_pct is not None and m.cpu_p95_pct > 85.0)
        or (m.memory_p95_pct is not None and m.memory_p95_pct > 90.0)
        or (m.throttled_requests_count or 0) > 0
    )
    if saturated:
        findings.append(
            PillarFinding(
                finding_id=deterministic_finding_id(
                    canonical_id=ctx.canonical_id, pillar=Pillar.PERFORMANCE_EFFICIENCY, rule_id='PERF_SATURATION'
                ),
                pillar=Pillar.PERFORMANCE_EFFICIENCY,
                rule_id='PERF_SATURATION',
                severity=Severity.HIGH,
                canonical_id=ctx.canonical_id,
                provider=ctx.provider,
                region=ctx.region,
                resource_type=ctx.resource_type,
                current_sku=ctx.current_sku,
                evidence={
                    'cpu_p95_pct': m.cpu_p95_pct,
                    'memory_p95_pct': m.memory_p95_pct,
                    'throttled_requests_count': m.throttled_requests_count,
                },
                financial_impact=h.financial(monthly, projected=monthly),
                remediation_action='UPGRADE_SKU',
            )
        )

    if ctx.config.burstable_sku and m.burst_credit_balance_min_pct is not None and m.burst_credit_balance_min_pct < 10.0:
        findings.append(
            PillarFinding(
                finding_id=deterministic_finding_id(
                    canonical_id=ctx.canonical_id, pillar=Pillar.PERFORMANCE_EFFICIENCY, rule_id='PERF_BURST_DEPLETED'
                ),
                pillar=Pillar.PERFORMANCE_EFFICIENCY,
                rule_id='PERF_BURST_DEPLETED',
                severity=Severity.MEDIUM,
                canonical_id=ctx.canonical_id,
                provider=ctx.provider,
                region=ctx.region,
                resource_type=ctx.resource_type,
                current_sku=ctx.current_sku,
                evidence={'burst_credit_balance_min_pct': m.burst_credit_balance_min_pct},
                financial_impact=h.financial(monthly),
                remediation_action='UPGRADE_GENERATION',
            )
        )

    if ctx.config.legacy_sku_generation:
        projected = monthly * 0.9 if monthly else None
        findings.append(
            PillarFinding(
                finding_id=deterministic_finding_id(
                    canonical_id=ctx.canonical_id, pillar=Pillar.PERFORMANCE_EFFICIENCY, rule_id='PERF_LEGACY_SKU'
                ),
                pillar=Pillar.PERFORMANCE_EFFICIENCY,
                rule_id='PERF_LEGACY_SKU',
                severity=Severity.LOW,
                canonical_id=ctx.canonical_id,
                provider=ctx.provider,
                region=ctx.region,
                resource_type=ctx.resource_type,
                current_sku=ctx.current_sku,
                evidence={'current_sku': ctx.current_sku},
                financial_impact=h.financial(monthly, savings=(monthly - projected) if monthly and projected else None, projected=projected),
                remediation_action='UPGRADE_GENERATION',
            )
        )

    if (
        m.disk_iops_provisioned
        and m.disk_iops_observed_max is not None
        and m.disk_iops_observed_max >= m.disk_iops_provisioned * 0.95
    ):
        findings.append(
            PillarFinding(
                finding_id=deterministic_finding_id(
                    canonical_id=ctx.canonical_id, pillar=Pillar.PERFORMANCE_EFFICIENCY, rule_id='PERF_DISK_IOPS_CEILING'
                ),
                pillar=Pillar.PERFORMANCE_EFFICIENCY,
                rule_id='PERF_DISK_IOPS_CEILING',
                severity=Severity.MEDIUM,
                canonical_id=ctx.canonical_id,
                provider=ctx.provider,
                region=ctx.region,
                resource_type=ctx.resource_type,
                current_sku=ctx.current_sku,
                evidence={
                    'disk_iops_provisioned': m.disk_iops_provisioned,
                    'disk_iops_observed_max': m.disk_iops_observed_max,
                },
                financial_impact=h.financial(monthly),
                remediation_action='RIGHTSIZE_SKU',
            )
        )

    return findings
