"""Plan entitlements from the platform, enforced by CloudSaver.

The platform owns plans and billing. Each workspace carries a `plan` block, either from the verify
response (workspace keys) or from the directory projection (Entra mode, workers). TIER_LIMITS is only
the fallback for workspaces the platform hasn't sent a plan block for yet.
"""
import logging
import re
import threading
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional
from urllib.parse import urlsplit

from fastapi import HTTPException
from pydantic import BaseModel

logger = logging.getLogger('cloudsaver.entitlements')
PROVIDERS = ('azure', 'aws', 'gcp', 'kubernetes')
PROVIDER_LABELS = {'azure': 'Azure', 'aws': 'AWS', 'gcp': 'GCP', 'kubernetes': 'Kubernetes'}
FREQUENCIES = ('manual', 'daily', 'hourly')
BILLING_STATES = ('active', 'grace', 'lapsed', 'none')
PLAN_CODE = re.compile(r'^[A-Z][A-Z0-9_]{0,15}$')
CONTACT = 'Contact your account manager.'


class PlanTier(str, Enum):
    STARTER = "STARTER"
    GROWTH = "GROWTH"
    ENTERPRISE = "ENTERPRISE"


class TierEntitlements(BaseModel):
    tier: str
    plan_name: str
    max_subscriptions: int
    max_resources_per_scan: int
    allowed_scan_frequencies: List[str]
    can_use_keyvault: bool
    can_export_terraform: bool
    can_dispatch_automated_alerts: bool
    can_use_ai_advisory: bool = False
    retention_days: int
    allowed_providers: List[str] = list(PROVIDERS)
    billing_state: str = 'none'
    current_period_end: Optional[str] = None
    grace_ends_at: Optional[str] = None
    subscription_plan_name: Optional[str] = None
    manage_billing_url: Optional[str] = None
    entitlements_version: Optional[int] = None
    source: str = 'fallback'


TIER_LIMITS: Dict[PlanTier, TierEntitlements] = {
    PlanTier.STARTER: TierEntitlements(
        tier=PlanTier.STARTER.value, plan_name='Starter',
        max_subscriptions=2,
        max_resources_per_scan=250,
        allowed_scan_frequencies=["manual"],
        can_use_keyvault=False,
        can_export_terraform=False,
        can_dispatch_automated_alerts=False,
        retention_days=7
    ),
    PlanTier.GROWTH: TierEntitlements(
        tier=PlanTier.GROWTH.value, plan_name='Growth',
        max_subscriptions=10,
        max_resources_per_scan=2500,
        allowed_scan_frequencies=["manual", "daily"],
        can_use_keyvault=False,
        can_use_ai_advisory=True,
        can_export_terraform=True,
        can_dispatch_automated_alerts=True,
        retention_days=90
    ),
    PlanTier.ENTERPRISE: TierEntitlements(
        tier=PlanTier.ENTERPRISE.value, plan_name='Enterprise',
        max_subscriptions=1000,
        max_resources_per_scan=100000,
        allowed_scan_frequencies=["manual", "daily", "hourly"],
        can_use_keyvault=True,
        can_use_ai_advisory=True,
        can_export_terraform=True,
        can_dispatch_automated_alerts=True,
        retention_days=365
    )
}
_warned = set()
_warned_lock = threading.Lock()


def plan_code(value):
    """Plan codes are uppercase; operators may define their own beyond the three built-in tiers."""
    code = value.strip().upper() if isinstance(value, str) else ''
    if not PLAN_CODE.fullmatch(code):
        raise ValueError('Invalid plan tier')
    return code


def _timestamp(value):
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if not isinstance(value, datetime):
        raise ValueError('Plan dates must be ISO 8601 timestamps')
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _name(value, required=False):
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > 60:
        raise ValueError('Plan names must be 1–60 characters')
    return value.strip()


def billing_url(value):
    """The manage-billing link is shown only when it's a plain HTTPS URL."""
    if not isinstance(value, str) or len(value) > 2048 or not value.startswith('https://'):
        return None
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    if not parsed.hostname or parsed.username or parsed.password or any(c.isspace() for c in value):
        return None
    return value


def _limits(value):
    if not isinstance(value, dict):
        raise ValueError('Plan entitlements must be an object')
    value = dict(value)
    value.setdefault('can_use_ai_advisory', False)

    def number(key):
        item = value.get(key)
        if isinstance(item, bool) or not isinstance(item, int) or item < 0:
            raise ValueError(f'Plan entitlement {key} must be a non-negative integer')
        return item

    def flag(key):
        if not isinstance(value.get(key), bool):
            raise ValueError(f'Plan entitlement {key} must be a boolean')
        return value[key]

    def subset(key, allowed, default=None):
        item = value.get(key, default)
        if not isinstance(item, list) or not all(isinstance(i, str) for i in item) or not set(item) <= set(allowed):
            raise ValueError(f'Plan entitlement {key} has unknown values')
        return [i for i in allowed if i in item]

    frequencies = subset('allowed_scan_frequencies', FREQUENCIES)
    return {'max_subscriptions': number('max_subscriptions'), 'max_resources_per_scan': number('max_resources_per_scan'),
            'allowed_scan_frequencies': frequencies if 'manual' in frequencies else ['manual'] + frequencies,
            'can_export_terraform': flag('can_export_terraform'), 'can_use_keyvault': flag('can_use_keyvault'),
            'can_dispatch_automated_alerts': flag('can_dispatch_automated_alerts'),
            'can_use_ai_advisory': flag('can_use_ai_advisory'),
            'retention_days': number('retention_days'),
            'allowed_providers': subset('allowed_providers', PROVIDERS, list(PROVIDERS))}


def normalize_plan(value):
    """Canonical plan block (contract identity-v1) or None; raises ValueError when it's malformed."""
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError('The plan block must be an object')
    code = plan_code(value.get('code'))
    if 'access_suspended' in value and type(value['access_suspended']) is not bool:
        raise ValueError('Billing access suspension must be a boolean')
    state = value.get('billing_state') or 'none'
    if state not in BILLING_STATES:
        raise ValueError('Unknown billing state')
    version = value.get('entitlements_version')
    if version is not None and (isinstance(version, bool) or not isinstance(version, int) or version < 0):
        raise ValueError('Entitlements version must be a non-negative integer')
    return {
        **({'access_suspended': True} if value.get('access_suspended') is True else {}),
        'code': code, 'name': _name(value.get('name')) or code.title(), 'billing_state': state,
        'current_period_end': _timestamp(value.get('current_period_end')),
        'grace_ends_at': _timestamp(value.get('grace_ends_at')),
        'subscription_plan_name': _name(value.get('subscription_plan_name')),
        'entitlements_version': version, 'entitlements': _limits(value.get('entitlements')),
        'manage_billing_url': billing_url(value.get('manage_billing_url')),
    }


def fallback_entitlements(tier_name) -> TierEntitlements:
    """Static limits for a plan code. Unknown codes get Starter limits under their own code."""
    try:
        code = plan_code(tier_name)
    except ValueError:
        code = PlanTier.STARTER.value
    known = TIER_LIMITS.get(PlanTier(code)) if code in PlanTier.__members__ else None
    if known:
        return known.model_copy(deep=True)
    return TIER_LIMITS[PlanTier.STARTER].model_copy(update={'tier': code, 'plan_name': code.title()}, deep=True)


def entitlements_for(tenant) -> TierEntitlements:
    """Effective entitlements: the verified or projected plan block, else TIER_LIMITS for plan_tier."""
    try:
        plan = normalize_plan((tenant or {}).get('plan'))
    except ValueError:
        logger.warning('Ignoring a malformed plan block tenant_id=%s', (tenant or {}).get('tenant_id'))
        plan = None
    if plan:
        return TierEntitlements(
            tier=plan['code'], plan_name=plan['name'], **plan['entitlements'], billing_state=plan['billing_state'],
            current_period_end=plan['current_period_end'], grace_ends_at=plan['grace_ends_at'],
            subscription_plan_name=plan['subscription_plan_name'], manage_billing_url=plan['manage_billing_url'],
            entitlements_version=plan['entitlements_version'], source=tenant.get('identity_provider') if tenant.get('identity_provider') in ('keycloak','offline_license') else 'platform')
    result = fallback_entitlements((tenant or {}).get('plan_tier') or PlanTier.STARTER.value)
    tenant_id = (tenant or {}).get('tenant_id')
    with _warned_lock:
        first = tenant_id not in _warned
        _warned.add(tenant_id)
    if first:
        logger.warning('entitlements_fallback tenant_id=%s plan=%s', tenant_id, result.tier)
    return result


def resolve(subject) -> TierEntitlements:
    """Accepts entitlements, a workspace dict, or a plan code (fallback limits)."""
    if isinstance(subject, TierEntitlements):
        return subject
    if isinstance(subject, dict):
        return entitlements_for(subject)
    return fallback_entitlements(subject)


def scope_quota_message(plan):
    return (f'Your {plan.plan_name} plan allows up to {plan.max_subscriptions} cloud scopes. '
            'Contact your account manager to change your plan.')


def enforce_subscription_quota(subject, current_count: int, adding_count: int = 1) -> None:
    plan = resolve(subject)
    if current_count + adding_count > plan.max_subscriptions:
        raise HTTPException(status_code=402, detail=scope_quota_message(plan))


def enforce_resource_quota(subject, count: int) -> None:
    plan = resolve(subject)
    if count > plan.max_resources_per_scan:
        raise HTTPException(402, f'This scan found more than {plan.max_resources_per_scan:,} resources, the limit for your '
                                 f'{plan.plan_name} plan. No partial results were saved. '
                                 'Contact your account manager to change your plan.')


def enforce_terraform_export(subject) -> None:
    if not resolve(subject).can_export_terraform:
        raise HTTPException(status_code=403,
                            detail='Terraform review is available on plans that include it. Contact your account manager.')


def enforce_keyvault_access(subject) -> None:
    if not resolve(subject).can_use_keyvault:
        raise HTTPException(status_code=403, detail="Key Vault access isn't included in your plan. " + CONTACT)


def enforce_scan_frequency(subject, frequency: str) -> None:
    if frequency not in resolve(subject).allowed_scan_frequencies:
        raise HTTPException(402, f"{frequency.capitalize()} scans aren't included in your plan. " + CONTACT)


def enforce_automated_alerts(subject) -> None:
    if not resolve(subject).can_dispatch_automated_alerts:
        raise HTTPException(402, "Automated alerts aren't included in your plan. " + CONTACT)


def enforce_providers(subject, providers) -> None:
    allowed = set(resolve(subject).allowed_providers)
    for provider in PROVIDERS:
        if provider in providers and provider not in allowed:
            raise HTTPException(403, f"{PROVIDER_LABELS[provider]} isn't included in your plan. " + CONTACT)


def billing_summary(tenant, workspace=None) -> dict:
    """GET /api/v1/billing/entitlements; the dashboard Plan tab is built against exactly these fields.

    Quotas are workspace-wide, so scopes are counted on the full workspace even for provider-scoped keys.
    """
    plan = entitlements_for(tenant)
    workspace = workspace or tenant
    return {
        'tenant_id': tenant['tenant_id'],
        'tier': plan.tier,
        'plan_name': plan.plan_name,
        'billing_state': plan.billing_state,
        'current_period_end': plan.current_period_end,
        'grace_ends_at': plan.grace_ends_at,
        'subscription_plan_name': plan.subscription_plan_name,
        'manage_billing_url': plan.manage_billing_url,
        'max_subscriptions': plan.max_subscriptions,
        'current_subscriptions': sum(len(workspace.get(k) or []) for k in
                                     ('subscription_ids', 'aws_accounts', 'gcp_projects', 'kubernetes_clusters')),
        'max_resources_per_scan': plan.max_resources_per_scan,
        'allowed_scan_frequencies': list(plan.allowed_scan_frequencies),
        'allowed_providers': list(plan.allowed_providers),
        'can_export_terraform': plan.can_export_terraform,
        'can_use_keyvault': plan.can_use_keyvault,
        'can_dispatch_automated_alerts': plan.can_dispatch_automated_alerts,
        'retention_days': plan.retention_days,
        'entitlements_source': 'platform' if plan.source == 'platform' else 'fallback',
        'settings_version': int((workspace or tenant).get('version') or 1),
        'plan_change_allowed': True,
    }
