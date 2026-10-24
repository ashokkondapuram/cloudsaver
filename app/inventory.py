"""Canonical inventory travels with findings without breaking list-based collector callers."""


class FindingBatch(list):
    def __init__(self, findings, inventory, *, basis='supported_resource_types'):
        super().__init__(findings)
        self.inventory = inventory
        self.inventory_basis = basis


def observation(finding):
    return dict({key: value for key, value in finding.items()
                 if key not in ('rule_id', 'severity', 'details', 'estimated_monthly_waste_usd', 'cost_attribution')},
                inventory_rule_id=finding['rule_id'])


def coverage(inventory, findings, evaluations=()):
    """Coverage is about measured rule outcomes, never inferred from an absence of findings."""
    identities = lambda rows: {(r.get('cloud_provider', 'azure'), r['resource_id']) for r in rows}
    resources = identities(inventory)
    evaluated = identities(r for r in evaluations if r['outcome'] in ('condition_detected', 'condition_not_detected'))
    unknown = identities(r for r in evaluations if r['outcome'] == 'insufficient_evidence')
    excluded = identities(r for r in evaluations if r['outcome'] in ('excluded', 'excluded_by_exception'))
    unsupported = identities(r for r in evaluations if r['outcome'] == 'unsupported_by_collector')
    applicable = identities(evaluations)
    return dict(discovered_count=len(resources), in_scope_count=len(resources),
                evaluated_count=len(evaluated), insufficient_evidence_count=len(unknown),
                excluded_count=len(excluded), unsupported_count=len((resources - applicable) | unsupported),
                finding_resource_count=len(identities(findings)), failed_scopes=[],
                basis='collector_visible_supported_resource_types',
                count_semantics='resource sets may overlap across different rule outcomes')


def coverage_manifest(inventory, findings, evaluations=()):
    from app.assessment import category
    keys = sorted({(r.get('cloud_provider', 'azure'), r.get('service') or category(r)) for r in inventory})
    groups = []
    for provider, service in keys:
        rows = [r for r in inventory if r.get('cloud_provider', 'azure') == provider and (r.get('service') or category(r)) == service]
        ids = {r['resource_id'] for r in rows}
        matches = lambda values: [r for r in values if r.get('cloud_provider', 'azure') == provider and r['resource_id'] in ids]
        groups.append(dict(provider=provider, service=service, **coverage(rows, matches(findings), matches(evaluations))))
    return dict(schema_version='2', total=coverage(inventory, findings, evaluations), by_provider_service=groups,
                failed_scopes=[], partial=False, clean_baseline=True)
