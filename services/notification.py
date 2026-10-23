import os
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from fastapi import Depends, Header, HTTPException

from services.common import internal_url, service, upstream


def webhook_url(value):
    """Only Slack and Teams HTTPS webhook hosts; any other destination is rejected."""
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

    @app.post('/api/v1/notifications/{scan_id}',status_code=202)
    async def notify(scan_id: UUID, row=Depends(tenant), authorization: str = Header()):
        from app.auth import require_workspace_role, Role
        require_workspace_role(row, Role.TENANT_ADMIN)
        # Scanner validates ownership and commits the durable delivery intent.
        # This service no longer makes unaudited direct webhook requests.
        return await upstream('POST', scanner, f'/api/v1/notifications/{scan_id}', authorization, transport=transport)

    return app
