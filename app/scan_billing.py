"""Attach provider billing to a scan snapshot at completion (scan-time window)."""
from __future__ import annotations

import logging
import os
from datetime import timedelta

from app.focus import FocusError, utc

logger = logging.getLogger('cloudsaver.scan_billing')


def billing_window_dates(scan, *, window_days=30):
    """Closed UTC day window ending the day before the scan observation midnight."""
    finish = utc(scan['timestamp']).replace(hour=0, minute=0, second=0, microsecond=0)
    begin = finish - timedelta(days=window_days)
    end = finish.date()
    start = begin.date()
    return start, end


def refresh_azure_billing_for_scan(tenant, repository, scan):
    """Pull subscription resource-level Azure Cost Management rows for the scan window.

    Returns 'ok' when every configured, in-scope binding's observed currencies imported cleanly,
    'failed' otherwise, so the scan can mark its cost evidence as degraded rather than silently
    completing on stale/partial data.
    """
    if os.getenv('CLOUDSAVER_SCAN_BILLING_REFRESH', 'true').lower() != 'true':
        return 'skipped'
    try:
        from app.collectors.billing_sync import _import_snapshot, azure_rows, bindings
    except ImportError:
        return 'skipped'
    try:
        selected = [b for b in bindings(tenant) if b['provider'] == 'azure']
    except FocusError:
        return 'skipped'
    if not selected:
        return 'skipped'
    start, end = billing_window_dates(scan)
    in_scope = {str(s) for s in tenant.get('subscription_ids', [])}
    failed = False
    for binding in selected:
        if binding['scope_id'] not in in_scope:
            continue
        try:
            observations, _, _ = azure_rows(binding, tenant, start, end)
        except Exception:
            logger.warning(
                'Scan billing refresh unavailable scope=%s scan_id=%s',
                binding['scope_id'],
                scan.get('scan_id'),
                exc_info=True,
            )
            failed = True
            continue
        if not observations:
            continue
        # Every observed currency is imported; no secondary-currency spend is dropped.
        for currency in sorted({row['currency'] for row in observations}):
            rows = [row for row in observations if row['currency'] == currency]
            try:
                _import_snapshot(repository, tenant, binding, rows, start, end, currency)
            except Exception:
                logger.warning(
                    'Scan billing import failed scope=%s currency=%s scan_id=%s',
                    binding['scope_id'],
                    currency,
                    scan.get('scan_id'),
                    exc_info=True,
                )
                failed = True
    return 'failed' if failed else 'ok'


def _attach_commitment_evidence(tenant, scan, store):
    try:
        from app.scan_commitment_evidence import attach_commitment_evidence

        return attach_commitment_evidence(tenant, scan, store)
    except Exception:
        logger.warning('Scan commitment evidence unavailable scan_id=%s', scan.get('scan_id'), exc_info=True)
        return scan


def materialize_scan_billing(tenant, scan, repository):
    """Refresh Azure CM (when configured), attach FOCUS costs to inventory/findings, freeze on the scan."""
    if scan.get('status') != 'completed':
        return scan
    if os.getenv('CLOUDSAVER_SCAN_BILLING_REFRESH', 'true').lower() == 'true':
        refresh_status = refresh_azure_billing_for_scan(tenant, repository, scan)
    else:
        refresh_status = 'skipped'
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                'Scan billing CM refresh skipped; using saved FOCUS charges scan_id=%s',
                scan.get('scan_id'),
            )
    attached = repository.attach(tenant, scan)
    start, end = billing_window_dates(scan)
    attached['billing_materialized'] = True
    attached['billing_window_start'] = start.isoformat()
    attached['billing_window_end'] = end.isoformat()
    attached['billing_refresh'] = dict(status=refresh_status)
    from app.resource_fetch_stages import sync_fetch_stages
    for obs in attached.get('inventory') or []:
        sync_fetch_stages((obs.get('evidence') or {}))
    from app.resource_analysis_service import reanalyze_scan_snapshot

    analyzed = reanalyze_scan_snapshot(attached)
    return _attach_commitment_evidence(tenant, analyzed, repository.store)
