"""Minimized external-AI payloads — no resource IDs, names, billing, raw config, tags, or free-text findings."""
from __future__ import annotations

import re
from typing import Any

from app.assessment import ai_context as single_finding_facts
from app.assessment_policy import MODEL_BASE_CODES, POLICY_VERSION
from app.data_governance import FACT_FIELDS

_EVALUATION_KEYS = frozenset(
    {'rule_id', 'rule_version', 'outcome', 'destructive_actions_blocked', 'safety_blocks', 'protected_reasons'}
)
_READINESS_KEYS = frozenset(
    {'configuration', 'configuration_observed', 'configuration_total', 'telemetry_pending_rule_ids'}
)
_IDENTIFIER_PATTERNS = [
    re.compile(pattern, re.I)
    for pattern in (
        r'/subscriptions/[^\s"\],;]+',
        r'\barn:[^\s"\],;]+',
        r'\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b',
        r'\b[\w.+-]+@[\w.-]+\.[a-z]{2,}\b',
        r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b',
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


def _allowlisted_facts(facts: dict) -> dict:
    return {key: facts[key] for key in FACT_FIELDS if key in facts}


def _finding_rows(findings: list[dict], per_finding_assessments: list[dict] | None) -> list[dict]:
    rows = []
    assessments = per_finding_assessments or []
    for index, finding in enumerate(findings or []):
        assessment = assessments[index] if index < len(assessments) else {}
        facts = single_finding_facts(finding, assessment).get('facts', {}) if assessment else {}
        rows.append(dict(rule_id=finding.get('rule_id'), facts=_allowlisted_facts(facts)))
    return [row for row in rows if row.get('rule_id')]


def _rule_evaluations(rows: list[dict] | None) -> list[dict]:
    cleaned = []
    for row in rows or []:
        if not row.get('rule_id'):
            continue
        cleaned.append({key: row[key] for key in _EVALUATION_KEYS if key in row})
    return cleaned


def _rule_matches(matches: dict | None) -> dict | None:
    if not matches:
        return None
    primary = matches.get('primary_match')
    alternates = matches.get('alternate_matches') or []
    payload = dict(
        primary_match=primary,
        alternate_matches=alternates,
        overlap_policy=matches.get('overlap_policy'),
        strategy_version=matches.get('strategy_version'),
    )
    return _redact_identifier_strings({k: v for k, v in payload.items() if v is not None})


def _rule_conflicts(conflicts: list[dict] | None) -> list[dict]:
    rows = []
    for row in conflicts or []:
        rows.append(
            dict(
                kind=row.get('kind'),
                severity=row.get('severity'),
                rule_id=row.get('rule_id'),
                message=row.get('message'),
            )
        )
    return _redact_identifier_strings(rows)


def _analysis_readiness(value: dict | None) -> dict | None:
    if not isinstance(value, dict):
        return None
    trimmed = {key: value[key] for key in _READINESS_KEYS if key in value}
    return trimmed or None


def build_resource_ai_context(
    assessment: dict,
    findings: list[dict],
    *,
    per_finding_assessments: list[dict] | None = None,
    rule_evaluations: list[dict] | None = None,
    rule_matches: dict | None = None,
    rule_conflicts: list[dict] | None = None,
    analysis_readiness: dict | None = None,
    reconciliation_status: str | None = None,
) -> dict[str, Any]:
    """Sanitized model input aligned with ``AI_DATA_GOVERNANCE`` minimization."""
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
        service_category=assessment['service_category'],
        resource_type=assessment.get('resource_type') or '',
        finding_count=assessment.get('finding_count', len(findings or [])),
        rule_ids=list(assessment.get('rule_ids') or []),
        policy_version=assessment.get('policy_version') or POLICY_VERSION,
        observation=assessment.get('observation'),
        disposition=assessment.get('disposition'),
        protected_reasons=list(assessment.get('protected_reasons') or []),
        risk_level=assessment.get('risk_level'),
        risk_check_codes=list(assessment.get('risk_check_codes') or []),
        evidence_gap_codes=list(assessment.get('evidence_gap_codes') or []),
        evidence_coverage=assessment.get('evidence_coverage'),
        findings=_finding_rows(findings, per_finding_assessments),
        rule_evaluations=_rule_evaluations(rule_evaluations),
        rule_matches=_rule_matches(rule_matches),
        rule_conflicts=_rule_conflicts(rule_conflicts),
        reconciliation_status=reconciliation_status,
        analysis_readiness=_analysis_readiness(analysis_readiness),
        risk_floor=assessment['risk_level'],
        checks=checks,
        protected=bool(assessment.get('protected_reasons')),
        guardrails=list(assessment.get('guardrails') or []),
        observed_check_codes=sorted(
            {c['code'] for pillar in assessment.get('pillars') or [] for c in pillar.get('checks') or [] if c.get('status') != 'unknown'}
        ),
    )
    return _redact_identifier_strings({k: v for k, v in context.items() if v is not None})


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
    stable.pop('review_priority', None)
    if stable.get('risk_check_codes'):
        stable['risk_check_codes'] = [code for code in stable['risk_check_codes'] if code != 'OBSERVATION_FRESHNESS']
    return stable
