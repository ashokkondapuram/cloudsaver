"""Self-service plan changes for workspace billing administrators."""
from datetime import datetime, timedelta, timezone

from app.entitlements import PlanTier, TIER_LIMITS, fallback_entitlements, normalize_plan, plan_code


def _entitlements_dict(tier):
    return {
        'max_subscriptions': tier.max_subscriptions,
        'max_resources_per_scan': tier.max_resources_per_scan,
        'allowed_scan_frequencies': list(tier.allowed_scan_frequencies),
        'can_export_terraform': tier.can_export_terraform,
        'can_use_keyvault': tier.can_use_keyvault,
        'can_dispatch_automated_alerts': tier.can_dispatch_automated_alerts,
        'retention_days': tier.retention_days,
        'allowed_providers': list(tier.allowed_providers),
    }


def build_plan_block(code, current=None):
    """Manual plan block stored on the workspace registry row."""
    tier = fallback_entitlements(plan_code(code))
    current = current or {}
    now = datetime.now(timezone.utc)
    period_end = (now + timedelta(days=30)).strftime('%Y-%m-%dT%H:%M:%SZ')
    block = {
        'code': tier.tier,
        'name': tier.plan_name,
        'billing_state': 'active',
        'current_period_end': current.get('current_period_end') or period_end,
        'grace_ends_at': None,
        'subscription_plan_name': tier.plan_name,
        'entitlements': _entitlements_dict(tier),
        'entitlements_version': int(current.get('entitlements_version') or 0) + 1,
        'manage_billing_url': current.get('manage_billing_url'),
    }
    return normalize_plan(block)


def list_plans():
    items = []
    for tier in (PlanTier.STARTER, PlanTier.GROWTH, PlanTier.ENTERPRISE):
        ent = TIER_LIMITS[tier]
        items.append({
            'code': ent.tier,
            'name': ent.plan_name,
            'max_subscriptions': ent.max_subscriptions,
            'max_resources_per_scan': ent.max_resources_per_scan,
            'allowed_scan_frequencies': list(ent.allowed_scan_frequencies),
            'can_export_terraform': ent.can_export_terraform,
            'can_use_keyvault': ent.can_use_keyvault,
            'can_dispatch_automated_alerts': ent.can_dispatch_automated_alerts,
            'retention_days': ent.retention_days,
            'allowed_providers': list(ent.allowed_providers),
        })
    return items
