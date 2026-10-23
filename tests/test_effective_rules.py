import httpx
import pytest

from app.effective_rules import enabled_rule_ids_for_tenant
from app.identity_client import IdentityClient, reset_shared_client

TID = '11111111-1111-4111-8111-111111111111'


@pytest.fixture(autouse=True)
def _reset():
    yield
    reset_shared_client(None)


def test_returns_enabled_ids_from_identity():
    def handle(request):
        assert request.url.path == f'/internal/v1/tenants/{TID}/analysis-rules/effective'
        return httpx.Response(200, json={'tenant_id': TID, 'enabled_rule_ids': ['ORPHANED_DISK', 'STOPPED_VM']})

    reset_shared_client(IdentityClient('http://identity', 'token', cache_seconds=0,
                                       transport=httpx.MockTransport(handle), subscribe=False))
    assert enabled_rule_ids_for_tenant(TID) == {'ORPHANED_DISK', 'STOPPED_VM'}


def test_falls_back_to_full_catalog_when_identity_unreachable():
    reset_shared_client(IdentityClient('http://identity', 'token', cache_seconds=0,
                                       transport=httpx.MockTransport(lambda r: httpx.Response(503, json={})),
                                       subscribe=False))
    assert enabled_rule_ids_for_tenant(TID) is None


def test_falls_back_when_identity_not_configured(monkeypatch):
    reset_shared_client(None)
    monkeypatch.delenv('CLOUDSAVER_IDENTITY_TOKEN', raising=False)
    assert enabled_rule_ids_for_tenant(TID) is None


def test_falls_back_on_malformed_payload():
    reset_shared_client(IdentityClient('http://identity', 'token', cache_seconds=0,
                                       transport=httpx.MockTransport(lambda r: httpx.Response(200, json={'enabled_rule_ids': 'nope'})),
                                       subscribe=False))
    assert enabled_rule_ids_for_tenant(TID) is None
