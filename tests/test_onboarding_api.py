import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.identity_client import IdentityClient, reset_shared_client
from app.onboarding_api import customer_access_router, onboarding_router

TID = '11111111-1111-4111-8111-111111111111'


@pytest.fixture(autouse=True)
def _reset():
    yield
    reset_shared_client(None)


def identity(handle):
    reset_shared_client(IdentityClient('http://identity', 'token', cache_seconds=0,
                                       transport=httpx.MockTransport(handle), subscribe=False))


def workspace_row():
    return {'tenant_id': TID}


def app():
    api = FastAPI()
    api.include_router(onboarding_router())
    api.include_router(customer_access_router(lambda: workspace_row()))
    return TestClient(api)


def test_claim_forwards_to_identity_and_maps_expired_key():
    identity(lambda r: httpx.Response(401, json={'detail': 'nope'}))
    client = app()
    response = client.post('/api/v1/onboarding/claim', json={'key': 'abc', 'display_name': 'Ada', 'email': 'ada@contoso.com'})
    assert response.status_code == 401
    assert 'invalid or has expired' in response.json()['detail']


def test_claim_requires_email_or_identity_pair():
    client = app()
    response = client.post('/api/v1/onboarding/claim', json={'key': 'abc', 'display_name': 'Ada'})
    assert response.status_code == 422


def test_claim_success_passes_upstream_fields():
    captured = {}

    def handle(request):
        captured['body'] = request.read()
        return httpx.Response(200, json={'valid': True, 'customer_id': 'c1'})

    identity(handle)
    client = app()
    response = client.post('/api/v1/onboarding/claim', json={'key': 'abc', 'display_name': 'Ada', 'email': 'ADA@contoso.com'})
    assert response.status_code == 200 and response.json()['valid'] is True
    import json
    body = json.loads(captured['body'])
    assert body['idp_issuer'] == 'urn:cloudsaver:email' and body['idp_subject'] == 'ada@contoso.com'


def test_access_export_proxies_and_sets_csv_headers():
    identity(lambda r: httpx.Response(200, text='record\n', headers={'content-type': 'text/csv'}))
    client = app()
    response = client.get('/api/v1/customer/access-export', headers={'Authorization': 'Bearer x'})
    assert response.status_code == 200
    assert response.headers['content-disposition'] == 'attachment; filename="access-review.csv"'
    assert response.text == 'record\n'


def test_members_route_scopes_to_callers_own_workspace():
    seen = {}

    def handle(request):
        seen['path'] = request.url.path
        return httpx.Response(200, json={'items': []})

    identity(handle)
    client = app()
    response = client.get('/api/v1/customer/members', headers={'Authorization': 'Bearer x'})
    assert response.status_code == 200
    assert seen['path'] == f'/customer/v1/workspaces/{TID}/members'


def test_upstream_error_detail_is_surfaced_and_truncated_otherwise():
    identity(lambda r: httpx.Response(409, json={'detail': 'Version conflict'}))
    client = app()
    response = client.get('/api/v1/customer/keys', headers={'Authorization': 'Bearer x'})
    assert response.status_code == 409 and response.json()['detail'] == 'Version conflict'
