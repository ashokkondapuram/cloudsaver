from fastapi import Depends, HTTPException

from services.common import service

WEBHOOK_GONE = 'Billing webhooks are handled by the platform.'


def create_app(settings=None, identity_client=None):
    app, settings, tenant = service('tenant-service', settings)

    @app.post('/api/v1/billing/webhook')
    def billing_webhook():
        raise HTTPException(410, WEBHOOK_GONE)

    from app.settings_api import create_router as settings_router
    app.include_router(settings_router(settings, tenant))
    from app.config import directory_mode
    if directory_mode() == 'cutover':
        # The tenant-service projector is the only writer of the registry projection after cutover.
        from app.directory_projector import DirectoryProjector
        from app.identity_client import shared_client
        client = identity_client or shared_client()
        projector = DirectoryProjector(settings.registry, client)
        # Identity events with directory=true wake the projector instead of waiting for the next poll.
        client.directory_listeners.append(projector.nudge)
        app.state.projector = projector.start()

    @app.get('/api/v1/me')
    def me(row=Depends(tenant)):
        from app.auth import workspace_response
        return workspace_response(row, settings.mode, settings)

    return app
