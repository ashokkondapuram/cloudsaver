"""Real Stripe SDK signature checks, deterministic transition and retry tests.

Persistence protocol is faked here; PostgreSQL transaction/RLS integration is
not claimed by this suite.
"""
import copy
import hashlib
import hmac
import json
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from database.billing_store import BillingEventError, BillingProvisioningError, BillingStore, transition
from services.billing import MAX_BODY, billing_router

SECRET = 'whsec_unit_tests_only_not_a_deployment_secret'
ROUTE = {'tenant_id': '11111111-1111-4111-8111-111111111111',
         'organization_id': '55555555-5555-4555-8555-555555555555'}
TIERS = {'price_growth': 'GROWTH', 'price_enterprise': 'ENTERPRISE'}


def subscription(event_id='evt_create', *, timestamp=100, subscription_id='sub_current',
                 subscription_created=50, status='active', price='price_growth', kind='customer.subscription.created'):
    return {'id': event_id, 'object': 'event', 'type': kind, 'created': timestamp,
            'data': {'object': {'id': subscription_id, 'object': 'subscription', 'created': subscription_created,
                                'customer': 'cus_known', 'status': status,
                                'items': {'data': [{'price': {'id': price}, 'quantity': 1}], 'has_more': False}}}}


def invoice(event_id='evt_invoice', *, timestamp=200, subscription_id='sub_current'):
    return {'id': event_id, 'object': 'event', 'type': 'invoice.payment_succeeded', 'created': timestamp,
            'data': {'object': {'id': 'in_paid', 'object': 'invoice', 'customer': 'cus_known', 'status': 'paid',
                                'parent': {'type': 'subscription_details', 'subscription_details': {'subscription': subscription_id}}}}}


def signed(body, timestamp=None):
    timestamp = timestamp or int(time.time())
    signature = hmac.new(SECRET.encode(), str(timestamp).encode() + b'.' + body, hashlib.sha256).hexdigest()
    return {'Stripe-Signature': f't={timestamp},v1={signature}', 'Content-Type': 'application/json'}


class MemoryStore:
    def __init__(self):
        self.events = set()
        self.state = {'plan_tier': 'STARTER', 'stripe_event_created': 0, 'stripe_subscription_created': 0}
        self.calls = []

    def apply_event(self, route, customer_id, event, tiers):
        self.calls.append((route, customer_id))
        assert route == ROUTE
        assert customer_id == 'cus_known'
        key = (route['tenant_id'], event['id'])
        if key in self.events:
            return 'duplicate'
        update, outcome = transition(self.state, event, tiers)
        self.state.update(update)
        self.events.add(key)
        return outcome


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv('STRIPE_WEBHOOK_SECRET', SECRET)
    monkeypatch.setenv('CLOUDSAVER_STRIPE_CUSTOMERS', json.dumps({'cus_known': ROUTE}))
    monkeypatch.setenv('STRIPE_PRICE_TIERS', json.dumps(TIERS))


def client(store):
    app = FastAPI()
    app.include_router(billing_router(store))
    return TestClient(app)


def deliver(client, event):
    raw = json.dumps(event, separators=(',', ':')).encode()
    return client.post('/api/v1/billing/webhook', content=raw, headers=signed(raw))


def test_actual_sdk_signature_required(configured):
    store = MemoryStore()
    response = client(store).post('/api/v1/billing/webhook', json=subscription())
    assert response.status_code == 400
    assert store.calls == []


def test_raw_body_tampering_is_rejected(configured):
    raw = json.dumps(subscription()).encode()
    store = MemoryStore()
    response = client(store).post('/api/v1/billing/webhook', content=raw + b' ', headers=signed(raw))
    assert response.status_code == 400
    assert store.calls == []


def test_real_signed_event_updates_only_configured_owner_and_deduplicates(configured):
    store = MemoryStore()
    api = client(store)
    event = subscription()
    event['data']['object']['metadata'] = {'tenant_id': 'attacker', 'organization_id': 'attacker'}
    assert deliver(api, event).status_code == 200
    assert store.state['plan_tier'] == 'GROWTH'
    response = deliver(api, event)
    assert response.json()['outcome'] == 'duplicate'
    assert len(store.events) == 1


def test_unmapped_customer_does_not_route_by_metadata(configured):
    store = MemoryStore()
    event = subscription()
    event['data']['object']['customer'] = 'cus_unknown'
    event['data']['object']['metadata'] = ROUTE
    assert deliver(client(store), event).status_code == 400
    assert not store.calls


def test_stale_events_cannot_downgrade_newer_subscription(configured):
    store = MemoryStore()
    api = client(store)
    assert deliver(api, subscription(timestamp=200, subscription_created=150, subscription_id='sub_new', price='price_enterprise')).status_code == 200
    result = deliver(api, subscription('evt_old_delete', timestamp=100, subscription_id='sub_old', kind='customer.subscription.deleted'))
    assert result.json()['outcome'] == 'ignored_stale_subscription'
    assert store.state['plan_tier'] == 'ENTERPRISE'


def test_old_subscription_deletion_does_not_revert_new_active_even_with_later_event():
    state, _ = transition({}, subscription(timestamp=200, subscription_created=150, subscription_id='sub_new'), TIERS)
    update, outcome = transition(state, subscription(timestamp=300, kind='customer.subscription.deleted', subscription_id='sub_old'), TIERS)
    assert outcome == 'ignored_other_subscription'
    assert not update


def test_untracked_deletion_never_assigns_subscription_and_blocks_stale_creation():
    state = {'plan_tier': 'STARTER'}
    update, reason = transition(state, subscription(timestamp=200, kind='customer.subscription.deleted'), TIERS)
    assert reason == 'ignored_untracked_deletion'
    assert 'stripe_subscription_id' not in update
    assert 'plan_tier' not in update
    state.update(update)
    assert transition(state, subscription(timestamp=100), TIERS)[1] == 'ignored_stale_subscription'


def test_old_subscription_update_cannot_replace_newer_subscription():
    state, _ = transition({}, subscription(timestamp=200, subscription_created=150, subscription_id='sub_new'), TIERS)
    update, outcome = transition(state, subscription(timestamp=300, subscription_created=50, subscription_id='sub_old'), TIERS)
    assert not update
    assert outcome == 'ignored_older_subscription'


def test_equal_second_current_cancellation_only_removes_entitlement():
    state, _ = transition({}, subscription(timestamp=200), TIERS)
    canceled, _ = transition(state, subscription(timestamp=200, kind='customer.subscription.deleted'), TIERS)
    assert canceled['plan_tier'] == 'STARTER'
    state.update(canceled)
    update, reason = transition(state, subscription(timestamp=201), TIERS)
    assert not update
    assert reason == 'ignored_canceled_subscription'


def test_equal_second_active_updates_are_not_arbitrarily_applied():
    state, _ = transition({}, subscription(timestamp=200), TIERS)
    update, reason = transition(state, subscription(timestamp=200, price='price_enterprise'), TIERS)
    assert not update
    assert reason == 'ignored_tied_subscription'


def test_unknown_or_multiple_prices_fail_closed_to_starter():
    state, _ = transition({}, subscription(timestamp=100), TIERS)
    update, reason = transition(state, subscription(timestamp=200, price='price_unknown'), TIERS)
    assert update['plan_tier'] == 'STARTER'
    assert reason == 'unknown_price_starter'
    event = subscription(timestamp=200)
    event['data']['object']['items']['data'].append({'price': {'id': 'price_enterprise'}})
    assert transition(state, event, TIERS)[0]['plan_tier'] == 'STARTER'


def test_paid_invoice_records_matching_active_subscription_without_resurrection():
    state, _ = transition({}, subscription(), TIERS)
    update, reason = transition(state, invoice(), TIERS)
    assert reason == 'payment_recorded'
    assert update['stripe_last_invoice_id'] == 'in_paid'
    assert 'plan_tier' not in update
    assert 'stripe_event_created' not in update
    state['stripe_subscription_status'] = 'canceled'
    assert transition(state, invoice(), TIERS)[0] == {}


def test_invoice_legacy_and_current_subscription_shapes_and_ambiguity():
    state, _ = transition({}, subscription(), TIERS)
    legacy = invoice()
    legacy['data']['object'].pop('parent')
    legacy['data']['object']['subscription'] = 'sub_current'
    assert transition(state, legacy, TIERS)[1] == 'payment_recorded'
    ambiguous = invoice()
    ambiguous['data']['object']['subscription'] = 'sub_different'
    with pytest.raises(BillingEventError):
        transition(state, ambiguous, TIERS)


def test_persistence_failure_requests_retry(configured):
    class BrokenStore:
        def apply_event(self, *args):
            raise BillingProvisioningError('database detail must not leak')
    result = deliver(client(BrokenStore()), subscription())
    assert result.status_code == 503
    assert 'database detail' not in result.text


def test_disabled_webhook_fails_closed(monkeypatch):
    monkeypatch.delenv('STRIPE_WEBHOOK_SECRET', raising=False)
    assert deliver(client(MemoryStore()), subscription()).status_code == 503


def test_oversized_body_rejected_before_signature(configured):
    result = client(MemoryStore()).post('/api/v1/billing/webhook', content=b'x' * (MAX_BODY + 1))
    assert result.status_code == 413


def test_old_signature_rejected(configured):
    raw = json.dumps(subscription()).encode()
    result = client(MemoryStore()).post('/api/v1/billing/webhook', content=raw, headers=signed(raw, int(time.time()) - 600))
    assert result.status_code == 400


@pytest.mark.parametrize('event', [[], {'type': []}, {'type': 'customer.subscription.created', 'data': []},
                                  {'type': 'invoice.payment_succeeded', 'data': {'object': {'parent': []}}}])
def test_signed_malformed_envelopes_rejected(configured, event):
    store = MemoryStore()
    assert deliver(client(store), event).status_code == 400
    assert not store.calls


def test_signed_invoice_bad_parent_rejected_before_persistence(configured):
    event = invoice()
    event['data']['object']['parent'] = ['bad-parent']
    store = MemoryStore()
    assert deliver(client(store), event).status_code == 400
    assert not store.calls


@pytest.mark.parametrize('superuser,bypass', [(True, False), (False, True)])
def test_billing_refuses_database_roles_that_bypass_tenant_isolation(monkeypatch, superuser, bypass):
    import psycopg
    queries = []

    class Cursor:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def execute(self, sql, *params):
            queries.append(sql)
        def fetchone(self):
            return {'rolsuper': superuser, 'rolbypassrls': bypass}

    class Connection:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def cursor(self):
            return Cursor()

    monkeypatch.setattr('database.billing_store.pooled_connect', lambda *args, **kwargs: Connection())
    with pytest.raises(BillingProvisioningError, match='non-superuser'):
        BillingStore('postgresql://test@localhost/test').apply_event(ROUTE, 'cus_known', subscription(), TIERS)
    assert len(queries) == 1
