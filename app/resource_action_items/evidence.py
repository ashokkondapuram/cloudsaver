from app.assessment_policy import MODEL_BASE_CODES

from app.resource_action_items.common import action, check_lookup

GAP_ACTIONS = {
    'BILLED_COST': action(
        title='Import or sync billing for this resource',
        rationale='Resource-period billed charges are missing; cost decisions need imported billing evidence.',
        kind='verify',
        pillar='cost',
        category='evidence',
        evidence_codes=['BILLED_COST'],
        effort='low',
    ),
    'RETAIL_ESTIMATE': action(
        title='Attach retail meter evidence',
        rationale='No verified retail run-rate is saved for this resource.',
        kind='verify',
        pillar='cost',
        category='evidence',
        evidence_codes=['RETAIL_ESTIMATE'],
        effort='low',
    ),
    'UTILIZATION_WINDOW': action(
        title='Collect complete utilization history',
        rationale='Fourteen-day hourly utilization with validated coverage is required before inferring idle capacity.',
        kind='verify',
        pillar='performance',
        category='evidence',
        evidence_codes=['UTILIZATION_WINDOW'],
    ),
    'OWNERSHIP': action(
        title='Assign and verify an owner',
        rationale='No ownership tag was supplied; confirm accountable owner before approval.',
        kind='verify',
        pillar='operations',
        category='evidence',
        evidence_codes=['OWNERSHIP'],
        effort='low',
    ),
    'OBSERVATION_FRESHNESS': action(
        title='Run a new scan',
        rationale='The saved observation is stale or missing a timestamp; refresh before planning changes.',
        kind='verify',
        pillar='operations',
        category='evidence',
        evidence_codes=['OBSERVATION_FRESHNESS'],
        effort='low',
        change_risk='low',
    ),
}


def collect_evidence_items(assessment, *, add):
    checks = check_lookup(assessment)
    for code in assessment.get('evidence_gap_codes') or []:
        if code in GAP_ACTIONS:
            add(dict(GAP_ACTIONS[code]))
        elif code in MODEL_BASE_CODES or code in checks:
            check = checks.get(code, {})
            title = check.get('explanation') or 'Required evidence for this check is incomplete.'
            add(
                action(
                    title=f'Close evidence gap: {title.split(".")[0]}',
                    rationale=check.get('explanation') or title,
                    kind='verify',
                    pillar=check.get('pillar', 'operations'),
                    category='evidence',
                    evidence_codes=[code],
                    effort='low',
                )
            )
    observation = assessment.get('observation') or {}
    if observation.get('status') in ('stale', 'invalid', 'unknown'):
        add(dict(GAP_ACTIONS['OBSERVATION_FRESHNESS']))
