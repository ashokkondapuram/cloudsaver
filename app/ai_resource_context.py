"""Build external-AI payloads: full resource evidence minus ``resource_id`` (uses ``resource_reference``)."""
from __future__ import annotations

import re
from typing import Any

from app.assessment import ai_context as single_finding_facts
from app.assessment_policy import POLICY_VERSION

_IDENTIFIER_PATTERNS = [
    re.compile(pattern, re.I)
    for pattern in (
        r'/subscriptions/[^\s"\],;]+',
        r'\barn:[^\s"\],;]+',
        r'\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b',
    )
]


def _redact_identifier_strings(value: Any) -> Any:
    if isinstance(value, str):
        text = value
        for pattern in _IDENTIFIER_PATTERNS:
            text = pattern.sub('[REDACTED]', text)
        return text
    if isinstance(value, dict):
        return {key: _redact_identifier_strings(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_identifier_strings(item) for item in value]
    return value


def omit_resource_ids(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned = {key: omit_resource_ids(item) for key, item in value.items() if key != 'resource_id'}
        return _redact_identifier_strings(cleaned)
    if isinstance(value, list):
        return _redact_identifier_strings([omit_resource_ids(item) for item in value])
    return _redact_identifier_strings(value)


def _finding_rows(findings: list[dict], per_finding_assessments: list[dict] | None) -> list[dict]:
    rows = []
    assessments = per_finding_assessments or []
    for index, finding in enumerate(findings or []):
        assessment = assessments[index] if index < len(assessments) else {}
        row = dict(
            rule_id=finding.get('rule_id'),
            severity=finding.get('severity'),
            details=finding.get('details'),
            estimated_monthly_waste_usd=finding.get('estimated_monthly_waste_usd'),
            opportunity_group_id=finding.get('opportunity_group_id'),
            cloud_provider=finding.get('cloud_provider', 'azure'),
            facts=single_finding_facts(finding, assessment).get('facts', {}) if assessment else {},
            evidence=omit_resource_ids(finding.get('evidence') or {}),
        )
        rows.append({k: v for k, v in row.items() if v is not None})
    return rows


def build_resource_ai_context(
    assessment: dict,
    findings: list[dict],
    *,
    per_finding_assessments: list[dict] | None = None,
    rule_evaluations: list[dict] | None = None,
    rule_matches: dict | None = None,
    rule_conflicts: list[dict] | None = None,
    costs: dict | None = None,
    analysis_readiness: dict | None = None,
    configuration_detail: dict | None = None,
    financial_overlaps: list[dict] | None = None,
) -> dict[str, Any]:
    """Operator-facing preview and model input: all structured fields except raw resource IDs."""
    from app.assessment_policy import MODEL_BASE_CODES

    merged_checks = [
        dict(pillar=c['pillar'], code=c['code'], status=c['status'])
        for pillar in assessment.get('pillars') or []
        for c in pillar.get('checks') or []
    ]
    checks = [
        dict(pillar=c['pillar'], code=c['code'], status=c['status'])
        for c in merged_checks
        if c['status'] != 'unknown' or c['code'] in MODEL_BASE_CODES
    ]
    context: dict[str, Any] = dict(
        resource_reference=assessment['resource_key'],
        provider=assessment['provider'],
        resource_name=assessment.get('resource_name'),
        resource_type=assessment.get('resource_type'),
        resource_group=assessment.get('resource_group'),
        scope_id=assessment.get('scope_id'),
        service_category=assessment['service_category'],
        finding_count=assessment.get('finding_count', len(findings or [])),
        rule_ids=list(assessment.get('rule_ids') or []),
        policy_version=assessment.get('policy_version') or POLICY_VERSION,
        observation=assessment.get('observation'),
        review_priority=assessment.get('review_priority'),
        disposition=assessment.get('disposition'),
        protected_reasons=list(assessment.get('protected_reasons') or []),
        risk_level=assessment.get('risk_level'),
        risk_check_codes=list(assessment.get('risk_check_codes') or []),
        evidence_gap_codes=list(assessment.get('evidence_gap_codes') or []),
        evidence_coverage=assessment.get('evidence_coverage'),
        retail_estimate_usd=assessment.get('retail_estimate_usd'),
        billed_cost_usd=assessment.get('billed_cost_usd'),
        effective_cost_usd=assessment.get('effective_cost_usd'),
        commitment_locked=assessment.get('commitment_locked'),
        currency=assessment.get('currency'),
        pillars=assessment.get('pillars'),
        findings=_finding_rows(findings, per_finding_assessments),
        rule_evaluations=omit_resource_ids(list(rule_evaluations or [])),
        rule_matches=omit_resource_ids(rule_matches) if rule_matches else None,
        rule_conflicts=list(rule_conflicts or []),
        costs=omit_resource_ids(costs) if costs else None,
        analysis_readiness=analysis_readiness,
        configuration_detail=omit_resource_ids(configuration_detail) if configuration_detail else None,
        financial_overlaps=omit_resource_ids(financial_overlaps) if financial_overlaps else None,
        risk_floor=assessment['risk_level'],
        checks=checks,
        protected=bool(assessment.get('protected_reasons')),
        guardrails=list(assessment.get('guardrails') or []),
        observed_check_codes=sorted(
            {c['code'] for pillar in assessment.get('pillars') or [] for c in pillar.get('checks') or [] if c.get('status') != 'unknown'}
        ),
    )
    return omit_resource_ids({k: v for k, v in context.items() if v is not None})


def stable_digest_context(context: dict) -> dict:
    """Fingerprint material for evidence_digest (exclude wall-clock freshness noise)."""
    observation = context.get('observation') or {}
    guardrails = [g for g in context.get('guardrails') or [] if g != 'REFRESH_OBSERVATION']
    checks = [c for c in context.get('checks') or [] if c.get('code') != 'OBSERVATION_FRESHNESS']
    stable = dict(
        context,
        observation=dict(observed_at=observation.get('observed_at')),
        guardrails=guardrails,
        checks=checks,
    )
    stable.pop('pillars', None)
    stable.pop('review_priority', None)
    if stable.get('risk_check_codes'):
        stable['risk_check_codes'] = [code for code in stable['risk_check_codes'] if code != 'OBSERVATION_FRESHNESS']
    return stable
