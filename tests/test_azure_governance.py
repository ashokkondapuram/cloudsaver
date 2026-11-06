from app.collectors.azure_governance import fetch_advisor_recommendations, fetch_policy_states


class _Reader:
    def __init__(self, pages):
        self._pages = list(pages)
        self.calls = []

    def get(self, url, params=None):
        self.calls.append((url, params))
        if not self._pages:
            return {'value': []}
        return self._pages.pop(0)


def test_fetch_policy_states_maps_compliance():
    rid = '/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Compute/disks/d1'
    reader = _Reader([{'value': [{'properties': {
        'policyDefinitionName': 'require-tag',
        'policyAssignmentName': 'corp-tags',
        'complianceState': 'NonCompliant',
    }}]}])
    rows = fetch_policy_states(reader, dict(resource_id=rid, subscription_id='sub'))
    assert rows[0]['compliance_state'] == 'NonCompliant'
    assert rows[0]['policy_definition_name'] == 'require-tag'
    assert 'resourceId eq' in reader.calls[0][1]['$filter']


def test_fetch_advisor_recommendations_maps_problem():
    rid = '/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Compute/disks/d1'
    reader = _Reader([{'value': [{'name': 'rec-1', 'properties': {
        'category': 'Cost',
        'impact': 'High',
        'shortDescription': {'problem': 'Disk unused', 'solution': 'Delete disk'},
        'lastUpdated': '2026-11-01T00:00:00Z',
    }}]}])
    rows = fetch_advisor_recommendations(reader, dict(resource_id=rid, subscription_id='sub'))
    assert rows[0]['problem'] == 'Disk unused'
    assert rows[0]['impact'] == 'High'
