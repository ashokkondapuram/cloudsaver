"""Storage tests against a recording fake in the repo's store.transaction(tenant) shape.
They verify tenant filtering, idempotency and guards; they do not execute SQL on PostgreSQL."""
from contextlib import contextmanager

from datetime import datetime, timezone

import pytest

from app.control_plane import store as cs
from app.control_plane.gitops_checks import CheckRecord


class Cur:
    def __init__(self, rows=None, rowcount=1):
        self._rows, self.rowcount = rows or [], rowcount

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows


class FakeDb:
    def __init__(self, script):
        self.calls, self.script = [], list(script)

    def json(self, v):
        return v

    def execute(self, sql, params=()):
        self.calls.append((sql, params))
        return self.script.pop(0) if self.script else Cur()


class FakeStore:
    def __init__(self, script=()):
        self.db, self.tenants = FakeDb(script), []

    @contextmanager
    def transaction(self, tenant_id, *, write=False):
        self.tenants.append(tenant_id)
        yield self.db


def test_every_read_and_write_filters_by_tenant():
    with pytest.raises(cs.NotFoundError):
        cs.get_plan_version(FakeStore([Cur()]), "t1", "x")
    s = FakeStore([Cur(), Cur([("id1", {}, "USD", None)])])
    cs.save_financial_scenario(s, "t1", "key-0001", "USD", {}, {"status": "computed"}, "h")
    assert s.tenants == ["t1"]
    for sql, params in s.db.calls:
        assert "tenant_id" in sql and "t1" in params


def test_idempotent_scenario_returns_existing_id():
    s = FakeStore([Cur(), Cur([("existing", {}, "USD", None)])])
    assert cs.save_financial_scenario(s, "t1", "key-0001", "USD", {}, {}, "h") == "existing"
    assert "ON CONFLICT (tenant_id,idempotency_key) DO NOTHING" in s.db.calls[0][0]


def test_stale_expected_version_conflicts():
    s = FakeStore([Cur([(1,)]), Cur([(3,)])])
    with pytest.raises(cs.ConflictError):
        cs.add_plan_version(s, "t1", "p", 2, "d", [], {}, "pol", "ev", "h")


def test_first_version_is_one_and_unknown_plan_not_found():
    s = FakeStore([Cur([(1,)]), Cur([(0,)]), Cur()])
    assert cs.add_plan_version(s, "t1", "p", 0, "d", [], {}, "pol", "ev", "h")["version"] == 1
    with pytest.raises(cs.NotFoundError):
        cs.add_plan_version(FakeStore([Cur()]), "t1", "p", 0, "d", [], {}, "pol", "ev", "h")


def test_illegal_and_concurrent_transitions():
    with pytest.raises(cs.ConflictError):
        cs.transition_state(FakeStore(), "t1", "v", "draft", "running")
    with pytest.raises(cs.ConflictError):
        cs.transition_state(FakeStore([Cur(rowcount=0)]), "t1", "v", "approved", "queued")
    cs.transition_state(FakeStore([Cur([(1,)]), Cur(rowcount=1)]), "t1", "v", "approved", "queued")


def test_approval_requires_matching_digest_and_human():
    with pytest.raises(cs.ConflictError):
        cs.record_approval(FakeStore([Cur([("other",)])]), "t1", "v", "digest", "a", True, datetime(2030, 1, 1, tzinfo=timezone.utc))
    with pytest.raises(cs.ConflictError):
        cs.record_approval(FakeStore(), "t1", "v", "digest", "a", False, datetime(2030, 1, 1, tzinfo=timezone.utc))
    assert cs.record_approval(FakeStore([Cur([("digest", "review_requested", "creator")]), Cur()]), "t1", "v", "digest", "a", True, datetime(2030, 1, 1, tzinfo=timezone.utc))


def test_approval_rejects_the_version_creator_as_approver():
    with pytest.raises(cs.ConflictError):
        cs.record_approval(FakeStore([Cur([("digest", "review_requested", "a")])]), "t1", "v", "digest", "a", True, datetime(2030, 1, 1, tzinfo=timezone.utc))


def test_replay_protection_and_reminders():
    assert cs.claim_delivery(FakeStore([Cur(rowcount=1)]), "t1", "d1", 7) is True
    assert cs.claim_delivery(FakeStore([Cur(rowcount=0)]), "t1", "d1", 7) is False
    assert cs.record_reminder(FakeStore([Cur(rowcount=0)]), "t1", "c1", 60, 40) is False
    assert cs.sent_reminders(FakeStore([Cur([("c1", 60)])]), "t1") == {("c1", 60)}


def test_record_check_is_insert_only():
    s = FakeStore()
    cs.record_check(s, "t1", CheckRecord(1, "b", "h", "pd", "pol", "ev", "blocked", True), "failure")
    sql = s.db.calls[0][0]
    assert sql.startswith("INSERT") and "ON CONFLICT DO NOTHING" in sql


# --- Real EnterpriseStore (SQLite) integration: the control-plane tables must exist and be
# reachable through the production store shape, not just the FakeStore above. ---
from tests.test_enterprise import evidence, workspace, TID  # noqa: E402


def test_control_plane_tables_exist(evidence):
    settings, repo, scan = evidence
    with repo.transaction(TID) as db:
        for table in ('cp_plans', 'cp_plan_versions', 'cp_plan_approvals', 'cp_action_assessments'):
            db.execute(f'SELECT COUNT(*) FROM {table}')  # raises OperationalError if the table is missing


def test_plan_version_update_trigger_blocks_non_state_columns(evidence):
    settings, repo, scan = evidence
    import sqlite3
    with repo.transaction(TID, write=True) as db:
        db.execute("INSERT INTO cp_plans(id,tenant_id,objective,owner_hash,created_at) VALUES('p1',%s,'x','h','2026-01-01')", (TID,))
        db.execute("INSERT INTO cp_plan_versions(id,tenant_id,plan_id,version,identity_digest,targets,parameters,policy_digest,evidence_digest,state,created_by_hash,created_at,updated_at) "
                   "VALUES('v1',%s,'p1',1,'d','[]','{}','p','e','draft','h','2026-01-01','2026-01-01')", (TID,))
    with pytest.raises(sqlite3.IntegrityError):
        with repo.transaction(TID, write=True) as db:
            db.execute("UPDATE cp_plan_versions SET targets='[\"changed\"]' WHERE id='v1'")
    with repo.transaction(TID, write=True) as db:
        db.execute("UPDATE cp_plan_versions SET state='assessed',updated_at='2026-01-02' WHERE id='v1'")
    with repo.transaction(TID) as db:
        row = db.execute("SELECT state FROM cp_plan_versions WHERE id='v1'").fetchone()
    assert row[0] == 'assessed'


def test_record_approval_against_real_store_accepts_a_future_expiry(evidence):
    """record_approval binds a raw datetime; SQLite's default adapter must not format it
    differently than the app's own _now() string, or the expires_at>created_at CHECK
    would compare two incompatible string formats and reject a genuinely future expiry."""
    from datetime import timedelta, timezone
    settings, repo, scan = evidence
    plan_id = cs.create_plan(repo, TID, 'x', 'ownerhash')
    pv_result = cs.add_plan_version(repo, TID, plan_id, 0, 'identity-1', ['r1'], {}, 'pd', 'ed', 'actorhash')
    cs.transition_state(repo, TID, pv_result['id'], 'draft', 'evidence_required')
    cs.transition_state(repo, TID, pv_result['id'], 'evidence_required', 'assessed')
    cs.transition_state(repo, TID, pv_result['id'], 'assessed', 'review_requested')
    approval_id = cs.record_approval(repo, TID, pv_result['id'], 'identity-1', 'approverhash', True,
                                     datetime.now(timezone.utc) + timedelta(hours=1))
    assert approval_id


def test_record_approval_against_real_store_rejects_the_version_creator(evidence):
    from datetime import timedelta, timezone
    settings, repo, scan = evidence
    plan_id = cs.create_plan(repo, TID, 'x', 'sameactor')
    pv_result = cs.add_plan_version(repo, TID, plan_id, 0, 'identity-2', ['r1'], {}, 'pd', 'ed', 'sameactor')
    cs.transition_state(repo, TID, pv_result['id'], 'draft', 'evidence_required')
    cs.transition_state(repo, TID, pv_result['id'], 'evidence_required', 'assessed')
    cs.transition_state(repo, TID, pv_result['id'], 'assessed', 'review_requested')
    with pytest.raises(cs.ConflictError):
        cs.record_approval(repo, TID, pv_result['id'], 'identity-2', 'sameactor', True,
                           datetime.now(timezone.utc) + timedelta(hours=1))


def test_record_approval_against_real_store_accepts_a_non_utc_offset_expiry(evidence):
    """A client-supplied non-UTC offset must be normalized before it is compared as TEXT against
    created_at (also TEXT); otherwise two timestamps that are the same instant in different offsets
    compare incorrectly under SQLite's lexicographic CHECK, and later under transition_state's
    expires_at>%s comparison too."""
    from datetime import timedelta, timezone
    settings, repo, scan = evidence
    plan_id = cs.create_plan(repo, TID, 'x', 'ownerhash')
    pv_result = cs.add_plan_version(repo, TID, plan_id, 0, 'identity-3', ['r1'], {}, 'pd', 'ed', 'actorhash')
    cs.transition_state(repo, TID, pv_result['id'], 'draft', 'evidence_required')
    cs.transition_state(repo, TID, pv_result['id'], 'evidence_required', 'assessed')
    cs.transition_state(repo, TID, pv_result['id'], 'assessed', 'review_requested')
    non_utc = (datetime.now(timezone.utc) + timedelta(hours=1)).astimezone(timezone(timedelta(hours=-8)))
    approval_id = cs.record_approval(repo, TID, pv_result['id'], 'identity-3', 'approverhash', True, non_utc)
    assert approval_id
    cs.transition_state(repo, TID, pv_result['id'], 'review_requested', 'approved')
