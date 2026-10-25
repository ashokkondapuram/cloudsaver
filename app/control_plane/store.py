"""Tenant-scoped storage for control-plane records.

Follows commitment_store.py: callers pass a `store` exposing `transaction(tenant_id)`, which yields a
db with `execute(sql, params)` and `json(value)`. Every statement filters on tenant_id (RLS is the
backstop). Evidence rows are append-only; only plan-version state may change.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4

from app.control_plane.plans import STATES

ALLOWED = {
    "draft": {"evidence_required", "assessed", "cancelled"},
    "evidence_required": {"assessed", "cancelled", "expired"},
    "assessed": {"review_requested", "evidence_required", "cancelled", "expired"},
    "review_requested": {"approved", "assessed", "cancelled", "expired"},
    "approved": {"queued", "cancelled", "expired"},
    "queued": {"running", "cancelled", "expired"},
    "running": {"verification_pending", "failed", "reconciliation_required"},
    "verification_pending": {"verified", "failed", "reconciliation_required"},
    "failed": {"reconciliation_required"},
}
assert set(ALLOWED) <= set(STATES)


class ConflictError(Exception):
    """Optimistic-version or state-precondition failure."""


class NotFoundError(Exception):
    """Non-enumerating: also raised for another tenant's id."""


def _now():
    return datetime.now(timezone.utc).isoformat()


def _load(value):
    return json.loads(value) if isinstance(value, (str, bytes)) else value


def _rowcount(cur):
    return getattr(cur, "rowcount", 0)


def save_financial_scenario(store, tenant_id, idempotency_key, currency, request, result, actor_hash, evidence_digest=None):
    """Idempotent: a replay returns the original row id and never overwrites it."""
    new_id = str(uuid4())
    with store.transaction(tenant_id) as db:
        db.execute("INSERT INTO cp_financial_scenarios(id,tenant_id,idempotency_key,currency,input,result,status,"
                   "evidence_digest,created_by_hash,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                   "ON CONFLICT (tenant_id,idempotency_key) DO NOTHING",
                   (new_id, tenant_id, idempotency_key, currency, db.json(request), db.json(result),
                    result.get("status", "unknown"), evidence_digest, actor_hash, _now()))
        row = db.execute("SELECT id FROM cp_financial_scenarios WHERE tenant_id=%s AND idempotency_key=%s",
                         (tenant_id, idempotency_key)).fetchone()
    return str(row[0])


def get_financial_scenario(store, tenant_id, scenario_id):
    with store.transaction(tenant_id) as db:
        row = db.execute("SELECT id,currency,input,result,status,evidence_digest,created_at FROM cp_financial_scenarios "
                         "WHERE tenant_id=%s AND id=%s", (tenant_id, scenario_id)).fetchone()
    if row is None:
        raise NotFoundError()
    return dict(id=str(row[0]), currency=row[1], input=_load(row[2]), result=_load(row[3]), status=row[4],
                evidence_digest=row[5], created_at=str(row[6]))


def save_action_assessment(store, tenant_id, idempotency_key, action_id, outcome, evidence_digest, policy_digest, actor_hash):
    new_id = str(uuid4())
    with store.transaction(tenant_id) as db:
        db.execute("INSERT INTO cp_action_assessments(id,tenant_id,idempotency_key,action_id,rule_version,findings,decision,"
                   "evidence_digest,policy_digest,created_by_hash,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                   "ON CONFLICT (tenant_id,idempotency_key) DO NOTHING",
                   (new_id, tenant_id, idempotency_key, action_id, outcome["rule_version"], db.json(outcome["findings"]),
                    outcome["decision"], evidence_digest, policy_digest, actor_hash, _now()))
        row = db.execute("SELECT id FROM cp_action_assessments WHERE tenant_id=%s AND idempotency_key=%s",
                         (tenant_id, idempotency_key)).fetchone()
    return str(row[0])


def get_action_assessment(store, tenant_id, assessment_id):
    with store.transaction(tenant_id) as db:
        row = db.execute("SELECT id,action_id,rule_version,findings,decision,evidence_digest,policy_digest,created_at "
                         "FROM cp_action_assessments WHERE tenant_id=%s AND id=%s", (tenant_id, assessment_id)).fetchone()
    if row is None:
        raise NotFoundError()
    return dict(id=str(row[0]), action_id=row[1], rule_version=row[2], findings=_load(row[3]), decision=row[4],
                evidence_digest=row[5], policy_digest=row[6], created_at=str(row[7]))


def create_plan(store, tenant_id, objective, owner_hash):
    plan_id = str(uuid4())
    with store.transaction(tenant_id) as db:
        db.execute("INSERT INTO cp_plans(id,tenant_id,objective,owner_hash,created_at) VALUES(%s,%s,%s,%s,%s)",
                   (plan_id, tenant_id, objective, owner_hash, _now()))
    return plan_id


def add_plan_version(store, tenant_id, plan_id, expected_version, identity_digest, targets, parameters,
                     policy_digest, evidence_digest, actor_hash):
    """expected_version is the caller's latest version (0 for the first). A stale value raises ConflictError."""
    version_id, now = str(uuid4()), _now()
    with store.transaction(tenant_id) as db:
        if db.execute("SELECT 1 FROM cp_plans WHERE tenant_id=%s AND id=%s", (tenant_id, plan_id)).fetchone() is None:
            raise NotFoundError()
        row = db.execute("SELECT COALESCE(MAX(version),0) FROM cp_plan_versions WHERE tenant_id=%s AND plan_id=%s",
                         (tenant_id, plan_id)).fetchone()
        if int(row[0]) != int(expected_version):
            raise ConflictError("plan changed; reload before creating a new version")
        version = int(row[0]) + 1
        db.execute("INSERT INTO cp_plan_versions(id,tenant_id,plan_id,version,identity_digest,targets,parameters,"
                   "policy_digest,evidence_digest,state,created_by_hash,created_at,updated_at) "
                   "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,'draft',%s,%s,%s)",
                   (version_id, tenant_id, plan_id, version, identity_digest, db.json(targets), db.json(parameters),
                    policy_digest, evidence_digest, actor_hash, now, now))
    return dict(id=version_id, version=version)


def transition_state(store, tenant_id, version_id, from_state, to_state):
    """Compare-and-set; a concurrent change or illegal transition raises ConflictError."""
    if to_state not in ALLOWED.get(from_state, ()):
        raise ConflictError(f"illegal transition {from_state} -> {to_state}")
    with store.transaction(tenant_id) as db:
        cur = db.execute("UPDATE cp_plan_versions SET state=%s,updated_at=%s WHERE tenant_id=%s AND id=%s AND state=%s",
                         (to_state, _now(), tenant_id, version_id, from_state))
        if _rowcount(cur) != 1:
            raise ConflictError("state changed concurrently or version not found")


def get_plan_version(store, tenant_id, version_id):
    with store.transaction(tenant_id) as db:
        row = db.execute("SELECT id,plan_id,version,identity_digest,targets,parameters,policy_digest,evidence_digest,state "
                         "FROM cp_plan_versions WHERE tenant_id=%s AND id=%s", (tenant_id, version_id)).fetchone()
    if row is None:
        raise NotFoundError()
    return dict(id=str(row[0]), plan_id=str(row[1]), version=row[2], identity_digest=row[3], targets=_load(row[4]),
                parameters=_load(row[5]), policy_digest=row[6], evidence_digest=row[7], state=row[8])


def record_approval(store, tenant_id, version_id, identity_digest, approver_hash, verified_human, expires_at):
    """Refuses unless the digest matches the stored version, so edited plans cannot inherit approval."""
    if not verified_human:
        raise ConflictError("approvals require a verified human")
    approval_id = str(uuid4())
    with store.transaction(tenant_id) as db:
        row = db.execute("SELECT identity_digest FROM cp_plan_versions WHERE tenant_id=%s AND id=%s",
                         (tenant_id, version_id)).fetchone()
        if row is None:
            raise NotFoundError()
        if row[0] != identity_digest:
            raise ConflictError("approval does not match this plan version")
        db.execute("INSERT INTO cp_plan_approvals(id,tenant_id,plan_version_id,identity_digest,approver_hash,"
                   "verified_human,expires_at,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
                   (approval_id, tenant_id, version_id, identity_digest, approver_hash, True, expires_at, _now()))
    return approval_id


def claim_delivery(store, tenant_id, delivery_id, repo_id):
    """True only for the first delivery of this id (webhook replay protection)."""
    with store.transaction(tenant_id) as db:
        cur = db.execute("INSERT INTO cp_gitops_deliveries(id,tenant_id,delivery_id,repo_id,received_at) "
                         "VALUES(%s,%s,%s,%s,%s) ON CONFLICT (tenant_id,delivery_id) DO NOTHING",
                         (str(uuid4()), tenant_id, delivery_id, repo_id, _now()))
    return _rowcount(cur) == 1


def record_check(store, tenant_id, rec, conclusion):
    with store.transaction(tenant_id) as db:
        db.execute("INSERT INTO cp_gitops_checks(id,tenant_id,repo_id,base_sha,head_sha,plan_digest,policy_digest,"
                   "evidence_digest,decision,trusted_plan,conclusion,created_at) "
                   "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                   (str(uuid4()), tenant_id, rec.repo_id, rec.base_sha, rec.head_sha, rec.plan_digest, rec.policy_digest,
                    rec.evidence_digest, rec.decision, rec.trusted_plan, conclusion, _now()))


def record_reminder(store, tenant_id, commitment_id, threshold_days, days_remaining):
    """True only the first time a threshold is crossed for a commitment."""
    with store.transaction(tenant_id) as db:
        cur = db.execute("INSERT INTO cp_commitment_reminders(id,tenant_id,commitment_id,threshold_days,days_remaining,"
                         "created_at) VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT (tenant_id,commitment_id,threshold_days) DO NOTHING",
                         (str(uuid4()), tenant_id, commitment_id, threshold_days, days_remaining, _now()))
    return _rowcount(cur) == 1


def sent_reminders(store, tenant_id):
    with store.transaction(tenant_id) as db:
        rows = db.execute("SELECT commitment_id,threshold_days FROM cp_commitment_reminders WHERE tenant_id=%s",
                          (tenant_id,)).fetchall()
    return {(r[0], r[1]) for r in rows}
