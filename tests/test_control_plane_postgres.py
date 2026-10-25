"""Control-plane isolation, concurrency, intent and rollback checks on isolated PostgreSQL databases."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import threading
from types import SimpleNamespace
from uuid import uuid4

import psycopg
from psycopg import sql
import pytest

from app.control_plane import store as cp
from app.control_plane.gitops_checks import CheckRecord
from app.enterprise_store import EnterpriseStore

ROOT = Path(__file__).resolve().parents[1]
from tests.test_outcomes import financial_postgres  # noqa: F401
from urllib.parse import urlsplit, urlunsplit
TABLES = ("cp_financial_scenarios", "cp_action_assessments", "cp_plans",
          "cp_plan_versions", "cp_plan_approvals", "cp_gitops_deliveries",
          "cp_gitops_checks", "cp_commitment_reminders")
ACTOR = "a" * 64
DIGEST = "d" * 64


@pytest.fixture
def repository(financial_postgres):
    runtime = financial_postgres
    owner = urlunsplit(urlsplit(os.environ["CLOUDSAVER_TEST_OWNER_URL"])._replace(path=urlsplit(runtime).path))
    store = EnterpriseStore(SimpleNamespace(database_url=runtime, database="/tmp/unused-control-plane.db"))
    return store, owner, runtime


def create_version(store, tenant):
    plan = cp.create_plan(store, tenant, "Independent integration test", ACTOR)
    version = cp.add_plan_version(store, tenant, plan, 0, DIGEST, ["vm"],
                                 {"sku": "D2"}, DIGEST, DIGEST, ACTOR)
    return plan, version["id"]


def test_real_tables_have_forced_rls_and_restricted_runtime(repository):
    store, _, _ = repository
    with store.transaction(str(uuid4())) as db:
        assert db.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone() == (False, False)
        for table in TABLES:
            assert db.execute("SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid=to_regclass(%s)",
                              ("public." + table,)).fetchone() == (True, True)


def test_real_tenant_reads_and_foreign_relationships(repository):
    store, _, _ = repository
    a, b = str(uuid4()), str(uuid4())
    plan, version = create_version(store, a)
    assert cp.get_plan_version(store, a, version)["plan_id"] == plan
    with pytest.raises(cp.NotFoundError):
        cp.get_plan_version(store, b, version)
    with store.transaction(b) as db:
        assert db.execute("SELECT count(*) FROM cp_plan_versions").fetchone()[0] == 0
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with store.transaction(b) as db:
            db.execute("INSERT INTO cp_plan_versions(id,tenant_id,plan_id,version,identity_digest,targets,parameters,"
                       "policy_digest,evidence_digest,created_by_hash,created_at,updated_at) "
                       "VALUES(%s,%s,%s,1,%s,%s,%s,%s,%s,%s,now(),now())",
                       (str(uuid4()), b, plan, DIGEST, db.json(["vm"]), db.json({}), DIGEST, DIGEST, ACTOR))


def test_no_context_cannot_read_or_insert(repository):
    _, _, runtime = repository
    with psycopg.connect(runtime) as db:
        assert db.execute("SELECT count(*) FROM cp_plans").fetchone()[0] == 0
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            db.execute("INSERT INTO cp_plans(id,tenant_id,objective,owner_hash,created_at) VALUES(%s,%s,%s,%s,now())",
                       (str(uuid4()), str(uuid4()), "test", ACTOR))


@pytest.mark.parametrize("table", TABLES)
def test_runtime_cannot_delete_or_rewrite_immutable_columns(repository, table):
    store, _, _ = repository
    for statement in ("DELETE FROM {} WHERE false", "UPDATE {} SET tenant_id=tenant_id WHERE false"):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with store.transaction(str(uuid4())) as db:
                db.execute(statement.format(table))


def test_concurrent_version_requests_return_a_domain_conflict(repository):
    store, _, _ = repository
    tenant = str(uuid4())
    plan = cp.create_plan(store, tenant, "Concurrent version test", ACTOR)
    barrier = threading.Barrier(2)

    def save():
        barrier.wait(timeout=10)
        try:
            cp.add_plan_version(store, tenant, plan, 0, DIGEST, ["vm"], {}, DIGEST, DIGEST, ACTOR)
            return "saved"
        except Exception as error:
            return type(error).__name__

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: save(), range(2)))
    assert sorted(outcomes) == ["ConflictError", "saved"]


def test_real_storage_rejects_a_changed_idempotent_request(repository):
    store, _, _ = repository
    tenant = str(uuid4())
    cp.save_financial_scenario(store, tenant, "same-key", "USD", {"amount": "1"},
                               {"status": "computed"}, ACTOR)
    with pytest.raises(cp.ConflictError):
        cp.save_financial_scenario(store, tenant, "same-key", "USD", {"amount": "999"},
                                   {"status": "computed"}, ACTOR)


def test_check_storage_refuses_a_contradictory_success(repository):
    store, _, _ = repository
    rec = CheckRecord(1, "b" * 40, "c" * 40, DIGEST, DIGEST, DIGEST, "blocked", False)
    with pytest.raises((cp.ConflictError, ValueError)):
        cp.record_check(store, str(uuid4()), rec, "success")


def test_real_approval_rejects_string_false_human(repository):
    store, _, _ = repository
    tenant = str(uuid4())
    _, version = create_version(store, tenant)
    with pytest.raises((cp.ConflictError, ValueError)):
        cp.record_approval(store, tenant, version, DIGEST, "b" * 64, "false",
                           datetime.now(timezone.utc) + timedelta(hours=1))


def request_review(store, tenant, version):
    cp.transition_state(store, tenant, version, "draft", "assessed")
    cp.transition_state(store, tenant, version, "assessed", "review_requested")


def test_real_queue_requires_current_approval_and_latest_version(repository):
    store, _, _ = repository
    tenant = str(uuid4())
    plan, version = create_version(store, tenant)
    request_review(store, tenant, version)
    with pytest.raises(cp.ConflictError):
        cp.transition_state(store, tenant, version, "review_requested", "approved")
    cp.record_approval(store, tenant, version, DIGEST, "b" * 64, True,
                       datetime.now(timezone.utc) + timedelta(hours=1))
    cp.transition_state(store, tenant, version, "review_requested", "approved")
    cp.transition_state(store, tenant, version, "approved", "queued")
    cp.add_plan_version(store, tenant, plan, 1, "e" * 64, ["vm"], {"sku": "D4"}, DIGEST, DIGEST, ACTOR)
    with pytest.raises(cp.ConflictError):
        cp.transition_state(store, tenant, version, "queued", "running")
    with pytest.raises(cp.NotFoundError):
        cp.record_approval(store, tenant, version, DIGEST, "b" * 64, True,
                           datetime.now(timezone.utc) + timedelta(hours=1))


def test_expired_approval_cannot_queue(repository, monkeypatch):
    store, _, _ = repository
    tenant = str(uuid4())
    _, version = create_version(store, tenant)
    request_review(store, tenant, version)
    cp.record_approval(store, tenant, version, DIGEST, "b" * 64, True,
                       datetime.now(timezone.utc) + timedelta(minutes=5))
    cp.transition_state(store, tenant, version, "review_requested", "approved")
    monkeypatch.setattr(cp, "_now", lambda: (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat())
    with pytest.raises(cp.ConflictError):
        cp.transition_state(store, tenant, version, "approved", "queued")


def test_startup_refuses_unforced_control_plane_rls(repository):
    _, owner, runtime = repository
    with psycopg.connect(owner) as db:
        db.execute("ALTER TABLE cp_plans NO FORCE ROW LEVEL SECURITY")
    try:
        with pytest.raises(ValueError, match="cp_plans"):
            EnterpriseStore(SimpleNamespace(database_url=runtime, database="/tmp/unused-control-plane.db"))
    finally:
        with psycopg.connect(owner) as db:
            db.execute("ALTER TABLE cp_plans FORCE ROW LEVEL SECURITY")


def test_populated_downgrade_preserves_control_plane_history(repository, monkeypatch):
    store, owner, _ = repository
    tenant = str(uuid4())
    cp.create_plan(store, tenant, "Must retain this history", ACTOR)
    spec = importlib.util.spec_from_file_location("cp_migration_probe", ROOT / "migrations/versions/0026_control_plane.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    from alembic import op
    with psycopg.connect(owner) as db:
        db.execute("SELECT set_config('app.current_tenant_id',%s,true)", (tenant,))
        assert db.execute("SELECT count(*) FROM cp_plans").fetchone()[0] == 1
        db.execute("SAVEPOINT safe_downgrade_probe")
        destructive = False
        try:
            monkeypatch.setattr(op, "execute", lambda statement: db.execute(str(statement)))
            class Bind:
                def execute(self, statement):
                    cursor = db.execute(str(statement))
                    return SimpleNamespace(scalar=lambda: cursor.fetchone()[0])
            monkeypatch.setattr(op, "get_bind", lambda: Bind())
            try:
                module.downgrade()
                destructive = db.execute("SELECT to_regclass('public.cp_plans')").fetchone()[0] is None
            except (ValueError, RuntimeError):
                pass
        finally:
            db.execute("ROLLBACK TO SAVEPOINT safe_downgrade_probe")
        assert destructive is False, "downgrade dropped populated control-plane history"
        for table in TABLES:
            assert db.execute("SELECT relforcerowsecurity FROM pg_class WHERE oid=to_regclass(%s)", (table,)).fetchone()[0]
