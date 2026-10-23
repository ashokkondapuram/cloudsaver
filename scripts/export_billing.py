"""Export CloudSaver's local billing state for the platform billing import (read-only).

  docker compose run --rm migrate python scripts/export_billing.py --output /tmp/billing-export.json

Reads CLOUDSAVER_MIGRATION_URL (the migrate container's schema owner) or CLOUDSAVER_DATABASE_URL. The file holds
identifiers only, no secrets. Write it to a temporary path, hand it to the platform importer and never commit it.
Counts go to stderr; the JSON goes to stdout unless --output is set (created with mode 0600).
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

WATERMARKS = ('stripe_subscription_created', 'stripe_event_created', 'stripe_event_id', 'stripe_last_invoice_id',
              'stripe_invoice_event_created')


def database_url():
    url = os.getenv('CLOUDSAVER_MIGRATION_URL') or os.getenv('CLOUDSAVER_DATABASE_URL')
    if not url:
        raise SystemExit('Set CLOUDSAVER_MIGRATION_URL or CLOUDSAVER_DATABASE_URL.')
    return url.replace('postgresql+psycopg://', 'postgresql://', 1)


def _iso(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        value = datetime.fromtimestamp(value, timezone.utc) if value > 0 else None
        if value is None:
            return None
    return value.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def organization(row):
    tenant_id, plan_tier, customer, subscription, status, *marks = row
    watermark = dict(zip(WATERMARKS, marks))
    return {'tenant_id': str(tenant_id), 'plan_tier': plan_tier, 'stripe_customer_id': customer,
            'stripe_subscription_id': subscription, 'subscription_status': status,
            # CloudSaver never stored the Stripe period end; the platform derives it from the subscription.
            'current_period_end': None,
            'billing_watermark': watermark if any(watermark.values()) else None}


def export(db):
    db.execute('SET TRANSACTION READ ONLY')
    tenants = {str(r[0]) for r in db.execute('SELECT tenant_id FROM public.tenant_registry')}
    # A schema owner that bypasses RLS sees every tenant directly; the app role needs the tenant context.
    tenants |= {str(r[0]) for r in db.execute('SELECT DISTINCT tenant_id FROM public.organizations')}
    organizations, events = [], []
    for tenant_id in sorted(tenants):
        db.execute("SELECT set_config('app.current_tenant_id', %s, true)", (tenant_id,))
        rows = db.execute('SELECT tenant_id, plan_tier, stripe_customer_id, stripe_subscription_id, '
                          'stripe_subscription_status, ' + ', '.join(WATERMARKS) +
                          ' FROM public.organizations WHERE tenant_id=%s ORDER BY created_at, id', (tenant_id,)).fetchall()
        organizations.extend(organization(row) for row in rows)
        events.extend({'event_id': r[0], 'event_type': r[1], 'created_at': _iso(r[2])} for r in db.execute(
            'SELECT event_id, event_type, event_created FROM public.stripe_events WHERE tenant_id=%s '
            'ORDER BY event_created, event_id', (tenant_id,)))
    return {'version': 1, 'exported_at': _iso(datetime.now(timezone.utc)),
            'organizations': organizations, 'stripe_events': events}


def write(document, output):
    text = json.dumps(document, indent=2, sort_keys=True) + '\n'
    if not output:
        sys.stdout.write(text)
        return
    descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(descriptor, 0o600)
    with os.fdopen(descriptor, 'w') as stream:
        stream.write(text)


def main(argv=None, connect=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--output', help='Write the export to this path (mode 0600) instead of stdout')
    args = parser.parse_args(argv)
    if connect is None:
        import psycopg
        connect = lambda: psycopg.connect(database_url(), connect_timeout=10)  # noqa: E731
    with connect() as db:
        document = export(db)
    write(document, args.output)
    print(f"Exported {len(document['organizations'])} organizations and {len(document['stripe_events'])} Stripe events.",
          file=sys.stderr)


if __name__ == '__main__':
    main()
