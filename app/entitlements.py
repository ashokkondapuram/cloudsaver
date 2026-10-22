"""
CloudSaver - Commercial Billing, Stripe Checkout & Entitlement Enforcement.
"""
import os
from typing import Dict, Any, Optional, List
from enum import Enum
from pydantic import BaseModel
from fastapi import HTTPException

class PlanTier(str, Enum):
    STARTER = "STARTER"
    GROWTH = "GROWTH"
    ENTERPRISE = "ENTERPRISE"

class TierEntitlements(BaseModel):
    tier: PlanTier
    max_subscriptions: int
    max_resources_per_scan: int
    allowed_scan_frequencies: List[str]
    can_use_keyvault: bool
    can_export_terraform: bool
    can_dispatch_automated_alerts: bool
    retention_days: int

TIER_LIMITS: Dict[PlanTier, TierEntitlements] = {
    PlanTier.STARTER: TierEntitlements(
        tier=PlanTier.STARTER,
        max_subscriptions=2,
        max_resources_per_scan=250,
        allowed_scan_frequencies=["manual"],
        can_use_keyvault=False,
        can_export_terraform=False,
        can_dispatch_automated_alerts=False,
        retention_days=7
    ),
    PlanTier.GROWTH: TierEntitlements(
        tier=PlanTier.GROWTH,
        max_subscriptions=10,
        max_resources_per_scan=2500,
        allowed_scan_frequencies=["manual", "daily"],
        can_use_keyvault=False,
        can_export_terraform=True,
        can_dispatch_automated_alerts=True,
        retention_days=90
    ),
    PlanTier.ENTERPRISE: TierEntitlements(
        tier=PlanTier.ENTERPRISE,
        max_subscriptions=1000,
        max_resources_per_scan=100000,
        allowed_scan_frequencies=["manual", "daily", "hourly"],
        can_use_keyvault=True,
        can_export_terraform=True,
        can_dispatch_automated_alerts=True,
        retention_days=365
    )
}

def get_tier_entitlements(tier_name: str) -> TierEntitlements:
    try:
        tier = PlanTier(tier_name.upper())
    except (ValueError, AttributeError):
        tier = PlanTier.STARTER
    return TIER_LIMITS[tier]

def enforce_subscription_quota(tier_name: str, current_count: int, adding_count: int = 1) -> None:
    entitlements = get_tier_entitlements(tier_name)
    if (current_count + adding_count) > entitlements.max_subscriptions:
        raise HTTPException(
            status_code=402,
            detail=(
                f"Subscription quota exceeded for tier {entitlements.tier.value}. "
                f"Current limit: {entitlements.max_subscriptions} subscriptions. "
                f"Upgrade to a higher tier to connect additional Azure subscriptions."
            )
        )

def enforce_terraform_export(tier_name: str) -> None:
    entitlements = get_tier_entitlements(tier_name)
    if not entitlements.can_export_terraform:
        raise HTTPException(
            status_code=403,
            detail="Terraform remediation export is available on Growth and Enterprise tiers. Please upgrade."
        )

def enforce_keyvault_access(tier_name: str) -> None:
    entitlements = get_tier_entitlements(tier_name)
    if not entitlements.can_use_keyvault:
        raise HTTPException(
            status_code=403,
            detail="Azure Key Vault credential dynamic resolution requires an Enterprise tier plan."
        )

def create_checkout_session(
    target_tier: str,
    tenant_id: str,
    organization_id: str,
    customer_id: Optional[str] = None,
    success_url: Optional[str] = None,
    cancel_url: Optional[str] = None,
    idempotency_key: Optional[str] = None
) -> Dict[str, Any]:
    try:
        tier = PlanTier(target_tier.upper())
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid target plan tier: {target_tier}")

    if tier == PlanTier.STARTER:
        raise HTTPException(status_code=400, detail="Cannot create checkout session for free Starter tier")

    if not idempotency_key or len(idempotency_key) > 128:
        raise HTTPException(400, 'A checkout idempotency key is required')
    import hashlib
    from urllib.parse import urlparse
    key = os.getenv('STRIPE_SECRET_KEY', '')
    return_url = os.getenv('CLOUDSAVER_BILLING_RETURN_URL', '')
    parsed = urlparse(return_url)
    if not key or parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise HTTPException(503, 'Stripe Checkout and its HTTPS return URL must be configured')
    if success_url or cancel_url:
        raise HTTPException(400, 'Checkout return URLs are controlled by the operator')
    try:
        from services.billing import configuration
        customers, tiers = configuration()
        routes = [(customer, route) for customer, route in customers.items() if route['tenant_id'] == tenant_id]
        prices = [price for price, mapped_tier in tiers.items() if mapped_tier == tier.value]
        if len(routes) != 1 or len(prices) != 1:
            raise ValueError('Ambiguous billing configuration')
        customer, route = routes[0]
        _verify_customer(route, customer)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, 'A persisted tenant/customer mapping and one price per tier are required') from None
    parameters = {'mode': 'subscription', 'customer': customer,
                  'client_reference_id': route['organization_id'],
                  'line_items': [{'price': prices[0], 'quantity': 1}],
                  'success_url': return_url, 'cancel_url': return_url}
    try:
        session = _stripe_checkout(key, parameters, hashlib.sha256((tenant_id + ':' + idempotency_key).encode()).hexdigest())
        url = urlparse(session.url)
        if url.scheme != 'https' or url.hostname != 'checkout.stripe.com' or url.username or url.password:
            raise ValueError('Unexpected checkout URL')
        return {'session_id': session.id, 'checkout_url': session.url, 'tier': tier.value}
    except Exception:
        raise HTTPException(502, 'Stripe Checkout is unavailable; retry with the same idempotency key') from None


def _verify_customer(route, customer):
    import psycopg
    with psycopg.connect(os.environ['CLOUDSAVER_DATABASE_URL'], connect_timeout=5) as db:
        db.execute("SELECT set_config('app.current_tenant_id', %s, true)", (route['tenant_id'],))
        row = db.execute('SELECT stripe_subscription_id,stripe_subscription_status FROM organizations WHERE id=%s AND tenant_id=%s AND stripe_customer_id=%s',
                         (route['organization_id'], route['tenant_id'], customer)).fetchone()
        if not row:
            raise ValueError('Customer is not provisioned')
        if row[0] and row[1] not in ('canceled', 'incomplete_expired'):
            raise HTTPException(409, 'An existing subscription must be changed through the operator billing workflow')


def _stripe_checkout(key, parameters, idempotency_key):
    import stripe
    return stripe.StripeClient(key).v1.checkout.sessions.create(parameters, {'idempotency_key': idempotency_key})
