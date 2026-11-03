"""Fetch a single JSON profile for any Azure resource using documented REST endpoints."""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from app.azure_resource_registry import normalize_arm_body, resolve_arm_api_version
from app.azure_rest_catalog import (
    AZURE_REST_CATALOG,
    COST_MANAGEMENT_QUERY_API_VERSION,
    catalog_operations,
    parse_arm_resource_type,
)
from app.collectors.azure_endpoint import arm_url, validate_arm_resource_path
from app.financial_balance import resource_financial_balance
from app.pricing import opportunity_totals

logger = logging.getLogger('cloudsaver.azure_json_profile')


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


def build_financial_snapshot(
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
    """Cost Management windows + retail + booked savings (JSON-friendly dict)."""
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


# Backward-compatible alias for tests and imports during consolidation.
build_snapshot = build_financial_snapshot


def _endpoint_descriptor(operation: str, **parts: str) -> dict[str, Any]:
    meta = AZURE_REST_CATALOG[operation]
    path = meta['path'].format(**parts)
    url = f"https://{meta['host']}{path if path.startswith('/') else '/' + path}"
    return dict(
        operation=operation,
        method=meta['method'],
        doc=meta['doc'],
        url=url,
        query={k: v.format(**parts) for k, v in (meta.get('query') or {}).items()},
    )


def _fetch_arm_json(tenant, scope_id: str, resource_id: str) -> dict[str, Any]:
    from app.cloud_http import BearerTokenCache, JSONReader
    from app.cloud_identity import azure_credential

    rtype = parse_arm_resource_type(resource_id)
    if not rtype:
        return dict(status='unsupported_type', reason='Not a Microsoft.* ARM resource ID')
    credential = azure_credential(tenant)
    reader = JSONReader(headers_factory=BearerTokenCache(credential, 'https://management.azure.com/.default'))
    calls: list[dict] = []
    try:
        version_cache: dict = {}
        version = resolve_arm_api_version(reader, scope_id, rtype, version_cache)
        if not version:
            provider_ns = rtype.split('/')[0]
            provider_ns_title = '.'.join(p.capitalize() for p in provider_ns.split('.'))
            calls.append(
                _endpoint_descriptor(
                    'provider_get',
                    subscription_id=scope_id,
                    resource_provider_namespace=provider_ns_title,
                )
            )
            return dict(
                status='api_version_unresolved',
                resource_type=rtype,
                calls=calls,
                reason='Provider metadata did not list a stable api-version for this type.',
            )
        scope = resource_id.split('/providers/')[0]
        validate_arm_resource_path(resource_id, scope_path_lower=scope.lower())
        call = _endpoint_descriptor('arm_resource_get', resource_id=resource_id, arm_api_version=version)
        call['query'] = {'api-version': version}
        calls.append(call)
        body = reader.get(arm_url(resource_id), {'api-version': version})
        if (body.get('id') or '').lower() != resource_id.lower():
            raise ValueError('ARM resource id mismatch')
        normalized = normalize_arm_body(body)
        catalog_pinned = False
        from app.azure_resource_registry import arm_api_version as catalog_arm_version

        if catalog_arm_version(rtype):
            catalog_pinned = True
        return dict(
            status='ok',
            resource_type=rtype,
            arm_api_version=version,
            document=normalized,
            raw_type=body.get('type'),
            location=body.get('location'),
            calls=calls,
            catalog_pinned=catalog_pinned,
        )
    except Exception as error:
        logger.warning('ARM JSON fetch failed resource=%s', resource_id, exc_info=True)
        return dict(status='error', resource_type=rtype, reason=str(error), calls=calls)
    finally:
        reader.close()
        credential.close()


def fetch_azure_resource_profile(
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
    """Return one JSON document: REST catalog, ARM body, Cost Management windows, retail, financial."""
    from app.collectors.billing_sync import azure_resource_rows

    fetch = fetch_rows or azure_resource_rows
    rtype = parse_arm_resource_type(resource_id)
    financial = build_financial_snapshot(
        tenant=tenant,
        scope_id=scope_id,
        resource_id=resource_id,
        observation_start=observation_start,
        observation_end=observation_end,
        baseline_start=baseline_start,
        baseline_end=baseline_end,
        scan_id=scan_id,
        scan_store=scan_store,
        evidence_store=evidence_store,
        findings=findings,
        fetch_rows=fetch,
    )
    arm = _fetch_arm_json(tenant, scope_id, resource_id)
    cm_url = _endpoint_descriptor('cost_management_query', subscription_id=scope_id)
    cm_url['query'] = {'api-version': COST_MANAGEMENT_QUERY_API_VERSION}
    retail_doc = AZURE_REST_CATALOG['retail_prices']['doc']
    return dict(
        schema_version='1',
        fetched_at=datetime.now(timezone.utc).isoformat(),
        resource_id=resource_id,
        subscription_id=scope_id,
        resource_type=rtype or arm.get('resource_type'),
        azure_rest_catalog=catalog_operations(),
        arm=arm,
        cost_management=dict(
            endpoint=cm_url,
            cost_types=['ActualCost', 'AmortizedCost'],
            observation=financial['observation'],
            baseline=financial.get('baseline'),
        ),
        retail_prices=dict(
            doc=retail_doc,
            monthly_run_rate_usd=financial['retail']['monthly_run_rate_usd'],
            window_run_rate_usd=financial['retail']['window_run_rate_usd'],
            basis=financial['retail'].get('basis'),
            scan_id=financial['retail'].get('scan_id'),
        ),
        financial=dict(
            balance=financial['balance'],
            booked_savings_usd=financial['booked_savings_usd'],
            booked_savings_basis=financial.get('booked_savings_basis'),
            finance_reconciled_benefit_usd=financial.get('finance_reconciled_benefit_usd'),
        ),
        warning=financial.get('warning'),
    )
