from __future__ import annotations

from app.analysis_service.context import UnifiedResourceContext
from app.analysis_service.evaluators import _helpers as h
from app.analysis_service.finding import Pillar, PillarFinding, Severity, deterministic_finding_id

_MANDATORY_TAGS = ('env', 'owner', 'cost_center', 'service')


def evaluate(ctx: UnifiedResourceContext) -> list[PillarFinding]:
    findings: list[PillarFinding] = []
    monthly = h.monthly_cost(ctx)

    if ctx.drift_detected or h.human_drift_events(ctx):
        event = h.human_drift_events(ctx)[0] if h.human_drift_events(ctx) else None
        findings.append(
            PillarFinding(
                finding_id=deterministic_finding_id(
                    canonical_id=ctx.canonical_id, pillar=Pillar.OPERATIONAL_EXCELLENCE, rule_id='OPS_IAC_DRIFT'
                ),
                pillar=Pillar.OPERATIONAL_EXCELLENCE,
                rule_id='OPS_IAC_DRIFT',
                severity=Severity.HIGH,
                canonical_id=ctx.canonical_id,
                provider=ctx.provider,
                region=ctx.region,
                resource_type=ctx.resource_type,
                current_sku=ctx.current_sku,
                evidence={
                    'drift_detected': ctx.drift_detected,
                    **(
                        {
                            'event_id': event.event_id,
                            'event_time': event.event_time,
                            'actor_identity': event.actor_identity,
                        }
                        if event
                        else {}
                    ),
                },
                financial_impact=h.financial(monthly),
                remediation_action='REVERT_IAC_DRIFT',
            )
        )

    missing = [tag for tag in _MANDATORY_TAGS if not ctx.tag(tag)]
    if missing and monthly and ctx.config.tags_collected:
        findings.append(
            PillarFinding(
                finding_id=deterministic_finding_id(
                    canonical_id=ctx.canonical_id, pillar=Pillar.OPERATIONAL_EXCELLENCE, rule_id='OPS_UNTAGGED'
                ),
                pillar=Pillar.OPERATIONAL_EXCELLENCE,
                rule_id='OPS_UNTAGGED',
                severity=Severity.MEDIUM,
                canonical_id=ctx.canonical_id,
                provider=ctx.provider,
                region=ctx.region,
                resource_type=ctx.resource_type,
                current_sku=ctx.current_sku,
                evidence={'missing_tags': missing, 'tags': ctx.tags},
                financial_impact=h.financial(monthly),
                remediation_action='APPLY_TAGS',
            )
        )

    env = ctx.env_label()
    if env in ('dev', 'staging', 'test') and (ctx.metrics.runtime_hours_30d or 0) >= 700:
        if ctx.metrics.cpu_max_pct is not None and ctx.metrics.cpu_max_pct < 2.0:
            savings = monthly * 0.65 if monthly else None
            findings.append(
                PillarFinding(
                    finding_id=deterministic_finding_id(
                        canonical_id=ctx.canonical_id,
                        pillar=Pillar.OPERATIONAL_EXCELLENCE,
                        rule_id='OPS_STALE_ENV',
                    ),
                    pillar=Pillar.OPERATIONAL_EXCELLENCE,
                    rule_id='OPS_STALE_ENV',
                    severity=Severity.LOW,
                    canonical_id=ctx.canonical_id,
                    provider=ctx.provider,
                    region=ctx.region,
                    resource_type=ctx.resource_type,
                    current_sku=ctx.current_sku,
                    evidence={'env': env, 'runtime_hours_30d': ctx.metrics.runtime_hours_30d, 'cpu_max_pct': ctx.metrics.cpu_max_pct},
                    financial_impact=h.financial(monthly, savings=savings),
                    remediation_action='APPLY_OFF_HOURS_SCHEDULE',
                )
            )

    for event in ctx.activity:
        if (ctx.metrics.error_5xx_rate_pct or 0) > 1.0:
            findings.append(
                PillarFinding(
                    finding_id=deterministic_finding_id(
                        canonical_id=ctx.canonical_id,
                        pillar=Pillar.OPERATIONAL_EXCELLENCE,
                        rule_id='OPS_CHANGE_FAILURE',
                    ),
                    pillar=Pillar.OPERATIONAL_EXCELLENCE,
                    rule_id='OPS_CHANGE_FAILURE',
                    severity=Severity.HIGH,
                    canonical_id=ctx.canonical_id,
                    provider=ctx.provider,
                    region=ctx.region,
                    resource_type=ctx.resource_type,
                    current_sku=ctx.current_sku,
                    evidence={
                        'event_time': event.event_time,
                        'event_name': event.event_name,
                        'error_5xx_rate_pct': ctx.metrics.error_5xx_rate_pct,
                    },
                    financial_impact=h.financial(monthly),
                    remediation_action='REVIEW_CHANGE',
                )
            )
            break

    return findings
