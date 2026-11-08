"""Stripe Checkout and webhook handling for platform billing."""
import logging

from identity.billing.providers import BillingEventError, load_provider
from identity.domain import Conflict, IdentityError, NotFound, uuid_text

logger = logging.getLogger('platform.identity')


def _stripe():
    import stripe
    provider = load_provider()
    if provider.name != 'stripe':
        raise IdentityError('Stripe is not the active billing provider.')
    stripe.api_key = provider._secret_key
    return stripe


def create_plan_change_checkout(service, tx, request_row, success_url, cancel_url):
    """Create a Checkout session for an approved plan-change awaiting payment."""
    stripe = _stripe()
    plans = {p['code']: p for p in tx.list_plans()}
    plan = plans.get(request_row['requested_plan_code'])
    if not plan:
        raise IdentityError('Choose an existing plan.')
    refs = plan.get('external_price_refs') or {}
    prices = refs.get('stripe') if isinstance(refs, dict) else None
    price_id = prices[0] if isinstance(prices, list) and prices else None
    if not price_id:
        raise IdentityError('Add a Stripe price reference to this plan before you collect payment.')
    session = stripe.checkout.Session.create(
        mode='payment',
        success_url=success_url,
        cancel_url=cancel_url,
        line_items=[{'price': price_id, 'quantity': 1}],
        metadata={
            'plan_change_request_id': str(request_row['id']),
            'tenant_id': str(request_row['tenant_id']),
            'requested_plan_code': request_row['requested_plan_code'],
        },
    )
    return session.url, session.id


def complete_plan_change_from_checkout(service, tx, session, actor, now):
    request_id = uuid_text(session['metadata']['plan_change_request_id'])
    req = tx.get_plan_change_request(request_id, lock=True)
    if not req or req['status'] != 'pending_payment':
        return None
    if req.get('stripe_checkout_session_id') and req['stripe_checkout_session_id'] != session.get('id'):
        logger.warning('Checkout session %s does not match request %s session %s; ignoring.',
                       session.get('id'), request_id, req['stripe_checkout_session_id'])
        return None
    # ponytail: amount/currency are not stored locally against the plan (only Stripe price refs);
    # a positive amount_total is a sanity floor. Add a stored plan price to compare exactly if abuse appears.
    if not isinstance(session.get('amount_total'), int) or session['amount_total'] <= 0:
        logger.warning('Checkout session %s has no positive amount_total; ignoring.', session.get('id'))
        return None
    workspace = tx.get_workspace(req['tenant_id'], lock=True)
    if not workspace or workspace['status'] == 'deleted':
        raise NotFound('Workspace not found.')
    customer_id = workspace['customer_id']
    sub = tx.current_subscription(customer_id)
    if sub and sub['provider'] == 'manual' and sub['plan_code'] != req['requested_plan_code']:
        if tx.update_subscription(sub['id'], sub['version'], {
                'plan_code': req['requested_plan_code'], 'updated_at': now, 'updated_by': actor['actor'][:120]}) is None:
            raise Conflict('Subscription changed while payment completed. Reload and review.')
        service._refresh_customer_billing(tx, customer_id, now)
        service._apply_subscription_plan(tx, customer_id, req['requested_plan_code'], actor, now)
        service._sync_customer_entitlements(tx, customer_id, actor, now)
    else:
        row = tx.update_workspace(workspace['tenant_id'], workspace['version'], {
            'plan_tier': req['requested_plan_code'], 'updated_at': now, 'updated_by': actor['actor'][:120]})
        if row is None:
            raise Conflict('Workspace changed while payment completed. Reload and review.')
        customer = tx.get_customer(row['customer_id'])
        service._changed(tx, row, customer)
    tx.update_plan_change_request(request_id, req['version'], {
        'status': 'approved', 'reviewed_by': actor['actor'][:120], 'updated_at': now,
        'stripe_checkout_session_id': session.get('id')})
    return request_id


def handle_stripe_webhook(service, body, headers, request_id=None):
    provider = load_provider()
    if provider.name != 'stripe':
        raise IdentityError('Stripe is not the active billing provider.', 404)
    try:
        event = provider.parse_webhook(body, headers)
    except BillingEventError as exc:
        raise IdentityError(str(exc), 400) from None
    now = service.now()
    actor = {'actor': 'stripe', 'actor_type': 'system'}
    if event.type in ('checkout.session.completed', 'checkout.session.async_payment_succeeded'):
        # Checkout sessions are a different object shape than the subscription/invoice events below
        # (no subscription items, no 'in_'/'sub_' id) and are never passed to provider.apply/transition.
        with service.store.transaction() as tx:
            if tx.provider_event('stripe', event.id):
                return {'received': True, 'duplicate': True}
            session = event.object
            if session.get('metadata', {}).get('plan_change_request_id') and session.get('payment_status') == 'paid':
                result = complete_plan_change_from_checkout(service, tx, session, actor, now)
                outcome = 'plan_change_paid' if result else 'plan_change_paid_but_not_applied'
                if not result:
                    logger.error('Stripe checkout %s was paid but the plan change could not be applied: '
                                 'request %s is no longer pending payment or the workspace changed concurrently.',
                                 session.get('id'), session.get('metadata', {}).get('plan_change_request_id'))
            else:
                outcome = 'ignored_checkout_session'
            tx.insert_provider_event({'provider': 'stripe', 'event_id': event.id, 'event_type': event.type,
                                      'event_created': event.created, 'customer_id': None, 'outcome': outcome})
            service._publish([{'directory': True, 'event': 'directory_changed'}], tx)
            return {'received': True, 'outcome': outcome}
    with service.store.transaction() as tx:
        if tx.provider_event('stripe', event.id):
            return {'received': True, 'duplicate': True}
        if not event.handled:
            tx.insert_provider_event({'provider': 'stripe', 'event_id': event.id, 'event_type': event.type,
                                      'event_created': event.created, 'customer_id': None, 'outcome': 'ignored'})
            return {'received': True, 'outcome': 'ignored'}
        customer_ref = event.customer_ref
        customer = tx.customer_by_external_ref('stripe', customer_ref) if customer_ref else None
        if not customer:
            tx.insert_provider_event({'provider': 'stripe', 'event_id': event.id, 'event_type': event.type,
                                      'event_created': event.created, 'customer_id': None, 'outcome': 'unknown_customer'})
            return {'received': True, 'outcome': 'unknown_customer'}
        settings = tx.get_billing_settings()
        prices = {}
        for plan in tx.list_plans():
            refs = plan.get('external_price_refs') or {}
            for price in refs.get('stripe') or []:
                prices[price] = plan['code']
        sub = tx.latest_provider_subscription(customer['id'], 'stripe')
        local_current = tx.current_subscription(customer['id'])
        if local_current and local_current.get('provider') == 'manual' and not sub:
            # A manual subscription is authoritative until an operator replaces it; Stripe does not overwrite it.
            logger.warning('Ignoring Stripe event %s for customer %s: a manual subscription is active.',
                           event.id, customer['id'])
            tx.insert_provider_event({'provider': 'stripe', 'event_id': event.id, 'event_type': event.type,
                                      'event_created': event.created, 'customer_id': customer['id'],
                                      'outcome': 'ignored_manual_subscription'})
            return {'received': True, 'outcome': 'ignored_manual_subscription'}
        state = {}
        if sub:
            state = {
                'external_subscription_ref': sub.get('external_subscription_ref'),
                'status': sub['status'],
                'plan_code': sub['plan_code'],
                'provider_event_created': tx.max_provider_event_created(customer['id'], 'stripe'),
                'provider_subscription_created': 0,
                'provider_invoice_event_created': 0,
            }
        update, outcome = provider.apply(event, state, prices, settings['default_plan_code'])
        if not tx.insert_provider_event({'provider': 'stripe', 'event_id': event.id, 'event_type': event.type,
                                         'event_created': event.created, 'customer_id': customer['id'], 'outcome': outcome}):
            return {'received': True, 'duplicate': True}
        if not update:
            return {'received': True, 'outcome': outcome}
        if sub:
            fields = {k: v for k, v in update.items() if k in ('plan_code', 'status', 'external_subscription_ref')}
            if fields and tx.update_subscription(sub['id'], sub['version'], dict(fields, updated_at=now, updated_by='stripe')) is None:
                raise Conflict('Subscription changed while applying the Stripe event. Retry the webhook.')
        else:
            from datetime import timedelta
            from uuid import uuid4
            # Stripe's subscription events don't carry the current period in the fields transition() extracts;
            # a placeholder 30-day period keeps billing_state() well-defined until the next invoice event updates it.
            tx.insert_subscription({
                'id': str(uuid4()), 'customer_id': customer['id'], 'plan_code': update.get('plan_code', settings['default_plan_code']),
                'status': update.get('status', 'active'), 'provider': 'stripe',
                'external_subscription_ref': update.get('external_subscription_ref'),
                'current_period_start': now, 'current_period_end': now + timedelta(days=30), 'cancel_at_period_end': False,
                'canceled_at': None, 'amount_minor': None, 'currency': None, 'interval': None,
                'grace_days': int(settings['default_grace_days']), 'entitlement_overrides': None, 'notes': '',
                'created_at': now, 'created_by': 'stripe', 'updated_at': now, 'updated_by': 'stripe', 'version': 1})
        service._refresh_customer_billing(tx, customer['id'], now)
        service._sync_customer_entitlements(tx, customer['id'], actor, now)
        service._event(tx, actor, 'provider_event_applied', details={'event_id': event.id, 'outcome': outcome}, request_id=request_id)
        service._publish([{'directory': True, 'event': 'directory_changed'}], tx)
    return {'received': True, 'outcome': outcome}
