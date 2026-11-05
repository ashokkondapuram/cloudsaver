from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from app.azure_json_profile import (
    aggregate_rows,
    booked_savings_delta,
    build_snapshot,
    scale_retail_monthly,
    validate_window,
)
from app.financial_balance import resource_financial_balance


def test_validate_window_exclusive_end():
    start = date(2026, 9, 1)
    end = date(2026, 10, 1)
    assert validate_window(start, end) == 30


def test_aggregate_and_booked_savings():
    rows = [
        dict(day=date(2026, 9, 1), currency='USD', billed='5.00', effective='4.50'),
        dict(day=date(2026, 9, 2), currency='USD', billed='3.00', effective='3.00'),
    ]
    obs = aggregate_rows(rows, expected_days=2)
    assert obs['billed_cost_usd'] == 8.0
    assert obs['coverage_complete'] is True
    booked = booked_savings_delta(20.0, 8.0)
    assert booked == 12.0


def test_build_snapshot_with_mock_fetch():
    calls = []

    def fetch(scope_id, resource_id, tenant, start, end):
        calls.append((start, end))
        amount = '40.00' if start == date(2026, 8, 1) else '25.00'
        days = (end - start).days
        return [
            dict(
                day=start + timedelta(days=i),
                currency='USD',
                billed=amount,
                effective=amount,
            )
            for i in range(days)
        ]

    tenant = dict(tenant_id=str(uuid4()))
    scan_store = type('ScanStore', (), {})()
    scan_id = uuid4()
    resource = f'/subscriptions/{uuid4()}/resourceGroups/rg/providers/Microsoft.Compute/disks/d1'
    scan_store.get = lambda tid, sid: dict(
        scan_id=sid,
        findings=[dict(cloud_provider='azure', resource_id=resource, retail_estimate_usd=30.0)],
        inventory=[],
    )

    snapshot = build_snapshot(
        tenant=tenant,
        scope_id=str(uuid4()),
        resource_id=resource,
        observation_start=date(2026, 9, 1),
        observation_end=date(2026, 10, 2),
        baseline_start=date(2026, 8, 1),
        baseline_end=date(2026, 9, 1),
        scan_id=scan_id,
        scan_store=scan_store,
        evidence_store=None,
        findings=[dict(estimated_monthly_waste_usd=10.0)],
        fetch_rows=fetch,
    )
    assert snapshot['observation']['billed_cost_usd'] == 25.0 * 31
    assert snapshot['baseline']['billed_cost_usd'] == 40.0 * 31
    assert snapshot['booked_savings_usd'] == snapshot['baseline']['billed_cost_usd'] - snapshot['observation']['billed_cost_usd']
    assert snapshot['retail']['monthly_run_rate_usd'] == 30.0
    assert snapshot['retail']['window_run_rate_usd'] == scale_retail_monthly(30.0, 31)
    assert snapshot['balance']['billed_vs_retail_usd'] is not None
    assert len(calls) == 2


def test_scale_retail_monthly():
    assert scale_retail_monthly(30, 30) == 30.0
    assert resource_financial_balance(
        billed_cost_usd=10,
        effective_cost_usd=9,
        retail_run_rate_usd=12,
        opportunity=None,
    )['retail_list_savings_usd'] == 2.0
