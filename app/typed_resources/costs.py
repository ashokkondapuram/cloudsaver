"""Load Azure (auto-sync) vs cost-center (FOCUS import) costs in the reporting currency."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal


def _split_costs(db, tenant_id, resource_ids, *, currency, begin, finish, scopes):
    if not resource_ids or not scopes:
        return {}
    fence = ' OR '.join('(fc.provider=%s AND fc.sub_account=%s)' for _ in scopes)
    scope_args = [v for pair in scopes for v in pair]
    normalized = sorted({rid.lower() if rid.lower().startswith('/subscriptions/') else rid for rid in resource_ids})
    result = {}
    for offset in range(0, len(normalized), 200):
        batch = normalized[offset:offset + 200]
        marks = ','.join('%s' for _ in batch)
        rows = db.execute(
            f"""
            SELECT fc.resource_id, fc.billed_cost, fc.effective_cost, fc.list_cost, fc.charge_id, fi.source_id
            FROM focus_charges fc
            JOIN focus_imports fi ON fi.id = fc.import_id AND fi.tenant_id = fc.tenant_id
            WHERE fc.tenant_id = %s AND fc.currency = %s
              AND fc.period_start >= %s AND fc.period_end <= %s
              AND ({fence})
              AND lower(fc.resource_id) IN ({marks})
            ORDER BY fc.id LIMIT 50001
            """,
            [tenant_id, currency, begin.isoformat(), finish.isoformat(), *scope_args, *batch],
        ).fetchall()
        if len(rows) > 50000:
            raise ValueError('Too many billing rows for typed resource persistence; narrow the window')
        for rid, billed, effective, list_cost, charge_id, source_id in rows:
            key = rid.lower() if rid.lower().startswith('/subscriptions/') else rid
            bucket = result.setdefault(key, {
                'azure_billed': Decimal(0), 'azure_effective': Decimal(0), 'azure_list': Decimal(0), 'azure_list_ok': True,
                'cost_center_billed': Decimal(0), 'cost_center_effective': Decimal(0), 'cost_center_list': Decimal(0),
                'cost_center_list_ok': True, 'azure_charge_count': 0, 'cost_center_charge_count': 0,
            })
            is_azure_sync = str(charge_id or '').startswith('auto:') or str(source_id or '').startswith('auto-sync:')
            target = 'azure' if is_azure_sync else 'cost_center'
            bucket[f'{target}_billed'] += Decimal(billed)
            bucket[f'{target}_effective'] += Decimal(effective)
            if list_cost is None:
                bucket[f'{target}_list_ok'] = False
            else:
                bucket[f'{target}_list'] += Decimal(list_cost)
            bucket[f'{target}_charge_count'] += 1
    for key, bucket in result.items():
        if not bucket.pop('azure_list_ok', True):
            bucket['azure_list'] = None
        if not bucket.pop('cost_center_list_ok', True):
            bucket['cost_center_list'] = None
    return result


def reporting_currency(workspace, scan, settings=None):
    import os
    import re
    from app.cloudsaver_platform_settings import default_billing_currency
    for source in (
        scan.get('billing_currency'),
        (workspace or {}).get('billing_currency'),
        default_billing_currency(settings),
        os.getenv('CLOUDSAVER_DEFAULT_BILLING_CURRENCY'),
    ):
        if isinstance(source, str) and re.fullmatch(r'[A-Z]{3}', source):
            return source
    return 'USD'


def cost_window(scan, *, days=30):
    finish = datetime.fromisoformat(str(scan['timestamp']).replace('Z', '+00:00')).astimezone(timezone.utc)
    finish = finish.replace(hour=0, minute=0, second=0, microsecond=0)
    begin = finish - timedelta(days=days)
    return begin.date(), finish.date()


def load_resource_costs(db, workspace, scan, resource_ids):
    from app.focus import authorized
    tenant_id = workspace['tenant_id']
    currency = reporting_currency(workspace, scan)
    begin, finish = cost_window(scan)
    scopes = [('azure', v) for v in workspace.get('subscription_ids', [])]
    scopes += [('aws', a['account_id']) for a in workspace.get('aws_accounts', [])]
    scopes += [('gcp', p['project_id']) for p in workspace.get('gcp_projects', [])]
    allowed = workspace.get('allowed_providers')
    scopes = sorted({pair for pair in scopes if allowed is None or pair[0] in allowed})
    split = _split_costs(db, tenant_id, resource_ids, currency=currency, begin=begin, finish=finish, scopes=scopes)
    return currency, begin, finish, split
