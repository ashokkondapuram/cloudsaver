from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.test_enterprise import AUTH, TID, workspace


def client(tmp_path):
    settings = Settings('azure', str(tmp_path / 'cp.db'), (workspace(),))
    return TestClient(create_app(settings=settings))


def test_plan_lifecycle_end_to_end(tmp_path):
    c = client(tmp_path)
    plan = c.post('/api/v1/control-plane/plans', json={'objective': 'Rightsize overprovisioned VMs'}, headers=AUTH).json()
    assert plan['objective'] == 'Rightsize overprovisioned VMs' and plan['id']
    version = c.post(f'/api/v1/control-plane/plans/{plan["id"]}/versions',
                      json={'expected_version': 0, 'targets': ['r1'], 'parameters': {}}, headers=AUTH).json()
    assert version['version'] == 1 and version['state'] == 'draft'
    moved = c.post(f'/api/v1/control-plane/plan-versions/{version["id"]}/transitions',
                    json={'from_state': 'draft', 'to_state': 'evidence_required'}, headers=AUTH)
    assert moved.status_code == 200 and moved.json()['state'] == 'evidence_required'


def test_illegal_transition_returns_409(tmp_path):
    c = client(tmp_path)
    plan = c.post('/api/v1/control-plane/plans', json={'objective': 'x'}, headers=AUTH).json()
    version = c.post(f'/api/v1/control-plane/plans/{plan["id"]}/versions',
                      json={'expected_version': 0, 'targets': ['r1'], 'parameters': {}}, headers=AUTH).json()
    response = c.post(f'/api/v1/control-plane/plan-versions/{version["id"]}/transitions',
                       json={'from_state': 'draft', 'to_state': 'approved'}, headers=AUTH)
    assert response.status_code == 409


def test_approval_then_full_path_to_approved(tmp_path):
    c = client(tmp_path)
    plan = c.post('/api/v1/control-plane/plans', json={'objective': 'x'}, headers=AUTH).json()
    version = c.post(f'/api/v1/control-plane/plans/{plan["id"]}/versions',
                      json={'expected_version': 0, 'targets': ['r1'], 'parameters': {}}, headers=AUTH).json()
    for pair in (('draft', 'evidence_required'), ('evidence_required', 'assessed'), ('assessed', 'review_requested')):
        c.post(f'/api/v1/control-plane/plan-versions/{version["id"]}/transitions',
               json={'from_state': pair[0], 'to_state': pair[1]}, headers=AUTH)
    expires = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    approval = c.post(f'/api/v1/control-plane/plan-versions/{version["id"]}/approvals',
                       json={'expires_at': expires}, headers=AUTH)
    assert approval.status_code == 201
    moved = c.post(f'/api/v1/control-plane/plan-versions/{version["id"]}/transitions',
                    json={'from_state': 'review_requested', 'to_state': 'approved'}, headers=AUTH)
    assert moved.status_code == 200 and moved.json()['state'] == 'approved'


def test_action_assessment_idempotent_replay_and_conflict(tmp_path):
    c = client(tmp_path)
    body = {'idempotency_key': 'replay-key-0001', 'action_id': 'resize-vm-1', 'supported': True, 'evidence': {}}
    first = c.post('/api/v1/control-plane/action-assessments', json=body, headers=AUTH)
    assert first.status_code == 201
    second = c.post('/api/v1/control-plane/action-assessments', json=body, headers=AUTH)
    assert second.status_code == 200 and second.json()['id'] == first.json()['id']
    conflict = c.post('/api/v1/control-plane/action-assessments',
                       json=dict(body, action_id='resize-vm-2'), headers=AUTH)
    assert conflict.status_code == 409


def test_financial_scenario_idempotent_replay(tmp_path):
    c = client(tmp_path)
    body = {'idempotency_key': 'scenario-key-001', 'currency': 'USD', 'commitment_fee': '100.00',
            'uncommitted_baseline': '50.00'}
    first = c.post('/api/v1/control-plane/financial-scenarios', json=body, headers=AUTH)
    assert first.status_code == 201 and first.json()['result']['status'] == 'computed'
    second = c.post('/api/v1/control-plane/financial-scenarios', json=body, headers=AUTH)
    assert second.status_code == 200 and second.json()['id'] == first.json()['id']
