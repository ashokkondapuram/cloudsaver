"""Fetch a single JSON profile for any Azure resource using documented REST endpoints."""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any

from app.azure_resource_registry import normalize_arm_body, resolve_arm_api_version
from app.azure_resource_finops import build_snapshot
from app.azure_rest_catalog import (
    AZURE_REST_CATALOG,
    COST_MANAGEMENT_QUERY_API_VERSION,
    catalog_operations,
    parse_arm_resource_type,
)
from app.collectors.azure_endpoint import arm_url, validate_arm_resource_path

logger = logging.getLogger('cloudsaver.azure_json_profile')


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
    financial = build_snapshot(
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
