from app.resource_action_items.common import action


def collect_finding_items(assessment, findings, rule_evaluations, *, add, protected):
    for evaluation in rule_evaluations or []:
        if evaluation.get('outcome') != 'condition_detected':
            continue
        rule = evaluation.get('rule_id') or 'rule'
        add(
            action(
                title=f'Review {rule.replace("_", " ").title()}',
                rationale=evaluation.get('reason') or 'Rule evaluation detected a condition that needs human review.',
                kind='investigate' if not protected else 'verify',
                pillar='operations',
                category='finding',
                evidence_codes=[rule],
                effort='medium',
            )
        )

    for finding in findings or []:
        rule = finding.get('rule_id')
        if not rule:
            continue
        add(
            action(
                title=f'Investigate finding {rule}',
                rationale=finding.get('details') or 'A waste or risk finding is attached to this resource.',
                kind='investigate' if not protected else 'verify',
                pillar='cost',
                category='finding',
                evidence_codes=[rule],
            )
        )
