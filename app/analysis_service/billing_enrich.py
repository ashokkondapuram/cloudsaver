"""Derive analysis-service cost fields when billing is merged onto inventory evidence."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from statistics import median

from app.collectors.billing_sync import (
    COST_SOURCE_ACTUAL_BILLED,
    COST_SOURCE_FOCUS_IMPORT,
    COST_SOURCE_RETAIL_ESTIMATED,
)


def _optional_float(value) -> float | None:
    try:
        if value is None:
            return None
        out = float(value)
        if out != out:
            return None
        return out
    except (TypeError, ValueError):
        return None


def _daily_amount(row: dict) -> float | None:
    for key in ('effective_cost_usd', 'effective', 'billed_cost_usd', 'billed'):
        parsed = _optional_float(row.get(key))
        if parsed is not None:
            return parsed
    return None


def _row_day(row: dict) -> date | None:
    day = row.get('day')
    if isinstance(day, date):
        return day
    if isinstance(day, str):
        try:
            return date.fromisoformat(day[:10])
        except ValueError:
            return None
    return None


def daily_cost_spike_pct(daily_rows: list[dict] | None) -> float | None:
    """Percent increase of the latest observed day vs the median of prior days."""
    if not daily_rows:
        return None
    amounts: list[tuple[date, float]] = []
    for row in daily_rows:
        if not isinstance(row, dict):
            continue
        day = _row_day(row)
        amount = _daily_amount(row)
        if day is None or amount is None:
            continue
        amounts.append((day, amount))
    if len(amounts) < 2:
        return None
    amounts.sort(key=lambda item: item[0])
    latest = amounts[-1][1]
    baseline = median([value for _, value in amounts[:-1]])
    if baseline <= 0:
        if latest <= 0:
            return None
        return 100.0
    return (latest - baseline) / baseline * 100.0


def effective_discount_rate(*, retail, amortized) -> float | None:
    retail_usd = _optional_float(retail)
    amortized_usd = _optional_float(amortized)
    if retail_usd is None or retail_usd <= 0 or amortized_usd is None:
        return None
    return max(0.0, min(1.0, 1.0 - (amortized_usd / retail_usd)))


def target_sku_retail_monthly_usd(evidence: dict) -> float | None:
    direct = _optional_float(evidence.get('target_sku_retail_monthly_usd'))
    if direct is not None:
        return direct
    pricing = evidence.get('pricing_evidence')
    if not isinstance(pricing, dict):
        return None
    for key in ('target_sku_retail_monthly_usd', 'target_retail_monthly_usd'):
        parsed = _optional_float(pricing.get(key))
        if parsed is not None:
            return parsed
    components = pricing.get('components')
    if not isinstance(components, dict) or 'target' not in components:
        return None
    from app.pricing import pricing_client

    rows = components['target']
    rows = rows if isinstance(rows, list) else [rows]
    total = Decimal(0)
    for row in rows:
        if not isinstance(row, dict):
            return None
        parsed = pricing_client.component(row)
        if parsed is None:
            return None
        total += parsed[0]
    if total <= 0:
        return None
    return float(total.quantize(Decimal('0.01')))


def infer_cost_source(evidence: dict) -> str | None:
    existing = evidence.get('cost_source')
    if isinstance(existing, str) and existing.strip():
        return existing.strip()
    if evidence.get('billed_cost_usd') is not None or evidence.get('effective_cost_usd') is not None:
        basis = evidence.get('billing_basis') or ''
        if isinstance(basis, str) and 'retail' in basis.casefold():
            return COST_SOURCE_RETAIL_ESTIMATED
        if evidence.get('billing_import_kind') == 'focus_manual':
            return COST_SOURCE_FOCUS_IMPORT
        return COST_SOURCE_ACTUAL_BILLED
    if (
        evidence.get('retail_estimate_usd') is not None
        or evidence.get('retail_monthly_usd') is not None
        or evidence.get('retail_monthly_equivalent_usd') is not None
    ):
        return COST_SOURCE_RETAIL_ESTIMATED
    return None


def enrich_inventory_billing_evidence(
    evidence: dict,
    *,
    daily_rows: list[dict] | None = None,
) -> dict:
    """Populate analysis cost fields without overwriting explicit ingestion values."""
    retail = (
        evidence.get('retail_monthly_usd')
        or evidence.get('retail_estimate_usd')
        or evidence.get('retail_monthly_equivalent_usd')
        or evidence.get('list_cost_usd')
    )
    amortized = evidence.get('effective_cost_usd') or evidence.get('amortized_cost_usd')

    cost_source = infer_cost_source(evidence)
    if cost_source is not None and evidence.get('cost_source') is None:
        evidence['cost_source'] = cost_source

    discount = effective_discount_rate(retail=retail, amortized=amortized)
    if discount is not None and evidence.get('effective_discount_rate') is None:
        evidence['effective_discount_rate'] = discount

    target = target_sku_retail_monthly_usd(evidence)
    if target is not None and evidence.get('target_sku_retail_monthly_usd') is None:
        evidence['target_sku_retail_monthly_usd'] = target

    rows = daily_rows
    if rows is None:
        stored = evidence.get('billing_daily_rows')
        rows = stored if isinstance(stored, list) else None
    spike = daily_cost_spike_pct(rows)
    if spike is not None and evidence.get('daily_cost_spike_pct') is None:
        evidence['daily_cost_spike_pct'] = spike
    return evidence


def billing_window(as_of: datetime, *, window_days: int = 30) -> tuple[datetime, datetime]:
    finish = as_of.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    begin = finish - timedelta(days=window_days)
    return begin, finish


def resource_daily_cost_rows(db, tenant, resource_ids, *, begin, finish, scopes_args, fence) -> dict[tuple, list[dict]]:
    """Load per-day billed/effective rows from focus_charges for attach-time spike analysis."""
    azure_ids = sorted({v.lower() for v in resource_ids if isinstance(v, str) and v.lower().startswith('/subscriptions/')})
    other_ids = sorted({v for v in resource_ids if isinstance(v, str) and not v.lower().startswith('/subscriptions/')})
    grouped: dict[tuple, dict[date, dict]] = {}

    def ingest(provider, account, rid, period_start, billed, effective, currency):
        key = (provider, rid.lower() if provider == 'azure' else rid)
        day = datetime.fromisoformat(str(period_start)).date()
        bucket = grouped.setdefault(key, {})
        entry = bucket.setdefault(day, dict(billed=Decimal(0), effective=Decimal(0), currency=currency))
        if entry['currency'] != currency:
            return
        entry['billed'] += Decimal(billed)
        entry['effective'] += Decimal(effective)

    for offset in range(0, len(azure_ids), 300):
        batch = azure_ids[offset : offset + 300]
        if not batch:
            continue
        marks = ','.join('%s' for _ in batch)
        rows = db.execute(
            'SELECT provider,sub_account,resource_id,period_start,billed_cost,effective_cost,currency FROM focus_charges '
            'WHERE tenant_id=%s AND (' + fence + ') AND provider=%s AND lower(resource_id) IN (' + marks + ') '
            'AND period_start>=%s AND period_start<%s ORDER BY period_start,id LIMIT 50001',
            [tenant['tenant_id'], *scopes_args, 'azure', *batch, begin.isoformat(), finish.isoformat()],
        ).fetchall()
        if len(rows) > 50000:
            raise ValueError('Daily billing row limit exceeded')
        for provider, account, rid, period_start, billed, effective, currency in rows:
            ingest(provider, account, rid, period_start, billed, effective, currency)

    for offset in range(0, len(other_ids), 300):
        batch = other_ids[offset : offset + 300]
        if not batch:
            continue
        marks = ','.join('%s' for _ in batch)
        rows = db.execute(
            'SELECT provider,sub_account,resource_id,period_start,billed_cost,effective_cost,currency FROM focus_charges '
            'WHERE tenant_id=%s AND (' + fence + ') AND resource_id IN (' + marks + ') '
            'AND period_start>=%s AND period_start<%s ORDER BY period_start,id LIMIT 50001',
            [tenant['tenant_id'], *scopes_args, *batch, begin.isoformat(), finish.isoformat()],
        ).fetchall()
        if len(rows) > 50000:
            raise ValueError('Daily billing row limit exceeded')
        for provider, account, rid, period_start, billed, effective, currency in rows:
            ingest(provider, account, rid, period_start, billed, effective, currency)

    result: dict[tuple, list[dict]] = {}
    for key, days in grouped.items():
        result[key] = [
            dict(
                day=day.isoformat(),
                billed_cost_usd=float(values['billed']),
                effective_cost_usd=float(values['effective']),
                currency=values['currency'],
                cost_source=COST_SOURCE_ACTUAL_BILLED,
            )
            for day, values in sorted(days.items())
        ]
    return result
