from app.resource_action_items.common import action

RISK_ACTIONS = {
    'PUBLIC_DATABASE': action(
        title='Remove public database access',
        rationale='Public accessibility is reported enabled; confirm network path and disable exposure before other changes.',
        kind='configure',
        pillar='security',
        category='risk',
        evidence_codes=['PUBLIC_DATABASE'],
        change_risk='high',
    ),
    'ENCRYPTION_AT_REST': action(
        title='Enable encryption at rest',
        rationale='Encryption is disabled or unverified; fix before capacity or lifecycle changes.',
        kind='configure',
        pillar='security',
        category='risk',
        evidence_codes=['ENCRYPTION_AT_REST'],
        change_risk='high',
    ),
    'ADMIN_INGRESS': action(
        title='Close public administrative ingress',
        rationale='Administrative ingress from the internet requires immediate review.',
        kind='configure',
        pillar='security',
        category='risk',
        evidence_codes=['ADMIN_INGRESS'],
        change_risk='high',
    ),
    'SNAPSHOT_EXPOSURE': action(
        title='Review snapshot exposure',
        rationale='A public or broadly shared snapshot increases data-exfiltration risk.',
        kind='investigate',
        pillar='security',
        category='risk',
        evidence_codes=['SNAPSHOT_EXPOSURE'],
    ),
    'ACCESS_AND_EXPOSURE': action(
        title='Review access and exposure controls',
        rationale='Observed access settings fail the service-specific exposure check.',
        kind='investigate',
        pillar='security',
        category='risk',
        evidence_codes=['ACCESS_AND_EXPOSURE'],
    ),
    'PROTECTED_INTENT': action(
        title='Honor protection and retention intent',
        rationale='Recovery, retention, or deletion protection was detected; do not plan destructive changes without explicit approval.',
        kind='retain',
        pillar='reliability',
        category='risk',
        evidence_codes=['PROTECTED_INTENT'],
        change_risk='low',
        confidence='high',
    ),
    'K8S_OOM_HISTORY': action(
        title='Do not reduce memory until OOM history is cleared',
        rationale='OOMKill evidence blocks safe memory reduction.',
        kind='retain',
        pillar='reliability',
        category='risk',
        evidence_codes=['K8S_OOM_HISTORY'],
    ),
    'K8S_CPU_THROTTLING': action(
        title='Address CPU throttling before rightsizing',
        rationale='Sustained throttling indicates insufficient CPU headroom.',
        kind='investigate',
        pillar='performance',
        category='risk',
        evidence_codes=['K8S_CPU_THROTTLING'],
    ),
    'K8S_SOURCE_RECONCILIATION': action(
        title='Reconcile conflicting Kubernetes sources',
        rationale='Inventory sources disagree; resolve before automation or resize.',
        kind='verify',
        pillar='operations',
        category='risk',
        evidence_codes=['K8S_SOURCE_RECONCILIATION'],
    ),
    'REQUEST_HEADROOM': action(
        title='Review request sizing against measured P95',
        rationale='Saved utilization shows request headroom pressure; validate SLO impact before scale-down.',
        kind='investigate',
        pillar='performance',
        category='risk',
        evidence_codes=['REQUEST_HEADROOM'],
    ),
    'DEPENDENCY_GRAPH': action(
        title='Map dependencies before change',
        rationale='Active associations or incomplete dependency coverage require topology review.',
        kind='verify',
        pillar='operations',
        category='risk',
        evidence_codes=['DEPENDENCY_GRAPH'],
    ),
}


def collect_risk_items(assessment, *, add, protected):
    for code in assessment.get('risk_check_codes') or []:
        if code not in RISK_ACTIONS:
            continue
        item = dict(RISK_ACTIONS[code])
        if protected and item['kind'] == 'decommission':
            continue
        add(item)
