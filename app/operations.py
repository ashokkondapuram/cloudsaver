"""Operator-managed runtime flags exposed read-only to authenticated workspaces."""
import os


def workspace_operations():
    webhook = os.getenv('CLOUDSAVER_NOTIFICATION_WEBHOOK', '').strip()
    return {
        'scheduled_scans_enabled': os.getenv('CLOUDSAVER_SCHEDULED_SCANS', 'false').lower() == 'true',
        'scheduled_scan_interval_seconds': int(os.getenv('CLOUDSAVER_SCAN_INTERVAL_SECONDS', '3600')),
        'automated_alerts_enabled': os.getenv('CLOUDSAVER_AUTOMATED_ALERTS', 'false').lower() == 'true',
        'notification_webhook_configured': bool(webhook),
    }
