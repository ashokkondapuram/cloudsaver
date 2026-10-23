"""Effective schedule and alert state from platform settings, tenant settings and plan entitlements."""
import os

INTERVALS = {'hourly': 3600, 'daily': 86400}


def platform_flags(settings=None):
    registry = getattr(settings, 'registry', None)
    if registry is not None:
        platform = registry.platform()
        return platform['scheduled_scans_enabled'], platform['automated_alerts_enabled']
    return (os.getenv('CLOUDSAVER_SCHEDULED_SCANS', 'false').lower() == 'true',
            os.getenv('CLOUDSAVER_AUTOMATED_ALERTS', 'false').lower() == 'true')


def _plan(workspace, plan):
    from app.entitlements import entitlements_for, resolve
    return entitlements_for(workspace) if plan is None else resolve(plan)


def effective_frequency(workspace, plan=None):
    """The tenant's choice, capped by what its plan allows."""
    from app.tenant_config import default_frequency
    plan = _plan(workspace, plan)
    allowed = plan.allowed_scan_frequencies
    chosen = (workspace.get('schedule') or {}).get('frequency') or default_frequency(plan.tier)
    order = ['hourly', 'daily', 'manual']
    return next(f for f in order[order.index(chosen):] if f in allowed or f == 'manual')


def scheduled_interval(settings, workspace, plan=None):
    """Seconds between scheduled scans, or None when the tenant is not scheduled."""
    scheduled, _ = platform_flags(settings)
    return INTERVALS.get(effective_frequency(workspace, plan)) if scheduled else None


def alerts_enabled(settings, workspace, plan=None):
    _, platform_alerts = platform_flags(settings)
    tenant_alerts = (getattr(settings, 'registry', None) is None
                     or bool((workspace.get('alerts') or {}).get('enabled')))
    return platform_alerts and tenant_alerts and _plan(workspace, plan).can_dispatch_automated_alerts


def workspace_operations(workspace, settings=None):
    from app.delivery_config import target_definitions
    from app.entitlements import entitlements_for
    plan = entitlements_for(workspace)
    scheduled, platform_alerts = platform_flags(settings)
    frequency = effective_frequency(workspace, plan)
    webhook = bool(workspace.get('webhook_configured')) or any(
        t['tenant_id'] == workspace['tenant_id'] for t in target_definitions())
    return {
        'scheduled_scans_enabled': scheduled and frequency != 'manual',
        'scheduled_scan_interval_seconds': INTERVALS.get(frequency, 0),
        'scan_frequency': frequency,
        'platform_scheduled_scans_enabled': scheduled,
        'automated_alerts_enabled': alerts_enabled(settings, workspace, plan),
        'platform_automated_alerts_enabled': platform_alerts,
        'notification_webhook_configured': webhook,
        'delivery_dispatcher_enabled': os.getenv('CLOUDSAVER_DELIVERY_ENABLED', 'false').lower() == 'true',
    }
