from app.resource_action_items.common import action
from app.resource_catalog import display_name


def _finding_snapshot(finding):
    return dict(finding)


def collect_finding_items(assessment, findings, rule_evaluations, *, add, protected):
    seen_rules: set[str] = set()

    def add_rule_action(rule_id, *, title, rationale, pillar, finding_evidence=None):
        if rule_id in seen_rules:
            return
        seen_rules.add(rule_id)
        payload = action(
            title=title,
            rationale=rationale,
            kind='investigate' if not protected else 'verify',
            pillar=pillar,
            category='finding',
            evidence_codes=[],
            effort='medium',
        )
        if finding_evidence is not None:
            payload['finding_evidence'] = finding_evidence
        add(payload)

    for evaluation in rule_evaluations or []:
        if evaluation.get('outcome') != 'condition_detected':
            continue
        rule = evaluation.get('rule_id') or 'rule'
        add_rule_action(
            rule,
            title=f'Review {display_name(rule)}',
            rationale=evaluation.get('reason') or 'Rule evaluation detected a condition that needs human review.',
            pillar='operations',
        )

    for finding in findings or []:
        rule = finding.get('rule_id')
        if not rule:
            continue
        add_rule_action(
            rule,
            title=f'Investigate {display_name(rule)}',
            rationale=finding.get('details') or 'A waste or risk finding is attached to this resource.',
            pillar='cost',
            finding_evidence=_finding_snapshot(finding),
        )
