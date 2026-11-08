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


def tight_plan(service, code, **limit):
    """A plan whose entitlements copy STARTER's except for the one platform limit under test, set to 1."""
    from identity.billing.catalog import SEED_PLANS
    entitlements = dict(next(p for p in SEED_PLANS if p['code'] == 'STARTER')['entitlements'])
    entitlements.update(limit)
    return service.create_plan({'code': code, 'name': code.title(), 'entitlements': entitlements}, OPERATOR)


def test_max_workspaces_entitlement_is_enforced():
    """BE-PLAT-03: create_workspace had no count check at all; a plan's max_workspaces must be enforced."""
    service = build()
    tight_plan(service, 'ONEWS', max_workspaces=1)
    customer = service.create_customer({'name': 'One workspace customer'}, OPERATOR)
    service.create_workspace({'tenant_id': TID, 'customer_id': customer['id'], 'name': 'First',
                              'plan_tier': 'ONEWS'}, OPERATOR)
    with pytest.raises(Conflict, match='maximum of 1 workspaces'):
        service.create_workspace({'tenant_id': '22222222-2222-4222-8222-222222222222', 'customer_id': customer['id'],
                                  'name': 'Second', 'plan_tier': 'ONEWS'}, OPERATOR)


def test_max_active_keys_per_workspace_entitlement_is_enforced(monkeypatch):
    """BE-PLAT-03: issuance used the hard-coded MAX_ACTIVE_KEYS=20 constant instead of the plan's
    max_active_keys_per_workspace entitlement."""
    service = build(clock=Clock())
    tight_plan(service, 'ONEKEY', max_active_keys_per_workspace=1)
    customer = service.create_customer({'name': 'One key customer'}, OPERATOR)
    service.create_workspace({'tenant_id': TID, 'customer_id': customer['id'], 'name': 'Workspace',
                              'plan_tier': 'ONEKEY'}, OPERATOR)
    payload = {'name': 'First key', 'roles': ['Viewer'], 'all_providers': True,
               'expires_at': (service.now() + timedelta(days=10)).isoformat()}
    service.issue_key(TID, payload, OPERATOR)
    with pytest.raises(Conflict, match='at most 1 active keys'):
        service.issue_key(TID, dict(payload, name='Second key'), OPERATOR)


def test_max_key_lifetime_days_entitlement_is_enforced():
    """BE-PLAT-03: expiry used the hard-coded MAX_EXPIRY_DAYS=365 constant instead of the plan's
    max_key_lifetime_days entitlement."""
    service = build(clock=Clock())
    tight_plan(service, 'SHORTLIFE', max_key_lifetime_days=1)
    customer = service.create_customer({'name': 'Short lifetime customer'}, OPERATOR)
    service.create_workspace({'tenant_id': TID, 'customer_id': customer['id'], 'name': 'Workspace',
                              'plan_tier': 'SHORTLIFE'}, OPERATOR)
    with pytest.raises(IdentityError, match='most 1 days'):
        service.issue_key(TID, {'name': 'Too long', 'roles': ['Viewer'], 'all_providers': True,
                                'expires_at': (service.now() + timedelta(days=10)).isoformat()}, OPERATOR)
    service.issue_key(TID, {'name': 'Fine', 'roles': ['Viewer'], 'all_providers': True,
                            'expires_at': (service.now() + timedelta(hours=12)).isoformat()}, OPERATOR)


def test_billing_customer_pagination_finds_lapsed_customers_scattered_through_the_list(monkeypatch):
    """BE-PLAT-08: the old implementation fetched limit+50 rows, filtered in Python, and only returned
    next_cursor if more than `limit` rows survived the filter -- so a lapsed customer past the first
    over-fetched batch was never reachable."""
    monkeypatch.setenv('PLATFORM_BILLING_ENABLED', 'true')
    service = build()
    lapsed_at = {80, 150, 220}
    for i in range(300):
        customer = service.create_customer({'name': f'Customer {i:04d}'}, OPERATOR)
        if i in lapsed_at:
            service.store.state['customers'][customer['id']]['billing_state'] = 'lapsed'
    found = []
    cursor = None
    for _ in range(20):
        page = service.list_billing_customers(billing_state='lapsed', cursor=cursor, limit=10)
        found += page['items']
        cursor = page['next_cursor']
        if not cursor:
            break
    assert len(found) == len(lapsed_at)
    assert len({row['customer_id'] for row in found}) == len(lapsed_at)
