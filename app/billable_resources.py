"""Billable vs free resource types across Azure, AWS, GCP, and Kubernetes."""
from app.resource_catalog import FAMILIES, catalog, family

VERSION = '1.0.0'

# Topology and configuration objects: useful for dependencies, not default cost workspace rows.
FREE_RESOURCE_TYPES = {
    'azure': (
        'microsoft.network/networkinterfaces',
        'microsoft.network/networksecuritygroups',
        'microsoft.network/routetables',
        'microsoft.network/virtualnetworks',
        'microsoft.network/subnets',
        'microsoft.resources/resourcegroups',
    ),
    'aws': (
        'aws:ec2:security-group',
        'aws:ec2:network-interface',
        'aws:ec2:subnet',
        'aws:ec2:vpc',
        'aws:iam:role',
    ),
    'gcp': (
        'compute.googleapis.com/Subnetwork',
        'compute.googleapis.com/Firewall',
        'compute.googleapis.com/Network',
    ),
    'kubernetes': (
        'kubernetes.io/ConfigMap',
        'kubernetes.io/Secret',
        'kubernetes.io/Namespace',
    ),
}


def billable_types(provider):
    kinds = set()
    for entry_provider, _, _, types, _ in FAMILIES:
        if entry_provider == provider:
            kinds.update(kind.lower() for kind in types)
    return sorted(kinds)


def billable_types_by_provider():
    return {provider: billable_types(provider) for provider in ('azure', 'aws', 'gcp', 'kubernetes')}


def free_types(provider=None):
    if provider is None:
        return {key: list(values) for key, values in FREE_RESOURCE_TYPES.items()}
    return list(FREE_RESOURCE_TYPES.get(provider, ()))


def is_free_resource(row):
    provider = row.get('cloud_provider', 'azure')
    kind = row.get('resource_type', '').lower()
    return kind in {value.lower() for value in FREE_RESOURCE_TYPES.get(provider, ())}


def is_billable_resource(row):
    if is_free_resource(row):
        return False
    if family(row):
        return True
    evidence = row.get('evidence') or {}
    if row.get('estimated_monthly_waste_usd') is not None:
        return True
    if evidence.get('billed_cost_usd') is not None or evidence.get('effective_cost_usd') is not None:
        return True
    return False


def include_in_cost_workspace(assessment_row, *, observation=None):
    """Default workspace lists billable catalog resources and anything with cost or finding signal."""
    if assessment_row.get('finding_count', 0):
        return True
    if assessment_row.get('retail_estimate_usd') is not None:
        return True
    if assessment_row.get('billed_cost_usd') is not None:
        return True
    source = observation or dict(
        cloud_provider=assessment_row['provider'],
        resource_type=assessment_row.get('resource_type', ''),
        resource_id=assessment_row['resource_id'],
        evidence={},
    )
    return is_billable_resource(source)


def billable_catalog():
    families = catalog()
    by_provider = billable_types_by_provider()
    return dict(
        schema_version=VERSION,
        billable=dict(
            providers=by_provider,
            families=families,
            totals=dict(
                provider_count=len(by_provider),
                family_count=len(families),
                resource_type_count=sum(len(entry['resource_types']) for entry in families),
            ),
        ),
        free=dict(by_provider=free_types()),
        semantics=dict(
            billable='Metered SKUs in the v1.4 FinOps catalog (compute, storage, network egress paths, databases, AI endpoints).',
            free='Configuration and topology objects excluded from default cost views unless billing or finding evidence is present.',
        ),
    )
