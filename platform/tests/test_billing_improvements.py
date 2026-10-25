from datetime import timedelta
import copy

import pytest

from identity.billing.importer import amount_minor, import_billing
from identity.domain import IdentityError, Conflict
from test_identity import build, workspace, TID, OPERATOR, Clock


@pytest.mark.parametrize('value', [1.25, True, 'NaN', '1e2', '1.001', '-1', '01.00'])
def test_importer_rejects_inexact_amounts(value):
    with pytest.raises(IdentityError):
        amount_minor(value, 'USD')


def test_currency_minor_units_are_explicit():
    assert amount_minor('12.34', 'USD') == 1234
    assert amount_minor('12', 'JPY') == 12
    assert amount_minor('12.345', 'KWD') == 12345


def test_import_is_atomic_and_idempotent():
    service = build()
    workspace(service)
    export = {'version': 1, 'organizations': [{'tenant_id': TID, 'plan_tier': 'GROWTH',
        'stripe_customer_id': 'cus_example', 'stripe_subscription_id': 'sub_example', 'subscription_status': 'active'}],
        'stripe_events': [{'tenant_id': TID, 'event_id': 'evt_example', 'event_type': 'invoice.payment_succeeded',
                           'created_at': service.now().isoformat()}]}
    terms = {TID: {'amount': '149.00', 'currency': 'USD', 'interval': 'month',
        'current_period_start': service.now().isoformat(), 'current_period_end': (service.now() + timedelta(days=30)).isoformat()}}
    with pytest.raises(IdentityError, match='explicit'):
        import_billing(service, export)
    assert import_billing(service, export, terms=terms)['changed'] == 3
    assert import_billing(service, export, terms=terms)['changed'] == 0
    before = copy.deepcopy(service.store.state)
    for field, value in [('interval', 'year'), ('grace_days', 1)]:
        different_terms = copy.deepcopy(terms)
        different_terms[TID][field] = value
        with pytest.raises(Conflict):
            import_billing(service, export, terms=different_terms)
        assert service.store.state == before
    different_status = copy.deepcopy(export)
    different_status['organizations'][0]['subscription_status'] = 'canceled'
    with pytest.raises(Conflict):
        import_billing(service, different_status, terms=terms)
    assert service.store.state == before
    conflict = copy.deepcopy(export)
    conflict['organizations'][0]['stripe_customer_id'] = 'cus_different'
    with pytest.raises(Conflict):
        import_billing(service, conflict, terms=terms)
    assert service.store.state == before


def test_missing_event_ownership_cannot_be_inferred():
    service = build()
    workspace(service)
    export = {'version': 1, 'organizations': [],
              'stripe_events': [{'event_id': 'evt_unknown', 'created_at': service.now().isoformat()}]}
    with pytest.raises(IdentityError):
        import_billing(service, export)


def test_billing_lapse_updates_projection_once_and_keeps_commercial_plan(monkeypatch):
    monkeypatch.setenv('PLATFORM_BILLING_ENABLED', 'true')
    clock = Clock()
    service = build(clock=clock)
    customer = workspace(service)
    sub = service.create_customer_subscription(customer['id'], {
        'plan_code': 'GROWTH', 'status': 'active', 'current_period_start': clock().isoformat(),
        'current_period_end': (clock() + timedelta(days=1)).isoformat(), 'grace_days': 0,
        'amount_minor': 14900, 'currency': 'USD', 'interval': 'month'}, OPERATOR)
    clock.value += timedelta(days=2)
    assert service.evaluate_billing()['changed'] == 1
    assert service.evaluate_billing()['changed'] == 0
    with service.store.transaction() as tx:
        assert tx.get_customer(customer['id'])['billing_state'] == 'lapsed'
        assert tx.get_workspace(TID)['plan_tier'] == 'STARTER'
        assert tx.get_subscription(sub['id'])['plan_code'] == 'GROWTH'
    assert any(e['event'] == 'entitlements_changed' for e in service.store.state['cache_events'])


def test_customer_billing_list_uses_default_plan_without_a_subscription():
    service=build();customer=workspace(service)
    result=service.list_billing_customers()
    assert any(row['customer_id']==customer['id'] for row in result['items'])
