"""Deterministic review action items from saved evidence — no model required."""
from __future__ import annotations

from app.assessment_policy import MODEL_BASE_CODES

_KIND = ('verify', 'investigate', 'configure', 'rightsize', 'retain', 'decommission')
_DEFAULT = dict(effort='medium', change_risk='medium', confidence='high', prerequisites=[], evidence_codes=[])


def _action(*, title, rationale, kind, pillar, evidence_codes, effort='medium', change_risk='medium', confidence='high', prerequisites=None):
    if kind not in _KIND:
        kind = 'investigate'
    return dict(
        title=title,
        rationale=rationale,
        kind=kind,
        pillar=pillar,
        effort=effort,
        change_risk=change_risk,
        confidence=confidence,
        evidence_codes=list(evidence_codes or []),
        prerequisites=list(prerequisites or []),
    )


_RISK_ACTIONS = {
    'PUBLIC_DATABASE': _action(
        title='Remove public database access',
        rationale='Public accessibility is reported enabled; confirm network path and disable exposure before other changes.',
        kind='configure',
        pillar='security',
        evidence_codes=['PUBLIC_DATABASE'],
        change_risk='high',
    ),
    'ENCRYPTION_AT_REST': _action(
        title='Enable encryption at rest',
        rationale='Encryption is disabled or unverified; fix before capacity or lifecycle changes.',
        kind='configure',
        pillar='security',
        evidence_codes=['ENCRYPTION_AT_REST'],
        change_risk='high',
    ),
    'ADMIN_INGRESS': _action(
        title='Close public administrative ingress',
        rationale='Administrative ingress from the internet requires immediate review.',
        kind='configure',
        pillar='security',
        evidence_codes=['ADMIN_INGRESS'],
        change_risk='high',
    ),
    'SNAPSHOT_EXPOSURE': _action(
        title='Review snapshot exposure',
        rationale='A public or broadly shared snapshot increases data-exfiltration risk.',
        kind='investigate',
        pillar='security',
        evidence_codes=['SNAPSHOT_EXPOSURE'],
    ),
    'ACCESS_AND_EXPOSURE': _action(
        title='Review access and exposure controls',
        rationale='Observed access settings fail the service-specific exposure check.',
        kind='investigate',
        pillar='security',
        evidence_codes=['ACCESS_AND_EXPOSURE'],
    ),
    'PROTECTED_INTENT': _action(
        title='Honor protection and retention intent',
        rationale='Recovery, retention, or deletion protection was detected; do not plan destructive changes without explicit approval.',
        kind='retain',
        pillar='reliability',
        evidence_codes=['PROTECTED_INTENT'],
        change_risk='low',
        confidence='high',
    ),
    'K8S_OOM_HISTORY': _action(
        title='Do not reduce memory until OOM history is cleared',
        rationale='OOMKill evidence blocks safe memory reduction.',
        kind='retain',
        pillar='reliability',
        evidence_codes=['K8S_OOM_HISTORY'],
    ),
    'K8S_CPU_THROTTLING': _action(
        title='Address CPU throttling before rightsizing',
        rationale='Sustained throttling indicates insufficient CPU headroom.',
        kind='investigate',
        pillar='performance',
        evidence_codes=['K8S_CPU_THROTTLING'],
    ),
    'K8S_SOURCE_RECONCILIATION': _action(
        title='Reconcile conflicting Kubernetes sources',
        rationale='Inventory sources disagree; resolve before automation or resize.',
        kind='verify',
        pillar='operations',
        evidence_codes=['K8S_SOURCE_RECONCILIATION'],
    ),
    'REQUEST_HEADROOM': _action(
        title='Review request sizing against measured P95',
        rationale='Saved utilization shows request headroom pressure; validate SLO impact before scale-down.',
        kind='investigate',
        pillar='performance',
        evidence_codes=['REQUEST_HEADROOM'],
    ),
    'DEPENDENCY_GRAPH': _action(
        title='Map dependencies before change',
        rationale='Active associations or incomplete dependency coverage require topology review.',
        kind='verify',
        pillar='operations',
        evidence_codes=['DEPENDENCY_GRAPH'],
    ),
}

_GAP_ACTIONS = {
    'BILLED_COST': _action(
        title='Import or sync billing for this resource',
        rationale='Resource-period billed charges are missing; cost decisions need imported billing evidence.',
        kind='verify',
        pillar='cost',
        evidence_codes=['BILLED_COST'],
        effort='low',
    ),
    'RETAIL_ESTIMATE': _action(
        title='Attach retail meter evidence',
        rationale='No verified retail run-rate is saved for this resource.',
        kind='verify',
        pillar='cost',
        evidence_codes=['RETAIL_ESTIMATE'],
        effort='low',
    ),
    'UTILIZATION_WINDOW': _action(
        title='Collect complete utilization history',
        rationale='Fourteen-day hourly utilization with validated coverage is required before inferring idle capacity.',
        kind='verify',
        pillar='performance',
        evidence_codes=['UTILIZATION_WINDOW'],
    ),
    'OWNERSHIP': _action(
        title='Assign and verify an owner',
        rationale='No ownership tag was supplied; confirm accountable owner before approval.',
        kind='verify',
        pillar='operations',
        evidence_codes=['OWNERSHIP'],
        effort='low',
    ),
    'OBSERVATION_FRESHNESS': _action(
        title='Run a new scan',
        rationale='The saved observation is stale or missing a timestamp; refresh before planning changes.',
        kind='verify',
        pillar='operations',
        evidence_codes=['OBSERVATION_FRESHNESS'],
        effort='low',
        change_risk='low',
    ),
}

_GUARDRAIL_STEPS = {
    'VERIFY_CURRENT_STATE': 'Confirm live state matches the saved observation.',
    'REVIEW_DEPENDENCIES': 'Review upstream and downstream dependencies.',
    'CONFIRM_OWNER_AND_RETENTION': 'Confirm owner, backup, and retention requirements.',
    'INDEPENDENT_CHANGE_APPROVAL': 'Obtain independent change approval outside this product.',
    'CREATE_PRE_DELETION_SNAPSHOT': 'Create an accepted pre-deletion snapshot where applicable.',
    'VERIFY_RESTORE_AND_RETENTION': 'Verify restore drills and retention policy.',
    'REFRESH_OBSERVATION': 'Run a new scan to refresh evidence.',
    'NO_DESTRUCTIVE_RECOMMENDATION': 'Do not execute destructive changes from estimates alone.',
    'INVENTORY_ONLY': 'This resource has no finding rule hit; review inventory evidence only.',
}


def _check_lookup(assessment):
    by_code = {}
    for pillar in assessment.get('pillars') or []:
        for check in pillar.get('checks') or []:
            by_code[check['code']] = dict(check, pillar=pillar.get('pillar', 'operations'))
    return by_code


def derive_action_items(assessment, findings=None, rule_evaluations=None, *, limit=12):
    """Return ordered, deduplicated action items for one resource assessment."""
    if not assessment or not isinstance(assessment, dict):
        return []
    items = []
    seen = set()

    def add(action):
        if not action:
            return
        key = (action['title'], action['kind'])
        if key in seen or len(items) >= limit:
            return
        seen.add(key)
        items.append(action)

    checks = _check_lookup(assessment)
    protected = assessment.get('disposition') == 'protected' or bool(assessment.get('protected_reasons'))

    for code in assessment.get('risk_check_codes') or []:
        if code in _RISK_ACTIONS:
            action = dict(_RISK_ACTIONS[code])
            if protected and action['kind'] == 'decommission':
                continue
            add(action)

    for evaluation in rule_evaluations or []:
        if evaluation.get('outcome') != 'condition_detected':
            continue
        rule = evaluation.get('rule_id') or 'rule'
        add(
            _action(
                title=f'Review {rule.replace("_", " ").title()}',
                rationale=evaluation.get('reason') or 'Rule evaluation detected a condition that needs human review.',
                kind='investigate' if not protected else 'verify',
                pillar='operations',
                evidence_codes=[rule],
                effort='medium',
            )
        )

    for finding in findings or []:
        rule = finding.get('rule_id')
        if not rule:
            continue
        add(
            _action(
                title=f'Investigate finding {rule}',
                rationale=finding.get('details') or 'A waste or risk finding is attached to this resource.',
                kind='investigate' if not protected else 'verify',
                pillar='cost',
                evidence_codes=[rule],
            )
        )

    for code in assessment.get('evidence_gap_codes') or []:
        if code in _GAP_ACTIONS:
            add(dict(_GAP_ACTIONS[code]))
        elif code in MODEL_BASE_CODES or code in checks:
            check = checks.get(code, {})
            add(
                _action(
                    title=f'Close evidence gap: {code.replace("_", " ").title()}',
                    rationale=check.get('explanation') or 'Required evidence for this check is incomplete.',
                    kind='verify',
                    pillar=check.get('pillar', 'operations'),
                    evidence_codes=[code],
                    effort='low',
                )
            )

    observation = assessment.get('observation') or {}
    if observation.get('status') in ('stale', 'invalid', 'unknown'):
        add(dict(_GAP_ACTIONS['OBSERVATION_FRESHNESS']))

    for guard in assessment.get('guardrails') or []:
        step = _GUARDRAIL_STEPS.get(guard)
        if not step:
            continue
        add(
            _action(
                title=guard.replace('_', ' ').title(),
                rationale=step,
                kind='verify',
                pillar='operations',
                evidence_codes=[guard],
                effort='low',
                change_risk='low',
                confidence='high',
            )
        )

    if protected and not any(i['kind'] == 'retain' for i in items):
        add(dict(_RISK_ACTIONS['PROTECTED_INTENT']))

    if assessment.get('disposition') == 'requires_review' and assessment.get('review_priority') == 'critical':
        add(
            _action(
                title='Prioritize critical review',
                rationale='Critical risk checks or exposure signals require review before any change.',
                kind='investigate',
                pillar='security',
                evidence_codes=assessment.get('risk_check_codes') or [],
                change_risk='high',
            )
        )

    return items[:limit]
