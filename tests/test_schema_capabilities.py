"""Schema capability probes and resource list ARM detail filtering."""
import pytest

from app.resource_assessment import matches


def test_postgres_schema_capabilities_empty_without_database():
    from app.schema_capabilities import postgres_schema_capabilities
    assert postgres_schema_capabilities('') == {}


def test_arm_detail_filter_on_inventory_rows():
    items = [
        {'provider': 'azure', 'service_category': 'compute', 'review_priority': 'high', 'ai': {'status': 'not_run', 'risk_level': None},
         'decision': None, 'pillars': {}, 'resource_name': 'a', 'resource_id': '/a', 'arm_detail': 'collected'},
        {'provider': 'azure', 'service_category': 'compute', 'review_priority': 'high', 'ai': {'status': 'not_run', 'risk_level': None},
         'decision': None, 'pillars': {}, 'resource_name': 'b', 'resource_id': '/b', 'arm_detail': 'fetch_failed'},
    ]
    filters = dict.fromkeys(('provider', 'service_category', 'review_priority', 'ai_status', 'ai_risk', 'decision', 'pillar_status'))
    assert all(matches(i, filters) for i in items)
    collected = [i for i in items if i.get('arm_detail') == 'collected']
    assert len(collected) == 1


class _Result:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class _Db:
    def __init__(self, rows):
        self._rows = iter(rows)

    def execute(self, sql, params=None):
        return _Result(next(self._rows, None))


def test_require_platform_outbox_lease_columns_skips_when_table_missing():
    from app.schema_capabilities import require_platform_outbox_lease_columns
    require_platform_outbox_lease_columns(_Db([None]))


def test_require_platform_outbox_lease_columns_raises_when_fence_missing():
    from app.schema_capabilities import require_platform_outbox_lease_columns
    with pytest.raises(ValueError, match='0033_platform_outbox_lease'):
        require_platform_outbox_lease_columns(_Db([(1,), None]))
