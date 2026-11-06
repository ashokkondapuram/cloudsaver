from app.resources_redis import _resource_from_cached, redis_is_newer


def test_redis_prefers_resource_while_refresh_in_progress():
    db = {'resource_id': '/subscriptions/x/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1', 'evidence': {'last_analyzed_at': '2026-11-05T10:00:00Z'}}
    cached = {
        'updated_at': '2026-11-05T10:05:00Z',
        'refresh_in_progress': True,
        'resource': {
            'resource_id': db['resource_id'],
            'resource_name': 'vm-live',
            'evidence': {
                'last_analyzed_at': '2026-11-05T10:00:00Z',
                'azure_status_fetched_at': '2026-11-05T10:05:00Z',
                'fetch_stages': {'analysis': 'running'},
            },
        },
        'findings': [{'resource_id': db['resource_id'], 'rule_id': 'idle-vm'}],
    }
    assert redis_is_newer(cached, db) is True
    resource = _resource_from_cached(cached)
    assert resource['resource_name'] == 'vm-live'
    assert cached['findings'][0]['rule_id'] == 'idle-vm'


def test_redis_keeps_db_when_older():
    db = {
        'resource_id': '/subscriptions/x/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1',
        'evidence': {
            'last_analyzed_at': '2026-11-05T12:00:00Z',
            'azure_status_fetched_at': '2026-11-05T12:00:00Z',
        },
    }
    cached = {
        'updated_at': '2026-11-05T11:00:00Z',
        'refresh_in_progress': False,
        'resource': {
            'resource_id': db['resource_id'],
            'evidence': {'last_analyzed_at': '2026-11-05T10:00:00Z'},
        },
    }
    assert redis_is_newer(cached, db) is False
