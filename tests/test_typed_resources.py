"""Tests for typed resource tables and dual cost split."""
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from app.typed_resources.azure_schemas import (
    AZURE_COMPUTE_DISKS,
    extract_row_fields,
    TYPE_TO_SPEC,
)
from app.typed_resources.costs import reporting_currency


def test_extract_disk_fields():
    obs = {
        'evidence': {
            'typed_configuration': {
                'diskSizeGB': 128,
                'diskState': 'Attached',
                'sku': {'name': 'Premium_LRS', 'tier': 'Premium'},
            },
            'arm_sku': {'name': 'Premium_LRS', 'tier': 'Premium'},
        }
    }
    row = extract_row_fields(obs, AZURE_COMPUTE_DISKS)
    assert row['disk_size_gb'] == 128
    assert row['sku_name'] == 'Premium_LRS'


def test_reporting_currency_prefers_scan():
    assert reporting_currency({}, {'billing_currency': 'EUR'}) == 'EUR'
    assert reporting_currency({'billing_currency': 'CAD'}, {}) == 'CAD'


def test_split_costs_classifies_auto_sync():
    from app.typed_resources.costs import _split_costs

    db = MagicMock()
    db.execute.return_value.fetchall.return_value = [
        ('/subscriptions/x/resourceGroups/r/providers/Microsoft.Compute/disks/d1', 10, 9, 11, 'auto:abc', 'auto-sync:azure:sub'),
        ('/subscriptions/x/resourceGroups/r/providers/Microsoft.Compute/disks/d1', 5, 5, 5, 'focus:1', 'finops:import:2026-01'),
    ]
    out = _split_costs(
        db,
        'tenant',
        ['/subscriptions/x/.../disks/d1'],
        currency='USD',
        begin=__import__('datetime').date(2026, 1, 1),
        finish=__import__('datetime').date(2026, 2, 1),
        scopes=[('azure', 'sub')],
    )
    key = '/subscriptions/x/resourcegroups/r/providers/microsoft.compute/disks/d1'
    assert out[key]['azure_billed'] == Decimal(10)
    assert out[key]['cost_center_billed'] == Decimal(5)


def test_typed_tables_registered_in_arm_catalog():
    from app import azure_resource_registry as reg

    for rtype in TYPE_TO_SPEC:
        assert rtype in reg._CATALOG, f'typed table {rtype} missing from ARM catalog'


def test_typed_persistence_derives_missing_display_fields_from_native_id():
    from uuid import uuid4
    from app.typed_resources.persist import persist_typed_resource_row

    db = MagicMock()
    rid = '/subscriptions/sub/resourceGroups/Accounting/providers/Microsoft.Compute/disks/archive'
    table = persist_typed_resource_row(
        db, {'tenant_id': str(uuid4())}, str(uuid4()), '2026-11-07T00:00:00Z',
        {'resource_id': rid, 'subscription_id': 'sub', 'resource_type': 'Microsoft.Compute/disks'},
    )
    assert table == AZURE_COMPUTE_DISKS['table']
    statement, values = db.execute.call_args.args
    assert values[3:7] == [rid, 'sub', 'Accounting', 'archive']
    assert 'ON CONFLICT' in statement
