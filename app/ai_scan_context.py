"""Attach scan-level rule and cost fields to resource AI context (still no resource_id)."""
from __future__ import annotations

from app.ai_resource_context import omit_resource_ids


def augment_ai_context_from_scan(scan, assessment, findings, context):
    from app.financial_balance import resource_financial_balance
    from app.pricing import opportunity_totals
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
    opportunity = opportunity_totals(findings)
    balance = resource_financial_balance(
        billed_cost_usd=assessment.get('billed_cost_usd'),
        effective_cost_usd=assessment.get('effective_cost_usd'),
        retail_run_rate_usd=assessment.get('retail_estimate_usd'),
        opportunity=opportunity,
    )
    costs = dict(
        billed_cost_usd=assessment.get('billed_cost_usd'),
        effective_cost_usd=assessment.get('effective_cost_usd'),
        retail_estimate_usd=assessment.get('retail_estimate_usd'),
        opportunity_usd=balance['retail_waste_opportunity_usd'],
        currency=assessment.get('currency') or 'USD',
        **balance,
    )
    obs_evidence = ((observation or {}).get('evidence') or {}) if observation else {}
    overlaps = [
        dict(resource_name=row.get('resource_name'), rule_id=row['rule_id'])
        for row in scan.get('findings') or []
        if row.get('opportunity_group_id') in groups
        and normalize_resource_id(provider, row.get('resource_id', '')) != selected_id
    ]
    updated = dict(
        context,
        rule_evaluations=omit_resource_ids(evaluations),
        rule_matches=omit_resource_ids(rule_detail['rule_matches']),
        rule_conflicts=list(rule_detail['rule_conflicts']),
        reconciliation_status=rule_detail.get('reconciliation_status'),
        costs=omit_resource_ids(costs),
        analysis_readiness=obs_evidence.get('analysis_readiness'),
        configuration_detail=omit_resource_ids(
            obs_evidence.get('typed_configuration') or (observation or {}).get('configuration_snapshot')
        ),
        financial_overlaps=overlaps or None,
    )
    return omit_resource_ids({k: v for k, v in updated.items() if v is not None})
