from database.connection import connect as pooled_connect
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path


def normalize_legacy_scan(payload):
    """Read legacy history without converting synthetic fixtures into live evidence."""
    if not isinstance(payload, dict) or payload.get('mode') != 'demo':
        return payload
    payload = dict(payload)
    providers = payload.get('cloud_providers') or ['azure']
    payload['mode'] = 'multi-cloud' if len(providers) > 1 else 'azure'
    payload['data_origin'] = 'legacy_synthetic'
    payload['scope_fingerprint'] = None
    payload['total_monthly_waste_usd'] = None
    payload['realizable_monthly_savings_usd'] = None
    payload['findings'] = [dict(f,estimated_monthly_waste_usd=None,cost_attribution=None,
                                details='Historical synthetic fixture; not live cloud evidence.') for f in payload.get('findings',[])]
    return payload


def _finalize_scan_payload(payload):
    from app.rule_id_canonical import normalize_scan
    return normalize_scan(normalize_legacy_scan(payload))


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
        if workspace is None or workspace['tenant_id'] != tenant_id or scan.get('status') != 'completed' or len(scan.get('inventory') or scan['findings']) != scan['total_items_found']:
            raise ValueError('Authenticated workspace and complete scan are required')
        from app.cloud_scope import validate_finding_scope
        for finding in scan['findings']:
            validate_finding_scope(finding, workspace)
        from app.rule_id_canonical import normalize_scan
        scan = normalize_scan(scan)
        with self.connection() as db:
            db.execute('INSERT INTO scans VALUES (?, ?, ?, ?)',
                       (scan['scan_id'], tenant_id, scan['timestamp'], json.dumps(scan)))

    def get(self, tenant_id, scan_id):
        with self.connection() as db:
            row = db.execute('SELECT payload FROM scans WHERE id=? AND tenant_id=?',
                             (scan_id, tenant_id)).fetchone()
        return _finalize_scan_payload(json.loads(row[0])) if row else None

    def list(self, tenant_id, limit=50):
        with self.connection() as db:
            rows = db.execute('SELECT payload FROM scans WHERE tenant_id=? ORDER BY timestamp DESC LIMIT ?',
                              (tenant_id, limit)).fetchall()
        return [_finalize_scan_payload(json.loads(row[0])) for row in rows]

    def list_light(self, tenant_id, limit=50):
        heavy = {'inventory', 'source_ledger', 'rule_evaluations', 'coverage_manifest'}
        return [{k: v for k, v in item.items() if k not in heavy} for item in self.list(tenant_id, limit)]

    def running_inventory_page(self, tenant_id, scan_id, *, offset=0, limit=100):
        scan = self.get(tenant_id, scan_id)
        if scan is None:
            return None
        inventory = scan.get('inventory') or []
        offset = max(0, int(offset))
        limit = max(1, min(int(limit), 1000))
        return dict(
            scan_id=scan['scan_id'],
            status=scan.get('status'),
            timestamp=scan.get('timestamp'),
            data_origin=scan.get('data_origin'),
            inventory_total=len(inventory),
            inventory=inventory[offset:offset + limit],
            findings=list(scan.get('findings') or []),
        )


class PostgresStore:
    """Every request uses a fresh transaction and transaction-local tenant context."""

    def __init__(self, url):
        import psycopg
        self.url = url
        with pooled_connect(url, connect_timeout=10) as db:
            role = db.execute('SELECT rolsuper, rolbypassrls, rolcreaterole FROM pg_roles WHERE rolname = current_user').fetchone()
            if any(role):
                raise ValueError('Application database role must not be superuser or BYPASSRLS')
            if db.execute("SELECT 1 FROM pg_class WHERE relnamespace='public'::regnamespace AND relname IN ('scans', 'organizations', 'tenants', 'subscriptions', 'waste_findings', 'scan_jobs', 'stripe_events', 'cloud_findings', 'gitops_requests', 'delivery_events', 'delivery_audit', 'delivery_dispatchers', 'tenant_registry', 'platform_settings', 'settings_audit', 'ai_inference_attempts', 'ai_inference_events', 'focus_imports', 'focus_charges') AND pg_has_role(current_user, relowner, 'USAGE') LIMIT 1").fetchone():
                raise ValueError('Application database role must not own storage tables or inherit their owner role')
            table = db.execute("SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE oid = 'public.scans'::regclass").fetchone()
            if not table or not all(table):
                raise ValueError('Apply PostgreSQL schema with forced row-level security first')
            tables = db.execute("SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class WHERE oid IN ('public.organizations'::regclass, 'public.tenants'::regclass, 'public.subscriptions'::regclass, 'public.waste_findings'::regclass)").fetchall()
            if len(tables) != 4 or any(not enabled or not forced for _, enabled, forced in tables):
                raise ValueError('Apply domain migrations with forced row-level security first')
            if not db.execute("SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='waste_findings' AND column_name='scan_id'").fetchone():
                raise ValueError('Apply Alembic migration 0002_scan_findings before starting the scanner')
            self.has_analysis_audit=bool(db.execute("SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='waste_findings' AND column_name='opportunity_group_id'").fetchone())
            cloud_table = db.execute("SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid=to_regclass('public.cloud_findings')").fetchone()
            if cloud_table != (True, True):
                raise ValueError('Apply migration 0005_cloud_findings with forced RLS')
            self.has_typed_resource_tables = bool(
                db.execute(
                    "SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name='azure_compute_disks'"
                ).fetchone()
            )

    @contextmanager
    def connection(self, tenant_id):
        import psycopg
        from uuid import UUID
        with pooled_connect(self.url, connect_timeout=10) as db:
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
        counted = scan.get('inventory') or scan['findings']
        if scan['status'] != 'completed' or len(counted) != scan['total_items_found']:
            raise ValueError('Only complete scan results can be stored')
        from app.cloud_scope import validate_finding_scope
        from app.waste_finding_evidence import waste_finding_evidence
        for finding in scan['findings']:
            validate_finding_scope(finding, workspace)
        from app.rule_id_canonical import normalize_scan
        scan = normalize_scan(scan)
        with self.connection(tenant_id) as db:
            owner = db.execute('SELECT organization_id FROM public.tenants WHERE tenant_id=%s', (tenant_id,)).fetchone()
            organization_id = owner[0] if owner else uuid5(NAMESPACE_URL, 'cloudsaver:organization:' + tenant_id)
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
                audit_columns=',opportunity_group_id,slo_burn_rate' if self.has_analysis_audit else ''
                audit_values=',%s,%s' if self.has_analysis_audit else ''
                cursor.executemany(f'''INSERT INTO public.waste_findings
                    (id, tenant_id, subscription_id, scan_id, resource_id, resource_name,
                     resource_type, resource_group, rule_id, severity, details, evidence,
                     estimated_monthly_waste_usd, observed_at{audit_columns})
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s{audit_values})''',
                    [(uuid4(), tenant_id, f['subscription_id'], scan['scan_id'], f['resource_id'],
                      f['resource_name'], f['resource_type'], f['resource_group'], f['rule_id'],
                      f['severity'], f['details'], Jsonb(waste_finding_evidence(f, scan_id=scan['scan_id'], mode=scan['mode'])),
                      f['estimated_monthly_waste_usd'], scan['timestamp'],*(_analysis_audit(f) if self.has_analysis_audit else ())) for f in scan['findings']
                     if f.get('cloud_provider', 'azure') == 'azure'])
                cursor.executemany(f'''INSERT INTO public.cloud_findings
                    (id,tenant_id,scan_id,cloud_provider,scope_id,resource_id,rule_id,payload,observed_at{audit_columns})
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s{audit_values})''',
                    [(uuid4(),tenant_id,scan['scan_id'],f['cloud_provider'],f['scope_id'],f['resource_id'],
                      f['rule_id'],Jsonb(f),scan['timestamp'],*(_analysis_audit(f) if self.has_analysis_audit else ())) for f in scan['findings']
                     if f.get('cloud_provider', 'azure') != 'azure'])
            if self.has_typed_resource_tables:
                from app.typed_resources.persist import persist_typed_resources
                persist_typed_resources(db, workspace, scan)

    def _ensure_tenant_rows(self, db, tenant_id, workspace):
        from uuid import UUID, uuid4, uuid5, NAMESPACE_URL
        owner = db.execute('SELECT organization_id FROM public.tenants WHERE tenant_id=%s', (tenant_id,)).fetchone()
        organization_id = owner[0] if owner else uuid5(NAMESPACE_URL, 'cloudsaver:organization:' + tenant_id)
        db.execute(
            'INSERT INTO public.organizations (id, tenant_id, name) VALUES (%s, %s, %s) ON CONFLICT (id) DO UPDATE SET name=EXCLUDED.name',
            (organization_id, tenant_id, workspace['name']),
        )
        db.execute(
            "INSERT INTO public.tenants (tenant_id, organization_id, display_name, connection_status) VALUES (%s, %s, %s, 'configured') ON CONFLICT (tenant_id) DO UPDATE SET display_name=EXCLUDED.display_name",
            (tenant_id, organization_id, workspace['name']),
        )
        subscriptions = {str(UUID(s)) for s in workspace['subscription_ids']}
        for subscription in sorted(subscriptions):
            db.execute(
                'INSERT INTO public.subscriptions (id, tenant_id, subscription_id, display_name) VALUES (%s, %s, %s, %s) ON CONFLICT (tenant_id, subscription_id) DO NOTHING',
                (uuid4(), tenant_id, subscription, subscription),
            )

    def begin_running_scan(self, tenant_id, workspace, scan):
        from uuid import UUID
        from psycopg.types.json import Jsonb
        tenant_id = str(UUID(tenant_id))
        if workspace is None or str(UUID(workspace['tenant_id'])) != tenant_id:
            raise ValueError('Authenticated workspace configuration is required')
        if scan.get('status') != 'running':
            raise ValueError('Running scan bootstrap requires status=running')
        payload = dict(scan)
        with self.connection(tenant_id) as db:
            self._ensure_tenant_rows(db, tenant_id, workspace)
            db.execute(
                'INSERT INTO public.scans (id, tenant_id, timestamp, payload) VALUES (%s, %s, %s, %s)',
                (scan['scan_id'], tenant_id, scan['timestamp'], Jsonb(payload)),
            )

    def upsert_inventory_observation(self, tenant_id, scan_id, observation, *, workspace, observed_at):
        from uuid import UUID
        from psycopg.types.json import Jsonb
        tenant_id = str(UUID(tenant_id))
        scan_id = str(UUID(scan_id))
        rid = observation['resource_id'].lower()
        with self.connection(tenant_id) as db:
            row = db.execute(
                'SELECT payload FROM public.scans WHERE id=%s AND tenant_id=%s FOR UPDATE',
                (scan_id, tenant_id),
            ).fetchone()
            if row is None:
                return
            payload = dict(row[0])
            inventory = []
            replaced = False
            for item in payload.get('inventory') or []:
                if (item.get('resource_id') or '').lower() == rid:
                    inventory.append(observation)
                    replaced = True
                else:
                    inventory.append(item)
            if not replaced:
                inventory.append(observation)
            payload['inventory'] = inventory
            evidence = observation.get('evidence') or {}
            if evidence.get('arm_detail') == 'collected':
                payload['items_arm_detail_collected'] = int(payload.get('items_arm_detail_collected') or 0) + 1
            elif evidence.get('arm_detail'):
                payload['items_arm_detail_processed'] = int(payload.get('items_arm_detail_processed') or 0) + 1
            db.execute(
                'UPDATE public.scans SET payload=%s WHERE id=%s AND tenant_id=%s',
                (Jsonb(payload), scan_id, tenant_id),
            )
            if self.has_typed_resource_tables and evidence.get('arm_detail') == 'collected':
                from app.typed_resources.persist import persist_typed_resource_row
                persist_typed_resource_row(db, workspace, scan_id, observed_at, observation)

    def abandon_running_scan(self, tenant_id, scan_id):
        from uuid import UUID
        tenant_id = str(UUID(tenant_id))
        scan_id = str(UUID(scan_id))
        with self.connection(tenant_id) as db:
            db.execute('DELETE FROM public.scans WHERE id=%s AND tenant_id=%s AND payload->>%s = %s', (scan_id, tenant_id, 'status', 'running'))

    def complete_scan(self, tenant_id, scan, *, workspace=None):
        """Finalize a running scan or insert a completed scan in one transaction."""
        from uuid import UUID, uuid4, uuid5, NAMESPACE_URL
        from psycopg.types.json import Jsonb
        tenant_id = str(UUID(tenant_id))
        if workspace is None or str(UUID(workspace['tenant_id'])) != tenant_id:
            raise ValueError('Authenticated workspace configuration is required')
        counted = scan.get('inventory') or scan['findings']
        if scan['status'] != 'completed' or len(counted) != scan['total_items_found']:
            raise ValueError('Only complete scan results can be stored')
        from app.cloud_scope import validate_finding_scope
        from app.waste_finding_evidence import waste_finding_evidence
        for finding in scan['findings']:
            validate_finding_scope(finding, workspace)
        from app.rule_id_canonical import normalize_scan
        scan = normalize_scan(scan)
        with self.connection(tenant_id) as db:
            existing = db.execute(
                'SELECT 1 FROM public.scans WHERE id=%s AND tenant_id=%s',
                (scan['scan_id'], tenant_id),
            ).fetchone()
            self._ensure_tenant_rows(db, tenant_id, workspace)
            if existing:
                db.execute(
                    'UPDATE public.scans SET timestamp=%s, payload=%s WHERE id=%s AND tenant_id=%s',
                    (scan['timestamp'], Jsonb(scan), scan['scan_id'], tenant_id),
                )
            else:
                db.execute(
                    'INSERT INTO public.scans (id, tenant_id, timestamp, payload) VALUES (%s, %s, %s, %s)',
                    (scan['scan_id'], tenant_id, scan['timestamp'], Jsonb(scan)),
                )
            with db.cursor() as cursor:
                audit_columns = ',opportunity_group_id,slo_burn_rate' if self.has_analysis_audit else ''
                audit_values = ',%s,%s' if self.has_analysis_audit else ''
                cursor.executemany(
                    f'''INSERT INTO public.waste_findings
                    (id, tenant_id, subscription_id, scan_id, resource_id, resource_name,
                     resource_type, resource_group, rule_id, severity, details, evidence,
                     estimated_monthly_waste_usd, observed_at{audit_columns})
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s{audit_values})''',
                    [(uuid4(), tenant_id, f['subscription_id'], scan['scan_id'], f['resource_id'],
                      f['resource_name'], f['resource_type'], f['resource_group'], f['rule_id'],
                      f['severity'], f['details'], Jsonb(waste_finding_evidence(f, scan_id=scan['scan_id'], mode=scan['mode'])),
                      f['estimated_monthly_waste_usd'], scan['timestamp'], *(_analysis_audit(f) if self.has_analysis_audit else ())) for f in scan['findings']
                     if f.get('cloud_provider', 'azure') == 'azure'],
                )
                cursor.executemany(
                    f'''INSERT INTO public.cloud_findings
                    (id,tenant_id,scan_id,cloud_provider,scope_id,resource_id,rule_id,payload,observed_at{audit_columns})
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s{audit_values})''',
                    [(uuid4(), tenant_id, scan['scan_id'], f['cloud_provider'], f['scope_id'], f['resource_id'],
                      f['rule_id'], Jsonb(f), scan['timestamp'], *(_analysis_audit(f) if self.has_analysis_audit else ())) for f in scan['findings']
                     if f.get('cloud_provider', 'azure') != 'azure'],
                )
            if self.has_typed_resource_tables:
                from app.typed_resources.persist import persist_typed_resources
                persist_typed_resources(db, workspace, scan)

    def get(self, tenant_id, scan_id):
        # Invalid UUIDs receive the same 404 as unknown or foreign IDs.
        from uuid import UUID
        try:
            scan_id = str(UUID(scan_id))
        except ValueError:
            return None
        with self.connection(tenant_id) as db:
            row = db.execute('SELECT payload FROM public.scans WHERE id=%s AND tenant_id=%s', (scan_id, tenant_id)).fetchone()
        return _finalize_scan_payload(row[0]) if row else None

    def list(self, tenant_id, limit=50):
        with self.connection(tenant_id) as db:
            rows = db.execute('SELECT payload FROM public.scans WHERE tenant_id=%s ORDER BY timestamp DESC LIMIT %s', (tenant_id, limit)).fetchall()
        return [_finalize_scan_payload(row[0]) for row in rows]

    def list_light(self, tenant_id, limit=50):
        """Scan metadata without multi-MB inventory (for lifecycle comparisons)."""
        with self.connection(tenant_id) as db:
            rows = db.execute(
                """SELECT payload - 'inventory' - 'source_ledger' - 'rule_evaluations' - 'coverage_manifest' AS payload
                   FROM public.scans WHERE tenant_id=%s ORDER BY timestamp DESC LIMIT %s""",
                (tenant_id, limit),
            ).fetchall()
        return [_finalize_scan_payload(row[0]) for row in rows]

    def running_inventory_page(self, tenant_id, scan_id, *, offset=0, limit=100):
        """Read one inventory page from Postgres without loading the full scan payload."""
        from uuid import UUID

        try:
            scan_id = str(UUID(scan_id))
        except ValueError:
            return None
        offset = max(0, int(offset))
        limit = max(1, min(int(limit), 1000))
        with self.connection(tenant_id) as db:
            row = db.execute(
                """
                SELECT
                    payload->>'status' AS status,
                    payload->>'scan_id' AS scan_id,
                    COALESCE(payload->>'timestamp', payload->>'observed_at') AS observed_at,
                    payload->>'data_origin' AS data_origin,
                    COALESCE(jsonb_array_length(payload->'inventory'), 0) AS inventory_total,
                    COALESCE(payload->'findings', '[]'::jsonb) AS findings,
                    (
                        SELECT COALESCE(jsonb_agg(sub.elem ORDER BY sub.ord), '[]'::jsonb)
                        FROM (
                            SELECT elem, ord
                            FROM jsonb_array_elements(COALESCE(payload->'inventory', '[]'::jsonb))
                                WITH ORDINALITY AS t(elem, ord)
                            WHERE ord > %s AND ord <= %s
                        ) sub
                    ) AS inventory
                FROM public.scans
                WHERE id = %s AND tenant_id = %s
                """,
                (offset, offset + limit, scan_id, tenant_id),
            ).fetchone()
        if not row:
            return None
        inventory = row[6] or []
        if isinstance(inventory, str):
            import json
            inventory = json.loads(inventory)
        findings = row[5] or []
        if isinstance(findings, str):
            import json
            findings = json.loads(findings)
        return dict(
            scan_id=row[1] or scan_id,
            status=row[0],
            timestamp=row[2],
            data_origin=row[3],
            inventory_total=int(row[4] or 0),
            inventory=list(inventory),
            findings=list(findings),
        )


def _analysis_audit(finding):
    import math
    group=finding.get('opportunity_group_id');burn=(finding.get('evidence') or {}).get('slo_burn_rate')
    if group is not None and (not isinstance(group,str) or len(group)>160):raise ValueError('Invalid opportunity group metadata')
    burn=burn if type(burn) in (int,float) and math.isfinite(burn) and 0<=burn<1000000 else None
    return group,burn
