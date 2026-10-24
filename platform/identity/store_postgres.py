"""platform-db persistence through the least-privilege identity_app role."""
from contextlib import contextmanager

from identity.billing.domain import ENDED
from identity.domain import SCOPE_KEYS, KEY_DEFAULTS

KEY_COLUMNS = ('id', 'key_id', 'tenant_id', 'name', 'roles', 'all_providers', 'allowed_providers', 'scope_restrictions',
               'format', 'hash_scheme', 'secret_digest', 'pepper_version', 'legacy_sha256', 'legacy_fingerprint',
               'created_at', 'created_by', 'expires_at', 'revoked_at', 'revoked_by', 'revoke_reason', 'rotated_from',
               'rotates_out_at', 'last_used_at', 'last_used_ip', 'source', 'version', 'purpose', 'subject_type',
               'subject_user_id', 'service_account_id', 'claimed_at')
SCOPE_SQL = {
    'azure': ('workspace_azure_subscriptions', ('subscription_id',)),
    'aws': ('workspace_aws_accounts', ('account_id', 'region', 'role_arn')),
    'gcp': ('workspace_gcp_projects', ('project_id', 'regions')),
    'kubernetes': ('workspace_kubernetes_clusters', ('cluster_id', 'prometheus_url', 'bearer_token_env')),
}
# jsonb columns; every other list value is a PostgreSQL array (roles, allowed_providers).
JSON_COLUMNS = frozenset({'identity', 'scope_restrictions', 'details', 'external_customer_refs', 'entitlements',
                          'entitlement_overrides', 'external_price_refs', 'snapshot', 'parameters', 'policy'})
ENDED_SQL = '(' + ','.join(f"'{s}'" for s in ENDED) + ')'


def _text(row, *fields):
    for field in fields:
        if row.get(field) is not None:
            row[field] = str(row[field])
    return row


def _json(name, value):
    from psycopg.types.json import Jsonb
    return Jsonb(value) if name in JSON_COLUMNS and value is not None else value


def _sub(row):
    return _text(dict(row), 'id', 'customer_id') if row else None


def _payment(row):
    return _text(dict(row), 'id', 'customer_id', 'subscription_id') if row else None


class PostgresTx:
    def __init__(self, db):
        self.db = db

    def get_ai_policy(self):
        return dict(self._one('SELECT policy,version,updated_at,updated_by FROM directory.ai_foundry_policy WHERE id=1'))

    def update_ai_policy(self, expected_version, fields):
        row = self._update('directory.ai_foundry_policy', 'id', 1, expected_version, fields)
        return dict(row) if row else None

    def _one(self, sql, params=()):
        return self.db.execute(sql, params).fetchone()

    def _all(self, sql, params=()):
        return self.db.execute(sql, params).fetchall()

    def _insert(self, table, row):
        columns = list(row)
        self.db.execute(f'INSERT INTO {table} ({", ".join(chr(34) + c + chr(34) for c in columns)}) '
                        f'VALUES ({", ".join(["%s"] * len(columns))})', [_json(c, row[c]) for c in columns])

    def _update(self, table, key_column, key, expected_version, fields):
        assignments = [f'"{name}"=%s' for name in fields] + ['version=version+1']
        values = [_json(name, v) for name, v in fields.items()]
        sql = f'UPDATE {table} SET {", ".join(assignments)} WHERE {key_column}=%s'
        values.append(key)
        if expected_version is not None:
            sql += ' AND version=%s'
            values.append(expected_version)
        return self._one(sql + ' RETURNING *', values)

    # customers
    def get_customer(self, customer_id, lock=False):
        row = self._one('SELECT * FROM directory.customers WHERE id=%s' + (' FOR UPDATE' if lock else ''), (customer_id,))
        return _text(dict(row), 'id') if row else None

    def list_customers(self, q, status, offset, limit):
        sql, params = 'SELECT * FROM directory.customers WHERE true', []
        if status:
            sql, params = sql + ' AND status=%s', params + [status]
        if q:
            sql, params = sql + " AND name ILIKE %s", params + ['%' + q.replace('%', r'\%').replace('_', r'\_') + '%']
        rows = self._all(sql + ' ORDER BY lower(name), id OFFSET %s LIMIT %s', params + [offset, limit])
        return [_text(dict(r), 'id') for r in rows]

    def customer_workspace_counts(self):
        rows = self._all("SELECT customer_id, count(*) AS total, count(*) FILTER (WHERE status='active') AS active "
                         "FROM directory.workspaces WHERE status <> 'deleted' GROUP BY customer_id")
        return {str(r['customer_id']): (r['total'], r['active']) for r in rows}

    def insert_customer(self, row):
        self._insert('directory.customers', row)

    def update_customer(self, customer_id, expected_version, fields):
        row = self._update('directory.customers', 'id', customer_id, expected_version, fields)
        return _text(dict(row), 'id') if row else None

    def set_customer_billing_state(self, customer_id, state, at):
        self.db.execute('UPDATE directory.customers SET billing_state=%s, billing_state_changed_at=%s WHERE id=%s',
                        (state, at, customer_id))

    def customer_by_external_ref(self, provider, ref):
        row = self._one('SELECT * FROM directory.customers WHERE external_customer_refs->>%s = %s', (provider, ref))
        return _text(dict(row), 'id') if row else None

    # workspaces
    def _with_scopes(self, rows):
        if not rows:
            return []
        result = {str(r['tenant_id']): _text(dict(r), 'tenant_id', 'customer_id') | {k: [] for k in SCOPE_KEYS.values()}
                  for r in rows}
        ids = list(result)
        for provider, (table, columns) in SCOPE_SQL.items():
            for row in self._all(f'SELECT tenant_id, {", ".join(columns)} FROM directory.{table} '
                                 'WHERE tenant_id = ANY(%s::uuid[]) ORDER BY tenant_id, position', (ids,)):
                target = result[str(row['tenant_id'])][SCOPE_KEYS[provider]]
                if provider == 'azure':
                    target.append(str(row['subscription_id']))
                else:
                    target.append({c: (row[c].strip() if c == 'account_id' else list(row[c]) if c == 'regions' else row[c])
                                   for c in columns})
        return [result[str(r['tenant_id'])] for r in rows]

    def get_workspace(self, tenant_id, lock=False):
        row = self._one('SELECT * FROM directory.workspaces WHERE tenant_id=%s' + (' FOR UPDATE' if lock else ''), (tenant_id,))
        return self._with_scopes([row])[0] if row else None

    def list_workspaces(self, q, status, customer_id, offset, limit):
        sql, params = 'SELECT * FROM directory.workspaces WHERE true', []
        if status:
            sql, params = sql + ' AND status=%s', params + [status]
        if customer_id:
            sql, params = sql + ' AND customer_id=%s', params + [customer_id]
        if q:
            sql, params = sql + ' AND (name ILIKE %s OR tenant_id::text LIKE %s)', params + ['%' + q.replace('%', r'\%') + '%', q.lower() + '%']
        return self._with_scopes(self._all(sql + ' ORDER BY lower(name), tenant_id OFFSET %s LIMIT %s', params + [offset, limit]))

    def insert_workspace(self, row):
        self._insert('directory.workspaces', {k: v for k, v in row.items() if k not in SCOPE_KEYS.values()})
        for provider, key in SCOPE_KEYS.items():
            self.replace_scopes(row['tenant_id'], provider, row[key], row['created_by'], row['created_at'], clear=False)

    def update_workspace(self, tenant_id, expected_version, fields):
        row = self._update('directory.workspaces', 'tenant_id', tenant_id, expected_version, fields)
        return self.get_workspace(tenant_id) if row else None

    def replace_scopes(self, tenant_id, provider, items, actor, now, clear=True):
        table, columns = SCOPE_SQL[provider]
        if clear:
            self.db.execute(f'DELETE FROM directory.{table} WHERE tenant_id=%s', (tenant_id,))
        for position, item in enumerate(items):
            values = [item] if provider == 'azure' else [item[c] for c in columns]
            self.db.execute(f'INSERT INTO directory.{table} (tenant_id, position, created_at, created_by, {", ".join(columns)}) '
                            f'VALUES (%s, %s, %s, %s, {", ".join(["%s"] * len(columns))})',
                            [tenant_id, position, now, actor, *values])

    # platform
    def get_platform(self):
        return dict(self._one('SELECT scheduled_scans_enabled, automated_alerts_enabled, resource_access, version, '
                              'updated_by, updated_at FROM directory.platform_settings WHERE id=1'))

    def update_platform(self, expected_version, fields):
        row = self._update('directory.platform_settings', 'id', 1, expected_version, fields)
        return {k: row[k] for k in ('scheduled_scans_enabled', 'automated_alerts_enabled', 'resource_access', 'version',
                                     'updated_by', 'updated_at')} if row else None

    # change feed
    def append_change(self, tenant_id, change_type, version, snapshot):
        from psycopg.types.json import Jsonb
        return self._one('INSERT INTO directory.directory_changes (tenant_id, change_type, version, snapshot) '
                         'VALUES (%s, %s, %s, %s) RETURNING seq', (tenant_id, change_type, version, Jsonb(snapshot)))['seq']

    def changes_after(self, after, limit):
        rows = self._all('SELECT * FROM directory.directory_changes WHERE seq > %s ORDER BY seq LIMIT %s', (after or 0, limit))
        return [_text(dict(r), 'tenant_id') for r in rows]

    def min_change_seq(self):
        return self._one('SELECT min(seq) AS seq FROM directory.directory_changes')['seq']

    def max_change_seq(self):
        return self._one('SELECT max(seq) AS seq FROM directory.directory_changes')['seq']

    # keys
    @staticmethod
    def _key(row):
        if not row:
            return None
        row = _text(dict(row), 'id', 'tenant_id', 'rotated_from', 'subject_user_id', 'service_account_id')
        for field in ('secret_digest', 'legacy_fingerprint'):
            if row[field] is not None:
                row[field] = bytes(row[field])
        if row['legacy_sha256']:
            row['legacy_sha256'] = row['legacy_sha256'].strip()
        row['roles'], row['allowed_providers'] = list(row['roles']), list(row['allowed_providers'])
        return row

    def key_by_key_id(self, key_id, lock=False):
        return self._key(self._one('SELECT * FROM identity.api_keys WHERE key_id=%s' + (' FOR UPDATE' if lock else ''), (key_id,)))

    def key_by_legacy(self, digest):
        return self._key(self._one('SELECT * FROM identity.api_keys WHERE legacy_sha256=%s', (digest,)))

    def key_by_digest(self, digest):
        return self._key(self._one('SELECT * FROM identity.api_keys WHERE secret_digest=%s', (digest,))) if digest else None

    def key_by_fingerprint(self, fingerprint):
        return self._key(self._one('SELECT * FROM identity.api_keys WHERE legacy_fingerprint=%s', (fingerprint,))) if fingerprint else None

    def list_keys(self, tenant_id):
        return [self._key(r) for r in self._all('SELECT * FROM identity.api_keys WHERE tenant_id=%s '
                                                'ORDER BY created_at DESC, key_id DESC', (tenant_id,))]

    def key_stats(self, now):
        rows = self._all('''SELECT tenant_id, max(last_used_at) AS last_used_at,
            count(*) FILTER (WHERE revoked_at IS NULL AND (expires_at IS NULL OR expires_at > %(now)s)
                             AND (rotates_out_at IS NULL OR rotates_out_at > %(now)s)) AS active,
            min(expires_at) FILTER (WHERE revoked_at IS NULL AND expires_at > %(now)s
                                    AND (rotates_out_at IS NULL OR rotates_out_at > %(now)s)) AS next_expiry
            FROM identity.api_keys GROUP BY tenant_id''', {'now': now})
        return {str(r['tenant_id']): {'active': r['active'], 'last_used_at': r['last_used_at'], 'next_expiry': r['next_expiry']}
                for r in rows}

    def insert_key(self, row):
        row = {**KEY_DEFAULTS, **row}
        self._insert('identity.api_keys', {c: row[c] for c in KEY_COLUMNS})

    def update_key(self, key_id, fields, expected_version=None):
        return self._key(self._update('identity.api_keys', 'key_id', key_id, expected_version, fields))

    # audit
    def append_event(self, row):
        self._insert('identity.key_events', {c: row[c] for c in ('id', 'occurred_at', 'actor', 'actor_type', 'action',
                                                                 'tenant_id', 'key_id', 'details', 'request_id')})

    def list_events(self, filters, before, limit):
        sql, params = 'SELECT * FROM identity.key_events WHERE true', []
        for name in ('tenant_id', 'key_id', 'actor', 'action'):
            if name in filters:
                sql, params = sql + f' AND {name}=%s', params + [filters[name]]
        if 'customer_id' in filters:
            sql += " AND (tenant_id = ANY(%s::uuid[]) OR details->>'customer_id' = %s)"
            params += [filters.get('tenant_ids', []), filters['customer_id']]
        if before is not None:
            sql, params = sql + ' AND occurred_at < %s', params + [before]
        return [dict(r) for r in self._all(sql + ' ORDER BY occurred_at DESC LIMIT %s', params + [limit])]

    # usage
    def record_usage(self, usage, failures, last_used):
        with self.db.cursor() as cursor:
            if usage:
                cursor.executemany('''INSERT INTO identity.key_usage_hourly AS u (key_id, hour, source_ip, success_count, failure_count, last_seen_at)
                    VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (key_id, hour, source_ip) DO UPDATE SET
                    success_count = u.success_count + EXCLUDED.success_count, failure_count = u.failure_count + EXCLUDED.failure_count,
                    last_seen_at = greatest(u.last_seen_at, EXCLUDED.last_seen_at)''', usage)
            if failures:
                cursor.executemany('''INSERT INTO identity.verification_failures_minute AS f (minute, source_ip, key_id, tenant_id, reason, caller, count)
                    VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (minute, source_ip, key_id, reason, caller)
                    DO UPDATE SET count = f.count + EXCLUDED.count''', failures)
            if last_used:
                cursor.executemany('UPDATE identity.api_keys SET last_used_at=%s, last_used_ip=%s WHERE key_id=%s AND '
                                   '(last_used_at IS NULL OR last_used_at < %s)',
                                   [(when, ip, key_id, when) for key_id, (when, ip) in last_used.items()])

    def list_usage(self, key_ids, start, end):
        return [dict(r) for r in self._all('SELECT * FROM identity.key_usage_hourly WHERE key_id = ANY(%s) AND hour BETWEEN %s AND %s '
                                           'ORDER BY hour, source_ip', (key_ids, start, end))]

    def list_failures(self, filters, start, limit):
        sql, params = 'SELECT * FROM identity.verification_failures_minute WHERE minute >= %s', [start]
        for name in ('tenant_id', 'reason'):
            if name in filters:
                sql, params = sql + f' AND {name}=%s', params + [filters[name]]
        if 'source_ip' in filters:
            sql, params = sql + ' AND source_ip=%s::inet', params + [filters['source_ip']]
        return [_text(dict(r), 'tenant_id') for r in self._all(sql + ' ORDER BY minute DESC LIMIT %s', params + [limit])]

    # billing: plans and settings
    def list_plans(self):
        return [dict(r) for r in self._all('SELECT * FROM billing.plans ORDER BY code')]

    def get_plan(self, code, lock=False):
        row = self._one('SELECT * FROM billing.plans WHERE code=%s' + (' FOR UPDATE' if lock else ''), (code,))
        return dict(row) if row else None

    def insert_plan(self, row):
        self._insert('billing.plans', row)

    def update_plan(self, code, expected_version, fields):
        row = self._update('billing.plans', 'code', code, expected_version, fields)
        return dict(row) if row else None

    def plan_usage(self):
        rows = self._all("SELECT plan_tier, count(DISTINCT customer_id) AS customers, count(*) AS workspaces "
                         "FROM directory.workspaces WHERE status <> 'deleted' GROUP BY plan_tier")
        return {r['plan_tier']: (r['customers'], r['workspaces']) for r in rows}

    def get_billing_settings(self, lock=False):
        row = self._one('SELECT * FROM billing.settings WHERE id=1' + (' FOR UPDATE' if lock else ''))
        return {k: v for k, v in dict(row).items() if k != 'id'}

    def update_billing_settings(self, expected_version, fields):
        row = self._update('billing.settings', 'id', 1, expected_version, fields)
        return {k: v for k, v in dict(row).items() if k != 'id'} if row else None

    # billing: subscriptions
    def get_subscription(self, subscription_id, lock=False):
        return _sub(self._one('SELECT * FROM billing.subscriptions WHERE id=%s' + (' FOR UPDATE' if lock else ''),
                              (subscription_id,)))

    def list_subscriptions(self, customer_id):
        return [_sub(r) for r in self._all('SELECT * FROM billing.subscriptions WHERE customer_id=%s '
                                           'ORDER BY created_at DESC, id DESC', (customer_id,))]

    def current_subscription(self, customer_id, lock=False):
        return _sub(self._one(f'SELECT * FROM billing.subscriptions WHERE customer_id=%s AND status NOT IN {ENDED_SQL}'
                              + (' FOR UPDATE' if lock else ''), (customer_id,)))

    def latest_subscription(self, customer_id):
        return _sub(self._one(f'SELECT * FROM billing.subscriptions WHERE customer_id=%s '
                              f'ORDER BY (status NOT IN {ENDED_SQL}) DESC, created_at DESC, id DESC LIMIT 1', (customer_id,)))

    def latest_subscriptions(self):
        rows = self._all(f'SELECT DISTINCT ON (customer_id) * FROM billing.subscriptions '
                         f'ORDER BY customer_id, (status NOT IN {ENDED_SQL}) DESC, created_at DESC, id DESC')
        return {str(r['customer_id']): _sub(r) for r in rows}

    def subscription_by_ref(self, provider, ref):
        return _sub(self._one('SELECT * FROM billing.subscriptions WHERE provider=%s AND external_subscription_ref=%s',
                              (provider, ref)))

    def latest_provider_subscription(self, customer_id, provider):
        return _sub(self._one('SELECT * FROM billing.subscriptions WHERE customer_id=%s AND provider=%s '
                              'ORDER BY created_at DESC, id DESC LIMIT 1 FOR UPDATE', (customer_id, provider)))

    def insert_subscription(self, row):
        self._insert('billing.subscriptions', row)

    def update_subscription(self, subscription_id, expected_version, fields):
        return _sub(self._update('billing.subscriptions', 'id', subscription_id, expected_version, fields))

    # billing: payments
    def get_payment(self, payment_id, lock=False):
        return _payment(self._one('SELECT * FROM billing.payments WHERE id=%s' + (' FOR UPDATE' if lock else ''), (payment_id,)))

    def list_payments(self, customer_id):
        return [_payment(r) for r in self._all('SELECT * FROM billing.payments WHERE customer_id=%s '
                                               'ORDER BY created_at DESC, id DESC', (customer_id,))]

    def insert_payment(self, row):
        self._insert('billing.payments', row)

    def update_payment(self, payment_id, expected_version, fields):
        return _payment(self._update('billing.payments', 'id', payment_id, expected_version, fields))

    def payment_by_ref(self, ref):
        return _payment(self._one('SELECT * FROM billing.payments WHERE external_payment_ref=%s', (ref,)))

    def reference_taken(self, customer_id, reference, exclude=None):
        return self._one("SELECT 1 AS taken FROM billing.payments WHERE customer_id=%s AND reference=%s AND status <> 'void' "
                         'AND id IS DISTINCT FROM %s::uuid', (customer_id, reference, exclude)) is not None

    def last_payments(self):
        rows = self._all("SELECT DISTINCT ON (customer_id) * FROM billing.payments WHERE status='paid' "
                         'ORDER BY customer_id, paid_at DESC')
        return {str(r['customer_id']): _payment(r) for r in rows}

    # billing: provider events (webhook dedupe)
    def provider_event(self, provider, event_id):
        row = self._one('SELECT * FROM billing.provider_events WHERE provider=%s AND event_id=%s', (provider, event_id))
        return _text(dict(row), 'customer_id') if row else None

    def insert_provider_event(self, row):
        return self._one('INSERT INTO billing.provider_events (provider, event_id, event_type, event_created, customer_id, outcome) '
                         'VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (provider, event_id) DO NOTHING RETURNING event_id',
                         (row['provider'], row['event_id'], row['event_type'], row['event_created'], row['customer_id'],
                          row['outcome'])) is not None

    def provider_watermark(self, customer_id, provider):
        return self._one("SELECT coalesce(max(event_created), 0) AS mark FROM billing.provider_events "
                         "WHERE customer_id=%s AND provider=%s AND outcome='ignored_untracked_deletion'",
                         (customer_id, provider))['mark']

    def max_provider_event_created(self, customer_id, provider):
        row = self._one('SELECT coalesce(max(event_created), 0) AS mark FROM billing.provider_events '
                        'WHERE customer_id=%s AND provider=%s', (customer_id, provider))
        return int(row['mark']) if row else 0

    def get_user(self, user_id):
        row = self._one('SELECT * FROM identity.users WHERE id=%s', (user_id,))
        return _text(dict(row), 'id') if row else None

    def get_user_by_idp(self, issuer, subject):
        row = self._one('SELECT * FROM identity.users WHERE idp_issuer=%s AND idp_subject=%s', (issuer, subject))
        return _text(dict(row), 'id') if row else None

    def insert_user(self, row):
        self._insert('identity.users', row)
        return row

    def get_customer_membership(self, customer_id, user_id):
        row = self._one('SELECT * FROM identity.customer_memberships WHERE customer_id=%s AND user_id=%s',
                        (customer_id, user_id))
        return _text(dict(row), 'customer_id', 'user_id') if row else None

    def list_customer_memberships(self, customer_id):
        return [_text(dict(r), 'customer_id', 'user_id') for r in self._all(
            'SELECT * FROM identity.customer_memberships WHERE customer_id=%s ORDER BY user_id', (customer_id,))]

    def upsert_customer_membership(self, customer_id, user_id, fields):
        existing = self._one('SELECT * FROM identity.customer_memberships WHERE customer_id=%s AND user_id=%s FOR UPDATE',
                               (customer_id, user_id))
        if existing:
            row = self._one('UPDATE identity.customer_memberships SET role=%s, status=%s, updated_at=%s, updated_by=%s, '
                            'version=version+1 WHERE customer_id=%s AND user_id=%s AND version=%s RETURNING *',
                            (fields['role'], fields.get('status', existing['status']), fields['updated_at'],
                             fields['updated_by'], customer_id, user_id, existing['version']))
            return dict(row) if row else None
        row = {'customer_id': customer_id, 'user_id': user_id, 'role': fields['role'], 'status': fields.get('status', 'active'),
               'created_at': fields['updated_at'], 'created_by': fields['updated_by'], 'updated_at': fields['updated_at'],
               'updated_by': fields['updated_by'], 'version': 1}
        self._insert('identity.customer_memberships', row)
        return row

    def get_workspace_membership(self, tenant_id, user_id):
        row = self._one('SELECT * FROM identity.workspace_memberships WHERE tenant_id=%s AND user_id=%s',
                        (tenant_id, user_id))
        return _text(dict(row), 'tenant_id', 'user_id') if row else None

    def list_workspace_memberships(self, tenant_id):
        return [_text(dict(r), 'tenant_id', 'user_id') for r in self._all(
            'SELECT * FROM identity.workspace_memberships WHERE tenant_id=%s ORDER BY user_id', (tenant_id,))]

    def upsert_workspace_membership(self, tenant_id, user_id, fields):
        existing = self._one('SELECT * FROM identity.workspace_memberships WHERE tenant_id=%s AND user_id=%s FOR UPDATE',
                               (tenant_id, user_id))
        if existing:
            row = self._one('UPDATE identity.workspace_memberships SET roles=%s, updated_at=%s, updated_by=%s, '
                            'version=version+1 WHERE tenant_id=%s AND user_id=%s AND version=%s RETURNING *',
                            (fields['roles'], fields['updated_at'], fields['updated_by'], tenant_id, user_id,
                             existing['version']))
            return dict(row) if row else None
        row = {'tenant_id': tenant_id, 'user_id': user_id, 'roles': fields['roles'], 'created_at': fields['updated_at'],
               'created_by': fields['updated_by'], 'updated_at': fields['updated_at'], 'updated_by': fields['updated_by'],
               'version': 1}
        self._insert('identity.workspace_memberships', row)
        return row

    def list_service_accounts(self, customer_id):
        return [_text(dict(r), 'id', 'customer_id') for r in self._all(
            'SELECT * FROM identity.service_accounts WHERE customer_id=%s ORDER BY name', (customer_id,))]

    def get_service_account(self, account_id):
        row = self._one('SELECT * FROM identity.service_accounts WHERE id=%s', (account_id,))
        return _text(dict(row), 'id', 'customer_id') if row else None

    def insert_service_account(self, row):
        self._insert('identity.service_accounts', row)

    def update_service_account(self, account_id, expected_version, fields):
        row = self._update('identity.service_accounts', 'id', account_id, expected_version, fields)
        return _text(dict(row), 'id', 'customer_id') if row else None

    def delete_workspace_membership(self, tenant_id, user_id):
        self.db.execute('DELETE FROM identity.workspace_memberships WHERE tenant_id=%s AND user_id=%s',
                        (tenant_id, user_id))

    def list_rule_catalog(self):
        return [dict(r) for r in self._all('SELECT * FROM analysis.rule_catalog ORDER BY id')]

    def list_workspace_rules(self, tenant_id):
        return [dict(r) for r in self._all('SELECT * FROM analysis.workspace_rules WHERE tenant_id=%s', (tenant_id,))]

    def upsert_workspace_rule(self, tenant_id, rule_id, fields):
        existing = self._one('SELECT * FROM analysis.workspace_rules WHERE tenant_id=%s AND rule_id=%s FOR UPDATE',
                             (tenant_id, rule_id))
        if existing:
            assignments = [f'"{name}"=%s' for name in fields] + ['version=version+1']
            values = [_json(name, v) for name, v in fields.items()] + [tenant_id, rule_id, existing['version']]
            row = self._one(f'UPDATE analysis.workspace_rules SET {", ".join(assignments)} '
                            'WHERE tenant_id=%s AND rule_id=%s AND version=%s RETURNING *', values)
            return dict(row) if row else None
        row = {'tenant_id': tenant_id, 'rule_id': rule_id, 'enabled': fields['enabled'],
               'parameters': fields.get('parameters', {}),
               'unavailable_reason': fields.get('unavailable_reason'), 'version': 1,
               'created_at': fields['updated_at'], 'created_by': fields['updated_by'],
               'updated_at': fields['updated_at'], 'updated_by': fields['updated_by']}
        self._insert('analysis.workspace_rules', row)
        return row





    # cache events (long poll)
    def insert_access_check(self, row):
        from psycopg.types.json import Jsonb
        self._insert('directory.access_checks', {**row, 'result': Jsonb(row['result']) if row.get('result') else None})

    def get_access_check(self, check_id, lock=False):
        row = self._one('SELECT * FROM directory.access_checks WHERE check_id=%s' + (' FOR UPDATE' if lock else ''),
                        (check_id,))
        return dict(row) if row else None

    def update_access_check(self, check_id, fields):
        from psycopg.types.json import Jsonb
        if 'result' in fields and fields['result'] is not None:
            fields = dict(fields, result=Jsonb(fields['result']))
        row = self._one('UPDATE directory.access_checks SET ' + ', '.join(f'{k}=%s' for k in fields) +
                        ' WHERE check_id=%s RETURNING *', [*fields.values(), check_id])
        return dict(row) if row else None

    def count_recent_access_checks(self, tenant_id, since):
        row = self._one('SELECT count(*) AS count FROM directory.access_checks WHERE '
                        '(tenant_id IS NOT DISTINCT FROM %s) AND requested_at >= %s', (tenant_id, since))
        return int(row['count'])

    def insert_plan_change_request(self, row):
        self._insert('billing.plan_change_requests', row)

    def get_plan_change_request(self, request_id, lock=False):
        row = self._one('SELECT * FROM billing.plan_change_requests WHERE id=%s' + (' FOR UPDATE' if lock else ''),
                        (request_id,))
        return _text(dict(row), 'id', 'customer_id', 'tenant_id') if row else None

    def pending_plan_request_for_tenant(self, tenant_id):
        row = self._one("SELECT * FROM billing.plan_change_requests WHERE tenant_id=%s AND status IN "
                        "('pending_approval', 'pending_payment') ORDER BY created_at DESC LIMIT 1", (tenant_id,))
        return _text(dict(row), 'id', 'customer_id', 'tenant_id') if row else None

    def list_plan_change_requests(self, status=None, limit=50):
        if status:
            rows = self._all('SELECT * FROM billing.plan_change_requests WHERE status=%s ORDER BY created_at DESC LIMIT %s',
                             (status, limit))
        else:
            rows = self._all('SELECT * FROM billing.plan_change_requests ORDER BY created_at DESC LIMIT %s', (limit,))
        return [_text(dict(r), 'id', 'customer_id', 'tenant_id') for r in rows]

    def update_plan_change_request(self, request_id, expected_version, fields):
        row = self._update('billing.plan_change_requests', 'id', request_id, expected_version, fields)
        return self.get_plan_change_request(request_id) if row else None

    def append_cache_event(self, tenant_id, key_id, event, directory, payload=None):
        from psycopg.types.json import Jsonb
        return self._one('INSERT INTO identity.cache_events (tenant_id, key_id, event, directory, payload) '
                         'VALUES (%s, %s, %s, %s, %s) RETURNING seq',
                         (tenant_id, key_id, event, directory, Jsonb(payload or {})))['seq']

    def cache_events_after(self, after, limit):
        rows = self._all('SELECT seq, tenant_id, key_id, event, directory, payload, created_at FROM identity.cache_events '
                         'WHERE seq > %s ORDER BY seq LIMIT %s', (after, limit))
        return [_text(dict(r), 'tenant_id') for r in rows]

    def cache_head(self):
        row = self._one('SELECT max(seq) AS seq FROM identity.cache_events')
        if row['seq'] is not None:
            return row['seq']
        sequence = self._one('SELECT last_value, is_called FROM identity.cache_events_seq_seq')
        return sequence['last_value'] if sequence['is_called'] else 0

    def cache_oldest(self, since):
        return self._one('SELECT min(seq) AS seq FROM identity.cache_events WHERE created_at >= %s', (since,))['seq']


class PostgresStore:
    def __init__(self, url):
        self.url = url
        with self._connect() as db:
            role = db.execute('SELECT rolsuper, rolbypassrls, rolcreaterole, rolcreatedb FROM pg_roles WHERE rolname=current_user').fetchone()
            if any(role.values()):
                raise ValueError('identity-service must connect with an unprivileged role')
            forced = db.execute("SELECT relforcerowsecurity FROM pg_class WHERE oid = to_regclass('billing.subscriptions')").fetchone()
            if not forced or not forced['relforcerowsecurity']:
                raise ValueError('Apply platform-db migrations (i0002_billing, forced RLS) before starting identity-service')

    @contextmanager
    def _connect(self):
        from psycopg.rows import dict_row
        from identity.db import connect
        with connect(self.url, row_factory=dict_row) as db:
            yield db

    @contextmanager
    def transaction(self):
        with self._connect() as db:
            db.execute("SET LOCAL statement_timeout='5s'")
            yield PostgresTx(db)
