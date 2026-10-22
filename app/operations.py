"""Operator-managed runtime flags exposed read-only to authenticated workspaces."""
import os


def workspace_operations(tenant_id=None):
    from app.delivery_config import target_definitions
    webhook = bool(tenant_id and any(t['tenant_id']==tenant_id for t in target_definitions()))
    return {
        'scheduled_scans_enabled': os.getenv('CLOUDSAVER_SCHEDULED_SCANS', 'false').lower() == 'true',
        'scheduled_scan_interval_seconds': int(os.getenv('CLOUDSAVER_SCAN_INTERVAL_SECONDS', '3600')),
        'automated_alerts_enabled': os.getenv('CLOUDSAVER_AUTOMATED_ALERTS', 'false').lower() == 'true',
        'notification_webhook_configured': bool(webhook),
        'delivery_dispatcher_enabled': os.getenv('CLOUDSAVER_DELIVERY_ENABLED','false').lower()=='true',
    }
