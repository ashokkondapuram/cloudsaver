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


def _advance_to_review(c, version_id):
    for pair in (('draft', 'evidence_required'), ('evidence_required', 'assessed'), ('assessed', 'review_requested')):
        c.post(f'/api/v1/control-plane/plan-versions/{version_id}/transitions',
               json={'from_state': pair[0], 'to_state': pair[1]}, headers=AUTH)


def test_self_approval_is_rejected_via_http(tmp_path):
    """A single workspace API key always resolves to the same actor hash, so the only self-approval
    scenario reachable over this auth mode is the version's own creator -- which must be blocked.
    The full "distinct approver succeeds" path is covered at the store layer
    (test_control_plane_store.py), since this test harness has no way to authenticate as two
    different human identities through a single workspace key."""
    c = client(tmp_path)
    plan = c.post('/api/v1/control-plane/plans', json={'objective': 'x'}, headers=AUTH).json()
    version = c.post(f'/api/v1/control-plane/plans/{plan["id"]}/versions',
                      json={'expected_version': 0, 'targets': ['r1'], 'parameters': {}}, headers=AUTH).json()
    _advance_to_review(c, version['id'])
    expires = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    approval = c.post(f'/api/v1/control-plane/plan-versions/{version["id"]}/approvals',
                       json={'expires_at': expires, 'identity_digest': version['identity_digest']}, headers=AUTH)
    assert approval.status_code == 409


def test_approval_rejects_a_stale_identity_digest(tmp_path):
    c = client(tmp_path)
    plan = c.post('/api/v1/control-plane/plans', json={'objective': 'x'}, headers=AUTH).json()
    version = c.post(f'/api/v1/control-plane/plans/{plan["id"]}/versions',
                      json={'expected_version': 0, 'targets': ['r1'], 'parameters': {}}, headers=AUTH).json()
    _advance_to_review(c, version['id'])
    expires = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    approval = c.post(f'/api/v1/control-plane/plan-versions/{version["id"]}/approvals',
                       json={'expires_at': expires, 'identity_digest': 'not-the-real-digest'}, headers=AUTH)
    assert approval.status_code == 409


def test_plan_version_rejects_unpersisted_conflict_fields(tmp_path):
    """exclusive_targets/consumes_ha_headroom/skus feed PlanVersion.identity() but have no column
    to persist them in, which would make the stored digest unreproducible -- so the request must
    not accept them until a schema migration adds the columns."""
    c = client(tmp_path)
    plan = c.post('/api/v1/control-plane/plans', json={'objective': 'x'}, headers=AUTH).json()
    response = c.post(f'/api/v1/control-plane/plans/{plan["id"]}/versions',
                       json={'expected_version': 0, 'targets': ['r1'], 'parameters': {}, 'skus': {'r1': 'Standard_D2'}},
                       headers=AUTH)
    assert response.status_code == 422


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


def test_action_assessment_conflict_on_changed_supported_flag(tmp_path):
    """supported changes the computed decision but was not part of any digest, so a replay with
    the same idempotency_key but a flipped supported flag must not silently return the stale result."""
    c = client(tmp_path)
    body = {'idempotency_key': 'replay-key-0002', 'action_id': 'resize-vm-1', 'supported': True, 'evidence': {}}
    first = c.post('/api/v1/control-plane/action-assessments', json=body, headers=AUTH)
    assert first.status_code == 201 and first.json()['decision'] == 'evidence_required'
    conflict = c.post('/api/v1/control-plane/action-assessments',
                       json=dict(body, supported=False), headers=AUTH)
    assert conflict.status_code == 409


def test_service_account_cannot_approve():
    """verified_human must not be hardcoded true regardless of caller; this test harness's workspace-
    key auth never sets subject_type, so this proves the guard directly rather than through HTTP,
    where every caller is indistinguishable from a human workspace-key session."""
    from fastapi import HTTPException
    import pytest
    from app.control_plane_api import _require_human_approver
    _require_human_approver({'tenant_id': TID})  # no subject_type: accepted (workspace-key operator)
    with pytest.raises(HTTPException) as excinfo:
        _require_human_approver({'tenant_id': TID, 'subject_type': 'service_account'})
    assert excinfo.value.status_code == 403


def test_financial_scenario_idempotent_replay(tmp_path):
    c = client(tmp_path)
    body = {'idempotency_key': 'scenario-key-001', 'currency': 'USD', 'commitment_fee': '100.00',
            'uncommitted_baseline': '50.00'}
    first = c.post('/api/v1/control-plane/financial-scenarios', json=body, headers=AUTH)
    assert first.status_code == 201 and first.json()['result']['status'] == 'computed'
    second = c.post('/api/v1/control-plane/financial-scenarios', json=body, headers=AUTH)
    assert second.status_code == 200 and second.json()['id'] == first.json()['id']
