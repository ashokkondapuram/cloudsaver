from fastapi import Depends

from services.common import service


def create_app(settings=None):
    app, settings, tenant = service('tenant-service', settings)

    @app.get('/api/v1/me')
    def me(row=Depends(tenant)):
        return {k: row[k] for k in ('tenant_id', 'name', 'subscription_ids')} | {'mode': settings.mode}

    return app
