"""Payment providers behind one interface. Manual is the default; Stripe turns on with two secrets.

StripeProvider is a port of CloudSaver's tested webhook logic (services/billing.py validate_event and
database/billing_store.py transition/invoice_subscription). Ownership never comes from Stripe metadata:
customers resolve through directory.customers.external_customer_refs and prices through
billing.plans.external_price_refs. No Checkout, payment or other remote Stripe request is ever made.
"""
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol

from identity.config import env
from identity.domain import IdentityError

logger = logging.getLogger('platform.identity')
HANDLED = {'customer.subscription.created', 'customer.subscription.updated',
           'customer.subscription.deleted', 'invoice.payment_succeeded'}
SECRET_NAMES = {'STRIPE_SECRET_KEY': 'platform-stripe-secret-key',
                'STRIPE_WEBHOOK_SECRET': 'platform-stripe-webhook-secret'}
TOLERANCE_SECONDS = 300


class BillingEventError(ValueError):
    pass


@dataclass
class ProviderEvent:
    id: str
    type: str
    created: int
    customer_ref: str | None
    object: dict = field(default_factory=dict)
    handled: bool = True


class BillingProvider(Protocol):
    name: str

    def configured(self) -> bool: ...

    def parse_webhook(self, body: bytes, headers: Mapping[str, str]) -> ProviderEvent: ...

    def apply(self, event: ProviderEvent, state: Mapping, prices: Mapping[str, str], default_plan: str) -> tuple[dict, str]: ...


class ManualProvider:
    """Operators record subscriptions and payments in the portal. There is no webhook."""
    name = 'manual'

    def configured(self):
        return True

    def parse_webhook(self, body, headers):
        raise IdentityError('The manual provider has no webhook.', 404)

    def apply(self, event, state, prices, default_plan):
        return {}, 'ignored_event_type'


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


def validate_event(event):
    if not isinstance(event, Mapping):
        raise BillingEventError('Invalid billing event')
    identifier(event.get('id'), 'evt_')
    integer(event.get('created'))
    data = event.get('data')
    obj = data.get('object') if isinstance(data, Mapping) else None
    if not isinstance(obj, Mapping):
        raise BillingEventError('Invalid billing event object')
    customer = identifier(obj.get('customer'), 'cus_')
    if event['type'].startswith('customer.subscription.'):
        identifier(obj.get('id'), 'sub_')
        integer(obj.get('created'))
        items = obj.get('items') or {}
        if not isinstance(items, Mapping):
            raise BillingEventError('Invalid subscription items')
        rows = items.get('data') or []
        if not isinstance(rows, list) or not all(isinstance(row, Mapping) for row in rows):
            raise BillingEventError('Invalid subscription item list')
    else:
        identifier(obj.get('id'), 'in_')
        parent = obj.get('parent') or {}
        if not isinstance(parent, Mapping) or not isinstance(parent.get('subscription_details') or {}, Mapping):
            raise BillingEventError('Invalid invoice subscription parent')
    return customer


def transition(state, event, prices, default_plan):
    """Conservative snapshot transition for one customer's Stripe subscription.

    Subscription and invoice watermarks are separate: a payment notification must not suppress a later
    subscription status update delivered out of order. Equal-second active updates are ignored; an
    equal-second cancellation of the current subscription can only remove entitlement, never add it.
    Unknown or ambiguous prices map to the default plan.
    """
    kind, created = event['type'], integer(event['created'])
    obj = event['data']['object']
    current_id = state.get('external_subscription_ref')
    current_status = state.get('status')
    if kind == 'invoice.payment_succeeded':
        subscription = invoice_subscription(obj)
        if not subscription or subscription != current_id or current_status not in ('active', 'trialing'):
            return {}, 'ignored_invoice_subscription'
        if obj.get('status') != 'paid':
            return {}, 'ignored_unpaid_invoice'
        if created <= (state.get('provider_invoice_event_created') or 0):
            return {}, 'ignored_stale_invoice'
        return {'invoice_ref': identifier(obj.get('id'), 'in_'), 'provider_invoice_event_created': created}, 'payment_recorded'

    subscription = identifier(obj.get('id'), 'sub_')
    subscription_created = integer(obj.get('created'))
    status = 'canceled' if kind == 'customer.subscription.deleted' else obj.get('status')
    if not isinstance(status, str) or len(status) > 32:
        raise BillingEventError('Invalid subscription status')
    watermark = state.get('provider_event_created') or 0
    active = status in ('active', 'trialing')
    if created < watermark:
        return {}, 'ignored_stale_subscription'
    if kind == 'customer.subscription.deleted' and current_id != subscription:
        if current_id is None:
            # Keep the chronology without assigning an untracked subscription.
            return {'provider_event_created': created}, 'ignored_untracked_deletion'
        return {}, 'ignored_other_subscription'
    if current_id and current_id != subscription:
        if not active:
            return {}, 'ignored_other_subscription'
        if created <= watermark or subscription_created <= (state.get('provider_subscription_created') or 0):
            return {}, 'ignored_older_subscription'
    elif current_id == subscription:
        if active and current_status == 'canceled':
            return {}, 'ignored_canceled_subscription'
        if created == watermark and active:
            return {}, 'ignored_tied_subscription'

    plan = default_plan
    reason = 'subscription_updated'
    if active:
        items = obj.get('items') or {}
        data = items.get('data') or []
        if not items.get('has_more') and len(data) == 1:
            try:
                price = identifier(data[0].get('price'), 'price_')
                quantity = data[0].get('quantity', 1)
                if type(quantity) is int and quantity > 0:
                    plan = prices.get(price, default_plan)
                    if price not in prices:
                        reason = 'unknown_price_default'
                else:
                    reason = 'ambiguous_price_default'
            except (BillingEventError, AttributeError):
                reason = 'unknown_price_default'
        else:
            reason = 'ambiguous_price_default'
    elif current_id == subscription:
        plan = state.get('plan_code') or default_plan
    return {
        'plan_code': plan,
        'external_subscription_ref': subscription,
        'status': status,
        'provider_subscription_created': subscription_created,
        'provider_event_created': created,
    }, reason


class StripeProvider:
    name = 'stripe'

    def __init__(self, secret_key, webhook_secret):
        self._secret_key, self._webhook_secret = secret_key or '', webhook_secret or ''

    def __repr__(self):
        return f'StripeProvider(configured={self.configured()})'

    def configured(self):
        return bool(self._secret_key and self._webhook_secret)

    def parse_webhook(self, body, headers):
        import stripe
        signature = headers.get('stripe-signature') or headers.get('Stripe-Signature') or ''
        try:
            event = stripe.Webhook.construct_event(bytes(body), signature, self._webhook_secret,
                                                   tolerance=TOLERANCE_SECONDS).to_dict()
        except (ValueError, TypeError, AttributeError, KeyError, stripe.SignatureVerificationError):
            raise BillingEventError('Invalid Stripe webhook payload or signature') from None
        kind = event.get('type') if isinstance(event, Mapping) else None
        if not isinstance(kind, str):
            raise BillingEventError('Invalid billing event type')
        if kind not in HANDLED:
            return ProviderEvent(str(event.get('id', ''))[:255], kind[:64], 0, None, {}, handled=False)
        customer = validate_event(event)
        return ProviderEvent(event['id'], kind, event['created'], customer, dict(event['data']['object']))

    def apply(self, event, state, prices, default_plan):
        return transition(state, {'id': event.id, 'type': event.type, 'created': event.created,
                                  'data': {'object': event.object}}, prices, default_plan)


def _from_key_vault(url, names):
    from azure.identity import DefaultAzureCredential
    from azure.keyvault.secrets import SecretClient
    client = SecretClient(url, DefaultAzureCredential())
    values = {}
    for name in names:
        try:
            values[name] = (client.get_secret(SECRET_NAMES[name]).value or '').strip()
        except Exception:
            logger.warning('Key Vault secret %s could not be read', SECRET_NAMES[name])
    return values


def load_provider():
    """The configured provider. Refuses to start when Stripe is switched on without both secrets."""
    name = (env('BILLING_PROVIDER', 'manual') or 'manual').strip().lower()
    if name == 'manual':
        return ManualProvider()
    if name != 'stripe':
        raise RuntimeError('PLATFORM_BILLING_PROVIDER must be manual or stripe')
    values = {key: env(key) for key in SECRET_NAMES}
    missing = [k for k, v in values.items() if not v]
    vault = env('KEYVAULT_URL')
    if missing and vault:
        values.update({k: v for k, v in _from_key_vault(vault, missing).items() if v})
        missing = [k for k, v in values.items() if not v]
    if missing:
        names = ' and '.join('PLATFORM_' + k for k in missing)
        raise RuntimeError(f'PLATFORM_BILLING_PROVIDER is stripe, but {names} is not set. Add the secret to Key Vault '
                           'or the untracked .env, or set PLATFORM_BILLING_PROVIDER=manual.')
    return StripeProvider(values['STRIPE_SECRET_KEY'], values['STRIPE_WEBHOOK_SECRET'])
