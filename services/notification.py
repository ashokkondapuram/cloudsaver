import os
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from fastapi import Depends, Header, HTTPException

from services.common import internal_url, service, upstream


def webhook_url(value):
    """Webhooks are operator configuration; visitors cannot supply destinations."""
    parsed = urlsplit(value)
    host = (parsed.hostname or '').lower()
    slack = host == 'hooks.slack.com' and parsed.path.startswith('/services/')
    teams = host.endswith('.webhook.office.com') or host.endswith('.environment.api.powerplatform.com')
    if parsed.scheme != 'https' or parsed.port not in (None, 443) or parsed.username or parsed.password or parsed.fragment or not (slack or teams):
        raise ValueError('Only configured HTTPS Slack or Teams webhook endpoints are allowed')
    return value


def create_app(settings=None, transport=None):
    app, settings, tenant = service('notification-service', settings)
    scanner = internal_url('SCANNER_SERVICE_URL', 'http://scanner-service:8002')

    @app.post('/api/v1/notifications/{scan_id}')
    async def notify(scan_id: UUID, row=Depends(tenant), authorization: str = Header()):
        # Lookup ownership before considering a send, even when notifications are disabled.
        scan = await upstream('GET', scanner, f'/api/v1/scans/{scan_id}', authorization, transport=transport)
        configured = os.getenv('CLOUDSAVER_NOTIFICATION_WEBHOOK', '')
        if not configured:
            raise HTTPException(503, 'Notifications are not configured')
        try:
            destination = webhook_url(configured)
        except ValueError:
            raise HTTPException(503, 'Notification destination configuration is invalid') from None
        message = f"CloudSaver {scan['mode']} scan completed: {scan['total_items_found']} review findings across {scan['subscriptions_scanned']} subscriptions."
        # Deliberately omit resource names, addresses, subscription IDs and credentials.
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=False, transport=transport) as client:
                response = await client.post(destination, json={'text': message})
            if response.status_code < 200 or response.status_code >= 300:
                raise HTTPException(502, 'Notification provider did not accept the message')
        except httpx.HTTPError:
            raise HTTPException(502, 'Notification provider unavailable') from None
        return {'status': 'sent', 'scan_id': str(scan_id)}

    return app
