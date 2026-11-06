"""Shape scan payloads for API responses (validation-safe, bounded size)."""

_HEAVY_FIELDS = (
    'inventory',
    'source_ledger',
    'scope_results',
    'rule_evaluations',
    'coverage',
    'coverage_manifest',
    'rule_manifest',
    'opportunity_summary',
)


def scan_for_api(payload, *, include_inventory=False):
    """Return a ScanSummary-compatible dict without multi-MB inventory blobs.

    Preserves ``pillar_analysis`` when present on the stored scan payload.
    """
    summary = dict(payload)
    summary.setdefault('scan_id', summary.get('scan_id') or summary.get('id'))
    summary.setdefault('subscriptions_scanned', 0)
    summary.setdefault('findings', [])
    summary.setdefault('total_monthly_waste_usd', None)
    summary.setdefault('realizable_monthly_savings_usd', None)
    summary.setdefault('cloud_providers', ['azure'])
    if not include_inventory:
        for key in _HEAVY_FIELDS:
            summary.pop(key, None)
        summary.setdefault('inventory', [])
    summary['items_arm_detail_collected'] = int(summary.get('items_arm_detail_collected') or 0)
    summary['items_arm_detail_processed'] = int(summary.get('items_arm_detail_processed') or 0)
    return summary
