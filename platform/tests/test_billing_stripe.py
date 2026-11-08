"""Real Stripe signatures and conservative transitions at the current Platform boundary.

The removed CloudSaver local-billing router is deliberately not recreated: it returns 410.
"""
import hashlib
import hmac
import json
import time

import pytest

from identity.billing.providers import BillingEventError, HANDLED, ProviderEvent, StripeProvider, transition
from identity.billing.stripe_webhook import handle_stripe_webhook
from identity.domain import Conflict
from test_identity import TID, build, workspace

SECRET = 'whsec_unit_tests_only_not_a_deployment_secret'
PRICES = {'price_growth': 'GROWTH', 'price_enterprise': 'ENTERPRISE'}


class FakeProvider:
    """A stand-in for StripeProvider that skips signature verification and the real `stripe` SDK import
    (unavailable in this test environment), so handle_stripe_webhook's own branching can still be exercised."""
    name = 'stripe'

    def __init__(self, event):
        self._event = event

    def parse_webhook(self, body, headers):
        return self._event

    def apply(self, event, state, prices, default_plan):
        return transition(state, {'id': event.id, 'type': event.type, 'created': event.created,
                                  'data': {'object': event.object}}, prices, default_plan)


def customer_with_stripe_ref(service, ref='cus_known'):
    customer = workspace(service)
    service.store.state['customers'][customer['id']]['external_customer_refs'] = {'stripe': ref}
    return customer


def subscription(*, stamp=100, created=50, key='sub_current', status='active', price='price_growth', deleted=False):
    return {'id': 'evt_' + str(stamp), 'object': 'event', 'type': 'customer.subscription.' + ('deleted' if deleted else 'updated'),
        'created': stamp, 'data': {'object': {'id': key, 'object': 'subscription', 'created': created,
        'customer': 'cus_known', 'status': status, 'items': {'data': [{'price': {'id': price}, 'quantity': 1}], 'has_more': False}}}}


def invoice(*, stamp=200, key='sub_current', status='paid'):
    return {'id': 'evt_invoice', 'object': 'event', 'type': 'invoice.payment_succeeded', 'created': stamp,
        'data': {'object': {'id': 'in_paid', 'object': 'invoice', 'customer': 'cus_known', 'status': status,
            'parent': {'type': 'subscription_details', 'subscription_details': {'subscription': key}}}}}


def signed(body, stamp=None):
    stamp = stamp or int(time.time())
    signature = hmac.new(SECRET.encode(), str(stamp).encode() + b'.' + body, hashlib.sha256).hexdigest()
    return {'Stripe-Signature': f't={stamp},v1={signature}'}


def apply(state, event):
    return transition(state, event, PRICES, 'STARTER')


@pytest.mark.parametrize('mutation', ['missing_signature', 'tampering', 'old_signature'])
def test_actual_sdk_rejects_invalid_signatures(mutation):
    provider = StripeProvider('sk_test_offline', SECRET)
    body = json.dumps(subscription()).encode()
    headers = signed(body, int(time.time()) - 1000) if mutation == 'old_signature' else signed(body)
    if mutation == 'tampering':
        body += b' '
    if mutation == 'missing_signature':
        headers = {}
    with pytest.raises(BillingEventError):
        provider.parse_webhook(body, headers)


def test_valid_raw_body_uses_real_sdk_and_does_not_leak_secrets():
    provider = StripeProvider('sk_test_offline', SECRET)
    raw = json.dumps(subscription()).encode()
    parsed = provider.parse_webhook(raw, signed(raw))
    assert parsed.customer_ref == 'cus_known' and parsed.type == 'customer.subscription.updated'
    assert SECRET not in repr(provider)


def test_old_subscription_deletion_never_reverts_new_active():
    state, _ = apply({}, subscription(stamp=200, created=150, key='sub_new'))
    update, reason = apply(state, subscription(stamp=300, key='sub_old', deleted=True))
    assert not update and reason == 'ignored_other_subscription'


def test_untracked_deletion_preserves_only_watermark_and_blocks_older_creation():
    update, reason = apply({}, subscription(stamp=200, deleted=True))
    assert reason == 'ignored_untracked_deletion'
    assert 'plan_code' not in update and 'external_subscription_ref' not in update
    assert apply(update, subscription(stamp=100))[1] == 'ignored_stale_subscription'


def test_older_subscription_cannot_replace_newer_subscription():
    state, _ = apply({}, subscription(stamp=200, created=150, key='sub_new'))
    assert apply(state, subscription(stamp=300, created=50, key='sub_old'))[1] == 'ignored_older_subscription'


def test_equal_second_active_updates_do_not_widen_entitlements():
    state, _ = apply({}, subscription(stamp=200))
    assert apply(state, subscription(stamp=200, price='price_enterprise'))[1] == 'ignored_tied_subscription'


def test_equal_second_cancellation_removes_access_without_resurrection():
    state, _ = apply({}, subscription(stamp=200))
    cancel, _ = apply(state, subscription(stamp=200, deleted=True))
    # The commercial plan is retained; canceled state removes access in the billing projection.
    assert cancel['status'] == 'canceled' and cancel['plan_code'] == 'GROWTH'
    state.update(cancel)
    assert apply(state, subscription(stamp=201))[1] == 'ignored_canceled_subscription'


@pytest.mark.parametrize('mutation', ['unknown_price', 'multiple_prices', 'pagination', 'invalid_quantity'])
def test_unknown_or_ambiguous_prices_fail_closed(mutation):
    event = subscription()
    items = event['data']['object']['items']
    if mutation == 'unknown_price':
        items['data'][0]['price']['id'] = 'price_unknown'
    elif mutation == 'multiple_prices':
        items['data'].append({'price': {'id': 'price_enterprise'}, 'quantity': 1})
    elif mutation == 'pagination':
        items['has_more'] = True
    else:
        items['data'][0]['quantity'] = True
    assert apply({}, event)[0]['plan_code'] == 'STARTER'


def test_paid_invoice_requires_matching_active_subscription():
    state, _ = apply({}, subscription())
    update, reason = apply(state, invoice())
    assert reason == 'payment_recorded' and update['invoice_ref'] == 'in_paid'
    assert 'plan_code' not in update and 'provider_event_created' not in update
    assert apply(state, invoice(key='sub_other'))[0] == {}
    assert apply({**state, 'status': 'canceled'}, invoice())[0] == {}
    assert apply(state, invoice(status='open'))[0] == {}


def test_invoice_legacy_shape_and_ambiguous_shapes():
    state, _ = apply({}, subscription())
    event = invoice()
    event['data']['object'].pop('parent')
    event['data']['object']['subscription'] = 'sub_current'
    assert apply(state, event)[1] == 'payment_recorded'
    event = invoice()
    event['data']['object']['subscription'] = 'sub_other'
    with pytest.raises(BillingEventError):
        apply(state, event)


def test_platform_webhook_deduplicates_and_does_not_trust_customer_metadata(monkeypatch):
    provider = StripeProvider('sk_test_offline', SECRET)
    monkeypatch.setattr('identity.billing.stripe_webhook.load_provider', lambda: provider)
    service = build()
    workspace(service)
    event = subscription()
    event['data']['object']['metadata'] = {'tenant_id': 'attacker', 'customer_id': 'attacker'}
    raw = json.dumps(event).encode()
    assert handle_stripe_webhook(service, raw, signed(raw))['outcome'] == 'unknown_customer'
    assert handle_stripe_webhook(service, raw, signed(raw))['duplicate'] is True
    assert len(service.store.state['provider_events']) == 1


@pytest.mark.parametrize('event', [{}, {'id': 'evt_bad', 'type': 'customer.subscription.updated', 'created': True, 'data': {}}])
def test_signed_malformed_envelope_is_rejected(event):
    raw = json.dumps(event).encode()
    with pytest.raises(BillingEventError):
        StripeProvider('sk_test_offline', SECRET).parse_webhook(raw, signed(raw))


def test_checkout_events_are_now_handled_with_their_real_object():
    """BE-PLAT-02 regression: checkout.session.completed used to be missing from HANDLED, so parse_webhook
    returned an empty object and the plan-change metadata could never be read."""
    assert {'checkout.session.completed', 'checkout.session.async_payment_succeeded'} <= HANDLED


def pending_payment_request(service, requested='GROWTH', session_id='cs_test_1'):
    created = service.create_plan_change_request(TID, {'requested_plan_code': requested, 'requested_by': 'ops'}, 'svc')
    with service.store.transaction() as tx:
        req = tx.get_plan_change_request(created['id'])
        tx.update_plan_change_request(created['id'], req['version'], {
            'status': 'pending_payment', 'stripe_checkout_session_id': session_id, 'updated_at': service.now()})
    return created['id']


def checkout_event(request_id, *, session_id='cs_test_1', paid=True, amount=1000, evt_id='evt_checkout'):
    obj = {'id': session_id, 'metadata': {'plan_change_request_id': request_id},
           'payment_status': 'paid' if paid else 'unpaid', 'amount_total': amount}
    return ProviderEvent(evt_id, 'checkout.session.completed', 100, None, obj)


def test_checkout_completed_applies_the_pending_plan_change(monkeypatch):
    service = build()
    workspace(service)
    request_id = pending_payment_request(service)
    monkeypatch.setattr('identity.billing.stripe_webhook.load_provider', lambda: FakeProvider(checkout_event(request_id)))
    result = handle_stripe_webhook(service, b'{}', {})
    assert result['outcome'] == 'plan_change_paid'
    assert service.get_workspace(TID)['plan_tier'] == 'GROWTH'
    with service.store.transaction() as tx:
        assert tx.get_plan_change_request(request_id)['status'] == 'approved'


def test_checkout_completed_unpaid_changes_nothing():
    service = build()
    workspace(service)
    request_id = pending_payment_request(service)
    event = checkout_event(request_id, paid=False)

    class Unpaid(FakeProvider):
        def parse_webhook(self, body, headers):
            return event
    import identity.billing.stripe_webhook as mod
    original = mod.load_provider
    mod.load_provider = lambda: Unpaid(event)
    try:
        result = handle_stripe_webhook(service, b'{}', {})
    finally:
        mod.load_provider = original
    assert result['outcome'] == 'ignored_checkout_session'
    assert service.get_workspace(TID)['plan_tier'] == 'ENTERPRISE'
    with service.store.transaction() as tx:
        assert tx.get_plan_change_request(request_id)['status'] == 'pending_payment'


def test_checkout_session_id_mismatch_is_ignored():
    """BE-PLAT-02: a checkout session must match the one minted for this request, not merely carry its id
    in metadata."""
    service = build()
    workspace(service)
    request_id = pending_payment_request(service, session_id='cs_real')
    event = checkout_event(request_id, session_id='cs_forged')
    from identity.billing.stripe_webhook import complete_plan_change_from_checkout
    with service.store.transaction() as tx:
        assert complete_plan_change_from_checkout(service, tx, event.object, {'actor': 'stripe', 'actor_type': 'system'},
                                                  service.now()) is None


def test_reject_is_forbidden_once_a_checkout_is_pending_payment(monkeypatch):
    """BE-PLAT-06: an operator must not be able to reject a request that is already awaiting a Stripe
    payment, since the customer could pay after the rejection and the plan change would be lost."""
    from identity.domain import Conflict
    from test_identity import OPERATOR
    service = build()
    workspace(service)
    request_id = pending_payment_request(service)
    with service.store.transaction() as tx:
        version = tx.get_plan_change_request(request_id)['version']
    with pytest.raises(Conflict):
        service.reject_plan_change_request(request_id, {'version': version}, OPERATOR)


def test_stripe_event_does_not_overwrite_a_manual_subscription(monkeypatch):
    """BE-PLAT-05(a): Stripe must never rewrite a provider='manual' row."""
    from datetime import timedelta
    from test_identity import OPERATOR
    service = build()
    customer = customer_with_stripe_ref(service)
    service.create_customer_subscription(customer['id'], {
        'plan_code': 'GROWTH', 'status': 'active', 'current_period_start': service.now().isoformat(),
        'current_period_end': (service.now() + timedelta(days=30)).isoformat(), 'grace_days': 0,
        'amount_minor': 1000, 'currency': 'USD', 'interval': 'month'}, OPERATOR)
    event = ProviderEvent('evt_manual_guard', 'customer.subscription.updated', 100, 'cus_known',
                          {'id': 'sub_x', 'created': 50, 'customer': 'cus_known', 'status': 'active',
                           'items': {'data': [{'price': {'id': 'price_growth'}, 'quantity': 1}], 'has_more': False}})
    monkeypatch.setattr('identity.billing.stripe_webhook.load_provider', lambda: FakeProvider(event))
    result = handle_stripe_webhook(service, b'{}', {})
    assert result['outcome'] == 'ignored_manual_subscription'
    with service.store.transaction() as tx:
        sub = tx.current_subscription(customer['id'])
        assert sub['provider'] == 'manual' and sub['plan_code'] == 'GROWTH'


def test_stale_stripe_subscription_version_raises_and_rolls_back_the_event(monkeypatch):
    """BE-PLAT-05(b): a None from update_subscription (version mismatch) must not be silently accepted,
    because the event id is only durably recorded if its whole transaction (including the update) commits."""
    from uuid import uuid4
    from identity.store_memory import MemoryTx
    service = build()
    customer = customer_with_stripe_ref(service)
    now = service.now()
    sub_id = str(uuid4())
    with service.store.transaction() as tx:
        tx.insert_subscription({'id': sub_id, 'customer_id': customer['id'], 'plan_code': 'STARTER',
            'status': 'active', 'provider': 'stripe', 'external_subscription_ref': 'sub_x',
            'current_period_start': now, 'current_period_end': now, 'cancel_at_period_end': False,
            'canceled_at': None, 'amount_minor': None, 'currency': None, 'interval': None,
            'grace_days': 14, 'entitlement_overrides': None, 'notes': '',
            'created_at': now, 'created_by': 'stripe', 'updated_at': now, 'updated_by': 'stripe', 'version': 1})
    # Simulate another process winning a concurrent write between this webhook's read and its update.
    monkeypatch.setattr(MemoryTx, 'update_subscription', lambda self, *a, **k: None)
    event = ProviderEvent('evt_stale', 'customer.subscription.updated', 200, 'cus_known',
                          {'id': 'sub_x', 'created': 60, 'customer': 'cus_known', 'status': 'active',
                           'items': {'data': [{'price': {'id': 'price_enterprise'}, 'quantity': 1}], 'has_more': False}})
    monkeypatch.setattr('identity.billing.stripe_webhook.load_provider', lambda: FakeProvider(event))
    with pytest.raises(Conflict):
        handle_stripe_webhook(service, b'{}', {})
    assert service.store.state['provider_events'] == {}
    assert service.store.state['subscriptions'][sub_id]['plan_code'] == 'STARTER'


def test_stripe_event_creates_a_subscription_when_none_exists(monkeypatch):
    """BE-PLAT-05(c): when there is no local subscription at all, the webhook must create one rather than
    recording the event as applied with nothing to show for it."""
    service = build()
    customer = customer_with_stripe_ref(service)
    event = ProviderEvent('evt_create', 'customer.subscription.updated', 100, 'cus_known',
                          {'id': 'sub_new', 'created': 50, 'customer': 'cus_known', 'status': 'active',
                           'items': {'data': [{'price': {'id': 'price_growth'}, 'quantity': 1}], 'has_more': False}})
    monkeypatch.setattr('identity.billing.stripe_webhook.load_provider', lambda: FakeProvider(event))
    result = handle_stripe_webhook(service, b'{}', {})
    assert result['outcome'] in ('subscription_updated', 'unknown_price_default')
    with service.store.transaction() as tx:
        sub = tx.latest_provider_subscription(customer['id'], 'stripe')
        assert sub and sub['external_subscription_ref'] == 'sub_new'
