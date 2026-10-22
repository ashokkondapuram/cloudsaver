"""
Tests for Stripe Checkout and Tier Entitlement enforcement.
"""
import unittest
from fastapi import HTTPException
from app.entitlements import (
    get_tier_entitlements, enforce_subscription_quota,
    enforce_terraform_export, enforce_keyvault_access,
    create_checkout_session, PlanTier
)

class TestEntitlements(unittest.TestCase):
    def test_starter_tier_limits(self):
        starter = get_tier_entitlements("STARTER")
        self.assertEqual(starter.max_subscriptions, 2)
        self.assertFalse(starter.can_export_terraform)
        self.assertFalse(starter.can_use_keyvault)

    def test_subscription_quota_enforcement(self):
        enforce_subscription_quota("STARTER", current_count=1, adding_count=1)
        with self.assertRaises(HTTPException) as ctx:
            enforce_subscription_quota("STARTER", current_count=2, adding_count=1)
        self.assertEqual(ctx.exception.status_code, 402)

    def test_terraform_export_restricted_on_starter(self):
        with self.assertRaises(HTTPException) as ctx:
            enforce_terraform_export("STARTER")
        self.assertEqual(ctx.exception.status_code, 403)
        enforce_terraform_export("GROWTH") # Allowed on Growth

    def test_keyvault_restricted_on_growth(self):
        with self.assertRaises(HTTPException) as ctx:
            enforce_keyvault_access("GROWTH")
        self.assertEqual(ctx.exception.status_code, 403)
        enforce_keyvault_access("ENTERPRISE") # Allowed on Enterprise

    def test_unconfigured_checkout_never_returns_synthetic_url(self):
        with self.assertRaises(HTTPException) as ctx:
            create_checkout_session("GROWTH", "tenant-1", "org-1", idempotency_key="test-checkout-key")
        self.assertEqual(ctx.exception.status_code, 503)

if __name__ == '__main__':
    unittest.main()


def test_checkout_uses_trusted_customer_price_and_idempotency(monkeypatch):
    import json
    from types import SimpleNamespace
    import app.entitlements as module
    tenant = '11111111-1111-4111-8111-111111111111'
    org = '33333333-3333-4333-8333-333333333333'
    monkeypatch.setenv('STRIPE_SECRET_KEY', 'test-placeholder')
    monkeypatch.setenv('CLOUDSAVER_BILLING_RETURN_URL', 'https://app.example/billing')
    monkeypatch.setenv('CLOUDSAVER_STRIPE_CUSTOMERS', json.dumps({'cus_known':dict(tenant_id=tenant, organization_id=org)}))
    monkeypatch.setenv('STRIPE_PRICE_TIERS', json.dumps({'price_growth':'GROWTH'}))
    verified, calls = [], []
    monkeypatch.setattr(module, '_verify_customer', lambda route, customer: verified.append((route, customer)))
    def checkout(key, params, idempotency):
        calls.append((params,idempotency))
        return SimpleNamespace(id='cs_test_real_stub', url='https://checkout.stripe.com/c/pay/stub')
    monkeypatch.setattr(module, '_stripe_checkout', checkout)
    for _ in range(2):
        response = module.create_checkout_session('GROWTH',tenant,org,idempotency_key='checkout-retry-key')
        assert response['session_id'] == 'cs_test_real_stub'
    assert calls[0] == calls[1]
    assert calls[0][0]['customer'] == 'cus_known' and calls[0][0]['client_reference_id'] == org
    assert calls[0][0]['line_items'] == [dict(price='price_growth',quantity=1)]
    assert len(verified) == 2
    with __import__('pytest').raises(HTTPException):
        module.create_checkout_session('GROWTH',tenant,org,success_url='https://evil.example',idempotency_key='checkout-key-123')
