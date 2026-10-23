"""Directory and key lifecycle rules. Stores only persist; every decision is made here."""
import hmac
import ipaddress
import logging
import os
from datetime import timedelta
from uuid import uuid4

from identity import keys as keyfmt
from identity.domain import (DEFAULT_EXPIRY_DAYS, EXPIRING_SOON_DAYS, MAX_ACTIVE_KEYS, MAX_EXPIRY_DAYS, PROVIDERS,
                             SCOPE_KEYS, STATUSES, TIERS, Conflict, IdentityError, NotFound, StaleVersion, Throttled,
                             configured_providers, empty_scopes, iso, normalize_identity_bindings, normalize_roles,
                             normalize_scope_items, parse_time, text, utcnow, uuid_text)

logger = logging.getLogger('cloudsaver.identity')
SYSTEM = {'actor': 'system', 'actor_type': 'system'}


def flag(name, default='false'):
    return os.getenv(name, default).lower() == 'true'


def client_ip(value):
    try:
        return str(ipaddress.ip_address(str(value)))
    except ValueError:
        raise IdentityError('client_ip must be an IP address.') from None


def key_status(row, now):
    if row['revoked_at']:
        return 'revoked'
    if (row['expires_at'] and row['expires_at'] <= now) or (row['rotates_out_at'] and row['rotates_out_at'] <= now):
        return 'expired'
    if row['rotates_out_at']:
        return 'rotating_out'
    if row['expires_at'] and row['expires_at'] - now <= timedelta(days=EXPIRING_SOON_DAYS):
        return 'expiring_soon'
    return 'active'


def snapshot(workspace, customer):
    """Complete directory state for one workspace; applying it twice is harmless."""
    return {
        'tenant_id': workspace['tenant_id'], 'customer_id': workspace['customer_id'], 'name': workspace['name'],
        'plan_tier': workspace['plan_tier'], 'status': workspace['status'],
        'active': workspace['status'] == 'active' and customer['status'] == 'active',
        'identity': workspace['identity'], 'version': workspace['version'],
        **{key: workspace[key] for key in SCOPE_KEYS.values()},
    }


class IdentityService:
    def __init__(self, store, peppers, throttle, events, usage, *, environment=None, clock=utcnow,
                 cache_seconds=None, provider_scoped_keys=None):
        self.store, self.peppers, self.throttle, self.events, self.usage = store, peppers, throttle, events, usage
        self.environment = environment or os.getenv('CLOUDSAVER_ENVIRONMENT', 'development')
        self.now = clock
        self.cache_seconds = int(cache_seconds if cache_seconds is not None else os.getenv('CLOUDSAVER_IDENTITY_CACHE_SECONDS', '15'))
        if not 0 <= self.cache_seconds <= 30:
            raise ValueError('CLOUDSAVER_IDENTITY_CACHE_SECONDS must be between 0 and 30')
        self.provider_scoped_keys = flag('CLOUDSAVER_PROVIDER_SCOPED_KEYS') if provider_scoped_keys is None else provider_scoped_keys
        self.metrics = {}

    def _count(self, *labels):
        self.metrics[labels] = self.metrics.get(labels, 0) + 1

    # ----- verification ---------------------------------------------------------------------------------
    def verify(self, presented, ip, caller, request_id=None):
        ip = client_ip(ip)
        retry = self.throttle.blocked(ip)
        if retry:
            return self._throttled(ip, caller, retry)
        kind, key_id = keyfmt.parse(presented)
        if kind == 'malformed':
            self.peppers.dummy_compare(presented if isinstance(presented, str) else '')
            return self._reject(ip, caller, 'malformed')
        if kind == 'v1':
            retry = self.throttle.blocked(ip, key_id)
            if retry:
                return self._throttled(ip, caller, retry, key_id)
        with self.store.transaction() as tx:
            row = self._match(tx, presented, kind, key_id)
            if row is None or row == 'mismatch':
                reason = 'secret_mismatch' if row == 'mismatch' else 'unknown'
                return self._reject(ip, caller, reason, key_id=key_id if row == 'mismatch' else None, mismatch=row == 'mismatch')
            now = self.now()
            workspace = tx.get_workspace(row['tenant_id'])
            customer = tx.get_customer(workspace['customer_id']) if workspace else None
            status = key_status(row, now)
            reason = None
            if status == 'revoked' or not workspace or workspace['status'] == 'deleted':
                reason = 'revoked'
            elif status == 'expired':
                reason = 'rotated_out' if row['rotates_out_at'] and row['rotates_out_at'] <= now else 'expired'
            elif workspace['status'] != 'active' or not customer or customer['status'] != 'active':
                reason = 'workspace_suspended'
            if reason:
                return self._reject(ip, caller, reason, key_id=row['key_id'], tenant_id=row['tenant_id'])
            self._upgrade(tx, row, presented, request_id)
        self.usage.success(row['key_id'], ip)
        self._count('verify', 'valid', caller)
        return self._grant(row, workspace, now)

    def _match(self, tx, presented, kind, key_id):
        if kind == 'v1':
            row = tx.key_by_key_id(key_id)
            if row is None or row['hash_scheme'] != 'hmac_sha256':
                self.peppers.dummy_compare(presented)
                return None
            digest = self.peppers.digest(presented, row['pepper_version'])
            if digest is None or not hmac.compare_digest(digest, bytes(row['secret_digest'])):
                return 'mismatch'
            return row
        legacy = keyfmt.sha256_hex(presented)
        row = tx.key_by_legacy(legacy)
        if row is not None:
            return row if hmac.compare_digest(row['legacy_sha256'], legacy) else None
        for version in self.peppers.versions():
            digest = self.peppers.digest(presented, version)
            row = tx.key_by_digest(digest)
            if row is not None and row['format'] == 'legacy' and hmac.compare_digest(bytes(row['secret_digest']), digest):
                return row
        return None

    def _upgrade(self, tx, row, presented, request_id):
        legacy = row['hash_scheme'] == 'sha256_legacy'
        if not legacy and row['pepper_version'] == self.peppers.current_version:
            return
        tx.update_key(row['key_id'], {'hash_scheme': 'hmac_sha256', 'secret_digest': self.peppers.digest(presented),
                                      'pepper_version': self.peppers.current_version, 'legacy_sha256': None})
        if legacy:
            self._event(tx, SYSTEM, 'hash_upgraded', row['tenant_id'], row['key_id'], {'name': row['name']}, request_id)

    def _grant(self, row, workspace, now):
        configured = configured_providers(workspace)
        allowed = configured if row['all_providers'] else [p for p in configured if p in row['allowed_providers']]
        ttl = self.cache_seconds
        for limit in (row['expires_at'], row['rotates_out_at']):
            if limit:
                ttl = min(ttl, max(0, int((limit - now).total_seconds())))
        return {'valid': True, 'tenant_id': row['tenant_id'], 'customer_id': workspace['customer_id'],
                'key_id': row['key_id'], 'key_name': row['name'], 'roles': list(row['roles']),
                'all_providers': row['all_providers'], 'allowed_providers': allowed, 'scope_restrictions': None,
                'workspace_status': workspace['status'], 'directory_version': workspace['version'],
                'expires_at': iso(row['expires_at']), 'rotates_out_at': iso(row['rotates_out_at']),
                'cache_ttl_seconds': ttl}

    def _reject(self, ip, caller, reason, *, key_id=None, tenant_id=None, mismatch=False):
        self.throttle.failure(ip, key_id, mismatch)
        self.usage.failure(ip, reason, caller, key_id=key_id, tenant_id=tenant_id)
        self._count('verify', reason, caller)
        logger.info('Workspace key rejected reason=%s key_id=%s caller=%s', reason, key_id or '-', caller)
        return {'valid': False, 'reason': reason}

    def _throttled(self, ip, caller, retry, key_id=None):
        self.usage.failure(ip, 'throttled', caller, key_id=key_id)
        self._count('verify', 'throttled', caller)
        raise Throttled(retry)

    # ----- helpers --------------------------------------------------------------------------------------
    def _event(self, tx, actor, action, tenant_id=None, key_id=None, details=None, request_id=None):
        tx.append_event({'id': str(uuid4()), 'occurred_at': self.now(), 'actor': actor['actor'][:120],
                         'actor_type': actor['actor_type'], 'action': action, 'tenant_id': tenant_id,
                         'key_id': key_id, 'details': details or {}, 'request_id': request_id})

    def _publish(self, messages):
        for message in messages:
            self.events.publish(message)

    def _changed(self, tx, workspace, customer=None, change_type='workspace_upserted'):
        customer = customer or tx.get_customer(workspace['customer_id'])
        return tx.append_change(workspace['tenant_id'], change_type, workspace['version'], snapshot(workspace, customer))

    @staticmethod
    def _version(payload):
        version = payload.get('version') if isinstance(payload, dict) else None
        if not isinstance(version, int) or isinstance(version, bool) or version < 0:
            raise IdentityError('Include the version you loaded.')
        return version

    # ----- customers ------------------------------------------------------------------------------------
    def customer_view(self, row, counts):
        total, active = counts.get(row['id'], (0, 0))
        return {**{k: row[k] for k in ('id', 'name', 'status', 'notes', 'version', 'created_by', 'updated_by')},
                'created_at': iso(row['created_at']), 'updated_at': iso(row['updated_at']),
                'deleted_at': iso(row['deleted_at']), 'workspace_count': total, 'active_workspace_count': active}

    def list_customers(self, q=None, status=None, cursor=None, limit=50):
        offset, limit = self._page(cursor, limit)
        if status and status not in STATUSES:
            raise IdentityError('Choose a valid status.')
        with self.store.transaction() as tx:
            rows = tx.list_customers(q, status, offset, limit + 1)
            counts = tx.customer_workspace_counts()
        return {'items': [self.customer_view(r, counts) for r in rows[:limit]],
                'next_cursor': str(offset + limit) if len(rows) > limit else None}

    def get_customer(self, customer_id):
        customer_id = uuid_text(customer_id)
        with self.store.transaction() as tx:
            row = tx.get_customer(customer_id)
            if not row:
                raise NotFound('Customer not found.')
            workspaces = tx.list_workspaces(None, None, customer_id, 0, 500)
            stats, counts = tx.key_stats(self.now()), tx.customer_workspace_counts()
        return {'customer': self.customer_view(row, counts),
                'workspaces': [self.workspace_view(w, row, stats) for w in workspaces]}

    def create_customer(self, payload, actor, request_id=None):
        now = self.now()
        row = {'id': str(uuid4()), 'name': text(payload.get('name'), 'Customer name', 120), 'status': 'active',
               'notes': text(payload.get('notes') or None, 'Notes', 500, required=False), 'version': 1,
               'created_at': now, 'created_by': actor['actor'][:120], 'updated_at': now,
               'updated_by': actor['actor'][:120], 'deleted_at': None}
        with self.store.transaction() as tx:
            tx.insert_customer(row)
            self._event(tx, actor, 'customer_created', details={'customer_id': row['id'], 'name': row['name']}, request_id=request_id)
            counts = tx.customer_workspace_counts()
        return self.customer_view(row, counts)

    def update_customer(self, customer_id, payload, actor, request_id=None):
        customer_id, version = uuid_text(customer_id), self._version(payload)
        fields = {}
        if 'name' in payload and payload['name'] is not None:
            fields['name'] = text(payload['name'], 'Customer name', 120)
        if 'notes' in payload:
            fields['notes'] = text(payload['notes'] or None, 'Notes', 500, required=False)
        return self._customer_write(customer_id, version, fields, actor, 'customer_updated', request_id)

    def set_customer_status(self, customer_id, payload, status, actor, request_id=None):
        customer_id, version = uuid_text(customer_id), self._version(payload)
        action = {'suspended': 'customer_updated', 'active': 'customer_updated', 'deleted': 'customer_updated'}[status]
        return self._customer_write(customer_id, version, {'status': status}, actor, action, request_id)

    def _customer_write(self, customer_id, version, fields, actor, action, request_id):
        messages = []
        with self.store.transaction() as tx:
            current = tx.get_customer(customer_id, lock=True)
            if not current or current['status'] == 'deleted':
                raise NotFound('Customer not found.')
            if current['version'] != version:
                raise StaleVersion()
            workspaces = tx.list_workspaces(None, None, customer_id, 0, 10000)
            if fields.get('status') == 'deleted':
                if any(w['status'] != 'deleted' for w in workspaces):
                    raise Conflict('Delete or move this customer\'s workspaces first.')
                fields['deleted_at'] = self.now()
            row = tx.update_customer(customer_id, version, dict(fields, updated_at=self.now(), updated_by=actor['actor'][:120]))
            if row is None:
                raise StaleVersion()
            if 'status' in fields and fields['status'] != current['status']:
                for workspace in workspaces:
                    if workspace['status'] != 'deleted':
                        self._changed(tx, workspace, row)
                        messages.append({'tenant_id': workspace['tenant_id'], 'event': 'customer_' + fields['status']})
            self._event(tx, actor, action, details={'customer_id': customer_id, 'changes': sorted(k for k in fields if k != 'deleted_at')},
                        request_id=request_id)
            counts = tx.customer_workspace_counts()
        self._publish(messages)
        return self.customer_view(row, counts)

    # ----- workspaces -----------------------------------------------------------------------------------
    def workspace_view(self, row, customer, stats):
        stat = stats.get(row['tenant_id'], {})
        return {**{k: row[k] for k in ('tenant_id', 'customer_id', 'name', 'plan_tier', 'status', 'identity', 'version',
                                       'created_by', 'updated_by')},
                **{key: row[key] for key in SCOPE_KEYS.values()},
                'customer_name': customer['name'] if customer else '', 'providers': configured_providers(row),
                'created_at': iso(row['created_at']), 'updated_at': iso(row['updated_at']),
                'suspended_at': iso(row['suspended_at']), 'deleted_at': iso(row['deleted_at']),
                'active_keys': stat.get('active', 0), 'last_used_at': iso(stat.get('last_used_at')),
                'next_expiry': iso(stat.get('next_expiry'))}

    def list_workspaces(self, q=None, status=None, customer_id=None, cursor=None, limit=50):
        offset, limit = self._page(cursor, limit)
        if status and status not in STATUSES:
            raise IdentityError('Choose a valid status.')
        customer_id = uuid_text(customer_id) if customer_id else None
        with self.store.transaction() as tx:
            rows = tx.list_workspaces(q, status, customer_id, offset, limit + 1)
            stats = tx.key_stats(self.now())
            customers = {c: tx.get_customer(c) for c in {r['customer_id'] for r in rows}}
        return {'items': [self.workspace_view(r, customers[r['customer_id']], stats) for r in rows[:limit]],
                'next_cursor': str(offset + limit) if len(rows) > limit else None}

    def get_workspace(self, tenant_id):
        tenant_id = uuid_text(tenant_id, 'Enter a valid workspace ID.')
        with self.store.transaction() as tx:
            row = tx.get_workspace(tenant_id)
            if not row:
                raise NotFound('Workspace not found.')
            return self.workspace_view(row, tx.get_customer(row['customer_id']), tx.key_stats(self.now()))

    def create_workspace(self, payload, actor, request_id=None, *, scopes=None, status='active', source_action='workspace_created'):
        tenant_id = uuid_text(payload.get('tenant_id'), 'Enter a valid workspace ID.')
        customer_id = uuid_text(payload.get('customer_id'), 'Choose a customer.')
        tier = payload.get('plan_tier', 'STARTER')
        if tier not in TIERS:
            raise IdentityError('Choose a valid plan.')
        now = self.now()
        row = {'tenant_id': tenant_id, 'customer_id': customer_id, 'name': text(payload.get('name'), 'Workspace name', 120),
               'plan_tier': tier, 'status': status, 'identity': normalize_identity_bindings(payload.get('identity')),
               'version': 1, 'created_at': now, 'created_by': actor['actor'][:120], 'updated_at': now,
               'updated_by': actor['actor'][:120], 'suspended_at': now if status == 'suspended' else None,
               'deleted_at': None, **empty_scopes()}
        for provider, key in SCOPE_KEYS.items():
            row[key] = normalize_scope_items(provider, (scopes or {}).get(key, []), tier)
        with self.store.transaction() as tx:
            customer = tx.get_customer(customer_id, lock=True)
            if not customer or customer['status'] == 'deleted':
                raise IdentityError('Choose an existing customer.')
            if tx.get_workspace(tenant_id):
                raise Conflict('A workspace with this ID already exists.')
            tx.insert_workspace(row)
            self._changed(tx, row, customer)
            self._event(tx, actor, source_action, tenant_id, details={'name': row['name'], 'customer_id': customer_id},
                        request_id=request_id)
            stats = tx.key_stats(now)
        return self.workspace_view(row, customer, stats)

    def update_workspace(self, tenant_id, payload, actor, request_id=None):
        tenant_id, version = uuid_text(tenant_id), self._version(payload)
        fields = {}
        if payload.get('name') is not None:
            fields['name'] = text(payload['name'], 'Workspace name', 120)
        if payload.get('plan_tier') is not None:
            if payload['plan_tier'] not in TIERS:
                raise IdentityError('Choose a valid plan.')
            fields['plan_tier'] = payload['plan_tier']
        if payload.get('customer_id') is not None:
            fields['customer_id'] = uuid_text(payload['customer_id'], 'Choose a customer.')
        if 'identity' in payload and payload['identity'] is not None:
            fields['identity'] = normalize_identity_bindings(payload['identity'])
        return self._workspace_write(tenant_id, version, fields, actor, 'workspace_updated', request_id)

    def replace_scopes(self, tenant_id, provider, payload, actor, request_id=None):
        tenant_id, version = uuid_text(tenant_id), self._version(payload)
        if provider not in PROVIDERS:
            raise NotFound('Unknown cloud provider.')
        return self._workspace_write(tenant_id, version, {}, actor, 'scopes_changed', request_id,
                                     scopes=(provider, payload.get('items')))

    def set_workspace_status(self, tenant_id, payload, status, actor, request_id=None):
        tenant_id, version = uuid_text(tenant_id), self._version(payload)
        now = self.now()
        fields = {'status': status}
        if status == 'suspended':
            fields['suspended_at'] = now
        elif status == 'active':
            fields['suspended_at'] = None
        else:
            fields['deleted_at'] = now
        action = {'suspended': 'workspace_suspended', 'active': 'workspace_reactivated', 'deleted': 'workspace_deleted'}[status]
        return self._workspace_write(tenant_id, version, fields, actor, action, request_id)

    def _workspace_write(self, tenant_id, version, fields, actor, action, request_id, *, scopes=None):
        messages, now = [], self.now()
        with self.store.transaction() as tx:
            current = tx.get_workspace(tenant_id, lock=True)
            if not current or current['status'] == 'deleted':
                raise NotFound('Workspace not found.')
            if current['version'] != version:
                raise StaleVersion()
            if 'customer_id' in fields:
                target = tx.get_customer(fields['customer_id'])
                if not target or target['status'] == 'deleted':
                    raise IdentityError('Choose an existing customer.')
            tier = fields.get('plan_tier', current['plan_tier'])
            if 'plan_tier' in fields:
                normalize_scope_items('azure', current['subscription_ids'], tier)
            if scopes:
                items = normalize_scope_items(scopes[0], scopes[1], tier)
                tx.replace_scopes(tenant_id, scopes[0], items, actor['actor'][:120], now)
            row = tx.update_workspace(tenant_id, version, dict(fields, updated_at=now, updated_by=actor['actor'][:120]))
            if row is None:
                raise StaleVersion()
            if scopes:
                messages += self._providers_changed(tx, current, row, actor, request_id)
            if fields.get('status') == 'deleted':
                count = self._revoke_all(tx, tenant_id, 'Workspace deleted', actor, request_id)
                messages.append({'tenant_id': tenant_id, 'event': 'workspace_deleted', 'revoked': count})
            elif 'status' in fields:
                messages.append({'tenant_id': tenant_id, 'event': action})
            self._changed(tx, row, None, 'workspace_deleted' if fields.get('status') == 'deleted' else 'workspace_upserted')
            details = {'name': row['name'], 'changes': sorted(k for k in fields if not k.endswith('_at'))}
            if scopes:
                details['provider'] = scopes[0]
            self._event(tx, actor, action, tenant_id, details=details, request_id=request_id)
            view = self.workspace_view(row, tx.get_customer(row['customer_id']), tx.key_stats(now))
        self._publish(messages + [{'directory': True, 'event': 'directory_changed'}])
        return view

    def _providers_changed(self, tx, before, after, actor, request_id):
        lost = set(configured_providers(before)) - set(configured_providers(after))
        gained = set(configured_providers(after)) - set(configured_providers(before))
        if not lost and not gained:
            return []
        for key in tx.list_keys(after['tenant_id']):
            if key['revoked_at']:
                continue
            if key['all_providers'] or lost & set(key['allowed_providers']):
                self._event(tx, actor, 'providers_changed', after['tenant_id'], key['key_id'],
                            {'name': key['name'], 'lost': sorted(lost), 'gained': sorted(gained) if key['all_providers'] else []},
                            request_id)
        return [{'tenant_id': after['tenant_id'], 'event': 'providers_changed'}]

    # ----- platform -------------------------------------------------------------------------------------
    @staticmethod
    def platform_view(row):
        return {**{k: row[k] for k in ('scheduled_scans_enabled', 'automated_alerts_enabled', 'version', 'updated_by')},
                'updated_at': iso(row['updated_at'])}

    def get_platform(self):
        with self.store.transaction() as tx:
            return self.platform_view(tx.get_platform())

    def update_platform(self, payload, actor, request_id=None):
        version = self._version(payload)
        fields = {}
        for name in ('scheduled_scans_enabled', 'automated_alerts_enabled'):
            if name in payload:
                if not isinstance(payload[name], bool):
                    raise IdentityError('Platform switches must be on or off.')
                fields[name] = payload[name]
        with self.store.transaction() as tx:
            row = tx.update_platform(version, dict(fields, updated_at=self.now(), updated_by=actor['actor'][:120]))
            if row is None:
                raise StaleVersion()
            tx.append_change(None, 'platform_updated', row['version'], {k: row[k] for k in ('scheduled_scans_enabled', 'automated_alerts_enabled', 'version')})
            self._event(tx, actor, 'platform_updated', details={'changes': sorted(fields)}, request_id=request_id)
        self._publish([{'directory': True, 'event': 'directory_changed'}])
        return self.platform_view(row)

    # ----- keys -----------------------------------------------------------------------------------------
    def key_view(self, row, workspace=None, rotated_from=None):
        now = self.now()
        effective = []
        if workspace:
            configured = configured_providers(workspace)
            effective = configured if row['all_providers'] else [p for p in configured if p in row['allowed_providers']]
        return {**{k: row[k] for k in ('key_id', 'tenant_id', 'name', 'all_providers', 'format', 'source', 'revoked_by',
                                       'revoke_reason', 'version')},
                'roles': list(row['roles']), 'allowed_providers': list(row['allowed_providers']),
                'effective_providers': effective, 'scope_restrictions': None, 'status': key_status(row, now),
                'created_at': iso(row['created_at']), 'created_by': row['created_by'],
                'expires_at': iso(row['expires_at']), 'revoked_at': iso(row['revoked_at']),
                'rotated_from': rotated_from, 'rotates_out_at': iso(row['rotates_out_at']),
                'last_used_at': iso(row['last_used_at']),
                'last_used_ip': str(row['last_used_ip']) if row['last_used_ip'] else None}

    def _key_views(self, tx, rows):
        workspaces, by_id = {}, {}
        for row in rows:
            if row['tenant_id'] not in workspaces:
                workspaces[row['tenant_id']] = tx.get_workspace(row['tenant_id'])
        for row in tx.list_keys(rows[0]['tenant_id']) if rows else []:
            by_id[row['id']] = row['key_id']
        return [self.key_view(r, workspaces[r['tenant_id']], by_id.get(r['rotated_from'])) for r in rows]

    def list_keys(self, tenant_id):
        tenant_id = uuid_text(tenant_id)
        with self.store.transaction() as tx:
            if not tx.get_workspace(tenant_id):
                raise NotFound('Workspace not found.')
            return {'items': self._key_views(tx, tx.list_keys(tenant_id))}

    def get_key(self, key_id):
        with self.store.transaction() as tx:
            row = self._key_row(tx, key_id)
            return self._key_views(tx, [row])[0]

    @staticmethod
    def _key_row(tx, key_id, lock=False):
        row = tx.key_by_key_id(key_id, lock=lock) if isinstance(key_id, str) and len(key_id) == 12 else None
        if row is None:
            raise NotFound('Key not found.')
        return row

    def _grant_fields(self, payload, workspace, defaults=None):
        defaults = defaults or {}
        roles = normalize_roles(payload['roles']) if payload.get('roles') is not None else defaults.get('roles')
        if roles is None:
            raise IdentityError('Select at least one role.')
        all_providers = payload.get('all_providers', defaults.get('all_providers'))
        if not isinstance(all_providers, bool):
            raise IdentityError('Choose whether the key includes providers added later.')
        allowed = payload.get('allowed_providers', defaults.get('allowed_providers', []))
        if payload.get('scope_restrictions') not in (None, {}):
            raise IdentityError('Scope-level key limits aren\'t available yet.')
        configured = configured_providers(workspace)
        if all_providers:
            allowed = []
        else:
            if not self.provider_scoped_keys:
                raise IdentityError('Provider-scoped keys aren\'t enabled yet. Include all providers.')
            if not isinstance(allowed, list) or not allowed or any(p not in configured for p in allowed):
                raise IdentityError('Select at least one provider configured for this workspace.')
            allowed = [p for p in PROVIDERS if p in allowed]
        return {'roles': roles, 'all_providers': all_providers, 'allowed_providers': allowed}

    def _expiry(self, value, *, default=None):
        now = self.now()
        if value is None:
            if default is None:
                raise IdentityError('Choose an expiry date.')
            return default
        expires = parse_time(value, 'Expiry date')
        if expires <= now:
            raise IdentityError('Choose an expiry date in the future.')
        if expires > now + timedelta(days=MAX_EXPIRY_DAYS, hours=1):
            raise IdentityError(f'Keys can expire at most {MAX_EXPIRY_DAYS} days from today.')
        return expires

    def _new_key_row(self, workspace, name, grant, expires, actor, rotated_from=None):
        key_id, secret = keyfmt.new_key(self.environment)
        return {'id': str(uuid4()), 'key_id': key_id, 'tenant_id': workspace['tenant_id'], 'name': name, **grant,
                'scope_restrictions': None, 'format': 'v1', 'hash_scheme': 'hmac_sha256',
                'secret_digest': self.peppers.digest(secret), 'pepper_version': self.peppers.current_version,
                'legacy_sha256': None, 'legacy_fingerprint': None, 'created_at': self.now(),
                'created_by': actor['actor'][:120], 'expires_at': expires, 'revoked_at': None, 'revoked_by': None,
                'revoke_reason': None, 'rotated_from': rotated_from, 'rotates_out_at': None, 'last_used_at': None,
                'last_used_ip': None, 'source': 'portal', 'version': 1}, secret

    def _open_keys(self, tx, tenant_id):
        now = self.now()
        return [k for k in tx.list_keys(tenant_id) if key_status(k, now) not in ('revoked', 'expired')]

    def issue_key(self, tenant_id, payload, actor, request_id=None):
        tenant_id = uuid_text(tenant_id)
        name = text(payload.get('name'), 'Key name', 80)
        with self.store.transaction() as tx:
            workspace = tx.get_workspace(tenant_id, lock=True)
            if not workspace or workspace['status'] == 'deleted':
                raise NotFound('Workspace not found.')
            grant = self._grant_fields(payload, workspace)
            expires = self._expiry(payload.get('expires_at'))
            if len(self._open_keys(tx, tenant_id)) >= MAX_ACTIVE_KEYS:
                raise Conflict(f'A workspace can have at most {MAX_ACTIVE_KEYS} active keys. Revoke a key first.')
            row, secret = self._new_key_row(workspace, name, grant, expires, actor)
            tx.insert_key(row)
            self._event(tx, actor, 'issued', tenant_id, row['key_id'],
                        {'name': name, 'roles': grant['roles'], 'all_providers': grant['all_providers'],
                         'allowed_providers': grant['allowed_providers'], 'expires_at': iso(expires)}, request_id)
            view = self.key_view(row, workspace)
        return {'key': view, 'secret': secret}

    def rotate_key(self, key_id, payload, actor, request_id=None):
        overlap = payload.get('overlap_hours', 24)
        if not isinstance(overlap, int) or isinstance(overlap, bool) or not 0 <= overlap <= 168:
            raise IdentityError('Choose an overlap between 0 and 168 hours.')
        now = self.now()
        with self.store.transaction() as tx:
            old = self._key_row(tx, key_id, lock=True)
            status = key_status(old, now)
            if status == 'rotating_out':
                raise Conflict('This key is already rotating out.')
            if status in ('revoked', 'expired'):
                raise Conflict('Only active keys can be rotated.')
            workspace = tx.get_workspace(old['tenant_id'], lock=True)
            if not workspace or workspace['status'] == 'deleted':
                raise NotFound('Workspace not found.')
            grant = self._grant_fields(payload, workspace, defaults={k: old[k] for k in ('roles', 'all_providers', 'allowed_providers')})
            duration = (old['expires_at'] - old['created_at']) if old['expires_at'] else timedelta(days=DEFAULT_EXPIRY_DAYS)
            duration = min(max(duration, timedelta(days=1)), timedelta(days=MAX_EXPIRY_DAYS))
            expires = self._expiry(payload.get('expires_at'), default=now + duration)
            row, secret = self._new_key_row(workspace, old['name'], grant, expires, actor, rotated_from=old['id'])
            tx.insert_key(row)
            previous = tx.update_key(old['key_id'], {'rotates_out_at': now + timedelta(hours=overlap)})
            self._event(tx, actor, 'rotated', old['tenant_id'], old['key_id'],
                        {'name': old['name'], 'new_key_id': row['key_id'], 'overlap_hours': overlap}, request_id)
            self._event(tx, actor, 'issued', old['tenant_id'], row['key_id'],
                        {'name': row['name'], 'rotated_from': old['key_id'], 'roles': grant['roles'],
                         'allowed_providers': grant['allowed_providers'], 'all_providers': grant['all_providers'],
                         'expires_at': iso(expires)}, request_id)
            result = {'key': self.key_view(row, workspace, old['key_id']), 'secret': secret,
                      'previous': self.key_view(previous, workspace)}
        self._publish([{'key_id': old['key_id'], 'event': 'rotated'}])
        return result

    def update_key(self, key_id, payload, actor, request_id=None):
        version = self._version(payload)
        with self.store.transaction() as tx:
            row = self._key_row(tx, key_id, lock=True)
            if row['version'] != version:
                raise StaleVersion()
            if key_status(row, self.now()) == 'revoked':
                raise Conflict('Revoked keys can\'t be changed.')
            workspace = tx.get_workspace(row['tenant_id'])
            fields, actions = {}, []
            if payload.get('name') is not None:
                fields['name'] = text(payload['name'], 'Key name', 80)
                actions.append('renamed')
            if any(payload.get(k) is not None for k in ('roles', 'all_providers', 'allowed_providers')):
                grant = self._grant_fields(payload, workspace, defaults={k: row[k] for k in ('roles', 'all_providers', 'allowed_providers')})
                if grant['roles'] != list(row['roles']):
                    actions.append('roles_changed')
                if (grant['all_providers'], grant['allowed_providers']) != (row['all_providers'], list(row['allowed_providers'])):
                    actions.append('providers_changed')
                fields.update(grant)
            if payload.get('expires_at') is not None:
                fields['expires_at'] = self._expiry(payload['expires_at'])
                actions.append('expiry_changed')
            updated = tx.update_key(row['key_id'], fields, expected_version=version)
            if updated is None:
                raise StaleVersion()
            for action in actions:
                details = {'name': updated['name']}
                if action == 'roles_changed':
                    details['roles'] = fields['roles']
                elif action == 'providers_changed':
                    details |= {'all_providers': fields['all_providers'], 'allowed_providers': fields['allowed_providers']}
                elif action == 'expiry_changed':
                    details['expires_at'] = iso(fields['expires_at'])
                self._event(tx, actor, action, row['tenant_id'], row['key_id'], details, request_id)
            view = self._key_views(tx, [updated])[0]
        if set(actions) - {'renamed'}:
            self._publish([{'key_id': row['key_id'], 'event': 'grant_changed'}])
        return view

    def revoke_key(self, key_id, payload, actor, request_id=None):
        reason = text(payload.get('reason'), 'Reason', 200)
        with self.store.transaction() as tx:
            row = self._key_row(tx, key_id, lock=True)
            if row['revoked_at']:
                raise Conflict('This key is already revoked.')
            updated = tx.update_key(row['key_id'], {'revoked_at': self.now(), 'revoked_by': actor['actor'][:120],
                                                    'revoke_reason': reason})
            self._event(tx, actor, 'revoked', row['tenant_id'], row['key_id'], {'name': row['name'], 'reason': reason}, request_id)
            view = self._key_views(tx, [updated])[0]
        self._publish([{'key_id': row['key_id'], 'event': 'revoked'}])
        return view

    def revoke_all(self, tenant_id, payload, actor, request_id=None):
        tenant_id = uuid_text(tenant_id)
        reason = text(payload.get('reason'), 'Reason', 200)
        with self.store.transaction() as tx:
            if not tx.get_workspace(tenant_id, lock=True):
                raise NotFound('Workspace not found.')
            count = self._revoke_all(tx, tenant_id, reason, actor, request_id)
        self._publish([{'tenant_id': tenant_id, 'event': 'revoked_all'}])
        return {'revoked': count}

    def _revoke_all(self, tx, tenant_id, reason, actor, request_id):
        count = 0
        for row in tx.list_keys(tenant_id):
            if not row['revoked_at']:
                tx.update_key(row['key_id'], {'revoked_at': self.now(), 'revoked_by': actor['actor'][:120], 'revoke_reason': reason})
                count += 1
        self._event(tx, actor, 'revoked_all', tenant_id, None, {'count': count, 'reason': reason}, request_id)
        return count

    # ----- usage, audit and failures --------------------------------------------------------------------
    def _range(self, start, end, days=7):
        end = parse_time(end, 'End date') if end else self.now()
        start = parse_time(start, 'Start date') if start else end - timedelta(days=days)
        if start > end or end - start > timedelta(days=92):
            raise IdentityError('Choose a range of up to 92 days.')
        return start, end

    @staticmethod
    def usage_view(row):
        return {'key_id': row['key_id'], 'hour': iso(row['hour']), 'source_ip': str(row['source_ip']),
                'success_count': row['success_count'], 'failure_count': row['failure_count'],
                'last_seen_at': iso(row['last_seen_at'])}

    def key_usage(self, key_id, start=None, end=None):
        start, end = self._range(start, end)
        with self.store.transaction() as tx:
            row = self._key_row(tx, key_id)
            return {'items': [self.usage_view(r) for r in tx.list_usage([row['key_id']], start, end)]}

    def workspace_usage(self, tenant_id, start=None, end=None):
        tenant_id = uuid_text(tenant_id)
        start, end = self._range(start, end)
        with self.store.transaction() as tx:
            ids = [k['key_id'] for k in tx.list_keys(tenant_id)]
            return {'items': [self.usage_view(r) for r in tx.list_usage(ids, start, end)] if ids else []}

    def audit(self, filters, before=None, limit=50):
        limit = max(1, min(int(limit or 50), 200))
        before = parse_time(before, 'Cursor') if before else None
        clean = {k: v for k, v in filters.items() if v}
        if clean.get('tenant_id'):
            clean['tenant_id'] = uuid_text(clean['tenant_id'])
        if clean.get('customer_id'):
            clean['customer_id'] = uuid_text(clean['customer_id'])
        with self.store.transaction() as tx:
            if clean.get('customer_id'):
                clean['tenant_ids'] = [w['tenant_id'] for w in tx.list_workspaces(None, None, clean['customer_id'], 0, 10000)]
            rows = tx.list_events(clean, before, limit + 1)
        items = [{'id': str(r['id']), 'occurred_at': iso(r['occurred_at']), 'actor': r['actor'], 'actor_type': r['actor_type'],
                  'action': r['action'], 'tenant_id': str(r['tenant_id']) if r['tenant_id'] else None,
                  'key_id': r['key_id'], 'details': r['details'] or {}} for r in rows[:limit]]
        return {'items': items, 'next_before': items[-1]['occurred_at'] if len(rows) > limit else None}

    def failures(self, filters, start=None):
        start = parse_time(start, 'Start date') if start else self.now() - timedelta(days=7)
        clean = {k: v for k, v in filters.items() if v}
        if clean.get('tenant_id'):
            clean['tenant_id'] = uuid_text(clean['tenant_id'])
        if clean.get('source_ip'):
            clean['source_ip'] = client_ip(clean['source_ip'])
        with self.store.transaction() as tx:
            rows = tx.list_failures(clean, start, 500)
        return {'items': [{'minute': iso(r['minute']), 'source_ip': str(r['source_ip']), 'key_id': r['key_id'] or None,
                           'tenant_id': str(r['tenant_id']) if r['tenant_id'] else None, 'reason': r['reason'],
                           'caller': r['caller'], 'count': r['count']} for r in rows]}

    # ----- change feed ----------------------------------------------------------------------------------
    def changes(self, after, limit=500):
        limit = max(1, min(int(limit), 500))
        with self.store.transaction() as tx:
            oldest = tx.min_change_seq()
            if after and oldest is not None and after < oldest - 1:
                raise IdentityError('The change cursor is older than the retention window. Resync from the snapshot.', 410)
            rows = tx.changes_after(after, limit)
        return {'items': [{'seq': r['seq'], 'tenant_id': r['tenant_id'], 'change_type': r['change_type'],
                           'version': r['version'], 'snapshot': r['snapshot'], 'occurred_at': iso(r['occurred_at'])}
                          for r in rows]}

    def directory_snapshot(self):
        with self.store.transaction() as tx:
            seq = tx.max_change_seq() or 0
            workspaces = tx.list_workspaces(None, None, None, 0, 100000)
            customers = {}
            for w in workspaces:
                customers.setdefault(w['customer_id'], tx.get_customer(w['customer_id']))
            platform = tx.get_platform()
        return {'seq': seq, 'workspaces': [snapshot(w, customers[w['customer_id']]) for w in workspaces],
                'platform': {k: platform[k] for k in ('scheduled_scans_enabled', 'automated_alerts_enabled', 'version')}}

    @staticmethod
    def _page(cursor, limit):
        try:
            offset = int(cursor or 0)
            limit = int(limit or 50)
        except (TypeError, ValueError):
            raise IdentityError('Invalid page cursor.') from None
        return max(0, offset), max(1, min(limit, 200))
