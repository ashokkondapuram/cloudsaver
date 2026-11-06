from datetime import date
from decimal import Decimal

from app.collectors.billing_sync import (
    COST_SOURCE_ACTUAL_BILLED,
    COST_SOURCE_FOCUS_IMPORT,
    COST_SOURCE_RETAIL_ESTIMATED,
    _accumulate_cost_amount,
    _cost_row_from_totals,
    focus_import_observation_row,
    retail_estimated_observation_row,
)


def test_merge_helper_tags_actual_billed():
    key = (date(2026, 9, 1), '/subscriptions/x/resourceGroups/rg/providers/Microsoft.Compute/disks/d1', 'USD')
    merged = {}
    _accumulate_cost_amount(merged, key, 'billed', Decimal('2'))
    _accumulate_cost_amount(merged, key, 'effective', Decimal('1.5'))
    row = _cost_row_from_totals(key[0], key[1], key[2], merged[key])
    assert row['cost_source'] == COST_SOURCE_ACTUAL_BILLED


def test_focus_import_observation_row():
    row = focus_import_observation_row(
        date(2026, 10, 1),
        '/subscriptions/x/resourceGroups/rg/providers/Microsoft.Compute/disks/d1',
        'USD',
        billed='9.50',
        effective='9.50',
        category='Usage',
    )
    assert row['cost_source'] == COST_SOURCE_FOCUS_IMPORT
    assert row['billed'] == '9.50'


def test_retail_estimated_observation_row():
    row = retail_estimated_observation_row(
        date(2026, 10, 1),
        'i-abc',
        'USD',
        billed='12',
    )
    assert row['cost_source'] == COST_SOURCE_RETAIL_ESTIMATED
    assert row['effective'] is None
    assert row['effective_present'] is False
