from app.evidence_extraction import (
    attach_action_item_evidence,
    attach_check_evidence,
    effective_observation_evidence,
    snapshot_for_fields,
)


def test_snapshot_dependency_graph():
    obs = {'dependency_refs': [{'relationship': 'vm_to_disk', 'from_resource_id': '/vm', 'to_resource_id': '/disk', 'verification_state': 'verified'}]}
    snap = snapshot_for_fields({}, [], observation=obs, code='DEPENDENCY_GRAPH')
    assert snap['dependency_refs'][0]['relationship'] == 'vm_to_disk'


def test_attach_check_evidence_includes_json():
    assessment = {
        'pillars': [
            {
                'pillar': 'cost',
                'checks': [
                    {
                        'code': 'BILLED_COST',
                        'evidence_fields': ['billed_cost_usd'],
                        'pillar': 'cost',
                        'status': 'unknown',
                        'explanation': 'missing',
                    }
                ],
            }
        ]
    }
    observation = {'evidence': {'billed_cost_usd': 12.5, 'currency': 'USD'}}
    attach_check_evidence(assessment, observation)
    assert assessment['pillars'][0]['checks'][0]['evidence_json']['billed_cost_usd'] == 12.5


def test_action_item_evidence_from_check():
    assessment = attach_check_evidence(
        {
            'pillars': [
                {
                    'pillar': 'reliability',
                    'checks': [
                        {
                            'code': 'HEALTH_PROBES',
                            'evidence_fields': ['health_probes_enabled'],
                            'pillar': 'reliability',
                            'status': 'observed',
                            'explanation': 'ok',
                        }
                    ],
                }
            ]
        },
        {'evidence': {'health_probes_enabled': True, 'health_check_paths': ['/health']}},
    )
    items = attach_action_item_evidence(
        [
            {
                'title': 'Close evidence gap: Health Probes',
                'rationale': 'x',
                'kind': 'verify',
                'pillar': 'reliability',
                'evidence_codes': ['HEALTH_PROBES'],
                'effort': 'low',
                'change_risk': 'medium',
                'confidence': 'high',
                'prerequisites': [],
            }
        ],
        assessment,
        {'evidence': {'health_probes_enabled': True}},
    )
    assert items[0]['evidence_json']['health_probes_enabled'] is True


def test_attach_check_uses_configuration_snapshot_and_typed_configuration():
    assessment = {
        'pillars': [
            {
                'pillar': 'security',
                'checks': [
                    {
                        'code': 'ACCESS_AND_EXPOSURE',
                        'evidence_fields': ['https_only'],
                        'pillar': 'security',
                        'status': 'observed',
                        'explanation': 'ok',
                    }
                ],
            }
        ]
    }
    observation = {
        'resource_type': 'Microsoft.Web/sites',
        'resource_id': '/subscriptions/s/resourceGroups/rg/providers/Microsoft.Web/sites/app1',
        'evidence': {},
        'configuration_snapshot': {
            'typed_configuration': {'httpsOnly': True, 'siteConfig': {'minTlsVersion': '1.2'}},
        },
    }
    attach_check_evidence(assessment, observation)
    payload = assessment['pillars'][0]['checks'][0]['evidence_json']
    assert payload.get('https_only') is True or payload.get('configuration', {}).get('httpsOnly') is True


def test_effective_observation_evidence_projects_hosted_app_count():
    observation = {
        'resource_type': 'Microsoft.Web/serverFarms',
        'resource_id': '/subscriptions/s/resourceGroups/rg/providers/Microsoft.Web/serverFarms/plan1',
        'evidence': {},
        'configuration_snapshot': {'hosted_app_count': 2, 'sku_tier': 'Standard'},
    }
    evidence = effective_observation_evidence(observation)
    assert evidence['hosted_app_count'] == 2
    assert evidence.get('sku_tier') == 'Standard'
