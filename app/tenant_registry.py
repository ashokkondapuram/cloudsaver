"""Runtime tenant registry: one-time bootstrap seed, short read cache, optimistic writes.

Reads are served from a per-process cache that expires after
CLOUDSAVER_REGISTRY_CACHE_SECONDS, so a change made in one service is visible to
every other service within that window without a restart.
"""
import logging
import os
import threading
import time
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from app.tenant_config import CONFIG_KEYS, SCOPE_KEYS, config_of, normalize_tenant

logger = logging.getLogger('cloudsaver.registry')
UNSET = object()
TENANT_FIELDS = set(CONFIG_KEYS) | {'name', 'plan_tier', 'active', 'api_key_sha256'}
DIRECTORY_FIELDS = set(SCOPE_KEYS) | {'identity', 'name', 'plan_tier', 'active', 'api_key_sha256'}


class VersionConflict(ValueError):
    pass


class TenantExists(ValueError):
    pass


def env_platform_defaults():
    def flag(name):
        return os.getenv(name, 'false').lower() == 'true'
    return {'scheduled_scans_enabled': flag('CLOUDSAVER_SCHEDULED_SCANS'),
            'automated_alerts_enabled': flag('CLOUDSAVER_AUTOMATED_ALERTS'), 'resource_access': {}}


def normalize_platform(value):
    keys = ('scheduled_scans_enabled', 'automated_alerts_enabled', 'resource_access')
    if not isinstance(value, dict) or set(value) - set(keys):
        raise ValueError('Unknown platform setting')
    if not all(isinstance(value.get(k), bool) for k in ('scheduled_scans_enabled', 'automated_alerts_enabled')):
        raise ValueError('Platform settings require boolean scheduled scan and alert switches')
    resource_access = value.get('resource_access', {})
    if resource_access is None:
        resource_access = {}
    if not isinstance(resource_access, dict):
        raise ValueError('Platform resource access must be an object')
    return {'scheduled_scans_enabled': value['scheduled_scans_enabled'],
            'automated_alerts_enabled': value['automated_alerts_enabled'], 'resource_access': resource_access}


class BaseRegistry:
    def __init__(self, bootstrap=(), ttl=None):
        self.bootstrap = tuple(bootstrap)
        self.ttl = float(os.getenv('CLOUDSAVER_REGISTRY_CACHE_SECONDS', '5')) if ttl is None else ttl
        self._lock = threading.RLock()
        self._cache = None
        self._seeded = False

    def _ensure_seeded(self):
        if self._seeded:
            return
        with self._lock:
            if not self._seeded:
                self._seed(self.bootstrap, env_platform_defaults())
                self._seeded = True

    def _snapshot(self):
        self._ensure_seeded()
        with self._lock:
            if self._cache and self._cache[0] > time.monotonic():
                return self._cache[1]
        tenants, platform = self._load()
        value = (tuple(tenants), platform)
        with self._lock:
            self._cache = (time.monotonic() + self.ttl, value)
        return value

    def invalidate(self):
        with self._lock:
            self._cache = None

    def all(self):
        return self._snapshot()[0]

    def platform(self):
        return self._snapshot()[1]

    def get(self, tenant_id):
        self._ensure_seeded()
        return self._read_one(str(UUID(str(tenant_id))))

    def create(self, raw, actor):
        self._ensure_seeded()
        tenant = normalize_tenant(dict(raw, version=1))
        if not self._insert(tenant, actor):
            raise TenantExists('A tenant with this ID or access key already exists')
        self.invalidate()
        return self._read_one(tenant['tenant_id'])

    def update(self, tenant_id, changes, expected_version, actor, *, webhook=UNSET):
        """Merge validated changes; webhook=None removes it, a string replaces it."""
        if set(changes) - TENANT_FIELDS:
            raise ValueError('Unknown workspace setting')
        current = self.get(tenant_id)
        if current is None:
            raise KeyError(tenant_id)
        if current['version'] != expected_version:
            raise VersionConflict('Settings changed since you loaded them')
        merged = normalize_tenant(dict(current, **changes), allow_missing_key=True)
        if not self._write(merged, expected_version, actor, webhook,
                           plan_changed=merged['plan_tier'] != current['plan_tier']):
            raise VersionConflict('Settings changed since you loaded them')
        self.invalidate()
        return self._read_one(merged['tenant_id'])

    def update_platform(self, changes, expected_version, actor):
        current = self.platform()
        if current['version'] != expected_version:
            raise VersionConflict('Platform settings changed since you loaded them')
        merged = normalize_platform({k: v for k, v in dict(current, **changes).items() if k != 'version'})
        if not self._write_platform(merged, expected_version, actor):
            raise VersionConflict('Platform settings changed since you loaded them')
        self.invalidate()
        return self.platform()

    def update_plan(self, tenant_id, plan_code, expected_version, actor):
        from app.billing_plan import build_plan_block

        current = self.get(tenant_id)
        if current is None:
            raise KeyError(tenant_id)
        if current['version'] != expected_version:
            raise VersionConflict('Settings changed since you loaded them')
        block = build_plan_block(plan_code, current.get('plan') or {})
        merged = normalize_tenant(dict(current, plan_tier=block['code'], plan=block), allow_missing_key=True)
        if not self._write_plan(merged, expected_version, actor, block):
            raise VersionConflict('Settings changed since you loaded them')
        self.invalidate()
        return self._read_one(merged['tenant_id'])

    # ----- directory projection (cutover) -----------------------------------------------------------
    @staticmethod
    def projected(current, snap):
        """Directory-owned fields from a change-feed snapshot over the tenant-owned preferences."""
        base = config_of(current) if current else {}
        return normalize_tenant(dict(
            base, **{k: snap[k] for k in SCOPE_KEYS}, identity=snap['identity'], tenant_id=snap['tenant_id'],
            name=snap['name'], plan_tier=snap['plan_tier'], plan=snap.get('plan'), active=bool(snap['active']),
            customer_id=snap['customer_id'], directory_version=snap['version'], api_key_sha256=None,
            version=current['version'] if current else 1),
            allow_missing_key=True)

    def apply_snapshot(self, snap):
        """Idempotent; snapshots older than the projected directory version are ignored."""
        self._ensure_seeded()
        changed = self._apply(snap)
        if changed:
            self.invalidate()
        return changed

    def deactivate_missing(self, tenant_ids):
        changed = self._deactivate_missing({str(UUID(t)) for t in tenant_ids})
        self.invalidate()
        return changed

    def apply_platform(self, value):
        self._ensure_seeded()
        current = self.platform()
        patch = {k: value[k] for k in ('scheduled_scans_enabled', 'automated_alerts_enabled', 'resource_access') if k in value}
        merged = normalize_platform({**{k: current[k] for k in ('scheduled_scans_enabled', 'automated_alerts_enabled', 'resource_access')}, **patch})
        if merged == {k: current[k] for k in merged}:
            return False
        self._write_platform(merged, current['version'], 'directory')
        self.invalidate()
        return True

    @staticmethod
    def _same(current, tenant):
        return current is not None and all(current.get(k) == tenant.get(k) for k in tenant if k not in ('version', 'webhook_configured'))


class MemoryRegistry(BaseRegistry):
    """Process-local registry for unit tests and SQLite development."""

    def __init__(self, bootstrap=(), ttl=0, platform=None):
        super().__init__(bootstrap, ttl)
        self._tenants, self._webhooks = {}, {}
        self._platform = dict(platform or env_platform_defaults(), version=1)
        self.audit = []

    def _seed(self, bootstrap, platform):
        for tenant in bootstrap:
            self._insert(dict(tenant, version=1), 'bootstrap')

    def _public(self, tenant):
        return dict(tenant, webhook_configured=tenant['tenant_id'] in self._webhooks)

    def _load(self):
        return [self._public(t) for t in sorted(self._tenants.values(), key=lambda t: (t['name'], t['tenant_id']))], dict(self._platform)

    def _read_one(self, tenant_id):
        tenant = self._tenants.get(tenant_id)
        return self._public(tenant) if tenant else None

    def _insert(self, tenant, actor):
        digest = tenant.get('api_key_sha256')
        if tenant['tenant_id'] in self._tenants or (digest and any(t.get('api_key_sha256') == digest for t in self._tenants.values())):
            return False
        self._tenants[tenant['tenant_id']] = dict(tenant, version=1)
        self.audit.append((tenant['tenant_id'], actor, 'tenant_created', 1))
        return True

    def _write_plan(self, tenant, expected_version, actor, plan_block):
        stored = self._tenants.get(tenant['tenant_id'])
        if not stored or stored['version'] != expected_version:
            return False
        self._tenants[tenant['tenant_id']] = dict(tenant, plan=plan_block, version=expected_version + 1)
        self.audit.append((tenant['tenant_id'], actor, 'plan_changed', expected_version + 1))
        return True

    def _write(self, tenant, expected_version, actor, webhook, *, plan_changed):
        stored = self._tenants.get(tenant['tenant_id'])
        if not stored or stored['version'] != expected_version:
            return False
        self._tenants[tenant['tenant_id']] = dict(tenant, version=expected_version + 1)
        if webhook is None:
            self._webhooks.pop(tenant['tenant_id'], None)
        elif webhook is not UNSET:
            self._webhooks[tenant['tenant_id']] = webhook
        self.audit.append((tenant['tenant_id'], actor, 'tenant_updated', expected_version + 1))
        return True

    def _write_platform(self, settings, expected_version, actor):
        if self._platform['version'] != expected_version:
            return False
        self._platform = dict(settings, version=expected_version + 1)
        self.audit.append((None, actor, 'platform_updated', expected_version + 1))
        return True

    def _apply(self, snap):
        current = self._tenants.get(snap['tenant_id'])
        if current and (current.get('directory_version') or 0) > snap['version']:
            return False
        tenant = self.projected(current, snap)
        if self._same(current, tenant):
            return False
        version = current['version'] + 1 if current else 1
        self._tenants[tenant['tenant_id']] = dict(tenant, version=version)
        self.audit.append((tenant['tenant_id'], 'directory', 'tenant_projected', version))
        return True

    def _deactivate_missing(self, tenant_ids):
        changed = 0
        for tid, tenant in self._tenants.items():
            if tid not in tenant_ids and tenant['active']:
                self._tenants[tid] = dict(tenant, active=False, version=tenant['version'] + 1)
                changed += 1
        return changed

    projection_seq = 0

    def projection_cursor(self):
        return self.projection_seq

    def set_projection_cursor(self, seq):
        self.projection_seq = seq

    def webhook_targets(self):
        return [dict(tenant_id=tid, channel=self._tenants[tid]['alerts']['channel'], url=url)
                for tid, url in self._webhooks.items()
                if self._tenants[tid]['active'] and self._tenants[tid]['alerts']['channel']]


class PostgresRegistry(BaseRegistry):
    SELECT = ('SELECT tenant_id, name, plan_tier, api_key_sha256, active, config, '
              'webhook_url IS NOT NULL, version, customer_id, directory_version, entitlements, entitlements_version, '
              'billing_state, plan_name, current_period_end, grace_ends_at, subscription_plan_name, manage_billing_url '
              'FROM public.tenant_registry')

    def __init__(self, url, bootstrap=(), ttl=None):
        super().__init__(bootstrap, ttl)
        self.url = url

    def _connect(self):
        from database.connection import connect
        return connect(self.url, connect_timeout=5)

    @staticmethod
    def _row(row):
        (tenant_id, name, tier, digest, active, config, has_webhook, version, customer_id, directory_version,
         entitlements, entitlements_version, billing_state, plan_name, period_end, grace_ends_at,
         subscription_plan_name, manage_billing_url) = row
        plan = None if entitlements is None else dict(
            code=tier, name=plan_name, billing_state=billing_state, current_period_end=period_end,
            grace_ends_at=grace_ends_at, subscription_plan_name=subscription_plan_name,
            entitlements_version=entitlements_version, entitlements=entitlements, manage_billing_url=manage_billing_url)
        tenant = normalize_tenant(dict(config, tenant_id=str(tenant_id), name=name, plan_tier=tier, plan=plan,
                                       api_key_sha256=digest.strip() if digest else None, active=active, version=version,
                                       customer_id=customer_id, directory_version=directory_version),
                                  allow_missing_key=True)
        tenant['webhook_configured'] = bool(has_webhook)
        return tenant

    def _rows(self, rows):
        result = []
        for row in rows:
            try:
                result.append(self._row(row))
            except ValueError:
                logger.error('Skipping a tenant registry row that failed validation')
        return result

    def _load(self):
        with self._connect() as db:
            rows = db.execute(self.SELECT + ' ORDER BY name, tenant_id').fetchall()
            platform = db.execute('SELECT settings, version FROM public.platform_settings WHERE id=1').fetchone()
        settings = (dict(normalize_platform(platform[0]), version=platform[1]) if platform
                    else dict(env_platform_defaults(), version=0))
        return self._rows(rows), settings

    def _read_one(self, tenant_id):
        with self._connect() as db:
            rows = db.execute(self.SELECT + ' WHERE tenant_id=%s', (tenant_id,)).fetchall()
        found = self._rows(rows)
        return found[0] if found else None

    def _seed(self, bootstrap, platform):
        from psycopg.types.json import Jsonb
        with self._connect() as db:
            for tenant in bootstrap:
                inserted = db.execute(
                    'INSERT INTO public.tenant_registry (tenant_id, name, plan_tier, api_key_sha256, active, config, updated_by) '
                    "VALUES (%s,%s,%s,%s,%s,%s,'bootstrap') ON CONFLICT DO NOTHING RETURNING tenant_id",
                    (tenant['tenant_id'], tenant['name'], tenant['plan_tier'], tenant['api_key_sha256'],
                     tenant['active'], Jsonb(config_of(tenant)))).fetchone()
                if inserted:
                    self._audit(db, tenant['tenant_id'], 'bootstrap', 'tenant_seeded', 1)
                    self._sync_domain(db, tenant, plan_changed=True)
            db.execute("INSERT INTO public.platform_settings (id, settings, updated_by) VALUES (1, %s, 'bootstrap') "
                       'ON CONFLICT (id) DO NOTHING', (Jsonb(normalize_platform(platform)),))

    def _insert(self, tenant, actor):
        from psycopg.types.json import Jsonb
        with self._connect() as db:
            inserted = db.execute(
                'INSERT INTO public.tenant_registry (tenant_id, name, plan_tier, api_key_sha256, active, config, updated_by) '
                'VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING tenant_id',
                (tenant['tenant_id'], tenant['name'], tenant['plan_tier'], tenant['api_key_sha256'],
                 tenant['active'], Jsonb(config_of(tenant)), actor)).fetchone()
            if not inserted:
                return False
            self._audit(db, tenant['tenant_id'], actor, 'tenant_created', 1)
            self._sync_domain(db, tenant, plan_changed=True)
        return True

    def _write_plan(self, tenant, expected_version, actor, plan_block):
        from psycopg.types.json import Jsonb
        with self._connect() as db:
            updated = db.execute(
                'UPDATE public.tenant_registry SET plan_tier=%s, entitlements=%s, entitlements_version=%s, '
                'billing_state=%s, plan_name=%s, current_period_end=%s, grace_ends_at=%s, subscription_plan_name=%s, '
                'manage_billing_url=%s, version=version+1, updated_by=%s, updated_at=now() '
                'WHERE tenant_id=%s AND version=%s RETURNING version',
                (tenant['plan_tier'], Jsonb(plan_block['entitlements']), plan_block.get('entitlements_version'),
                 plan_block['billing_state'], plan_block['name'], plan_block.get('current_period_end'),
                 plan_block.get('grace_ends_at'), plan_block.get('subscription_plan_name'),
                 plan_block.get('manage_billing_url'), actor, tenant['tenant_id'], expected_version)).fetchone()
            if not updated:
                return False
            self._audit(db, tenant['tenant_id'], actor, 'plan_changed', updated[0])
            self._sync_domain(db, tenant, plan_changed=True)
        return True

    def _write(self, tenant, expected_version, actor, webhook, *, plan_changed):
        from psycopg.types.json import Jsonb
        webhook_sql, params = '', []
        if webhook is not UNSET:
            webhook_sql, params = ', webhook_url=%s', [webhook]
        with self._connect() as db:
            updated = db.execute(
                'UPDATE public.tenant_registry SET name=%s, plan_tier=%s, api_key_sha256=%s, active=%s, config=%s, '
                'version=version+1, updated_by=%s, updated_at=now()' + webhook_sql +
                ' WHERE tenant_id=%s AND version=%s RETURNING version',
                [tenant['name'], tenant['plan_tier'], tenant['api_key_sha256'], tenant['active'],
                 Jsonb(config_of(tenant)), actor, *params, tenant['tenant_id'], expected_version]).fetchone()
            if not updated:
                return False
            self._audit(db, tenant['tenant_id'], actor, 'tenant_updated', updated[0])
            self._sync_domain(db, tenant, plan_changed=plan_changed)
        return True

    def _write_platform(self, settings, expected_version, actor):
        from psycopg.types.json import Jsonb
        with self._connect() as db:
            updated = db.execute('UPDATE public.platform_settings SET settings=%s, version=version+1, updated_by=%s, '
                                 'updated_at=now() WHERE id=1 AND version=%s RETURNING version',
                                 (Jsonb(settings), actor, expected_version)).fetchone()
            if updated:
                self._audit(db, None, actor, 'platform_updated', updated[0])
        return bool(updated)

    def _apply(self, snap):
        from psycopg.types.json import Jsonb
        with self._connect() as db:
            row = db.execute(self.SELECT + ' WHERE tenant_id=%s FOR UPDATE', (snap['tenant_id'],)).fetchone()
            current = self._row(row) if row else None
            if current and (current.get('directory_version') or 0) > snap['version']:
                return False
            tenant = self.projected(current, snap)
            if self._same(current, tenant):
                return False
            plan = tenant.get('plan') or {}
            version = db.execute(
                'INSERT INTO public.tenant_registry (tenant_id, name, plan_tier, api_key_sha256, active, config, customer_id, '
                'directory_version, entitlements, entitlements_version, billing_state, plan_name, current_period_end, '
                'grace_ends_at, subscription_plan_name, manage_billing_url, projected_at, updated_by) '
                "VALUES (%s,%s,%s,NULL,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now(),'directory') "
                'ON CONFLICT (tenant_id) DO UPDATE SET name=EXCLUDED.name, plan_tier=EXCLUDED.plan_tier, api_key_sha256=NULL, '
                'active=EXCLUDED.active, config=EXCLUDED.config, customer_id=EXCLUDED.customer_id, '
                'directory_version=EXCLUDED.directory_version, entitlements=EXCLUDED.entitlements, '
                'entitlements_version=EXCLUDED.entitlements_version, billing_state=EXCLUDED.billing_state, '
                'plan_name=EXCLUDED.plan_name, current_period_end=EXCLUDED.current_period_end, '
                'grace_ends_at=EXCLUDED.grace_ends_at, subscription_plan_name=EXCLUDED.subscription_plan_name, '
                'manage_billing_url=EXCLUDED.manage_billing_url, projected_at=now(), version=tenant_registry.version+1, '
                "updated_by='directory', updated_at=now() RETURNING version",
                (tenant['tenant_id'], tenant['name'], tenant['plan_tier'], tenant['active'], Jsonb(config_of(tenant)),
                 tenant['customer_id'], tenant['directory_version'],
                 Jsonb(plan['entitlements']) if plan else None, plan.get('entitlements_version'), plan.get('billing_state'),
                 plan.get('name'), plan.get('current_period_end'), plan.get('grace_ends_at'),
                 plan.get('subscription_plan_name'), plan.get('manage_billing_url'))).fetchone()[0]
            self._audit(db, tenant['tenant_id'], 'directory', 'tenant_projected', version)
            self._sync_domain(db, tenant, plan_changed=current is None or current['plan_tier'] != tenant['plan_tier'])
        return True

    def _deactivate_missing(self, tenant_ids):
        with self._connect() as db:
            rows = db.execute(self.SELECT + ' WHERE active AND NOT (tenant_id = ANY(%s::uuid[])) FOR UPDATE',
                              (sorted(tenant_ids),)).fetchall()
            for tenant in self._rows(rows):
                db.execute("UPDATE public.tenant_registry SET active=false, version=version+1, updated_by='directory', "
                           'updated_at=now(), projected_at=now() WHERE tenant_id=%s', (tenant['tenant_id'],))
                self._audit(db, tenant['tenant_id'], 'directory', 'tenant_projected', tenant['version'] + 1)
                self._sync_domain(db, dict(tenant, active=False), plan_changed=False)
        return len(rows)

    def projection_cursor(self):
        with self._connect() as db:
            row = db.execute('SELECT seq FROM public.directory_projection_cursor WHERE id=1').fetchone()
        return row[0] if row else 0

    def set_projection_cursor(self, seq):
        with self._connect() as db:
            db.execute('INSERT INTO public.directory_projection_cursor (id, seq) VALUES (1, %s) '
                       'ON CONFLICT (id) DO UPDATE SET seq=EXCLUDED.seq, updated_at=now()', (seq,))

    def webhook_targets(self):
        with self._connect() as db:
            rows = db.execute("SELECT tenant_id, config->'alerts'->>'channel', webhook_url FROM public.tenant_registry "
                              "WHERE active AND webhook_url IS NOT NULL AND config->'alerts'->>'channel' IS NOT NULL").fetchall()
        return [dict(tenant_id=str(r[0]), channel=r[1], url=r[2]) for r in rows]

    @staticmethod
    def _audit(db, tenant_id, actor, action, version):
        db.execute('INSERT INTO public.settings_audit (id, tenant_id, actor, action, version) VALUES (%s,%s,%s,%s,%s)',
                   (uuid4(), tenant_id, actor[:80], action, version))

    @staticmethod
    def _sync_domain(db, tenant, *, plan_changed):
        """Mirror registry state into RLS-protected domain rows used by workers and billing."""
        tid = tenant['tenant_id']
        db.execute("SELECT set_config('app.current_tenant_id', %s, true)", (tid,))
        row = db.execute('SELECT organization_id FROM public.tenants WHERE tenant_id=%s', (tid,)).fetchone()
        if row:
            organization_id = row[0]
        else:
            existing = db.execute('SELECT id FROM public.organizations WHERE tenant_id=%s ORDER BY created_at LIMIT 1',
                                  (tid,)).fetchone()
            organization_id = existing[0] if existing else uuid5(NAMESPACE_URL, 'cloudsaver:organization:' + tid)
            db.execute('INSERT INTO public.organizations (id, tenant_id, name, plan_tier) VALUES (%s,%s,%s,%s) '
                       'ON CONFLICT (id) DO NOTHING', (organization_id, tid, tenant['name'], tenant['plan_tier']))
        db.execute('UPDATE public.organizations SET name=%s WHERE id=%s AND tenant_id=%s',
                   (tenant['name'], organization_id, tid))
        if plan_changed:
            db.execute('UPDATE public.organizations SET plan_tier=%s WHERE id=%s AND tenant_id=%s',
                       (tenant['plan_tier'], organization_id, tid))
        db.execute('INSERT INTO public.tenants (tenant_id, organization_id, display_name, connection_status) '
                   'VALUES (%s,%s,%s,%s) ON CONFLICT (tenant_id) DO UPDATE SET display_name=EXCLUDED.display_name, '
                   'connection_status=EXCLUDED.connection_status',
                   (tid, organization_id, tenant['name'], 'connected' if tenant['active'] else 'pending'))
        for sid in tenant['subscription_ids']:
            db.execute('INSERT INTO public.subscriptions (id, tenant_id, subscription_id, display_name, active) '
                       "VALUES (%s,%s,%s,'Configured subscription',true) "
                       'ON CONFLICT (tenant_id, subscription_id) DO UPDATE SET active=true',
                       (uuid5(NAMESPACE_URL, 'cloudsaver:sub:' + tid + ':' + sid), tid, sid))
        db.execute('UPDATE public.subscriptions SET active=false WHERE tenant_id=%s AND NOT (subscription_id = ANY(%s::uuid[]))',
                   (tid, tenant['subscription_ids']))


_registries = {}
_registries_lock = threading.Lock()


def registry_for(url, bootstrap=()):
    with _registries_lock:
        if url not in _registries:
            _registries[url] = PostgresRegistry(url, bootstrap)
        return _registries[url]
