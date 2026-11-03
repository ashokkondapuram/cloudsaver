"""Attach scan-level rule signals to AI context (no billing, config snapshots, or overlap names)."""
from __future__ import annotations

from app.ai_resource_context import build_resource_ai_context


def augment_ai_context_from_scan(scan, assessment, findings, context):
    from app.assessment import assess
    from app.rule_detail import build_resource_rule_detail, evaluations_for_resource, normalize_resource_id

    provider = assessment['provider']
    selected_id = normalize_resource_id(provider, assessment['resource_id'])
    observation = next(
        (
            row
            for row in scan.get('inventory') or []
            if row.get('cloud_provider', 'azure') == provider
            and normalize_resource_id(provider, row.get('resource_id', '')) == selected_id
        ),
        None,
    )
    evaluations = evaluations_for_resource(
        scan.get('rule_evaluations') or [],
        provider=provider,
        resource_id=assessment['resource_id'],
    )
    groups = {row['opportunity_group_id'] for row in findings if row.get('opportunity_group_id')}
    opportunity_group_id = next(iter(groups), None) if len(groups) == 1 else None
    rule_detail = build_resource_rule_detail(
        assessment,
        findings,
        evaluations,
        observation,
        opportunity_group_id=opportunity_group_id,
    )
    obs_evidence = ((observation or {}).get('evidence') or {}) if observation else {}
    observed_at = scan.get('timestamp')
    per_finding = [assess(finding, observed_at=observed_at) for finding in findings] if findings else []
    return build_resource_ai_context(
        assessment,
        findings,
        per_finding_assessments=per_finding,
        rule_evaluations=evaluations,
        rule_matches=rule_detail['rule_matches'],
        rule_conflicts=rule_detail['rule_conflicts'],
        analysis_readiness=obs_evidence.get('analysis_readiness'),
        reconciliation_status=rule_detail.get('reconciliation_status'),
    )
