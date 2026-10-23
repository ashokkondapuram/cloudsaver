"""CloudSaver 1.3.0 no longer sells plans or takes Stripe webhooks; billing lives in the platform."""
import hashlib
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app as scanner
from services.gateway import create_app as gateway
from services.tenant import create_app as tenant_service

ROOT = Path(__file__).resolve().parents[1]
TID = '11111111-1111-4111-8111-111111111111'
SID = '33333333-3333-4333-8333-333333333333'
KEY = 'billing-removed-workspace-key-32-characters'
CHECKOUT = 'Plan changes are handled by your account manager.'
WEBHOOK = 'Billing webhooks are handled by the platform.'


class Limiter:
    async def check(self, tenant_id):
        return None


@pytest.fixture
def settings(tmp_path):
    return Settings('azure', str(tmp_path / 'billing.sqlite3'), (
        dict(tenant_id=TID, name='Billing', subscription_ids=[SID], plan_tier='GROWTH',
             api_key_sha256=hashlib.sha256(KEY.encode()).hexdigest()),))


def offline(request):
    raise AssertionError('Removed billing routes must not call upstream services')


@pytest.mark.parametrize('app', ['gateway', 'scanner'])
def test_checkout_returns_gone_with_or_without_a_key(settings, app):
    built = gateway(settings, Limiter(), httpx.MockTransport(offline)) if app == 'gateway' else scanner(settings)
    client = TestClient(built)
    for headers in ({}, {'Authorization': 'Bearer ' + KEY}):
        response = client.post('/api/v1/billing/checkout', headers=headers,
                               json={'target_tier': 'GROWTH', 'idempotency_key': 'test-key-12345678'})
        assert response.status_code == 410 and response.json()['detail'] == CHECKOUT


@pytest.mark.parametrize('app', ['gateway', 'tenant'])
def test_webhook_returns_gone_for_any_payload(settings, app):
    built = gateway(settings, Limiter(), httpx.MockTransport(offline)) if app == 'gateway' else tenant_service(settings)
    client = TestClient(built)
    for content in (b'{"type": "invoice.paid"}', b'x' * 2_000_000, b''):
        response = client.post('/api/v1/billing/webhook', content=content, headers={'Stripe-Signature': 't=1,v1=x'})
        assert response.status_code == 410 and response.json()['detail'] == WEBHOOK


def test_entitlements_no_longer_offer_checkout(settings):
    data = TestClient(scanner(settings)).get('/api/v1/billing/entitlements', headers={'Authorization': 'Bearer ' + KEY}).json()
    assert 'checkout_available' not in data and data['manage_billing_url'] is None


def test_stripe_code_dependency_and_settings_are_gone():
    assert not (ROOT / 'services/billing.py').exists() and not (ROOT / 'database/billing_store.py').exists()
    assert 'stripe' not in (ROOT / 'requirements.txt').read_text().lower()
    assert 'stripe' not in (ROOT / 'requirements-dev.txt').read_text().lower()
    example = (ROOT / '.env.example').read_text()
    for name in ('STRIPE_SECRET_KEY', 'STRIPE_WEBHOOK_SECRET', 'CLOUDSAVER_STRIPE_CUSTOMERS', 'STRIPE_PRICE_TIERS',
                 'CLOUDSAVER_BILLING_RETURN_URL'):
        assert name not in example
    import app.entitlements as entitlements
    for name in ('checkout_configured', 'create_checkout_session', '_verify_customer', '_stripe_checkout'):
        assert not hasattr(entitlements, name)
    import app.schemas as schemas
    assert not hasattr(schemas, 'BillingCheckoutRequest')
