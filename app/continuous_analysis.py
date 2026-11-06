"""Background refresh for resources whose evidence or analysis is still incomplete."""
from __future__ import annotations

import logging
import os

from app.resource_timestamps import evidence_needs_refresh

logger = logging.getLogger('cloudsaver.continuous_analysis')

ENABLED = os.getenv('CLOUDSAVER_CONTINUOUS_ANALYSIS_ENABLED', 'true').lower() == 'true'
BATCH_SIZE = max(1, min(int(os.getenv('CLOUDSAVER_CONTINUOUS_ANALYSIS_BATCH', '20')), 200))
PAGE_SIZE = max(50, min(int(os.getenv('CLOUDSAVER_CONTINUOUS_ANALYSIS_PAGE_SIZE', '200')), 1000))


def _latest_completed_scan(store, tenant_id: str) -> dict | None:
    for scan in store.list(tenant_id, limit=8):
        if scan.get('status') == 'completed' and scan.get('data_origin') != 'legacy_synthetic':
            return scan
    return None


def refresh_incomplete_resources(*, settings, store) -> dict:
    """Re-fetch Azure evidence for up to BATCH_SIZE stale or incomplete inventory rows."""
    if not ENABLED:
        return dict(enabled=False, refreshed=0, examined=0)
    from app.effective_rules import policy_for_tenant
    from app.resource_refresh import refresh_resource_observation

    refreshed = 0
    examined = 0
    tenants = getattr(settings, 'tenants', ()) or ()
    for tenant in tenants:
        if refreshed >= BATCH_SIZE:
            break
        tenant_id = tenant.get('tenant_id')
        if not tenant_id:
            continue
        scan = _latest_completed_scan(store, tenant_id)
        if not scan:
            continue
        scan_id = scan['scan_id']
        policies = policy_for_tenant(tenant_id)
        offset = 0
        while refreshed < BATCH_SIZE:
            page = store.running_inventory_page(tenant_id, scan_id, offset=offset, limit=PAGE_SIZE)
            if not page:
                break
            rows = page.get('inventory') or []
            if not rows:
                break
            for observation in rows:
                examined += 1
                evidence = observation.get('evidence') or {}
                if not evidence_needs_refresh(evidence):
                    continue
                try:
                    refresh_resource_observation(
                        tenant,
                        scan,
                        observation,
                        store=store,
                        policies=policies,
                    )
                    refreshed += 1
                except Exception:
                    logger.warning(
                        'Continuous analysis refresh failed resource_id=%s scan_id=%s',
                        observation.get('resource_id'),
                        scan_id,
                        exc_info=True,
                    )
                if refreshed >= BATCH_SIZE:
                    break
            offset += len(rows)
            if offset >= int(page.get('inventory_total') or 0):
                break
    return dict(enabled=True, refreshed=refreshed, examined=examined)
