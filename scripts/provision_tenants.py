"""Operator-only domain provisioning from trusted tenant configuration.

Run after owner migrations, with the restricted runtime PostgreSQL connection.
This is deliberately not exposed as an HTTP tenant-registration endpoint.
"""
import argparse
from pathlib import Path
import os
import sys
from uuid import UUID, NAMESPACE_URL, uuid5

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import Settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tenant-id', help='Provision only this configured Azure tenant')
    parser.add_argument('--organization-id', help='Explicit organization UUID; requires --tenant-id')
    parser.add_argument('--stripe-customer-id', help='Trusted existing Stripe customer binding; requires --tenant-id')
    parser.add_argument('--activate', action='store_true', help='Mark configured subscriptions active and tenant connected for scheduled scans')
    args = parser.parse_args()
    if (args.organization_id or args.stripe_customer_id) and not args.tenant_id:
        parser.error('Explicit organization/customer binding requires --tenant-id')
    if args.stripe_customer_id and (not args.stripe_customer_id.startswith('cus_') or len(args.stripe_customer_id) > 255):
        parser.error('Stripe customer ID must start with cus_')
    settings = Settings.load()
    if not settings.database_url:
        parser.error('CLOUDSAVER_DATABASE_URL must select the restricted PostgreSQL application role')
    tenants = list(settings.tenants)
    if args.tenant_id:
        tid = str(UUID(args.tenant_id))
        tenants = [t for t in tenants if t['tenant_id'] == tid]
        if not tenants:
            parser.error('Tenant is not in trusted CLOUDSAVER_TENANTS')
    import psycopg
    for tenant in tenants:
        tid = tenant['tenant_id']
        oid = str(UUID(args.organization_id)) if args.organization_id else str(uuid5(NAMESPACE_URL, 'cloudsaver:org:' + tid))
        with psycopg.connect(settings.database_url, connect_timeout=10) as db:
            role = db.execute('SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname=current_user').fetchone()
            if any(role):
                raise RuntimeError('Use the restricted application role; provisioning refuses RLS bypass')
            db.execute("SELECT set_config('app.current_tenant_id', %s, true)", (tid,))
            db.execute('INSERT INTO organizations (id, tenant_id, name) VALUES (%s, %s, %s) ON CONFLICT (id) DO NOTHING',
                       (oid, tid, tenant['name']))
            organization = db.execute('SELECT id FROM organizations WHERE id=%s AND tenant_id=%s FOR UPDATE', (oid, tid)).fetchone()
            if not organization:
                raise RuntimeError('Organization identity does not belong to the configured tenant')
            existing = db.execute('SELECT organization_id FROM tenants WHERE tenant_id=%s', (tid,)).fetchone()
            if existing and str(existing[0]) != oid:
                raise RuntimeError('Tenant already belongs to another organization; no reassignment performed')
            status = 'connected' if args.activate else 'pending'
            db.execute('INSERT INTO tenants (tenant_id, organization_id, display_name, connection_status) VALUES (%s,%s,%s,%s) ON CONFLICT (tenant_id) DO NOTHING',
                       (tid, oid, tenant['name'], status))
            if args.activate:
                db.execute("UPDATE tenants SET connection_status='connected' WHERE tenant_id=%s AND organization_id=%s", (tid, oid))
            for sid in tenant['subscription_ids']:
                identity = str(uuid5(NAMESPACE_URL, 'cloudsaver:sub:' + tid + ':' + sid))
                db.execute('INSERT INTO subscriptions (id, tenant_id, subscription_id, display_name, active) VALUES (%s,%s,%s,%s,%s) ON CONFLICT (tenant_id,subscription_id) DO NOTHING',
                           (identity, tid, sid, 'Configured subscription', args.activate))
                if args.activate:
                    db.execute('UPDATE subscriptions SET active=true WHERE tenant_id=%s AND subscription_id=%s', (tid, sid))
            if args.stripe_customer_id:
                previous = db.execute('SELECT stripe_customer_id FROM organizations WHERE id=%s AND tenant_id=%s', (oid, tid)).fetchone()[0]
                if previous and previous != args.stripe_customer_id:
                    raise RuntimeError('Organization has a different Stripe customer; no reassignment performed')
                db.execute('UPDATE organizations SET stripe_customer_id=%s WHERE id=%s AND tenant_id=%s', (args.stripe_customer_id, oid, tid))
        print('Provisioned configured tenant ' + tid + ' with organization ' + oid + (' (active)' if args.activate else ' (pending)'))


if __name__ == '__main__':
    main()
