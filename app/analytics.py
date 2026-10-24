"""Current-snapshot analytics; history is never summed."""
from collections import Counter

def summarize(scans):
    # Scans are snapshots. Summing history would count the same resources again.
    if not scans:
        return {'scan_id': None, 'total_items_found': 0, 'categories': {}, 'monthly_opportunity_usd': None}
    latest = scans[0]
    from app.pricing import opportunity_totals
    return {
        **opportunity_totals(latest['findings']),
        'scan_id': latest['scan_id'], 'timestamp': latest['timestamp'], 'mode': latest['mode'],
        'total_items_found': latest['total_items_found'],
        'categories': dict(Counter(row['rule_id'] for row in latest['findings'])),
        'monthly_opportunity_usd': opportunity_totals(latest['findings'])['total_monthly_opportunity_usd'],
        'cost_basis': 'azure_retail_where_available' if latest['mode'] in ('azure', 'multi-cloud') else 'not_yet_billing_attributed',
    }
