"""Stripe snapshot webhook, with raw-byte signature verification.

Protocol references: https://docs.stripe.com/webhooks and
https://docs.stripe.com/api/invoices/object . No checkout or payment is created.
"""
import json
import os
from collections.abc import Mapping
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from database.billing_store import BillingEventError, BillingStore, identifier, integer

MAX_BODY = 1024 * 1024
HANDLED = {'customer.subscription.created', 'customer.subscription.updated',
           'customer.subscription.deleted', 'invoice.payment_succeeded'}


def configuration():
    try:
        customers = json.loads(os.environ['CLOUDSAVER_STRIPE_CUSTOMERS'])
        tiers = json.loads(os.environ['STRIPE_PRICE_TIERS'])
        if not isinstance(customers, dict) or not isinstance(tiers, dict) or not tiers:
            raise ValueError
        result, owners = {}, set()
        for customer, route in customers.items():
            identifier(customer, 'cus_')
            owner = (str(UUID(route['tenant_id'])), str(UUID(route['organization_id'])))
            if owner in owners:
                raise ValueError
            owners.add(owner)
            result[customer] = dict(tenant_id=owner[0], organization_id=owner[1])
        for price, tier in tiers.items():
            identifier(price, 'price_')
            if tier not in ('STARTER', 'GROWTH', 'ENTERPRISE'):
                raise ValueError
        return result, tiers
    except (KeyError, TypeError, ValueError, AttributeError):
        raise HTTPException(503, 'Billing customer and price mapping configuration is unavailable') from None


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


def billing_router(store=None):
    router = APIRouter()

    @router.post('/api/v1/billing/webhook')
    async def stripe_webhook(request: Request):
        secret = os.getenv('STRIPE_WEBHOOK_SECRET', '')
        if not secret:
            raise HTTPException(503, 'Stripe webhook verification is not configured')
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > MAX_BODY:
                raise HTTPException(413, 'Webhook body exceeds the 1 MiB limit')
            body.extend(chunk)
        try:
            import stripe
        except ImportError:
            raise HTTPException(503, 'Stripe webhook verification is unavailable') from None
        try:
            event = stripe.Webhook.construct_event(bytes(body), request.headers.get('stripe-signature', ''),
                                                   secret, tolerance=300)
            event = event.to_dict()
        except (ValueError, TypeError, AttributeError, KeyError, stripe.SignatureVerificationError):
            raise HTTPException(400, 'Invalid Stripe webhook payload or signature') from None
        kind = event.get('type')
        if not isinstance(kind, str):
            raise HTTPException(400, 'Invalid billing event type')
        if kind not in HANDLED:
            return {'received': True, 'outcome': 'ignored_event_type'}
        try:
            customer = validate_event(event)
        except BillingEventError:
            raise HTTPException(400, 'Invalid billing event data') from None
        customers, tiers = configuration()
        route = customers.get(customer)
        if route is None:
            raise HTTPException(400, 'Billing customer is not provisioned')
        try:
            persistence = store or BillingStore(os.getenv('CLOUDSAVER_DATABASE_URL', ''))
            outcome = await run_in_threadpool(persistence.apply_event, route, customer, event, tiers)
        except BillingEventError:
            raise HTTPException(400, 'Invalid billing event data') from None
        except Exception:
            # Stripe retries non-2xx deliveries; do not acknowledge a lost write.
            raise HTTPException(503, 'Billing persistence unavailable; retry this event') from None
        return {'received': True, 'outcome': outcome}

    return router
