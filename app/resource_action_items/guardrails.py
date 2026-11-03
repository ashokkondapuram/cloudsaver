from app.resource_action_items.common import action
from app.resource_action_items.risk import RISK_ACTIONS

GUARDRAIL_STEPS = {
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


def collect_guardrail_items(assessment, *, add):
    for guard in assessment.get('guardrails') or []:
        step = GUARDRAIL_STEPS.get(guard)
        if not step:
            continue
        add(
            action(
                title=guard.replace('_', ' ').title(),
                rationale=step,
                kind='verify',
                pillar='operations',
                category='guardrail',
                evidence_codes=[guard],
                effort='low',
                change_risk='low',
                confidence='high',
            )
        )


def collect_priority_items(assessment, *, add, protected, items):
    if protected and not any(i['kind'] == 'retain' for i in items):
        add(dict(RISK_ACTIONS['PROTECTED_INTENT']))

    if assessment.get('disposition') == 'requires_review' and assessment.get('review_priority') == 'critical':
        add(
            action(
                title='Prioritize critical review',
                rationale='Critical risk checks or exposure signals require review before any change.',
                kind='investigate',
                pillar='security',
                category='priority',
                evidence_codes=assessment.get('risk_check_codes') or [],
                change_risk='high',
            )
        )
