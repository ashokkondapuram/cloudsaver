"""Effective schedule and alert state from platform settings, tenant settings and plan."""
import os

INTERVALS = {'hourly': 3600, 'daily': 86400}


def platform_flags(settings=None):
    registry = getattr(settings, 'registry', None)
    if registry is not None:
        platform = registry.platform()
        return platform['scheduled_scans_enabled'], platform['automated_alerts_enabled']
    return (os.getenv('CLOUDSAVER_SCHEDULED_SCANS', 'false').lower() == 'true',
            os.getenv('CLOUDSAVER_AUTOMATED_ALERTS', 'false').lower() == 'true')


def effective_frequency(workspace, tier):
    """The tenant's choice, capped by what its plan allows."""
    from app.entitlements import get_tier_entitlements
    from app.tenant_config import default_frequency
    allowed = get_tier_entitlements(tier).allowed_scan_frequencies
    chosen = (workspace.get('schedule') or {}).get('frequency') or default_frequency(tier)
    order = ['hourly', 'daily', 'manual']
    return next(f for f in order[order.index(chosen):] if f in allowed or f == 'manual')


def scheduled_interval(settings, workspace, tier):
    """Seconds between scheduled scans, or None when the tenant is not scheduled."""
    scheduled, _ = platform_flags(settings)
    return INTERVALS.get(effective_frequency(workspace, tier)) if scheduled else None


def alerts_enabled(settings, workspace, tier):
    from app.entitlements import get_tier_entitlements
    _, platform_alerts = platform_flags(settings)
    tenant_alerts = (getattr(settings, 'registry', None) is None
                     or bool((workspace.get('alerts') or {}).get('enabled')))
    return platform_alerts and tenant_alerts and get_tier_entitlements(tier).can_dispatch_automated_alerts


def workspace_operations(workspace, settings=None):
    from app.delivery_config import target_definitions
    tier = workspace.get('plan_tier', 'STARTER')
    scheduled, platform_alerts = platform_flags(settings)
    frequency = effective_frequency(workspace, tier)
    webhook = bool(workspace.get('webhook_configured')) or any(
        t['tenant_id'] == workspace['tenant_id'] for t in target_definitions())
    return {
        'scheduled_scans_enabled': scheduled and frequency != 'manual',
        'scheduled_scan_interval_seconds': INTERVALS.get(frequency, 0),
        'scan_frequency': frequency,
        'platform_scheduled_scans_enabled': scheduled,
        'automated_alerts_enabled': alerts_enabled(settings, workspace, tier),
        'platform_automated_alerts_enabled': platform_alerts,
        'notification_webhook_configured': webhook,
        'delivery_dispatcher_enabled': os.getenv('CLOUDSAVER_DELIVERY_ENABLED', 'false').lower() == 'true',
    }
