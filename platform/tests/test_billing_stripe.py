"""Real Stripe signatures and conservative transitions at the current Platform boundary.

The removed CloudSaver local-billing router is deliberately not recreated: it returns 410.
"""
import hashlib
import hmac
import json
import time

import pytest

from identity.billing.providers import BillingEventError, StripeProvider, transition
from identity.billing.stripe_webhook import handle_stripe_webhook
from test_identity import build, workspace

SECRET = 'whsec_unit_tests_only_not_a_deployment_secret'
PRICES = {'price_growth': 'GROWTH', 'price_enterprise': 'ENTERPRISE'}


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
