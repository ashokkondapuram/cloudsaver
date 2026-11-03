"""Live Azure Cost Management + scan retail evidence for one resource and window."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from app.financial_balance import resource_financial_balance
from app.pricing import opportunity_totals


def validate_window(start: date, end: date, *, label: str = 'window') -> int:
    days = (end - start).days
    if not 1 <= days <= 366:
        raise ValueError(f'{label} must span 1 to 366 UTC days (exclusive end date)')
    latest_end = datetime.now(timezone.utc).date() + timedelta(days=1)
    if end > latest_end:
        raise ValueError(f'{label} end date cannot extend beyond tomorrow UTC')
    return days


def aggregate_rows(rows, *, expected_days: int):
    if not rows:
        return dict(
            billed_cost_usd=None,
            effective_cost_usd=None,
            currency=None,
            day_count=0,
            expected_days=expected_days,
            coverage_complete=False,
        )
    billed = effective = Decimal(0)
    currency = rows[0]['currency']
    days = set()
    for row in rows:
        if row['currency'] != currency:
            raise ValueError('Multiple currencies in one resource billing response')
        days.add(row['day'])
        billed += Decimal(str(row['billed']))
        effective += Decimal(str(row['effective']))
    quantize = lambda value: float(value.quantize(Decimal('0.01')))
    day_count = len(days)
    return dict(
        billed_cost_usd=quantize(billed),
        effective_cost_usd=quantize(effective),
        currency=currency,
        day_count=day_count,
        expected_days=expected_days,
        coverage_complete=day_count == expected_days,
    )


def scale_retail_monthly(monthly_usd, window_days: int) -> float | None:
    if monthly_usd is None:
        return None
    value = Decimal(str(monthly_usd)) * Decimal(window_days) / Decimal(30)
    return float(value.quantize(Decimal('0.01')))


def retail_monthly_from_scan(scan_store, tenant, scan_id, provider, resource_id):
    if scan_store is None or scan_id is None:
        return None, None, None
    scan = scan_store.get(tenant['tenant_id'], str(scan_id))
    if not scan:
        return None, None, None
    normalize = resource_id.lower() if provider == 'azure' else resource_id
    retail = None
    for collection in (scan.get('findings') or [], scan.get('inventory') or []):
        for row in collection:
            if row.get('cloud_provider', 'azure') != provider:
                continue
            rid = row.get('resource_id')
            if not isinstance(rid, str):
                continue
            key = rid.lower() if provider == 'azure' else rid
            if key != normalize:
                continue
            candidate = row.get('retail_estimate_usd') or row.get('estimated_monthly_waste_usd')
            if candidate is not None:
                retail = candidate
    basis = 'azure_retail_meters_from_scan' if retail is not None else None
    return retail, str(scan_id), basis


def booked_savings_delta(baseline_billed, observation_billed):
    if baseline_billed is None or observation_billed is None:
        return None
    delta = Decimal(str(baseline_billed)) - Decimal(str(observation_billed))
    return float(delta.quantize(Decimal('0.01')))


def finance_reconciled_benefit(store, tenant_id, provider, resource_id):
    if store is None:
        return None
    rid = resource_id.lower() if provider == 'azure' else resource_id
    row = store.execute(
        "SELECT verification FROM savings_cases WHERE tenant_id=%s AND provider=%s AND resource_id=%s "
        "AND state='financially_reconciled' ORDER BY updated_at DESC LIMIT 1",
        (tenant_id, provider, rid),
    ).fetchone()
    if not row or not row[0]:
        return None
    try:
        payload = row[0] if isinstance(row[0], dict) else __import__('json').loads(row[0])
    except (TypeError, ValueError):
        return None
    benefit = (payload or {}).get('reconciled_financial_benefit')
    if benefit is None:
        return None
    try:
        return float(Decimal(str(benefit)).quantize(Decimal('0.01')))
    except Exception:
        return None


def build_snapshot(
    *,
    tenant,
    scope_id: str,
    resource_id: str,
    observation_start: date,
    observation_end: date,
    baseline_start: date | None = None,
    baseline_end: date | None = None,
    scan_id=None,
    scan_store=None,
    evidence_store=None,
    findings=None,
    fetch_rows,
):
    """fetch_rows(scope_id, resource_id, tenant, start, end) -> list of daily billing dicts."""
    obs_days = validate_window(observation_start, observation_end, label='Observation window')
    obs_rows = fetch_rows(scope_id, resource_id, tenant, observation_start, observation_end)
    observation = aggregate_rows(obs_rows, expected_days=obs_days)
    observation.update(
        start=observation_start.isoformat(),
        end=observation_end.isoformat(),
        source='azure_cost_management',
    )

    baseline = None
    booked = None
    if baseline_start is not None and baseline_end is not None:
        base_days = validate_window(baseline_start, baseline_end, label='Baseline window')
        base_rows = fetch_rows(scope_id, resource_id, tenant, baseline_start, baseline_end)
        baseline = aggregate_rows(base_rows, expected_days=base_days)
        baseline.update(
            start=baseline_start.isoformat(),
            end=baseline_end.isoformat(),
            source='azure_cost_management',
        )
        booked = booked_savings_delta(
            baseline.get('billed_cost_usd'),
            observation.get('billed_cost_usd'),
        )

    provider = 'azure'
    monthly_retail, retail_scan_id, retail_basis = retail_monthly_from_scan(
        scan_store, tenant, scan_id, provider, resource_id
    )
    window_retail = scale_retail_monthly(monthly_retail, obs_days)
    opportunity = opportunity_totals(findings or [])
    balance = resource_financial_balance(
        billed_cost_usd=observation.get('billed_cost_usd'),
        effective_cost_usd=observation.get('effective_cost_usd'),
        retail_run_rate_usd=window_retail,
        opportunity=opportunity,
    )

    reconciled = finance_reconciled_benefit(
        evidence_store, tenant['tenant_id'], provider, resource_id
    )
    warnings = []
    if not observation.get('coverage_complete'):
        warnings.append('Observation billing window has missing days in Cost Management.')
    if baseline and not baseline.get('coverage_complete'):
        warnings.append('Baseline billing window has missing days in Cost Management.')
    if monthly_retail is None:
        warnings.append('Azure retail run-rate is unknown without scan retail meters on this resource.')
    if booked is not None and booked > 0 and reconciled is None:
        warnings.append(
            'Positive billing delta is provisional until finance reconciliation in Savings & investigations.'
        )

    return dict(
        resource_id=resource_id,
        scope_id=scope_id,
        provider=provider,
        observation=observation,
        baseline=baseline,
        retail=dict(
            monthly_run_rate_usd=monthly_retail,
            window_run_rate_usd=window_retail,
            basis=retail_basis,
            scan_id=retail_scan_id,
        ),
        balance=balance,
        booked_savings_usd=booked,
        booked_savings_basis='baseline_minus_observation_billed'
        if baseline is not None
        else None,
        finance_reconciled_benefit_usd=reconciled,
        warning=' '.join(warnings) if warnings else None,
    )
