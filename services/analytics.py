from collections import Counter

from fastapi import Depends, Header

from services.common import internal_url, service, upstream


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


def create_app(settings=None, transport=None):
    app, settings, tenant = service('analytics-service', settings)
    scanner = internal_url('SCANNER_SERVICE_URL', 'http://scanner-service:8002')

    @app.get('/api/v1/analytics')
    async def analytics(row=Depends(tenant), authorization: str = Header()):
        scans = await upstream('GET', scanner, '/api/v1/scans', authorization,
                               params={'limit': 1}, transport=transport)
        return summarize(scans)

    return app
