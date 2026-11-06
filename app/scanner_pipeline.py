"""Post-collection scan pipeline steps (pricing, analysis, baselines) — single entry for worker and sync API."""
from __future__ import annotations

from typing import Any


def finalize_scan_payload(
    scan: dict[str, Any],
    *,
    tenant_id: str,
    settings,
    previous_completed_scan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Attach activity watermarks, pillar analysis, and drift baselines; mutates and returns *scan*."""
    from app.collectors.activity_ingestion_watermark import (
        apply_watermarks_to_inventory,
        load_previous_scope_watermarks_from_scan,
    )
    from app.analysis_service.pipeline import attach_pillar_analysis
    from app.drift.scan_baselines import capture_scan_drift_baselines_for_tenant

    prev_wm = load_previous_scope_watermarks_from_scan(previous_completed_scan)
    apply_watermarks_to_inventory(scan.get('inventory') or [], previous=prev_wm)
    attach_pillar_analysis(scan)
    capture_scan_drift_baselines_for_tenant(scan, tenant_id, settings)
    return scan
