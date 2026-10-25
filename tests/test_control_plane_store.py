"""Storage tests against a recording fake in the repo's store.transaction(tenant) shape.
They verify tenant filtering, idempotency and guards; they do not execute SQL on PostgreSQL."""
from contextlib import contextmanager

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
    def transaction(self, tenant_id):
        self.tenants.append(tenant_id)
        yield self.db


def test_every_read_and_write_filters_by_tenant():
    with pytest.raises(cs.NotFoundError):
        cs.get_plan_version(FakeStore([Cur()]), "t1", "x")
    s = FakeStore([Cur(), Cur([("id1",)])])
    cs.save_financial_scenario(s, "t1", "key-0001", "USD", {}, {"status": "computed"}, "h")
    assert s.tenants == ["t1"]
    for sql, params in s.db.calls:
        assert "tenant_id" in sql and "t1" in params


def test_idempotent_scenario_returns_existing_id():
    s = FakeStore([Cur(), Cur([("existing",)])])
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
    cs.transition_state(FakeStore([Cur(rowcount=1)]), "t1", "v", "approved", "queued")


def test_approval_requires_matching_digest_and_human():
    with pytest.raises(cs.ConflictError):
        cs.record_approval(FakeStore([Cur([("other",)])]), "t1", "v", "digest", "a", True, "2030-01-01")
    with pytest.raises(cs.ConflictError):
        cs.record_approval(FakeStore(), "t1", "v", "digest", "a", False, "2030-01-01")
    assert cs.record_approval(FakeStore([Cur([("digest",)]), Cur()]), "t1", "v", "digest", "a", True, "2030-01-01")


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
