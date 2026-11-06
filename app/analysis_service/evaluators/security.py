from __future__ import annotations

from app.analysis_service.context import UnifiedResourceContext
from app.analysis_service.evaluators import _helpers as h
from app.analysis_service.finding import Pillar, PillarFinding, Severity, deterministic_finding_id

_SECURITY_EVENTS = (
    'AuthorizeSecurityGroupIngress',
    'PutBucketPolicy',
    'SetIamPolicy',
    'roleAssignments/write',
)


def evaluate(ctx: UnifiedResourceContext) -> list[PillarFinding]:
    findings: list[PillarFinding] = []
    monthly = h.monthly_cost(ctx)

    if ctx.config.encrypted_at_rest is False:
        sev = Severity.CRITICAL if ctx.config.publicly_accessible else Severity.HIGH
        findings.append(
            PillarFinding(
                finding_id=deterministic_finding_id(
                    canonical_id=ctx.canonical_id, pillar=Pillar.SECURITY, rule_id='SEC_UNENCRYPTED'
                ),
                pillar=Pillar.SECURITY,
                rule_id='SEC_UNENCRYPTED',
                severity=sev,
                canonical_id=ctx.canonical_id,
                provider=ctx.provider,
                region=ctx.region,
                resource_type=ctx.resource_type,
                current_sku=ctx.current_sku,
                evidence={'encrypted_at_rest': False, 'publicly_accessible': ctx.config.publicly_accessible},
                financial_impact=h.financial(monthly),
                remediation_action='ENABLE_ENCRYPTION',
            )
        )

    if ctx.config.publicly_accessible or ctx.config.sensitive_port_exposed_to_internet:
        findings.append(
            PillarFinding(
                finding_id=deterministic_finding_id(
                    canonical_id=ctx.canonical_id, pillar=Pillar.SECURITY, rule_id='SEC_EXPOSED_PERIMETER'
                ),
                pillar=Pillar.SECURITY,
                rule_id='SEC_EXPOSED_PERIMETER',
                severity=Severity.CRITICAL,
                canonical_id=ctx.canonical_id,
                provider=ctx.provider,
                region=ctx.region,
                resource_type=ctx.resource_type,
                current_sku=ctx.current_sku,
                evidence={
                    'publicly_accessible': ctx.config.publicly_accessible,
                    'sensitive_port_exposed_to_internet': ctx.config.sensitive_port_exposed_to_internet,
                },
                financial_impact=h.financial(monthly),
                remediation_action='RESTRICT_NETWORK',
            )
        )

    for event in h.human_drift_events(ctx):
        if any(name in event.event_name for name in _SECURITY_EVENTS):
            findings.append(
                PillarFinding(
                    finding_id=deterministic_finding_id(
                        canonical_id=ctx.canonical_id,
                        pillar=Pillar.SECURITY,
                        rule_id=f'SEC_DRIFT:{event.event_id}',
                    ),
                    pillar=Pillar.SECURITY,
                    rule_id='SEC_OUT_OF_BAND_DRIFT',
                    severity=Severity.CRITICAL,
                    canonical_id=ctx.canonical_id,
                    provider=ctx.provider,
                    region=ctx.region,
                    resource_type=ctx.resource_type,
                    current_sku=ctx.current_sku,
                    evidence={
                        'event_id': event.event_id,
                        'event_time': event.event_time,
                        'actor_identity': event.actor_identity,
                        'event_name': event.event_name,
                        'changed_fields': event.changed_fields,
                    },
                    financial_impact=h.financial(monthly),
                    remediation_action='REVERT_IAC_DRIFT',
                )
            )
            break

    if ctx.config.zero_traffic_14d and ctx.config.attached_iam_or_sa and monthly:
        findings.append(
            PillarFinding(
                finding_id=deterministic_finding_id(
                    canonical_id=ctx.canonical_id, pillar=Pillar.SECURITY, rule_id='SEC_ZOMBIE_RESOURCE'
                ),
                pillar=Pillar.SECURITY,
                rule_id='SEC_ZOMBIE_RESOURCE',
                severity=Severity.MEDIUM,
                canonical_id=ctx.canonical_id,
                provider=ctx.provider,
                region=ctx.region,
                resource_type=ctx.resource_type,
                current_sku=ctx.current_sku,
                evidence={'zero_traffic_14d': True, 'attached_iam_or_sa': True},
                financial_impact=h.financial(monthly, savings=monthly),
                remediation_action='DELETE_ORPHAN',
            )
        )

    wiz = ctx.wiz_issues or []
    if wiz:
        rank = {
            'CRITICAL': 4,
            'HIGH': 3,
            'MEDIUM': 2,
            'LOW': 1,
        }
        sev_from = {
            'CRITICAL': Severity.CRITICAL,
            'HIGH': Severity.HIGH,
            'MEDIUM': Severity.MEDIUM,
            'LOW': Severity.LOW,
        }
        best_rank = 0
        top_sev = Severity.LOW
        top_name = ''
        for item in wiz:
            if not isinstance(item, dict):
                continue
            s = str(item.get('severity') or '').upper()
            r = rank.get(s, 0)
            if r > best_rank:
                best_rank = r
                top_sev = sev_from.get(s, Severity.MEDIUM)
                top_name = str(item.get('rule_name') or item.get('rule_id') or '')
        if best_rank == 0:
            top_sev = Severity.MEDIUM
        sample = []
        for item in wiz[:12]:
            if isinstance(item, dict):
                sample.append(
                    {
                        'issue_id': item.get('issue_id'),
                        'severity': item.get('severity'),
                        'status': item.get('status'),
                        'rule_name': item.get('rule_name'),
                    }
                )
        findings.append(
            PillarFinding(
                finding_id=deterministic_finding_id(
                    canonical_id=ctx.canonical_id, pillar=Pillar.SECURITY, rule_id='WIZ_SECURITY_POSTURE'
                ),
                pillar=Pillar.SECURITY,
                rule_id='WIZ_SECURITY_POSTURE',
                severity=top_sev,
                canonical_id=ctx.canonical_id,
                provider=ctx.provider,
                region=ctx.region,
                resource_type=ctx.resource_type,
                current_sku=ctx.current_sku,
                evidence={
                    'source': 'wiz',
                    'open_issue_count': len(wiz),
                    'max_severity': top_sev.value,
                    'primary_rule': top_name,
                    'issues_sample': sample,
                },
                financial_impact=h.financial(monthly),
                remediation_action='REMEDIATE_WIZ_ISSUES',
            )
        )

    return findings
