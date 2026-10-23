import hashlib

import httpx
import pytest
from fastapi.routing import APIRoute

from app.config import Settings
from app.main import create_app as scanner
from app.route_inventory import ROUTES, classify
from services.analytics import create_app as analytics
from services.gateway import create_app as gateway
from services.notification import create_app as notification
from services.tenant import create_app as tenant_service

TID = '11111111-1111-4111-8111-111111111111'
SID = '33333333-3333-4333-8333-333333333333'
DOCS = {'/docs', '/docs/oauth2-redirect', '/redoc', '/openapi.json'}


class Limiter:
    async def check(self, tenant_id):
        return None


def settings(tmp_path):
    return Settings('azure', str(tmp_path / 'routes.sqlite3'), (
        dict(tenant_id=TID, name='Routes', subscription_ids=[SID], api_key_sha256=hashlib.sha256(b'x' * 40).hexdigest()),))


def routes(app):
    for route in app.routes:
        if isinstance(route, APIRoute) and route.path not in DOCS:
            for method in route.methods - {'HEAD', 'OPTIONS'}:
                yield method, route.path


@pytest.fixture
def apps(tmp_path):
    config = settings(tmp_path)
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={}))
    return {
        'gateway': gateway(config, Limiter(), transport),
        'tenant': tenant_service(config),
        'scanner': scanner(config, scanner=lambda tenant: []),
        'analytics': analytics(config, transport),
        'notification': notification(config, transport),
    }


def test_every_service_route_is_classified(apps):
    missing = sorted({f'{name}: {method} {path}' for name, app in apps.items() for method, path in routes(app)
                      if classify(method, path) is None})
    assert not missing, 'Classify these routes in app/route_inventory.py:\n' + '\n'.join(missing)


def test_inventory_has_no_stale_entries(apps):
    live = {route for app in apps.values() for route in routes(app)}
    stale = sorted(f'{m} {p}' for (m, p) in ROUTES if (m, p) not in live)
    # Alternate parameter spellings are kept so gateway proxies and services can name parameters differently.
    assert all('{' in item for item in stale), stale


def test_removed_billing_routes_are_public_gone_responses():
    assert classify('POST', '/api/v1/billing/webhook') == 'public'
    assert classify('POST', '/api/v1/billing/checkout') == 'public'
