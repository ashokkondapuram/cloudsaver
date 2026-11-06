from datetime import date, timedelta
from uuid import uuid4

import pytest

from app.analysis_service.billing_enrich import (
    daily_cost_spike_pct,
    effective_discount_rate,
    enrich_inventory_billing_evidence,
    target_sku_retail_monthly_usd,
)
from app.analysis_service.loader import context_from_inventory_row
from app.collectors.billing_sync import COST_SOURCE_ACTUAL_BILLED, COST_SOURCE_RETAIL_ESTIMATED
from app.focus import FocusRepository, ImportRequest
from tests.support import azure_disk_finding
from tests.test_ai_advisory import SUB
from tests.test_enterprise import batch, charge, workspace
from tests.test_v140 import NOW

pytest_plugins = ['tests.test_enterprise']


def test_daily_cost_spike_pct_from_synthetic_rows():
    rows = [dict(day=date(2026, 10, day), effective_cost_usd=10.0) for day in range(1, 30)]
    rows.append(dict(day=date(2026, 10, 30), effective_cost_usd=14.0))
    assert daily_cost_spike_pct(rows) == pytest.approx(40.0)


def test_effective_discount_rate_from_retail_and_amortized():
    assert effective_discount_rate(retail=100.0, amortized=85.0) == pytest.approx(0.15)


def test_target_sku_retail_from_pricing_evidence():
    evidence = dict(
        pricing_evidence=dict(
            target_retail_monthly_usd=60.0,
        )
    )
    assert target_sku_retail_monthly_usd(evidence) == 60.0


def test_enrich_inventory_billing_evidence_sets_analysis_fields():
    evidence = dict(
        billed_cost_usd=11.0,
        effective_cost_usd=9.0,
        retail_estimate_usd=10.0,
        pricing_evidence=dict(target_retail_monthly_usd=6.0),
    )
    daily = [
        dict(day=date(2026, 10, 1), effective_cost_usd=1.0),
        dict(day=date(2026, 10, 2), effective_cost_usd=3.0),
    ]
    enrich_inventory_billing_evidence(evidence, daily_rows=daily)
    assert evidence['cost_source'] == COST_SOURCE_ACTUAL_BILLED
    assert evidence['effective_discount_rate'] == pytest.approx(0.1)
    assert evidence['target_sku_retail_monthly_usd'] == 6.0
    assert evidence['daily_cost_spike_pct'] == pytest.approx(200.0)


def test_focus_attach_enriches_inventory_evidence(evidence):
    _, store, _ = evidence
    repo = FocusRepository(store)
    tenant = workspace()
    disk = azure_disk_finding(SUB)
    end = NOW.replace(hour=0, minute=0, second=0, microsecond=0)
    start = end - timedelta(days=30)
    records = []
    for offset in range(29):
        day = start + timedelta(days=offset)
        records.append(
            charge(
                offset + 1,
                '1.00',
                ResourceId=disk['resource_id'],
                ChargePeriodStart=day.isoformat(),
                ChargePeriodEnd=(day + timedelta(days=1)).isoformat(),
                EffectiveCost='1.00',
            )
        )
    spike_day = start + timedelta(days=29)
    records.append(
        charge(
            30,
            '1.40',
            x_ChargeId='charge-spike',
            ResourceId=disk['resource_id'],
            ChargePeriodStart=spike_day.isoformat(),
            ChargePeriodEnd=(spike_day + timedelta(days=1)).isoformat(),
            EffectiveCost='1.40',
        )
    )
    repo.import_records(
        tenant,
        ImportRequest.model_validate(
            batch(records, source_id='analysis-enrich', period_start=start.date().isoformat(), period_end=end.date().isoformat()),
        ),
    )
    scan = dict(
        scan_id=str(uuid4()),
        timestamp=NOW.isoformat(),
        findings=[],
        inventory=[dict(disk, evidence={'encrypted': True})],
    )
    attached = repo.attach(tenant, scan)
    enriched = attached['inventory'][0]['evidence']
    assert enriched['billed_cost_usd'] == pytest.approx(30.4)
    assert enriched['cost_source'] == COST_SOURCE_ACTUAL_BILLED
    assert enriched['daily_cost_spike_pct'] == pytest.approx(40.0)
    ctx = context_from_inventory_row(attached['inventory'][0], observed_at=NOW.isoformat())
    assert ctx.cost.cost_source == COST_SOURCE_ACTUAL_BILLED
    assert ctx.cost.daily_cost_spike_pct == pytest.approx(40.0)


def test_retail_only_evidence_gets_retail_cost_source():
    evidence = dict(retail_estimate_usd=12.0)
    enrich_inventory_billing_evidence(evidence, daily_rows=[])
    assert evidence['cost_source'] == COST_SOURCE_RETAIL_ESTIMATED
