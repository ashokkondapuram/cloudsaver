"""Backend hardening contracts exercised through HTTP, with no cloud calls."""
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.runtime import install
from app.config import Settings
from services.gateway import create_app as gateway
from tests.test_services import configuration, Limiter, KEY


def runtime(tmp_path):
    app = FastAPI()
    install(app, Settings('azure', str(tmp_path / 'db'), ()))
    @app.get('/healthz')
    def live():
        return {'status': 'alive'}
    @app.get('/failure')
    def broken():
        raise RuntimeError('sensitive-provider-response')
    @app.get('/forbidden')
    def forbidden():
        raise HTTPException(401, 'Authentication required', headers={'WWW-Authenticate': 'Bearer'})
    return app


def test_errors_have_safe_problem_details_and_correlation(tmp_path):
    app = runtime(tmp_path)
    request_id = str(uuid4())
    with TestClient(app) as client:
        for path, status in [('/failure', 500), ('/forbidden', 401), ('/missing', 404)]:
            response = client.get(path, headers={'X-Request-ID': request_id})
            assert response.status_code == status
            assert response.headers['content-type'] == 'application/problem+json'
            assert response.headers['x-request-id'] == request_id
            assert response.json()['request_id'] == request_id
            assert response.json()['instance'] == path
            assert 'sensitive-provider-response' not in response.text
        assert client.get('/forbidden').headers['www-authenticate'] == 'Bearer'
        generated = client.get('/healthz', headers={'X-Request-ID': 'untrusted-arbitrary-text'}).headers['x-request-id']
        assert str(UUID(generated)) == generated


def test_readiness_fails_closed_but_liveness_stays_up(tmp_path):
    app = runtime(tmp_path)
    async def up():
        pass
    async def down():
        raise RuntimeError('private-db-url')
    app.state.readiness_checks = {'database': up, 'redis': down}
    with TestClient(app) as client:
        response = client.get('/readyz')
        assert response.status_code == 503
        assert response.json() == {'status': 'unready', 'dependencies': {'database': 'up', 'redis': 'down'}}
        assert client.get('/healthz').status_code == 200
        assert client.get('/health/live').status_code == 200
        assert client.get('/health/ready').status_code == 503
        app.state.readiness_checks['redis'] = up
        assert client.get('/readyz').status_code == 200
        assert client.get('/health/ready').status_code == 200


def test_cors_is_explicit_and_validation_does_not_echo_input(tmp_path, monkeypatch):
    monkeypatch.setenv('CLOUDSAVER_ALLOWED_ORIGINS', 'https://console.example.com')
    app = runtime(tmp_path)
    with TestClient(app) as client:
        response = client.options('/healthz', headers={'Origin': 'https://console.example.com', 'Access-Control-Request-Method': 'GET'})
        assert response.headers['access-control-allow-origin'] == 'https://console.example.com'
        response = client.get('/healthz', headers={'Origin': 'https://attacker.example'})
        assert 'access-control-allow-origin' not in response.headers
    monkeypatch.setenv('CLOUDSAVER_ALLOWED_ORIGINS', '*')
    with pytest.raises(ValueError, match='CORS origins'):
        runtime(tmp_path)


def test_gateway_forwards_correlation_and_job_status_without_tenant_header_trust(tmp_path):
    seen = []
    job_id = str(uuid4())
    def handler(request):
        seen.append(request)
        assert 'x-tenant-id' not in request.headers
        assert UUID(request.headers['x-request-id'])
        return httpx.Response(202, json={'job_id': job_id, 'status': 'queued', 'poll_url': '/api/v1/scan-jobs/' + job_id})
    with TestClient(gateway(configuration(tmp_path), Limiter(), httpx.MockTransport(handler))) as client:
        response = client.post('/api/v1/scan-jobs', json={'idempotency_key': str(uuid4()), 'subscription_ids': ['33333333-3333-4333-8333-333333333333']}, headers={'Authorization': 'Bearer ' + KEY, 'X-Tenant-ID': str(uuid4())})
        assert response.status_code == 202 and response.headers['retry-after'] == '3'
        assert response.headers['location'] == '/api/v1/scan-jobs/' + job_id
        assert seen[0].headers['x-request-id'] == response.headers['x-request-id']
        response = client.post('/api/v1/scan-jobs', json={'idempotency_key': 'private-invalid-input', 'subscription_ids': []}, headers={'Authorization': 'Bearer ' + KEY})
        assert response.status_code == 422 and 'private-invalid-input' not in response.text
