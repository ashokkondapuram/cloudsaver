from app.resource_action_items.common import action


def collect_finding_items(assessment, findings, rule_evaluations, *, add, protected):
    seen_rules: set[str] = set()

    def add_rule_action(rule_id, *, title, rationale, pillar):
        if rule_id in seen_rules:
            return
        seen_rules.add(rule_id)
        add(
            action(
                title=title,
                rationale=rationale,
                kind='investigate' if not protected else 'verify',
                pillar=pillar,
                category='finding',
                evidence_codes=[rule_id],
                effort='medium',
            )
        )

    for evaluation in rule_evaluations or []:
        if evaluation.get('outcome') != 'condition_detected':
            continue
        rule = evaluation.get('rule_id') or 'rule'
        add_rule_action(
            rule,
            title=f'Review {rule.replace("_", " ").title()}',
            rationale=evaluation.get('reason') or 'Rule evaluation detected a condition that needs human review.',
            pillar='operations',
        )

    for finding in findings or []:
        rule = finding.get('rule_id')
        if not rule:
            continue
        add_rule_action(
            rule,
            title=f'Investigate finding {rule}',
            rationale=finding.get('details') or 'A waste or risk finding is attached to this resource.',
            pillar='cost',
        )
