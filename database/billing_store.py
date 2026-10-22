"""Atomic Stripe event handling against tenant-scoped PostgreSQL records.

This module never discovers tenant ownership from Stripe metadata. Routes are
trusted server configuration and must agree with an already provisioned row.
"""
from collections.abc import Mapping


class BillingEventError(ValueError):
    pass


class BillingProvisioningError(RuntimeError):
    pass


def identifier(value, prefix):
    if isinstance(value, Mapping):
        value = value.get('id')
    if not isinstance(value, str) or not value.startswith(prefix) or len(value) > 255:
        raise BillingEventError('Invalid billing object identifier')
    return value


def integer(value):
    if type(value) is not int or value <= 0:
        raise BillingEventError('Invalid billing object timestamp')
    return value


def invoice_subscription(obj):
    legacy = obj.get('subscription')
    parent = obj.get('parent') or {}
    details = parent.get('subscription_details') or {}
    current = details.get('subscription')
    legacy_id = identifier(legacy, 'sub_') if legacy else None
    current_id = identifier(current, 'sub_') if current else None
    if legacy_id and current_id and legacy_id != current_id:
        raise BillingEventError('Ambiguous invoice subscription')
    return current_id or legacy_id


def transition(state, event, tiers):
    """Conservative snapshot transition; no remote Stripe requests or payment actions.

Subscription and invoice watermarks are separate: a payment notification must
not suppress a subsequent subscription status update delivered out of order.
Equal-second active updates are ignored; equal-second cancellation of the
current subscription can only remove entitlement, never add it.
"""
    kind, created = event['type'], integer(event['created'])
    obj = event['data']['object']
    current_id = state.get('stripe_subscription_id')
    current_status = state.get('stripe_subscription_status')
    if kind == 'invoice.payment_succeeded':
        subscription = invoice_subscription(obj)
        if not subscription or subscription != current_id or current_status not in ('active', 'trialing'):
            return {}, 'ignored_invoice_subscription'
        if obj.get('status') != 'paid':
            return {}, 'ignored_unpaid_invoice'
        if created <= (state.get('stripe_invoice_event_created') or 0):
            return {}, 'ignored_stale_invoice'
        return {'stripe_last_invoice_id': identifier(obj.get('id'), 'in_'),
                'stripe_invoice_event_created': created}, 'payment_recorded'

    subscription = identifier(obj.get('id'), 'sub_')
    subscription_created = integer(obj.get('created'))
    status = 'canceled' if kind == 'customer.subscription.deleted' else obj.get('status')
    if not isinstance(status, str) or len(status) > 32:
        raise BillingEventError('Invalid subscription status')
    watermark = state.get('stripe_event_created') or 0
    active = status in ('active', 'trialing')
    if created < watermark:
        return {}, 'ignored_stale_subscription'
    if kind == 'customer.subscription.deleted' and current_id != subscription:
        if current_id is None:
            # Retain chronology without assigning an untracked subscription.
            return {'stripe_event_created': created, 'stripe_event_id': event['id']}, 'ignored_untracked_deletion'
        return {}, 'ignored_other_subscription'
    if current_id and current_id != subscription:
        if not active:
            return {}, 'ignored_other_subscription'
        if created <= watermark or subscription_created <= (state.get('stripe_subscription_created') or 0):
            return {}, 'ignored_older_subscription'
    elif current_id == subscription:
        if active and current_status == 'canceled':
            return {}, 'ignored_canceled_subscription'
        if created == watermark and active:
            return {}, 'ignored_tied_subscription'

    tier = 'STARTER'
    reason = 'subscription_updated'
    if active:
        items = obj.get('items') or {}
        data = items.get('data') or []
        if not items.get('has_more') and len(data) == 1:
            try:
                price = identifier(data[0].get('price'), 'price_')
                quantity = data[0].get('quantity', 1)
                if type(quantity) is int and quantity > 0:
                    tier = tiers.get(price, 'STARTER')
                    if price not in tiers:
                        reason = 'unknown_price_starter'
                else:
                    reason = 'ambiguous_price_starter'
            except (BillingEventError, AttributeError):
                reason = 'unknown_price_starter'
        else:
            reason = 'ambiguous_price_starter'
    return {
        'plan_tier': tier,
        'stripe_subscription_id': subscription,
        'stripe_subscription_status': status,
        'stripe_subscription_created': subscription_created,
        'stripe_event_created': created,
        'stripe_event_id': event['id'],
    }, reason


class BillingStore:
    def __init__(self, database_url):
        if not database_url or not database_url.startswith(('postgresql://', 'postgresql+psycopg://')):
            raise BillingProvisioningError('Billing requires configured PostgreSQL persistence')
        self.database_url = database_url.replace('postgresql+psycopg://', 'postgresql://', 1)

    def apply_event(self, route, customer_id, event, tiers):
        import psycopg
        from psycopg.rows import dict_row

        with psycopg.connect(self.database_url, row_factory=dict_row, connect_timeout=5) as connection:
            with connection.cursor() as cursor:
                cursor.execute('SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user')
                role = cursor.fetchone()
                if role is None or role['rolsuper'] or role['rolbypassrls']:
                    raise BillingProvisioningError('Billing requires a non-superuser role without BYPASSRLS')
                cursor.execute("SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class WHERE oid IN ('public.organizations'::regclass, 'public.stripe_events'::regclass)")
                tables = cursor.fetchall()
                if len(tables) != 2 or not all(row['relrowsecurity'] and row['relforcerowsecurity'] for row in tables):
                    raise BillingProvisioningError('Billing requires forced row-level security on its tables')
                cursor.execute("SELECT set_config('app.current_tenant_id', %s, true)", (route['tenant_id'],))
                cursor.execute('''SELECT plan_tier, stripe_subscription_id, stripe_subscription_status,
                                         stripe_subscription_created, stripe_event_created,
                                         stripe_invoice_event_created
                                  FROM public.organizations
                                  WHERE tenant_id=%s AND id=%s AND stripe_customer_id=%s
                                  FOR UPDATE''', (route['tenant_id'], route['organization_id'], customer_id))
                state = cursor.fetchone()
                if state is None:
                    raise BillingProvisioningError('Customer mapping does not match provisioned organization')
                cursor.execute('SELECT 1 FROM public.stripe_events WHERE tenant_id=%s AND event_id=%s',
                               (route['tenant_id'], event['id']))
                if cursor.fetchone():
                    return 'duplicate'
                update, outcome = transition(state, event, tiers)
                cursor.execute('''INSERT INTO public.stripe_events
                                  (tenant_id,event_id,organization_id,event_type,event_created,outcome)
                                  VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (tenant_id,event_id) DO NOTHING
                                  RETURNING event_id''',
                               (route['tenant_id'], event['id'], route['organization_id'], event['type'], event['created'], outcome))
                if cursor.fetchone() is None:
                    return 'duplicate'
                if update:
                    # Keys originate only in transition(), never from event JSON.
                    allowed = {'plan_tier', 'stripe_subscription_id', 'stripe_subscription_status',
                               'stripe_subscription_created', 'stripe_event_created', 'stripe_event_id',
                               'stripe_last_invoice_id', 'stripe_invoice_event_created'}
                    if not set(update).issubset(allowed):
                        raise RuntimeError('Invalid billing update columns')
                    assignments = ', '.join(f'{name}=%s' for name in update)
                    cursor.execute(f'UPDATE public.organizations SET {assignments} WHERE tenant_id=%s AND id=%s AND stripe_customer_id=%s',
                                   (*update.values(), route['tenant_id'], route['organization_id'], customer_id))
                return outcome
