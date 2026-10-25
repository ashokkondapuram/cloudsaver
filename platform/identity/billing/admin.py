"""Portal billing admin API (plans, subscriptions, payments, customer billing overview)."""
from uuid import uuid4

from identity.billing.catalog import SEED_PLANS, SEED_SETTINGS, merged, validate_entitlements
from identity.billing.domain import (
    BILLING_STATES, ENDED, LAPSED_ACTIONS, PAYMENT_METHODS, PAYMENT_STATUSES, PLAN_CODE, PLAN_STATUSES, PROVIDER_NAMES,
    SUBSCRIPTION_STATUSES, billing_state, choice, currency, day, free_text, https_url, iso_day, optional_day, timestamp, whole,
)
from identity.billing.projection import workspace_plan_block
from identity.billing.providers import billing_provider_configured
from identity.config import billing_session_flags, env, flag
from identity.domain import Conflict, IdentityError, NotFound, StaleVersion, iso, parse_time, text, uuid_text


def _seed_entitlements(code, stored):
    base = next((p['entitlements'] for p in SEED_PLANS if p['code'] == code), {})
    merged = {**base, **(stored or {})}
    return validate_entitlements(merged)


class BillingOps:
    def evaluate_billing(self):
        if not flag('BILLING_ENABLED'):
            return {'changed': 0}
        actor = {'actor': 'billing-evaluator', 'actor_type': 'system'}
        changed, offset = 0, 0
        while True:
            with self.store.transaction() as tx:
                page = tx.list_customers(None, None, offset, 100)
            for candidate in page:
                if candidate['status'] == 'deleted':
                    continue
                with self.store.transaction() as tx:
                    customer = tx.get_customer(candidate['id'], lock=True)
                    if not customer or customer['status'] == 'deleted':
                        continue
                    now = self.now()
                    sub = tx.latest_subscription(customer['id'])
                    state, boundary = billing_state(sub, now)
                    if state == (customer.get('billing_state') or 'none'):
                        continue
                    tx.set_customer_billing_state(customer['id'], state, boundary or now)
                    self._sync_customer_entitlements(tx, customer['id'], actor, now)
                    self._event(tx, actor, 'billing_state_changed', details={
                        'customer_id': customer['id'], 'from': customer.get('billing_state'), 'to': state})
                    for workspace in tx.list_workspaces(None, None, customer['id'], 0, 10000):
                        self._publish([{'tenant_id': workspace['tenant_id'], 'event': 'entitlements_changed', 'directory': True}], tx)
                    changed += 1
            offset += len(page)
            if len(page) < 100:
                return {'changed': changed}

    def _plan_row_view(self, row, usage):
        customers, workspaces = usage.get(row['code'], (0, 0))
        refs = row.get('external_price_refs') or {}
        return {
            'code': row['code'], 'name': row['name'], 'description': row.get('description'),
            'status': row['status'], 'list_price_minor': row.get('list_price_minor'),
            'currency': row.get('currency'), 'interval': row.get('interval'),
            'entitlements': _seed_entitlements(row['code'], row.get('entitlements')),
            'external_price_refs': refs if isinstance(refs, dict) else {},
            'customer_count': customers, 'workspace_count': workspaces,
            'version': row['version'], 'created_at': iso(row['created_at']), 'created_by': row['created_by'],
            'updated_at': iso(row['updated_at']), 'updated_by': row['updated_by'],
        }

    def _subscription_view(self, row, plans):
        plan = plans.get(row['plan_code']) or {}
        return {
            'id': str(row['id']), 'customer_id': str(row['customer_id']), 'plan_code': row['plan_code'],
            'plan_name': plan.get('name') or row['plan_code'], 'status': row['status'], 'provider': row['provider'],
            'external_subscription_ref': row.get('external_subscription_ref'),
            'current_period_start': iso(row['current_period_start']),
            'current_period_end': iso(row['current_period_end']),
            'cancel_at_period_end': bool(row['cancel_at_period_end']),
            'canceled_at': iso(row.get('canceled_at')),
            'amount_minor': int(row['amount_minor']), 'currency': row['currency'], 'interval': row['interval'],
            'grace_days': int(row['grace_days']),
            'entitlement_overrides': row.get('entitlement_overrides'),
            'notes': row.get('notes'), 'version': row['version'],
            'created_at': iso(row['created_at']), 'created_by': row['created_by'],
            'updated_at': iso(row['updated_at']), 'updated_by': row['updated_by'],
        }

    def _payment_view(self, row):
        return {
            'id': str(row['id']), 'customer_id': str(row['customer_id']),
            'subscription_id': str(row['subscription_id']) if row.get('subscription_id') else None,
            'amount_minor': int(row['amount_minor']), 'currency': row['currency'], 'status': row['status'],
            'method': row['method'], 'reference': row['reference'],
            'invoice_date': iso_day(row.get('invoice_date')), 'due_date': iso_day(row.get('due_date')),
            'paid_at': iso(row.get('paid_at')), 'period_start': iso_day(row['period_start']),
            'period_end': iso_day(row['period_end']), 'provider': row['provider'],
            'external_payment_ref': row.get('external_payment_ref'), 'notes': row.get('notes'),
            'void_reason': row.get('void_reason'), 'voided_by': row.get('voided_by'),
            'voided_at': iso(row.get('voided_at')), 'version': row['version'],
            'created_at': iso(row['created_at']), 'created_by': row['created_by'],
            'updated_at': iso(row['updated_at']), 'updated_by': row['updated_by'],
        }

    def _billing_settings_view(self, row):
        flags = billing_session_flags()
        configured = billing_provider_configured(flags['billing_provider'])
        public = env('PUBLIC_URL', 'http://127.0.0.1:3100')
        return {
            'default_plan_code': row['default_plan_code'], 'default_grace_days': int(row['default_grace_days']),
            'lapsed_action': row['lapsed_action'], 'lapsed_plan_code': row['lapsed_plan_code'],
            'default_manage_billing_url': row.get('default_manage_billing_url'),
            'require_subscription_for_keys': bool(row['require_subscription_for_keys']),
            'version': row['version'], 'updated_at': iso(row['updated_at']), 'updated_by': row['updated_by'],
            'billing_enabled': flags['billing_enabled'],
            'provider': {'name': flags['billing_provider'], 'configured': configured,
                         'webhook_url': f'{public.rstrip("/")}/api/webhooks/stripe' if flags['billing_provider'] == 'stripe' else None},
        }

    def _refresh_customer_billing(self, tx, customer_id, now):
        sub = tx.latest_subscription(customer_id)
        state, at = billing_state(sub, now)
        tx.set_customer_billing_state(customer_id, state, at or now)

    def _sync_customer_entitlements(self, tx, customer_id, actor, now):
        if not flag('BILLING_ENABLED'):
            return
        customer = tx.get_customer(customer_id)
        if not customer:
            return
        for workspace in tx.list_workspaces(None, None, customer_id, 0, 10_000):
            if workspace['status'] == 'deleted':
                continue
            plan = workspace_plan_block(tx, workspace, customer, now)
            fields = {}
            if workspace.get('entitlements') != plan['entitlements']:
                fields['entitlements'] = plan['entitlements']
                fields['entitlements_version'] = int(workspace.get('entitlements_version') or 1) + 1
                plan['entitlements_version'] = fields['entitlements_version']
            if workspace['plan_tier'] != plan['code']:
                fields['plan_tier'] = plan['code']
            row = workspace
            if fields:
                fields['updated_at'] = now
                fields['updated_by'] = actor['actor'][:120]
                updated = tx.update_workspace(workspace['tenant_id'], workspace['version'], fields)
                if updated is None:
                    raise StaleVersion()
                row = updated
            self._changed(tx, row, customer, change_type='entitlements_changed')

    def _apply_subscription_plan(self, tx, customer_id, plan_code, actor, now):
        if not flag('BILLING_ENABLED'):
            return
        for workspace in tx.list_workspaces(None, None, customer_id, 0, 10_000):
            if workspace['status'] == 'deleted' or workspace['plan_tier'] == plan_code:
                continue
            row = tx.update_workspace(workspace['tenant_id'], workspace['version'], {
                'plan_tier': plan_code, 'updated_at': now, 'updated_by': actor['actor'][:120]})
            if row:
                customer = tx.get_customer(customer_id)
                self._changed(tx, row, customer)

    def list_plans(self):
        with self.store.transaction() as tx:
            usage = tx.plan_usage()
            rows = tx.list_plans()
        return {'items': [self._plan_row_view(r, usage) for r in rows]}

    def get_plan(self, code):
        code = text(code, 'Plan code', 16)
        with self.store.transaction() as tx:
            row = tx.get_plan(code)
            if not row:
                raise NotFound('Plan not found.')
            return self._plan_row_view(row, tx.plan_usage())

    def create_plan(self, payload, actor, request_id=None):
        code = text(payload.get('code'), 'Plan code', 16)
        if not PLAN_CODE.fullmatch(code):
            raise IdentityError('Plan code must start with a letter and use uppercase letters, numbers, or underscores.')
        name = text(payload.get('name'), 'Name', 80)
        description = free_text(payload.get('description'), 'Description', 500) if payload.get('description') else None
        entitlements = validate_entitlements(payload['entitlements'])
        refs = payload.get('external_price_refs') or {}
        if refs and not isinstance(refs, dict):
            raise IdentityError('External price references must be an object.')
        now = self.now()
        with self.store.transaction() as tx:
            if tx.get_plan(code):
                raise Conflict('A plan with this code already exists.')
            row = {'code': code, 'name': name, 'description': description, 'status': 'active',
                   'list_price_minor': whole(payload['list_price_minor'], 'List price', 0) if payload.get('list_price_minor') is not None else None,
                   'currency': currency(payload['currency']) if payload.get('currency') else None,
                   'interval': choice(payload['interval'], ('month', 'year', 'custom'), 'Choose a valid interval.') if payload.get('interval') else None,
                   'external_price_refs': refs, 'entitlements': entitlements,
                   'created_at': now, 'created_by': actor['actor'][:120], 'updated_at': now,
                   'updated_by': actor['actor'][:120], 'version': 1}
            tx.insert_plan(row)
            self._event(tx, actor, 'plan_created', details={'code': code}, request_id=request_id)
        return self.get_plan(code)

    def update_plan(self, code, payload, actor, request_id=None):
        code = text(code, 'Plan code', 16)
        version = self._version(payload)
        fields = {}
        if payload.get('name') is not None:
            fields['name'] = text(payload['name'], 'Name', 80)
        if 'description' in payload:
            fields['description'] = free_text(payload.get('description'), 'Description', 500) if payload.get('description') else None
        if payload.get('entitlements') is not None:
            fields['entitlements'] = validate_entitlements(payload['entitlements'])
        if 'list_price_minor' in payload:
            fields['list_price_minor'] = whole(payload['list_price_minor'], 'List price', 0) if payload['list_price_minor'] is not None else None
        if 'currency' in payload:
            fields['currency'] = currency(payload['currency']) if payload['currency'] else None
        if 'interval' in payload and payload['interval'] is not None:
            fields['interval'] = choice(payload['interval'], ('month', 'year', 'custom'), 'Choose a valid interval.')
        if 'external_price_refs' in payload:
            refs = payload['external_price_refs'] or {}
            if not isinstance(refs, dict):
                raise IdentityError('External price references must be an object.')
            fields['external_price_refs'] = refs
        now = self.now()
        with self.store.transaction() as tx:
            updated = tx.update_plan(code, version, dict(fields, updated_at=now, updated_by=actor['actor'][:120]))
            if updated is None:
                if not tx.get_plan(code):
                    raise NotFound('Plan not found.')
                raise StaleVersion()
            self._event(tx, actor, 'plan_updated', details={'code': code}, request_id=request_id)
        return self.get_plan(code)

    def retire_plan(self, code, payload, actor, request_id=None):
        code = text(code, 'Plan code', 16)
        version = self._version(payload)
        now = self.now()
        with self.store.transaction() as tx:
            updated = tx.update_plan(code, version, {'status': 'retired', 'updated_at': now, 'updated_by': actor['actor'][:120]})
            if updated is None:
                if not tx.get_plan(code):
                    raise NotFound('Plan not found.')
                raise StaleVersion()
            self._event(tx, actor, 'plan_retired', details={'code': code}, request_id=request_id)
        return self.get_plan(code)

    def get_billing_settings(self):
        with self.store.transaction() as tx:
            row = tx.get_billing_settings()
        return self._billing_settings_view(row)

    def update_billing_settings(self, payload, actor, request_id=None):
        version = self._version(payload)
        fields = {}
        if payload.get('default_plan_code') is not None:
            fields['default_plan_code'] = text(payload['default_plan_code'], 'Default plan', 16)
        if payload.get('default_grace_days') is not None:
            fields['default_grace_days'] = whole(payload['default_grace_days'], 'Grace period', 0, 60)
        if payload.get('lapsed_action') is not None:
            fields['lapsed_action'] = choice(payload['lapsed_action'], LAPSED_ACTIONS, 'Choose a valid lapsed action.')
        if payload.get('lapsed_plan_code') is not None:
            fields['lapsed_plan_code'] = text(payload['lapsed_plan_code'], 'Lapsed plan', 16)
        if 'default_manage_billing_url' in payload:
            fields['default_manage_billing_url'] = https_url(payload.get('default_manage_billing_url'))
        if payload.get('require_subscription_for_keys') is not None:
            fields['require_subscription_for_keys'] = bool(payload['require_subscription_for_keys'])
        now = self.now()
        with self.store.transaction() as tx:
            updated = tx.update_billing_settings(version, dict(fields, updated_at=now, updated_by=actor['actor'][:120]))
            if updated is None:
                raise StaleVersion()
            self._event(tx, actor, 'billing_settings_updated', details={'changes': sorted(fields)}, request_id=request_id)
        return self._billing_settings_view(updated)

    def list_billing_customers(self, billing_state=None, plan=None, renews_before=None, cursor=None, limit=50):
        offset, limit = self._page(cursor, limit)
        if billing_state and billing_state not in BILLING_STATES:
            raise IdentityError('Choose a valid billing status.')
        renews_cutoff = day(renews_before, 'Renews before') if renews_before else None
        with self.store.transaction() as tx:
            customers = tx.list_customers(None, None, offset, limit + 50)
            subs = tx.latest_subscriptions()
            payments = tx.last_payments()
            plans = {p['code']: p for p in tx.list_plans()}
        items = []
        for customer in customers:
            if customer['status'] == 'deleted':
                continue
            sub = subs.get(str(customer['id']))
            state = customer.get('billing_state') or 'none'
            plan_code = sub['plan_code'] if sub else SEED_SETTINGS['default_plan_code']
            plan_row = plans.get(plan_code, {})
            if billing_state and state != billing_state:
                continue
            if plan and plan_code != plan:
                continue
            period_end = sub['current_period_end'] if sub else None
            if renews_cutoff and (not period_end or (period_end.date() if hasattr(period_end, 'date') else period_end) > renews_cutoff):
                continue
            pay = payments.get(str(customer['id']))
            items.append({
                'customer_id': str(customer['id']), 'customer_name': customer['name'],
                'billing_state': state, 'plan_code': plan_code,
                'plan_name': plan_row.get('name') or plan_code,
                'subscription_id': str(sub['id']) if sub else None,
                'subscription_status': sub['status'] if sub else None,
                'current_period_end': iso(period_end) if period_end else None,
                'amount_minor': int(sub['amount_minor']) if sub else None,
                'currency': sub['currency'] if sub else None,
                'interval': sub['interval'] if sub else None,
                'last_payment': None if not pay else {
                    'paid_at': iso(pay.get('paid_at')), 'amount_minor': int(pay['amount_minor']),
                    'currency': pay['currency'], 'reference': pay['reference'],
                },
            })
        page = items[:limit]
        return {'items': page, 'next_cursor': str(offset + limit) if len(items) > limit else None}

    def list_customer_subscriptions(self, customer_id):
        customer_id = uuid_text(customer_id)
        with self.store.transaction() as tx:
            if not tx.get_customer(customer_id):
                raise NotFound('Customer not found.')
            rows = tx.list_subscriptions(customer_id)
            plans = {p['code']: p for p in tx.list_plans()}
            current = tx.current_subscription(customer_id)
        views = [self._subscription_view(r, plans) for r in rows]
        current_view = self._subscription_view(current, plans) if current else None
        return {'current': current_view, 'items': views}

    def create_customer_subscription(self, customer_id, payload, actor, request_id=None):
        customer_id = uuid_text(customer_id)
        plan_code = text(payload['plan_code'], 'Plan', 16)
        status = choice(payload['status'], SUBSCRIPTION_STATUSES, 'Choose a valid subscription status.')
        if status in ENDED:
            raise IdentityError('Choose an active subscription status.')
        start = timestamp(payload['current_period_start'], 'Period start')
        end = timestamp(payload['current_period_end'], 'Period end')
        if end <= start:
            raise IdentityError('Choose an end date after the start date.')
        amount = whole(payload['amount_minor'], 'Amount', 0)
        cur = currency(payload['currency'])
        interval = choice(payload['interval'], ('month', 'year', 'custom'), 'Choose a valid billing interval.')
        with self.store.transaction() as tx:
            if not tx.get_customer(customer_id, lock=True):
                raise NotFound('Customer not found.')
            if tx.current_subscription(customer_id):
                raise Conflict('This customer already has a subscription. Edit or cancel it first.')
            if not tx.get_plan(plan_code):
                raise IdentityError('Choose an existing plan.')
            settings = tx.get_billing_settings()
            grace = payload.get('grace_days')
            grace_days = whole(grace, 'Grace period', 0, 60) if grace is not None else int(settings['default_grace_days'])
            notes = free_text(payload.get('notes'), 'Notes', 500)
            overrides = None
            if 'entitlement_overrides' in payload:
                raw = payload['entitlement_overrides']
                overrides = validate_entitlements(raw, partial=True) if raw else None
            now = self.now()
            row = {'id': str(uuid4()), 'customer_id': customer_id, 'plan_code': plan_code, 'status': status,
                   'provider': 'manual', 'external_subscription_ref': None,
                   'current_period_start': start, 'current_period_end': end, 'cancel_at_period_end': False,
                   'canceled_at': None, 'amount_minor': amount, 'currency': cur, 'interval': interval,
                   'grace_days': grace_days, 'entitlement_overrides': overrides, 'notes': notes,
                   'created_at': now, 'created_by': actor['actor'][:120], 'updated_at': now,
                   'updated_by': actor['actor'][:120], 'version': 1}
            tx.insert_subscription(row)
            self._refresh_customer_billing(tx, customer_id, now)
            self._apply_subscription_plan(tx, customer_id, plan_code, actor, now)
            self._sync_customer_entitlements(tx, customer_id, actor, now)
            plans = {p['code']: p for p in tx.list_plans()}
            self._event(tx, actor, 'subscription_created', details={'customer_id': customer_id, 'plan_code': plan_code},
                        request_id=request_id)
            self._publish([{'directory': True, 'event': 'directory_changed'}], tx)
            return self._subscription_view(tx.get_subscription(row['id']), plans)

    def get_subscription(self, subscription_id):
        subscription_id = uuid_text(subscription_id)
        with self.store.transaction() as tx:
            row = tx.get_subscription(subscription_id)
            if not row:
                raise NotFound('Subscription not found.')
            plans = {p['code']: p for p in tx.list_plans()}
        return self._subscription_view(row, plans)

    def cancel_subscription(self, subscription_id, payload, actor, request_id=None):
        subscription_id = uuid_text(subscription_id)
        version = self._version(payload)
        at_period_end = bool(payload.get('at_period_end'))
        reason = free_text(payload.get('reason'), 'Reason', 500)
        now = self.now()
        with self.store.transaction() as tx:
            current = tx.get_subscription(subscription_id, lock=True)
            if not current:
                raise NotFound('Subscription not found.')
            if current['provider'] == 'stripe':
                from identity.billing.domain import STRIPE_MANAGED
                raise IdentityError(STRIPE_MANAGED)
            if current['status'] in ENDED:
                raise Conflict('This subscription has already ended.')
            fields = {}
            if reason:
                prior = (current.get('notes') or '').strip()
                fields['notes'] = free_text(f'{prior}\n{reason}'.strip() if prior else reason, 'Notes', 500)
            if at_period_end:
                fields['cancel_at_period_end'] = True
            else:
                fields['status'] = 'canceled'
                fields['canceled_at'] = now
            updated = tx.update_subscription(subscription_id, version, dict(fields, updated_at=now, updated_by=actor['actor'][:120]))
            if updated is None:
                raise StaleVersion()
            self._refresh_customer_billing(tx, current['customer_id'], now)
            self._sync_customer_entitlements(tx, current['customer_id'], actor, now)
            plans = {p['code']: p for p in tx.list_plans()}
            self._event(tx, actor, 'subscription_changed', details={'subscription_id': subscription_id, 'cancel': True},
                        request_id=request_id)
            self._publish([{'directory': True, 'event': 'directory_changed'}], tx)
            return self._subscription_view(updated, plans)

    def update_subscription(self, subscription_id, payload, actor, request_id=None):
        subscription_id = uuid_text(subscription_id)
        version = self._version(payload)
        with self.store.transaction() as tx:
            current = tx.get_subscription(subscription_id, lock=True)
            if not current:
                raise NotFound('Subscription not found.')
            if current['provider'] == 'stripe' and any(k in payload for k in payload if k not in ('version', 'notes', 'entitlement_overrides')):
                from identity.billing.domain import STRIPE_MANAGED
                raise IdentityError(STRIPE_MANAGED)
            fields = {}
            for key, parser in (
                ('plan_code', lambda v: text(v, 'Plan', 16)),
                ('status', lambda v: choice(v, SUBSCRIPTION_STATUSES, 'Choose a valid status.')),
                ('current_period_start', lambda v: timestamp(v, 'Period start')),
                ('current_period_end', lambda v: timestamp(v, 'Period end')),
                ('amount_minor', lambda v: whole(v, 'Amount', 0)),
                ('currency', currency),
                ('interval', lambda v: choice(v, ('month', 'year', 'custom'), 'Choose a valid interval.')),
                ('grace_days', lambda v: whole(v, 'Grace period', 0, 60)),
                ('notes', lambda v: free_text(v, 'Notes', 500)),
            ):
                if key in payload and payload[key] is not None:
                    fields[key] = parser(payload[key])
            if 'plan_code' in fields and not tx.get_plan(fields['plan_code']):
                raise IdentityError('Choose an existing plan.')
            if 'entitlement_overrides' in payload:
                overrides = payload['entitlement_overrides']
                fields['entitlement_overrides'] = validate_entitlements(overrides, partial=True) if overrides else None
            now = self.now()
            updated = tx.update_subscription(subscription_id, version, dict(fields, updated_at=now, updated_by=actor['actor'][:120]))
            if updated is None:
                raise StaleVersion()
            self._refresh_customer_billing(tx, current['customer_id'], now)
            if 'plan_code' in fields:
                self._apply_subscription_plan(tx, current['customer_id'], fields['plan_code'], actor, now)
            if 'plan_code' in fields or 'entitlement_overrides' in fields or 'status' in fields:
                self._sync_customer_entitlements(tx, current['customer_id'], actor, now)
            plans = {p['code']: p for p in tx.list_plans()}
            self._event(tx, actor, 'subscription_changed', details={'subscription_id': subscription_id}, request_id=request_id)
            return self._subscription_view(updated, plans)

    def list_customer_payments(self, customer_id):
        customer_id = uuid_text(customer_id)
        with self.store.transaction() as tx:
            if not tx.get_customer(customer_id):
                raise NotFound('Customer not found.')
            rows = tx.list_payments(customer_id)
        return {'items': [self._payment_view(r) for r in rows]}

    def create_customer_payment(self, customer_id, payload, actor, request_id=None):
        customer_id = uuid_text(customer_id)
        amount = whole(payload['amount_minor'], 'Amount', 1)
        cur = currency(payload['currency'])
        status = choice(payload['status'], PAYMENT_STATUSES, 'Choose a valid payment status.')
        method = choice(payload['method'], PAYMENT_METHODS, 'Choose a valid payment method.')
        reference = free_text(payload['reference'], 'Reference', 80, required=True)
        period_start = day(payload['period_start'], 'Period start')
        period_end = day(payload['period_end'], 'Period end')
        if period_end < period_start:
            raise IdentityError('Choose an end date on or after the start date.')
        now = self.now()
        with self.store.transaction() as tx:
            if not tx.get_customer(customer_id):
                raise NotFound('Customer not found.')
            if tx.reference_taken(customer_id, reference, None):
                raise Conflict('A payment with this reference already exists for this customer.')
            sub_id = payload.get('subscription_id')
            if sub_id is not None:
                sub_id = uuid_text(sub_id)
                sub = tx.get_subscription(sub_id)
                if not sub or sub['customer_id'] != customer_id:
                    raise IdentityError('Choose a subscription for this customer.')
            row = {'id': str(uuid4()), 'customer_id': customer_id, 'subscription_id': sub_id,
                   'amount_minor': amount, 'currency': cur, 'status': status, 'method': method, 'reference': reference,
                   'invoice_date': optional_day(payload.get('invoice_date'), 'Invoice date') if payload.get('invoice_date') else None,
                   'due_date': optional_day(payload.get('due_date'), 'Due date') if payload.get('due_date') else None,
                   'paid_at': parse_time(payload['paid_at'], 'Paid at') if payload.get('paid_at') else None,
                   'period_start': period_start, 'period_end': period_end, 'provider': 'manual',
                   'external_payment_ref': None, 'notes': free_text(payload.get('notes'), 'Notes', 500),
                   'void_reason': None, 'voided_by': None, 'voided_at': None,
                   'created_at': now, 'created_by': actor['actor'][:120], 'updated_at': now,
                   'updated_by': actor['actor'][:120], 'version': 1}
            tx.insert_payment(row)
            self._event(tx, actor, 'payment_recorded', details={'customer_id': customer_id, 'reference': reference},
                        request_id=request_id)
            return self._payment_view(tx.get_payment(row['id']))

    def get_customer_entitlements(self, customer_id):
        customer_id = uuid_text(customer_id)
        now = self.now()
        with self.store.transaction() as tx:
            customer = tx.get_customer(customer_id)
            if not customer:
                raise NotFound('Customer not found.')
            sub = tx.latest_subscription(customer_id)
            settings = tx.get_billing_settings()
            plans = {p['code']: p for p in tx.list_plans()}
            workspaces = tx.list_workspaces(None, None, customer_id, 0, 10_000)
        plan_code = sub['plan_code'] if sub else settings['default_plan_code']
        plan_row = plans.get(plan_code) or plans.get(settings['default_plan_code'])
        plan_ent = _seed_entitlements(plan_code, (plan_row or {}).get('entitlements'))
        values, sources = merged(plan_ent, (sub or {}).get('entitlement_overrides'))
        state, _ = billing_state(sub, now)
        blocked = flag('BILLING_ENABLED') and settings['require_subscription_for_keys'] and state not in ('active', 'grace')
        effective = {k: {'value': values[k], 'source': 'override' if sources[k] == 'override' else 'plan'} for k in values}
        return {
            'customer_id': str(customer_id), 'billing_state': state,
            'plan': {'code': plan_code, 'name': (plan_row or {}).get('name') or plan_code},
            'subscription': self._subscription_view(sub, plans) if sub else None,
            'issuance_blocked': blocked,
            'effective': effective,
            'workspaces': [{'tenant_id': str(w['tenant_id']), 'name': w['name'], 'plan_tier': w['plan_tier'],
                            'entitlements_version': w.get('entitlements_version', 1)} for w in workspaces if w['status'] != 'deleted'],
        }
