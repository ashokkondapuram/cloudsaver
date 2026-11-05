"""Code Mode API, validation, and stub worker execution."""
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth import Role, UserClaims
from app.code_mode_validate import validate_snippet
from app.config import Settings
from app.main import create_app


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv('CLOUDSAVER_AUTH_MODE', 'entra')
    monkeypatch.setenv('CLOUDSAVER_KEY_VERIFIER', 'local')
    monkeypatch.setenv('CLOUDSAVER_CODE_MODE_ENABLED', 'true')
    monkeypatch.setenv('CLOUDSAVER_CODE_MODE_STUB', 'true')
    tid = str(uuid4())
    tenant = dict(tenant_id=tid, subscription_ids=[str(uuid4())], name='Code Mode QA', plan_tier='ENTERPRISE')

    class Validator:
        def verify_token(self, value):
            if value != 'admin':
                raise HTTPException(401, 'Invalid human credential')
            return UserClaims(user_id=str(uuid4()), tenant_id=tid, roles=[Role.TENANT_ADMIN], subject_type='user')

    settings = Settings('azure', str(tmp_path / 'code-mode.sqlite3'), (tenant,))
    client = TestClient(create_app(settings, identity_validator=Validator()))
    return type('Ctx', (), {'api': client, 'headers': {'Authorization': 'Bearer admin'}, 'tenant': tenant})()


def test_validate_snippet_rejects_fetch():
    with pytest.raises(ValueError, match='forbidden'):
        validate_snippet('function transform(input) { return fetch("https://evil"); }')


def test_code_mode_run_stub(setup):
    status = setup.api.get('/api/v1/code-mode/status', headers=setup.headers)
    assert status.status_code == 200
    body = status.json()
    assert body['enabled'] is True
    assert body['stub_mode'] is True

    run = setup.api.post(
        '/api/v1/code-mode/runs',
        headers=setup.headers,
        json={
            'request_key': str(uuid4()),
            'snippet': 'function transform(input) { return { ok: true, n: input.n }; }',
            'input': {'n': 1},
            'acknowledge_sandbox': True,
        },
    )
    assert run.status_code == 201, run.text
    payload = run.json()
    assert payload['state'] == 'succeeded'
    assert payload['result']['output']['stub'] is True

    listing = setup.api.get('/api/v1/code-mode/runs', headers=setup.headers)
    assert listing.status_code == 200
    assert any(item['id'] == payload['id'] for item in listing.json()['items'])

    detail = setup.api.get(f"/api/v1/code-mode/runs/{payload['id']}", headers=setup.headers)
    assert detail.status_code == 200
    assert len(detail.json()['events']) >= 2


def test_code_mode_requires_acknowledgment(setup):
    run = setup.api.post(
        '/api/v1/code-mode/runs',
        headers=setup.headers,
        json={
            'request_key': str(uuid4()),
            'snippet': 'function transform(input) { return input; }',
            'input': {},
            'acknowledge_sandbox': False,
        },
    )
    assert run.status_code == 422
