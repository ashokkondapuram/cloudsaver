"""Process-local directory and billing store for unit tests; mirrors the PostgreSQL store contract."""
import copy
import threading
from contextlib import contextmanager

from identity.billing.catalog import SEED_PLANS, SEED_SETTINGS
from identity.billing.domain import ENDED
from identity.domain import CUSTOMER_DEFAULTS, SCOPE_KEYS, WORKSPACE_DEFAULTS, utcnow


def _newest(rows):
    return sorted(rows, key=lambda r: (r['created_at'], r['id']), reverse=True)


def _versioned(row, expected_version, fields):
    if not row or (expected_version is not None and row['version'] != expected_version):
        return None
    row.update(copy.deepcopy(fields), version=row['version'] + 1)
    return copy.deepcopy(row)


class MemoryTx:
    def __init__(self, state):
        self.s = state

    # customers
    def get_customer(self, customer_id, lock=False):
        row = self.s['customers'].get(customer_id)
        return copy.deepcopy(row) if row else None

    def list_customers(self, q, status, offset, limit):
        rows = [c for c in self.s['customers'].values()
                if (not status or c['status'] == status) and (not q or q.lower() in c['name'].lower())]
        rows.sort(key=lambda c: (c['name'].lower(), c['id']))
        return copy.deepcopy(rows[offset:offset + limit])

    def customer_workspace_counts(self):
        counts = {}
        for w in self.s['workspaces'].values():
            if w['status'] != 'deleted':
                total, active = counts.get(w['customer_id'], (0, 0))
                counts[w['customer_id']] = (total + 1, active + (w['status'] == 'active'))
        return counts

    def insert_customer(self, row):
        self.s['customers'][row['id']] = copy.deepcopy(CUSTOMER_DEFAULTS) | copy.deepcopy(row)

    def update_customer(self, customer_id, expected_version, fields):
        return _versioned(self.s['customers'].get(customer_id), expected_version, fields)

    def set_customer_billing_state(self, customer_id, state, at):
        self.s['customers'][customer_id].update(billing_state=state, billing_state_changed_at=at)

    def customer_by_external_ref(self, provider, ref):
        for row in self.s['customers'].values():
            if ref and (row.get('external_customer_refs') or {}).get(provider) == ref:
                return copy.deepcopy(row)
        return None

    # workspaces
    def get_workspace(self, tenant_id, lock=False):
        row = self.s['workspaces'].get(tenant_id)
        return copy.deepcopy(row) if row else None

    def list_workspaces(self, q, status, customer_id, offset, limit):
        rows = [w for w in self.s['workspaces'].values()
                if (not status or w['status'] == status) and (not customer_id or w['customer_id'] == customer_id)
                and (not q or q.lower() in w['name'].lower() or q.lower() in w['tenant_id'])]
        rows.sort(key=lambda w: (w['name'].lower(), w['tenant_id']))
        return copy.deepcopy(rows[offset:offset + limit])

    def insert_workspace(self, row):
        self.s['workspaces'][row['tenant_id']] = copy.deepcopy(WORKSPACE_DEFAULTS) | copy.deepcopy(row)

    def update_workspace(self, tenant_id, expected_version, fields):
        return _versioned(self.s['workspaces'].get(tenant_id), expected_version, fields)

    def replace_scopes(self, tenant_id, provider, items, actor, now):
        self.s['workspaces'][tenant_id][SCOPE_KEYS[provider]] = copy.deepcopy(items)

    # platform
    def get_platform(self):
        return dict(self.s['platform'])

    def update_platform(self, expected_version, fields):
        return _versioned(self.s['platform'], expected_version, fields)

    # change feed
    def append_change(self, tenant_id, change_type, version, snapshot):
        self.s['seq'] += 1
        self.s['changes'].append({'seq': self.s['seq'], 'tenant_id': tenant_id, 'change_type': change_type,
                                  'version': version, 'snapshot': copy.deepcopy(snapshot), 'occurred_at': utcnow()})
        return self.s['seq']

    def changes_after(self, after, limit):
        return [copy.deepcopy(c) for c in self.s['changes'] if c['seq'] > (after or 0)][:limit]

    def min_change_seq(self):
        return self.s['changes'][0]['seq'] if self.s['changes'] else None

    def max_change_seq(self):
        return self.s['seq']

    # keys
    def _find(self, field, value):
        for row in self.s['keys'].values():
            if row[field] is not None and row[field] == value:
                return dict(row)
        return None

    def key_by_key_id(self, key_id, lock=False):
        row = self.s['keys'].get(key_id)
        return dict(row) if row else None

    def key_by_legacy(self, digest):
        return self._find('legacy_sha256', digest)

    def key_by_digest(self, digest):
        return self._find('secret_digest', digest) if digest else None

    def key_by_fingerprint(self, fingerprint):
        return self._find('legacy_fingerprint', fingerprint) if fingerprint else None

    def list_keys(self, tenant_id):
        rows = [dict(k) for k in self.s['keys'].values() if k['tenant_id'] == tenant_id]
        return sorted(rows, key=lambda k: (k['created_at'], k['key_id']), reverse=True)

    def key_stats(self, now):
        from identity.service import key_status
        stats = {}
        for k in self.s['keys'].values():
            item = stats.setdefault(k['tenant_id'], {'active': 0, 'last_used_at': None, 'next_expiry': None})
            if k['last_used_at'] and (not item['last_used_at'] or k['last_used_at'] > item['last_used_at']):
                item['last_used_at'] = k['last_used_at']
            if key_status(k, now) in ('active', 'expiring_soon', 'rotating_out'):
                item['active'] += 1
                if k['expires_at'] and (not item['next_expiry'] or k['expires_at'] < item['next_expiry']):
                    item['next_expiry'] = k['expires_at']
        return stats

    def insert_key(self, row):
        for field in ('key_id', 'secret_digest', 'legacy_sha256', 'legacy_fingerprint'):
            if row[field] is not None and self._find(field, row[field]):
                raise ValueError('Duplicate key material')
        self.s['keys'][row['key_id']] = dict(row)

    def update_key(self, key_id, fields, expected_version=None):
        row = self.s['keys'].get(key_id)
        if not row or (expected_version is not None and row['version'] != expected_version):
            return None
        if row['revoked_at'] and 'revoked_at' in fields and fields['revoked_at'] is None:
            raise ValueError('Revoked keys stay revoked')
        row.update(fields, version=row['version'] + 1)
        return dict(row)

    # audit
    def append_event(self, row):
        self.s['events'].append(copy.deepcopy(row))

    def list_events(self, filters, before, limit):
        rows = [e for e in self.s['events']
                if all(e.get(k) == filters[k] for k in ('tenant_id', 'key_id', 'actor', 'action') if k in filters)
                and ('customer_id' not in filters or e['tenant_id'] in filters.get('tenant_ids', ())
                     or (e['details'] or {}).get('customer_id') == filters['customer_id'])
                and (before is None or e['occurred_at'] < before)]
        rows.sort(key=lambda e: e['occurred_at'], reverse=True)
        return copy.deepcopy(rows[:limit])

    # usage
    def record_usage(self, usage, failures, last_used):
        for key_id, hour, ip, success, failure, seen in usage:
            item = self.s['usage'].setdefault((key_id, hour, ip), {'key_id': key_id, 'hour': hour, 'source_ip': ip,
                                                                   'success_count': 0, 'failure_count': 0, 'last_seen_at': seen})
            item['success_count'] += success
            item['failure_count'] += failure
            item['last_seen_at'] = max(item['last_seen_at'], seen)
        for minute, ip, key_id, tenant_id, reason, caller, count in failures:
            item = self.s['failures'].setdefault((minute, ip, key_id, reason, caller), {
                'minute': minute, 'source_ip': ip, 'key_id': key_id, 'tenant_id': tenant_id, 'reason': reason,
                'caller': caller, 'count': 0})
            item['count'] += count
        for key_id, (when, ip) in last_used.items():
            if key_id in self.s['keys']:
                self.s['keys'][key_id].update(last_used_at=when, last_used_ip=ip)

    def list_usage(self, key_ids, start, end):
        rows = [dict(u) for u in self.s['usage'].values() if u['key_id'] in key_ids and start <= u['hour'] <= end]
        return sorted(rows, key=lambda u: (u['hour'], u['source_ip']))

    def list_failures(self, filters, start, limit):
        rows = [dict(f) for f in self.s['failures'].values() if f['minute'] >= start
                and all(f.get(k) == filters[k] for k in ('tenant_id', 'source_ip', 'reason') if k in filters)]
        return sorted(rows, key=lambda f: f['minute'], reverse=True)[:limit]

    # billing: plans and settings
    def list_plans(self):
        return copy.deepcopy(sorted(self.s['plans'].values(), key=lambda p: p['code']))

    def get_plan(self, code, lock=False):
        row = self.s['plans'].get(code)
        return copy.deepcopy(row) if row else None

    def insert_plan(self, row):
        if row['code'] in self.s['plans']:
            raise ValueError('Duplicate plan')
        self.s['plans'][row['code']] = copy.deepcopy(row)

    def update_plan(self, code, expected_version, fields):
        return _versioned(self.s['plans'].get(code), expected_version, fields)

    def plan_usage(self):
        customers, workspaces = {}, {}
        for w in self.s['workspaces'].values():
            if w['status'] != 'deleted':
                customers.setdefault(w['plan_tier'], set()).add(w['customer_id'])
                workspaces[w['plan_tier']] = workspaces.get(w['plan_tier'], 0) + 1
        return {code: (len(customers[code]), workspaces[code]) for code in workspaces}

    def get_billing_settings(self, lock=False):
        return copy.deepcopy(self.s['billing_settings'])

    def update_billing_settings(self, expected_version, fields):
        return _versioned(self.s['billing_settings'], expected_version, fields)

    # billing: subscriptions
    def get_subscription(self, subscription_id, lock=False):
        row = self.s['subscriptions'].get(subscription_id)
        return copy.deepcopy(row) if row else None

    def list_subscriptions(self, customer_id):
        return copy.deepcopy(_newest([r for r in self.s['subscriptions'].values() if r['customer_id'] == customer_id]))

    def current_subscription(self, customer_id, lock=False):
        rows = [r for r in self.s['subscriptions'].values() if r['customer_id'] == customer_id and r['status'] not in ENDED]
        return copy.deepcopy(rows[0]) if rows else None

    def latest_subscription(self, customer_id):
        rows = self.list_subscriptions(customer_id)
        current = [r for r in rows if r['status'] not in ENDED]
        return (current or rows or [None])[0]

    def latest_subscriptions(self):
        return {c: self.latest_subscription(c) for c in {r['customer_id'] for r in self.s['subscriptions'].values()}}

    def subscription_by_ref(self, provider, ref):
        for row in self.s['subscriptions'].values():
            if row['provider'] == provider and row['external_subscription_ref'] == ref:
                return copy.deepcopy(row)
        return None

    def latest_provider_subscription(self, customer_id, provider):
        rows = [r for r in self.list_subscriptions(customer_id) if r['provider'] == provider]
        return rows[0] if rows else None

    def insert_subscription(self, row):
        if row['status'] not in ENDED and self.current_subscription(row['customer_id']):
            raise ValueError('One current subscription per customer')
        self.s['subscriptions'][row['id']] = copy.deepcopy(row)

    def update_subscription(self, subscription_id, expected_version, fields):
        return _versioned(self.s['subscriptions'].get(subscription_id), expected_version, fields)

    # billing: payments
    def get_payment(self, payment_id, lock=False):
        row = self.s['payments'].get(payment_id)
        return copy.deepcopy(row) if row else None

    def list_payments(self, customer_id):
        return copy.deepcopy(_newest([r for r in self.s['payments'].values() if r['customer_id'] == customer_id]))

    def insert_payment(self, row):
        if row['external_payment_ref'] and self.payment_by_ref(row['external_payment_ref']):
            raise ValueError('Duplicate external payment')
        self.s['payments'][row['id']] = copy.deepcopy(row)

    def update_payment(self, payment_id, expected_version, fields):
        return _versioned(self.s['payments'].get(payment_id), expected_version, fields)

    def payment_by_ref(self, ref):
        return next((copy.deepcopy(r) for r in self.s['payments'].values() if r['external_payment_ref'] == ref), None)

    def reference_taken(self, customer_id, reference, exclude=None):
        return any(r['customer_id'] == customer_id and r['reference'] == reference and r['status'] != 'void'
                   and r['id'] != exclude for r in self.s['payments'].values())

    def last_payments(self):
        result = {}
        for row in self.s['payments'].values():
            if row['status'] == 'paid':
                best = result.get(row['customer_id'])
                if best is None or row['paid_at'] > best['paid_at']:
                    result[row['customer_id']] = copy.deepcopy(row)
        return result

    # billing: provider events (webhook dedupe)
    def provider_event(self, provider, event_id):
        row = self.s['provider_events'].get((provider, event_id))
        return dict(row) if row else None

    def insert_provider_event(self, row):
        key = (row['provider'], row['event_id'])
        if key in self.s['provider_events']:
            return False
        self.s['provider_events'][key] = dict(row, received_at=utcnow())
        return True

    def provider_watermark(self, customer_id, provider):
        return max((r['event_created'] or 0 for r in self.s['provider_events'].values()
                    if r['provider'] == provider and r['customer_id'] == customer_id
                    and r['outcome'] == 'ignored_untracked_deletion'), default=0)

    # cache events (long poll)
    def insert_access_check(self, row):
        self.s['access_checks'][row['check_id']] = copy.deepcopy(row)

    def get_access_check(self, check_id, lock=False):
        row = self.s['access_checks'].get(check_id)
        return copy.deepcopy(row) if row else None

    def update_access_check(self, check_id, fields):
        row = self.s['access_checks'].get(check_id)
        if not row:
            return None
        row.update(copy.deepcopy(fields))
        return copy.deepcopy(row)

    def count_recent_access_checks(self, tenant_id, since):
        return sum(1 for row in self.s['access_checks'].values()
                   if row['requested_at'] >= since
                   and ((row['tenant_id'] is None) if tenant_id is None else row['tenant_id'] == tenant_id))

    def append_cache_event(self, tenant_id, key_id, event, directory, payload=None):
        self.s['cache_seq'] += 1
        self.s['cache_events'].append({'seq': self.s['cache_seq'], 'tenant_id': tenant_id, 'key_id': key_id,
                                       'event': event, 'directory': directory, 'payload': copy.deepcopy(payload or {}),
                                       'created_at': utcnow()})
        return self.s['cache_seq']

    def cache_events_after(self, after, limit):
        return [dict(e) for e in self.s['cache_events'] if e['seq'] > after][:limit]

    def cache_head(self):
        return self.s['cache_seq']

    def cache_oldest(self, since):
        return next((e['seq'] for e in self.s['cache_events'] if e['created_at'] >= since), None)


class MemoryStore:
    def __init__(self):
        now = utcnow()
        plans = {p['code']: dict(copy.deepcopy(p), status='active', list_price_minor=None, currency=None, interval=None,
                                 external_price_refs={}, version=1, created_at=now, created_by='bootstrap',
                                 updated_at=now, updated_by='bootstrap') for p in SEED_PLANS}
        self.state = {'customers': {}, 'workspaces': {}, 'keys': {}, 'events': [], 'changes': [], 'seq': 0,
                      'usage': {}, 'failures': {}, 'plans': plans, 'subscriptions': {}, 'payments': {},
                      'provider_events': {}, 'cache_events': [], 'cache_seq': 0,
                      'billing_settings': dict(SEED_SETTINGS, version=1, updated_at=now, updated_by='bootstrap'),
                      'access_checks': {},
                      'platform': {'scheduled_scans_enabled': False, 'automated_alerts_enabled': False,
                                   'resource_access': {}, 'version': 1, 'updated_by': 'bootstrap', 'updated_at': now}}
        self._lock = threading.RLock()

    @contextmanager
    def transaction(self):
        with self._lock:
            saved = copy.deepcopy(self.state)
            try:
                yield MemoryTx(self.state)
            except BaseException:
                self.state.clear()
                self.state.update(saved)
                raise
