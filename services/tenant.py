from fastapi import Depends

from services.common import service


def create_app(settings=None, billing_store=None):
    app, settings, tenant = service('tenant-service', settings)
    from services.billing import billing_router
    app.include_router(billing_router(billing_store))
    from app.settings_api import create_router as settings_router
    app.include_router(settings_router(settings, tenant))

    @app.get('/api/v1/me')
    def me(row=Depends(tenant)):
        from app.auth import workspace_response
        return workspace_response(row, settings.mode, settings)

    return app
