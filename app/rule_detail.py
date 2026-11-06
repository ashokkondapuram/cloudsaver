"""Per-resource rule evaluations, primary match resolution, and explicit conflict records."""
from __future__ import annotations

from typing import Any

from app.domain.resource.identity import canonical_resource_id
from app.rule_match_strategy import resolve_resource_matches


def normalize_resource_id(provider: str, resource_id: str) -> str:
    return canonical_resource_id(provider, resource_id)


def evaluations_for_resource(
    scan_evaluations: list[dict],
    *,
    provider: str,
    resource_id: str,
) -> list[dict]:
    """Return rule evaluation rows for one resource (provider-safe id matching)."""
    selected = normalize_resource_id(provider, resource_id)
    rows = []
    for row in scan_evaluations or []:
        if row.get('cloud_provider', 'azure') != provider:
            continue
        if normalize_resource_id(provider, row.get('resource_id', '')) != selected:
            continue
        rows.append(row)
    rows.sort(key=lambda item: (item.get('rule_id') or '', item.get('outcome') or ''))
    return rows


def match_resource_payload(assessment: dict, observation: dict | None) -> dict:
    obs = observation or {}
    evidence = obs.get('evidence') if isinstance(obs.get('evidence'), dict) else {}
    return dict(
        resource_id=assessment['resource_id'],
        resource_type=assessment.get('resource_type') or obs.get('resource_type') or '',
        cloud_provider=assessment.get('provider') or assessment.get('cloud_provider') or 'azure',
        evidence=evidence,
        reconciliation_status=obs.get('reconciliation_status') or assessment.get('reconciliation_status'),
    )


def rule_conflicts(
    *,
    reconciliation_status: str | None,
    findings: list[dict],
    evaluations: list[dict],
) -> list[dict[str, Any]]:
    """Surface reconciliation and finding/evaluation drift for operators."""
    conflicts: list[dict[str, Any]] = []
    if reconciliation_status == 'source_conflict':
        conflicts.append(
            dict(
                kind='source_reconciliation',
                severity='block',
                rule_id=None,
                message='Inventory sources disagree on this resource. Resolve reconciliation before acting on rules or savings.',
            )
        )
    eval_by_rule = {row['rule_id']: row for row in evaluations if row.get('rule_id')}
    finding_rules = {row['rule_id'] for row in findings if row.get('rule_id')}
    for finding in findings:
        rule_id = finding.get('rule_id')
        if not rule_id:
            continue
        evaluation = eval_by_rule.get(rule_id)
        if evaluation is None:
            conflicts.append(
                dict(
                    kind='finding_without_evaluation',
                    severity='review',
                    rule_id=rule_id,
                    message='A saved finding exists without a matching rule evaluation row for this observation.',
                )
            )
            continue
        if evaluation.get('outcome') != 'condition_detected':
            conflicts.append(
                dict(
                    kind='outcome_mismatch',
                    severity='review',
                    rule_id=rule_id,
                    message=(
                        f"Finding is materialized but the saved evaluation outcome is "
                        f"{evaluation.get('outcome')!r}."
                    ),
                )
            )
    for rule_id, evaluation in eval_by_rule.items():
        if evaluation.get('outcome') != 'condition_detected':
            continue
        if rule_id in finding_rules:
            continue
        conflicts.append(
            dict(
                kind='evaluation_without_finding',
                severity='info',
                rule_id=rule_id,
                message='Rule evaluation detected a condition but no priced finding was materialized (policy, scope, or attribution).',
            )
        )
    return conflicts


def build_resource_rule_detail(
    assessment: dict,
    findings: list[dict],
    evaluations: list[dict],
    observation: dict | None,
    *,
    opportunity_group_id: str | None = None,
) -> dict[str, Any]:
    resource = match_resource_payload(assessment, observation)
    matches = resolve_resource_matches(
        resource,
        evaluations,
        opportunity_group_id=opportunity_group_id,
    )
    status = resource.get('reconciliation_status')
    conflicts = rule_conflicts(
        reconciliation_status=status,
        findings=findings,
        evaluations=evaluations,
    )
    return dict(
        rule_matches=matches,
        rule_conflicts=conflicts,
        reconciliation_status=status,
    )
