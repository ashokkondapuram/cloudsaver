from datetime import date
from decimal import Decimal

from app.collectors.billing_sync import (
    COST_SOURCE_ACTUAL_BILLED,
    _accumulate_cost_amount,
    _cost_row_from_totals,
)


def test_cost_merge_keeps_absent_component_null():
    key = (date(2026, 9, 1), '/subscriptions/x/resourceGroups/rg/providers/Microsoft.Compute/disks/d1', 'USD')
    merged = {}
    _accumulate_cost_amount(merged, key, 'effective', Decimal('3.50'))
    row = _cost_row_from_totals(key[0], key[1], key[2], merged[key])
    assert row['billed'] is None
    assert row['effective'] == '3.50'
    assert row['billed_present'] is False
    assert row['effective_present'] is True
    assert row['cost_source'] == COST_SOURCE_ACTUAL_BILLED
