from __future__ import annotations

from app.analysis_service.context import UnifiedResourceContext
from app.analysis_service.evaluators import _helpers as h
from app.analysis_service.finding import (
    Pillar,
    PillarFinding,
    Severity,
    deterministic_finding_id,
)


def evaluate(ctx: UnifiedResourceContext) -> list[PillarFinding]:
    findings: list[PillarFinding] = []
    monthly = h.monthly_cost(ctx)

    if h.is_orphan_disk(ctx):
        findings.append(
            PillarFinding(
                finding_id=deterministic_finding_id(
                    canonical_id=ctx.canonical_id, pillar=Pillar.COST_OPTIMIZATION, rule_id='COST_ORPHAN_DISK'
                ),
                pillar=Pillar.COST_OPTIMIZATION,
                rule_id='COST_ORPHAN_DISK',
                severity=Severity.HIGH,
                canonical_id=ctx.canonical_id,
                provider=ctx.provider,
                region=ctx.region,
                resource_type=ctx.resource_type,
                current_sku=ctx.current_sku,
                evidence={'disk_state': ctx.config.disk_state, 'cost_source': ctx.cost.cost_source},
                financial_impact=h.financial(monthly, savings=monthly),
                remediation_action='DELETE_ORPHAN',
            )
        )

    if h.is_idle_compute(ctx):
        findings.append(
            PillarFinding(
                finding_id=deterministic_finding_id(
                    canonical_id=ctx.canonical_id, pillar=Pillar.COST_OPTIMIZATION, rule_id='COST_IDLE_COMPUTE'
                ),
                pillar=Pillar.COST_OPTIMIZATION,
                rule_id='COST_IDLE_COMPUTE',
                severity=Severity.MEDIUM,
                canonical_id=ctx.canonical_id,
                provider=ctx.provider,
                region=ctx.region,
                resource_type=ctx.resource_type,
                current_sku=ctx.current_sku,
                evidence={
                    'cpu_max_pct': ctx.metrics.cpu_max_pct,
                    'network_in_total_gb': ctx.metrics.network_in_total_gb,
                    'network_out_total_gb': ctx.metrics.network_out_total_gb,
                },
                financial_impact=h.financial(monthly, savings=monthly),
                remediation_action='STOP_IDLE',
            )
        )

    if h.is_rightsizing_candidate(ctx):
        rate = h.discount_rate(ctx)
        savings = None
        if monthly is not None:
            savings = monthly * 0.35 * (1.0 - rate)
        findings.append(
            PillarFinding(
                finding_id=deterministic_finding_id(
                    canonical_id=ctx.canonical_id, pillar=Pillar.COST_OPTIMIZATION, rule_id='COST_RIGHTSIZE'
                ),
                pillar=Pillar.COST_OPTIMIZATION,
                rule_id='COST_RIGHTSIZE',
                severity=Severity.MEDIUM,
                canonical_id=ctx.canonical_id,
                provider=ctx.provider,
                region=ctx.region,
                resource_type=ctx.resource_type,
                current_sku=ctx.current_sku,
                evidence={
                    'cpu_p95_pct': ctx.metrics.cpu_p95_pct,
                    'memory_p95_pct': ctx.metrics.memory_p95_pct,
                    'effective_discount_rate': rate,
                },
                financial_impact=h.financial(monthly, savings=savings),
                remediation_action='RIGHTSIZE_SKU',
            )
        )

    retail = ctx.cost.retail_monthly_equivalent_usd
    actual = ctx.cost.actual_amortized_30d_usd
    runtime = ctx.metrics.runtime_hours_30d
    if retail and actual is not None and runtime is not None and runtime >= 700 and abs(actual - retail) < 0.01:
        findings.append(
            PillarFinding(
                finding_id=deterministic_finding_id(
                    canonical_id=ctx.canonical_id,
                    pillar=Pillar.COST_OPTIMIZATION,
                    rule_id='COST_COMMITMENT_GAP',
                ),
                pillar=Pillar.COST_OPTIMIZATION,
                rule_id='COST_COMMITMENT_GAP',
                severity=Severity.LOW,
                canonical_id=ctx.canonical_id,
                provider=ctx.provider,
                region=ctx.region,
                resource_type=ctx.resource_type,
                current_sku=ctx.current_sku,
                evidence={'runtime_hours_30d': runtime, 'actual_amortized_30d_usd': actual, 'retail_monthly_equivalent_usd': retail},
                financial_impact=h.financial(monthly, savings=monthly * 0.15 if monthly else None),
                remediation_action='PURCHASE_COMMITMENT',
            )
        )

    for event in ctx.activity:
        if 'Modify' in event.event_name or 'Resize' in event.event_name:
            if monthly and monthly > 0:
                findings.append(
                    PillarFinding(
                        finding_id=deterministic_finding_id(
                            canonical_id=ctx.canonical_id,
                            pillar=Pillar.COST_OPTIMIZATION,
                            rule_id=f'COST_SPIKE_DRIFT:{event.event_id}',
                        ),
                        pillar=Pillar.COST_OPTIMIZATION,
                        rule_id='COST_SPIKE_DRIFT',
                        severity=Severity.MEDIUM,
                        canonical_id=ctx.canonical_id,
                        provider=ctx.provider,
                        region=ctx.region,
                        resource_type=ctx.resource_type,
                        current_sku=ctx.current_sku,
                        evidence={
                            'event_id': event.event_id,
                            'event_time': event.event_time,
                            'event_name': event.event_name,
                            'actor_identity': event.actor_identity,
                        },
                        financial_impact=h.financial(monthly),
                        remediation_action='REVIEW_COST_SPIKE',
                    )
                )
            break

    return findings
