from app.billable_resources import (
    billable_catalog,
    billable_types,
    include_in_cost_workspace,
    is_billable_resource,
    is_free_resource,
)
from app.resource_catalog import FAMILIES


def test_billable_catalog_covers_all_v14_families():
    payload = billable_catalog()
    assert payload['billable']['totals']['family_count'] == len(FAMILIES)
    assert len(billable_types('azure')) >= 10
    assert 'microsoft.network/networkinterfaces' in payload['free']['by_provider']['azure']


def test_free_resources_are_excluded_from_default_cost_workspace():
    nic = dict(cloud_provider='azure', resource_type='microsoft.network/networkinterfaces', resource_id='/x/nic')
    assert is_free_resource(nic) and not is_billable_resource(nic)
    row = dict(provider='azure', resource_id='/x/nic', resource_type='microsoft.network/networkinterfaces',
               finding_count=0, retail_estimate_usd=None, billed_cost_usd=None)
    assert include_in_cost_workspace(row, observation=nic) is False


def test_billable_disk_with_billing_stays_in_cost_workspace():
    disk = dict(cloud_provider='azure', resource_type='microsoft.compute/disks', resource_id='/x/disk', evidence={'billed_cost_usd': 3})
    assert is_billable_resource(disk)
    row = dict(provider='azure', resource_id='/x/disk', resource_type='microsoft.compute/disks',
               finding_count=0, retail_estimate_usd=None, billed_cost_usd=3)
    assert include_in_cost_workspace(row, observation=disk)
