from fastapi import Depends

from services.common import service


def create_app(settings=None, billing_store=None):
    app, settings, tenant = service('tenant-service', settings)
    from services.billing import billing_router
    app.include_router(billing_router(billing_store))

    @app.get('/api/v1/me')
    def me(row=Depends(tenant)):
        from app.auth import workspace_response
        return workspace_response(row, settings.mode)

    return app
