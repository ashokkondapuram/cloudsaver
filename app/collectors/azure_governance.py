"""Read-only Azure Policy compliance and Advisor recommendations for one resource."""
from __future__ import annotations

from app.collectors.azure_endpoint import arm_url
from app.collectors.azure_live import pages
from app.collectors.live_common import collect

ADVISOR_API = '2023-01-01'
POLICY_API = '2019-10-01'
_MAX_ROWS = 40


def _odata_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def fetch_advisor_recommendations(reader, resource):
    rid = resource.get('resource_id') or ''
    sub = resource.get('subscription_id') or ''
    if not rid or not sub:
        return []
    url = arm_url(f'/subscriptions/{sub}/providers/Microsoft.Advisor/recommendations')
    params = {
        'api-version': ADVISOR_API,
        '$filter': f'ResourceId eq {_odata_string(rid)}',
    }
    rows = []
    for item in pages(reader, url, params):
        props = item.get('properties') or {}
        short = props.get('shortDescription') or {}
        rows.append(
            dict(
                recommendation_id=item.get('name'),
                category=props.get('category'),
                impact=props.get('impact'),
                problem=short.get('problem'),
                solution=short.get('solution'),
                last_updated=props.get('lastUpdated'),
                risk=props.get('risk'),
            )
        )
        if len(rows) >= _MAX_ROWS:
            break
    return rows


def fetch_policy_states(reader, resource):
    rid = (resource.get('resource_id') or '').lower()
    sub = resource.get('subscription_id') or ''
    if not rid or not sub:
        return []
    url = arm_url(f'/subscriptions/{sub}/providers/Microsoft.PolicyInsights/policyStates/latest/queryResults')
    params = {
        'api-version': POLICY_API,
        '$filter': f'resourceId eq {_odata_string(rid)}',
    }
    rows = []
    for item in pages(reader, url, params):
        props = item.get('properties') or item
        if not isinstance(props, dict):
            continue
        rows.append(
            dict(
                policy_definition_id=props.get('policyDefinitionId'),
                policy_definition_name=props.get('policyDefinitionName'),
                policy_assignment_id=props.get('policyAssignmentId'),
                policy_assignment_name=props.get('policyAssignmentName'),
                policy_set_definition_name=props.get('policySetDefinitionName'),
                compliance_state=props.get('complianceState'),
                timestamp=props.get('timestamp'),
            )
        )
        if len(rows) >= _MAX_ROWS:
            break
    return rows


def enrich_azure_governance_row(reader, resource) -> dict:
    """Attach policy and Advisor rows to resource evidence (Azure only)."""
    if (resource.get('cloud_provider') or 'azure') != 'azure':
        return resource
    evidence = resource.setdefault('evidence', {})
    policies = collect(evidence, 'azure_policy', lambda: fetch_policy_states(reader, resource))
    if policies is not None:
        evidence['azure_policy_states'] = policies
    advisor = collect(evidence, 'advisor', lambda: fetch_advisor_recommendations(reader, resource))
    if advisor is not None:
        evidence['azure_advisor_recommendations'] = advisor
    return resource


def governance_on_scan(settings=None) -> bool:
    from app.cloudsaver_platform_settings import integration_flag

    return integration_flag(settings, 'azure_governance_on_scan', 'CLOUDSAVER_AZURE_GOVERNANCE_ON_SCAN')
