import pytest

from app.azure_resource_registry import arm_api_version, catalog_entries, normalize_arm_body, supports_arm_detail


def test_catalog_lists_known_types():
    entries = catalog_entries()
    assert entries
    assert all(entry['provider'] == 'azure' for entry in entries)
    assert supports_arm_detail('Microsoft.Compute/disks')


def test_normalize_strips_secret_like_keys():
    body = {
        'id': '/subscriptions/x/resourceGroups/r/providers/Microsoft.Compute/disks/d1',
        'type': 'Microsoft.Compute/disks',
        'location': 'eastus',
        'properties': {
            'diskSizeGB': 128,
            'diskState': 'Attached',
            'encryption': {'type': 'EncryptionAtRestWithPlatformKey'},
            'connectionString': 'must-not-appear',
            'creationData': {'createOption': 'Empty'},
        },
    }
    normalized = normalize_arm_body(body)
    assert normalized['typed_configuration']['diskSizeGB'] == 128
    assert normalized['typed_configuration']['creationData']['createOption'] == 'Empty'
    assert 'connectionString' not in str(normalized)


def test_resolve_arm_api_version_from_provider_metadata():
    from app.azure_resource_registry import resolve_arm_api_version

    class Reader:
        def get(self, url, params=None):
            assert url.startswith('https://management.azure.com/')
            if 'Microsoft.Network' in url:
                return {'resourceTypes': []}
            assert 'Microsoft.Compute' in url
            return {
                'resourceTypes': [
                    {'resourceType': 'disks', 'apiVersions': ['2023-04-02', '2022-03-02']},
                ],
            }

    cache = {}
    version = resolve_arm_api_version(Reader(), 'sub-id', 'microsoft.network/loadbalancers', cache)
    assert version == '2023-05-01'
    version = resolve_arm_api_version(Reader(), 'sub-id', 'microsoft.compute/disks', cache)
    assert version == '2023-04-02'


def test_arm_api_version_for_disk():
    assert arm_api_version('microsoft.compute/disks') == '2023-04-02'


def test_enrich_arm_details_attaches_configuration():
    from app.collectors.azure_arm_detail import enrich_arm_details
    from app.collectors.azure_endpoint import validate_arm_resource_path

    rid = '/subscriptions/s/resourceGroups/r/providers/Microsoft.Compute/disks/d1'
    validate_arm_resource_path(rid, scope_path_lower='/subscriptions/s/resourcegroups/r')

    inventory = [{
        'resource_id': '/subscriptions/s/resourceGroups/r/providers/Microsoft.Compute/disks/d1',
        'resource_type': 'Microsoft.Compute/disks',
        'subscription_id': 's',
        'evidence': {},
    }]

    class Reader:
        def get(self, url, params=None):
            assert url.startswith('https://management.azure.com/')
            assert params == {'api-version': '2023-04-02'}
            return {
                'id': inventory[0]['resource_id'],
                'type': 'Microsoft.Compute/disks',
                'location': 'eastus',
                'properties': {'diskSizeGB': 64, 'diskState': 'Unattached'},
            }

    enrich_arm_details(Reader(), inventory)
    evidence = inventory[0]['evidence']
    assert evidence['arm_detail'] == 'collected'
    assert evidence['typed_configuration']['diskSizeGB'] == 64
    assert evidence.get('arm_fetched_at')


def test_enrich_arm_details_metadata_failure_stays_per_resource(monkeypatch):
    from app.collectors.azure_arm_detail import enrich_arm_details

    inventory = [{
        'resource_id': '/subscriptions/s/resourceGroups/r/providers/Microsoft.Custom/widgets/w1',
        'resource_type': 'Microsoft.Custom/widgets',
        'subscription_id': 's',
        'evidence': {},
    }]

    class Reader:
        def get(self, url, params=None):
            raise RuntimeError('provider metadata unavailable')

    enrich_arm_details(Reader(), inventory, settings={'integrations': {'azure_arm_detail_max': 5}})
    assert inventory[0]['evidence']['arm_detail'] == 'fetch_failed'


def test_enrich_arm_details_attempt_budget_counts_metadata_calls(monkeypatch):
    from app.collectors import azure_arm_detail

    monkeypatch.setattr(azure_arm_detail, '_max_attempts', lambda settings=None: 1)

    inventory = [
        {
            'resource_id': '/subscriptions/s/resourceGroups/r/providers/Microsoft.Custom/widgets/w1',
            'resource_type': 'Microsoft.Custom/widgets',
            'subscription_id': 's',
            'evidence': {},
        },
        {
            'resource_id': '/subscriptions/s/resourceGroups/r/providers/Microsoft.Custom/widgets/w2',
            'resource_type': 'Microsoft.Custom/widgets',
            'subscription_id': 's',
            'evidence': {},
        },
    ]

    class Reader:
        def get(self, url, params=None):
            return {'resourceTypes': []}

    from app.collectors.azure_arm_detail import enrich_arm_details

    enrich_arm_details(Reader(), inventory)
    assert inventory[0]['evidence']['arm_detail'] == 'api_version_unresolved'
    assert inventory[1]['evidence']['arm_detail'] == 'resource_budget_exceeded'
