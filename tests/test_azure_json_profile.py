from datetime import date, timedelta
from uuid import uuid4

from app.azure_json_profile import fetch_azure_resource_profile
from app.azure_rest_catalog import parse_arm_resource_type


def test_parse_arm_resource_type():
    rid = '/subscriptions/x/resourceGroups/rg/providers/Microsoft.Compute/disks/d1'
    assert parse_arm_resource_type(rid) == 'microsoft.compute/disks'


def test_fetch_profile_composes_json(monkeypatch):
    monkeypatch.setattr(
        'app.azure_json_profile._fetch_arm_json',
        lambda tenant, scope, rid: dict(status='ok', resource_type='microsoft.compute/disks', location='eastus'),
    )
    tenant = dict(tenant_id=str(uuid4()))

    def fetch(scope_id, resource_id, tenant, start, end):
        days = (end - start).days
        return [
            dict(day=start + timedelta(days=i), currency='USD', billed='1.00', effective='1.00')
            for i in range(days)
        ]

    resource = f'/subscriptions/{uuid4()}/resourceGroups/rg/providers/Microsoft.Compute/disks/d1'
    profile = fetch_azure_resource_profile(
        tenant=tenant,
        scope_id=str(uuid4()),
        resource_id=resource,
        observation_start=date(2026, 9, 1),
        observation_end=date(2026, 10, 1),
        baseline_start=date(2026, 8, 1),
        baseline_end=date(2026, 9, 1),
        fetch_rows=fetch,
    )
    assert profile['schema_version'] == '1'
    assert profile['arm']['status'] == 'ok'
    assert profile['cost_management']['observation']['billed_cost_usd'] == 30.0
    assert profile['financial']['booked_savings_usd'] is not None
    assert any(item['operation'] == 'cost_management_query' for item in profile['azure_rest_catalog'])
