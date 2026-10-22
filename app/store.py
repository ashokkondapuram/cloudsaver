import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path


class Store:
    def __init__(self, path):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('CREATE TABLE IF NOT EXISTS scans (id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, timestamp TEXT NOT NULL, payload TEXT NOT NULL)')
            db.execute('CREATE INDEX IF NOT EXISTS scans_owner ON scans(tenant_id, timestamp DESC)')

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def save(self, tenant_id, scan, *, workspace=None):
        if workspace is None or workspace['tenant_id'] != tenant_id or scan.get('status') != 'completed' or len(scan['findings']) != scan['total_items_found']:
            raise ValueError('Authenticated workspace and complete scan are required')
        from app.cloud_scope import validate_finding_scope, demo_workspace
        effective = demo_workspace(workspace) if scan['mode'] == 'demo' else workspace
        for finding in scan['findings']:
            validate_finding_scope(finding, effective)
        with self.connection() as db:
            db.execute('INSERT INTO scans VALUES (?, ?, ?, ?)',
                       (scan['scan_id'], tenant_id, scan['timestamp'], json.dumps(scan)))

    def get(self, tenant_id, scan_id):
        with self.connection() as db:
            row = db.execute('SELECT payload FROM scans WHERE id=? AND tenant_id=?',
                             (scan_id, tenant_id)).fetchone()
        return json.loads(row[0]) if row else None

    def list(self, tenant_id, limit=50):
        with self.connection() as db:
            rows = db.execute('SELECT payload FROM scans WHERE tenant_id=? ORDER BY timestamp DESC LIMIT ?',
                              (tenant_id, limit)).fetchall()
        return [json.loads(row[0]) for row in rows]


class PostgresStore:
    """Every request uses a fresh transaction and transaction-local tenant context."""

    def __init__(self, url):
        import psycopg
        self.url = url
        with psycopg.connect(url, connect_timeout=10) as db:
            role = db.execute('SELECT rolsuper, rolbypassrls, rolcreaterole FROM pg_roles WHERE rolname = current_user').fetchone()
            if any(role):
                raise ValueError('Application database role must not be superuser or BYPASSRLS')
            if db.execute("SELECT 1 FROM pg_class WHERE relnamespace='public'::regnamespace AND relname IN ('scans', 'organizations', 'tenants', 'subscriptions', 'waste_findings', 'scan_jobs', 'stripe_events', 'cloud_findings') AND pg_has_role(current_user, relowner, 'USAGE') LIMIT 1").fetchone():
                raise ValueError('Application database role must not own storage tables or inherit their owner role')
            table = db.execute("SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE oid = 'public.scans'::regclass").fetchone()
            if not table or not all(table):
                raise ValueError('Apply PostgreSQL schema with forced row-level security first')
            tables = db.execute("SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class WHERE oid IN ('public.organizations'::regclass, 'public.tenants'::regclass, 'public.subscriptions'::regclass, 'public.waste_findings'::regclass)").fetchall()
            if len(tables) != 4 or any(not enabled or not forced for _, enabled, forced in tables):
                raise ValueError('Apply domain migrations with forced row-level security first')
            if not db.execute("SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='waste_findings' AND column_name='scan_id'").fetchone():
                raise ValueError('Apply Alembic migration 0002_scan_findings before starting the scanner')
            cloud_table = db.execute("SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid=to_regclass('public.cloud_findings')").fetchone()
            if cloud_table != (True, True):
                raise ValueError('Apply migration 0005_cloud_findings with forced RLS')

    @contextmanager
    def connection(self, tenant_id):
        import psycopg
        from uuid import UUID
        with psycopg.connect(self.url, connect_timeout=10) as db:
            db.execute("SELECT set_config('app.current_tenant_id', %s, true)", (str(UUID(tenant_id)),))
            yield db

    def save(self, tenant_id, scan, *, workspace=None):
        """Commit the snapshot and normalized rows together, or roll back all of them.

        Workspace scope comes from authenticated server configuration. Older
        snapshots remain readable; ingestion never rewrites historical results.
        """
        from uuid import UUID, uuid4, uuid5, NAMESPACE_URL
        from psycopg.types.json import Jsonb
        tenant_id = str(UUID(tenant_id))
        if workspace is None or str(UUID(workspace['tenant_id'])) != tenant_id:
            raise ValueError('Authenticated workspace configuration is required')
        subscriptions = {str(UUID(s)) for s in workspace['subscription_ids']}
        if scan['status'] != 'completed' or len(scan['findings']) != scan['total_items_found']:
            raise ValueError('Only complete scan results can be stored')
        from app.cloud_scope import validate_finding_scope, demo_workspace
        effective = demo_workspace(workspace) if scan['mode'] == 'demo' else workspace
        for finding in scan['findings']:
            validate_finding_scope(finding, effective)
        organization_id = uuid5(NAMESPACE_URL, 'cloudsaver:organization:' + tenant_id)
        with self.connection(tenant_id) as db:
            db.execute('INSERT INTO public.scans (id, tenant_id, timestamp, payload) VALUES (%s, %s, %s, %s)',
                       (scan['scan_id'], tenant_id, scan['timestamp'], Jsonb(scan)))
            db.execute('INSERT INTO public.organizations (id, tenant_id, name) VALUES (%s, %s, %s) ON CONFLICT (id) DO UPDATE SET name=EXCLUDED.name',
                       (organization_id, tenant_id, workspace['name']))
            db.execute("INSERT INTO public.tenants (tenant_id, organization_id, display_name, connection_status) VALUES (%s, %s, %s, 'configured') ON CONFLICT (tenant_id) DO UPDATE SET display_name=EXCLUDED.display_name",
                       (tenant_id, organization_id, workspace['name']))
            for subscription in sorted(subscriptions):
                db.execute('INSERT INTO public.subscriptions (id, tenant_id, subscription_id, display_name) VALUES (%s, %s, %s, %s) ON CONFLICT (tenant_id, subscription_id) DO NOTHING',
                           (uuid4(), tenant_id, subscription, subscription))
            with db.cursor() as cursor:
                cursor.executemany('''INSERT INTO public.waste_findings
                    (id, tenant_id, subscription_id, scan_id, resource_id, resource_name,
                     resource_type, resource_group, rule_id, severity, details, evidence,
                     estimated_monthly_waste_usd, observed_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)''',
                    [(uuid4(), tenant_id, f['subscription_id'], scan['scan_id'], f['resource_id'],
                      f['resource_name'], f['resource_type'], f['resource_group'], f['rule_id'],
                      f['severity'], f['details'], Jsonb({'mode': scan['mode']}),
                      f['estimated_monthly_waste_usd'], scan['timestamp']) for f in scan['findings']
                     if f.get('cloud_provider', 'azure') == 'azure'])
                cursor.executemany('''INSERT INTO public.cloud_findings
                    (id,tenant_id,scan_id,cloud_provider,scope_id,resource_id,rule_id,payload,observed_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                    [(uuid4(),tenant_id,scan['scan_id'],f['cloud_provider'],f['scope_id'],f['resource_id'],
                      f['rule_id'],Jsonb(f),scan['timestamp']) for f in scan['findings']
                     if f.get('cloud_provider', 'azure') != 'azure'])

    def get(self, tenant_id, scan_id):
        # Invalid UUIDs receive the same 404 as unknown or foreign IDs.
        from uuid import UUID
        try:
            scan_id = str(UUID(scan_id))
        except ValueError:
            return None
        with self.connection(tenant_id) as db:
            row = db.execute('SELECT payload FROM public.scans WHERE id=%s AND tenant_id=%s', (scan_id, tenant_id)).fetchone()
        return row[0] if row else None

    def list(self, tenant_id, limit=50):
        with self.connection(tenant_id) as db:
            rows = db.execute('SELECT payload FROM public.scans WHERE tenant_id=%s ORDER BY timestamp DESC LIMIT %s', (tenant_id, limit)).fetchall()
        return [row[0] for row in rows]
