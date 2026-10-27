# Control-Plane Plan Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the service layer and REST API for the existing-but-unused `cp_plans` / `cp_plan_versions` / `cp_plan_approvals` / `cp_action_assessments` schema (migration `0026_control_plane.py`), completing the spec's propose → assess → approve chain without touching GitOps execution, financial scenarios, or commitment reminders (each deferred to its own follow-up plan).

**Architecture:** One new store module (`app/control_plane_store.py`) following the existing `ObservabilityStore`/`BillingJobs` pattern (a class wrapping `EnterpriseStore`'s tenant-scoped transactions), plus one new FastAPI router (`app/control_plane_api.py`) mounted at `/api/v1/plans` alongside the other domain routers in `app/main.py`. No new tables: the Postgres schema and RLS already exist from migration `0026_control_plane.py`; this plan only adds the missing SQLite parity (for tests/dev) and the application code on top.

**Tech Stack:** Python, FastAPI, the project's existing `EnterpriseStore` (Postgres with forced RLS in production, SQLite in dev/test), pytest + `TestClient`.

**Spec:** The user-pasted CloudSaver architecture spec (Appendix B "Improvement planning"/"Approval" components, Appendix D plan/plan-version/approval routes, Appendix E `plan`/`plan_version`/`approval` tables, Section H "Ownership, proposal and approval" steps 3 and 5, and the change state machine `draft → validated → approval_pending → approved → execution_queued → executing → applied_unverified → verified | verification_failed`). Note the *existing* migration uses its own, already-reviewed state names (`draft, evidence_required, assessed, review_requested, approved, queued, running, verification_pending, verified, failed, reconciliation_required, cancelled, expired` — see `migrations/versions/0026_control_plane.py:27-28`); this plan implements against the **existing migration's state names**, not the spec's prose names, since the schema is already migrated and reviewed.

## Global Constraints

- DB grants on `cp_plans`, `cp_plan_approvals`, `cp_action_assessments` are `SELECT,INSERT` only — these rows are **immutable once written**; the service layer must never attempt `UPDATE`/`DELETE` on them.
- `cp_plan_versions` additionally grants `UPDATE (state, updated_at)` only (`migrations/versions/0026_control_plane.py:63`) — every other column on an existing plan-version row is immutable; a new fact requires a new plan version, not an edit.
- `cp_plan_approvals.verified_human` has a DB `CHECK (verified_human=true)` (line 31) — the API must only ever insert `true`; there is no path to record an automated/non-human approval in this table.
- The approver must not be the same person who created the plan version being approved (spec Section H step 5: "The requester and automation cannot approve their own change"). Compare `actor(tenant)` hashes, not role names (this app's `Role` enum has no distinct "Engineer"/"Approver" split — see `app/auth.py:16-19`).
- Reuse `app.focus.digest` (canonical `sha256(json.dumps(value, sort_keys=True, separators=(',',':')))`, `app/focus.py:138-139`) for every `*_digest` column — do not invent a second hashing scheme.
- Reuse `app.observability_store.actor(tenant)` (`app/observability_store.py:23-24`) for every `*_hash` column — do not duplicate this helper.
- Follow the existing router convention exactly: `def create_router(store, current_tenant):` returning an `APIRouter`, mounted via `api.include_router(control_plane_router(evidence_store, current_tenant))` in `app/main.py` next to the other `api.include_router(...)` calls (see `app/main.py:66-71` for the exact sibling pattern).
- Gate every mutating route behind `require_workspace_role(tenant, Role.TENANT_ADMIN)` (`app/auth.py:92-95`), matching the existing pattern in `app/finops_api.py`'s `finance()`/`require_workspace_role` helper dependency.

## Review Focus

- Self-approval: a plan version's `created_by_hash` actor attempts to approve their own version — must be rejected (spec Section H step 5).
- Stale approval after a new version: version 1 is approved, then version 2 of the same plan is created — version 2 has no approval of its own and a transition to `approved` on version 2 must fail (spec's "a new artifact or material state change requires new approval").
- Illegal state transition: attempting `draft → approved` directly (skipping `evidence_required`/`assessed`/`review_requested`) must be rejected (spec's state machine is not a free-for-all).
- Idempotency-key reuse with a different body: two `POST` action-assessments share an idempotency key but different `action_id`/`findings` — must return a conflict, not silently serve the first result (spec's "Additional request and pagination invariants": "a changed body returns 409 idempotency_conflict").
- Expired approval: an approval row exists but its `expires_at` is in the past — a transition to `approved` using it must fail (spec's "expiration job" / "Changed artifact/state, revoked authority or expired approval blocks dispatch").

---

## Task 1: SQLite schema parity for the control-plane tables

**Files:**
- Modify: `app/enterprise_store.py` (inside the `else:` / SQLite branch's `executescript(...)` call, alongside the existing `savings_*` table block — see lines 151–177 for the exact style to match: `TEXT` columns, `UNIQUE(...)`, `CREATE TRIGGER ... BEFORE UPDATE/DELETE ... RAISE(ABORT, '...')` for append-only tables)
- Test: `tests/test_control_plane_store.py`

**Interfaces:**
- Produces: four working SQLite tables — `cp_plans`, `cp_plan_versions`, `cp_plan_approvals`, `cp_action_assessments` — reachable through the existing `evidence` pytest fixture (`tests/test_enterprise.py:42-48`, which builds a SQLite-backed `EnterpriseStore`). Later tasks' `ControlPlaneStore` methods run against these tables in tests exactly as they would against the real Postgres schema in production (Postgres already has them via `migrations/versions/0026_control_plane.py`; this task only fixes the dev/test SQLite path, which currently has no DDL for these tables at all).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_control_plane_store.py
from tests.test_enterprise import evidence, workspace, TID

def test_control_plane_tables_exist(evidence):
    settings, repo, scan = evidence
    with repo.store.transaction(TID) as db:
        for table in ('cp_plans', 'cp_plan_versions', 'cp_plan_approvals', 'cp_action_assessments'):
            db.execute(f'SELECT COUNT(*) FROM {table}')  # raises OperationalError if the table is missing
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_control_plane_store.py::test_control_plane_tables_exist -v`
Expected: FAIL with `sqlite3.OperationalError: no such table: cp_plans`

- [ ] **Step 3: Add the four `CREATE TABLE IF NOT EXISTS` statements (plus triggers) to the SQLite `executescript` block in `app/enterprise_store.py`**

Mirror the Postgres column list from `migrations/versions/0026_control_plane.py:11-28` exactly, using SQLite types (`TEXT` for `uuid`/`jsonb`/`timestamptz`/`varchar`, `INTEGER` for `integer`, SQLite's loose `boolean` affinity for `verified_human`). Keep every `UNIQUE(...)` and `CHECK(...)` clause from the Postgres DDL (SQLite supports both). Add:
  - `BEFORE UPDATE`/`BEFORE DELETE` triggers raising `ABORT` on `cp_plans`, `cp_plan_approvals`, `cp_action_assessments` (fully immutable, matching the Postgres `SELECT,INSERT`-only grant).
  - One `BEFORE UPDATE` trigger on `cp_plan_versions` that raises `ABORT` unless every column *except* `state` and `updated_at` is unchanged between `OLD` and `NEW` (matching the Postgres `GRANT UPDATE (state, updated_at)` at line 63). No `BEFORE DELETE` trigger is needed since Postgres grants no `DELETE` either, but add one for consistency with the fully-immutable tables.
- Also add `'cp_plans'`, `'cp_plan_versions'`, `'cp_plan_approvals'`, `'cp_action_assessments'` to the `TABLES` tuple check that the SQLite bootstrap uses to confirm table creation (follow however the existing `savings_*` tables are registered, if they're listed separately from `CONTROL_PLANE_TABLES`).

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_control_plane_store.py::test_control_plane_tables_exist -v`
Expected: PASS

- [ ] **Step 5: Write a failing test for the restricted-update trigger**

```python
def test_plan_version_update_trigger_blocks_non_state_columns(evidence):
    settings, repo, scan = evidence
    import sqlite3, pytest
    with repo.store.transaction(TID, write=True) as db:
        db.execute("INSERT INTO cp_plans(id,tenant_id,objective,owner_hash,created_at) VALUES('p1',%s,'x','h','2026-01-01')", (TID,))
        db.execute("INSERT INTO cp_plan_versions(id,tenant_id,plan_id,version,identity_digest,targets,parameters,policy_digest,evidence_digest,state,created_by_hash,created_at,updated_at) "
                   "VALUES('v1',%s,'p1',1,'d','[]','{}','p','e','draft','h','2026-01-01','2026-01-01')", (TID,))
    with pytest.raises(sqlite3.OperationalError):
        with repo.store.transaction(TID, write=True) as db:
            db.execute("UPDATE cp_plan_versions SET objective_unused=1 WHERE id='v1'")  # placeholder; use an real immutable column, e.g. targets
```

(Adjust the UPDATE to target a real immutable column, e.g. `targets`, and confirm a same-transaction `UPDATE ... SET state='assessed', updated_at=...` on the same row still succeeds in a second assertion.)

- [ ] **Step 6: Run test to verify it passes**

Run: `python3 -m pytest tests/test_control_plane_store.py -v`
Expected: PASS (both tests)

- [ ] **Step 7: Commit**

```bash
git add app/enterprise_store.py tests/test_control_plane_store.py
git commit -m "test: add SQLite parity for the control-plane plan/assessment tables"
```

---

## Task 2: Plans and plan versions

**Files:**
- Create: `app/control_plane_store.py`
- Modify: `tests/test_control_plane_store.py`

**Interfaces:**
- Consumes: `app.observability_store.actor(tenant) -> str`, `app.focus.digest(value) -> str`, `app.v150_store.WorkflowConflict`.
- Produces:
  - `class ControlPlaneStore: def __init__(self, store):`
  - `def create_plan(self, tenant: dict, objective: str) -> dict` — returns `{id, objective, owner_hash, created_at}`. Raises `ValueError` if `objective` is empty or over 500 chars.
  - `def get_plan(self, tid: str, id: str) -> dict | None`
  - `def list_plans(self, tid: str, *, limit: int = 50) -> list[dict]`
  - `def create_plan_version(self, tenant: dict, plan_id: str, *, targets: list[dict], parameters: dict) -> dict` — returns `{id, plan_id, version, identity_digest, targets, parameters, policy_digest, evidence_digest, state, created_by_hash, created_at, updated_at}`. `version` auto-increments per `plan_id` starting at 1. Initial `state` is `'draft'`. `identity_digest = digest(targets)`; `evidence_digest = digest([t.get('evidence_id') for t in targets])`; `policy_digest = digest({'rule_policy_version': parameters.get('rule_policy_version')})`. Raises `WorkflowConflict` if `plan_id` doesn't exist for this tenant. Raises `ValueError` if `targets` is empty, not a list, or over 200 entries, or `parameters` is not a dict.
  - `def get_plan_version(self, tid: str, id: str) -> dict | None`
  - `def list_plan_versions(self, tid: str, plan_id: str) -> list[dict]` — ordered by `version` ascending.

- [ ] **Step 1: Write the failing tests**

```python
def test_create_plan_and_list(evidence):
    settings, repo, scan = evidence
    from app.control_plane_store import ControlPlaneStore
    cp = ControlPlaneStore(repo.store)
    plan = cp.create_plan(workspace(), 'Rightsize overprovisioned VMs')
    assert plan['objective'] == 'Rightsize overprovisioned VMs' and plan['id']
    assert cp.get_plan(TID, plan['id']) == plan
    assert cp.list_plans(TID) == [plan]

def test_create_plan_rejects_empty_objective(evidence):
    settings, repo, scan = evidence
    from app.control_plane_store import ControlPlaneStore
    import pytest
    cp = ControlPlaneStore(repo.store)
    with pytest.raises(ValueError):
        cp.create_plan(workspace(), '')

def test_create_plan_version_increments_and_digests(evidence):
    settings, repo, scan = evidence
    from app.control_plane_store import ControlPlaneStore
    cp = ControlPlaneStore(repo.store)
    plan = cp.create_plan(workspace(), 'Rightsize overprovisioned VMs')
    v1 = cp.create_plan_version(workspace(), plan['id'], targets=[{'resource_id': 'r1', 'evidence_id': 'e1'}], parameters={'rule_policy_version': 'pol_1'})
    v2 = cp.create_plan_version(workspace(), plan['id'], targets=[{'resource_id': 'r1', 'evidence_id': 'e2'}], parameters={'rule_policy_version': 'pol_1'})
    assert v1['version'] == 1 and v2['version'] == 2 and v1['state'] == 'draft'
    assert v1['identity_digest'] != v2['identity_digest']  # different evidence_id changes the digest
    assert cp.list_plan_versions(TID, plan['id']) == [v1, v2]

def test_create_plan_version_requires_existing_plan(evidence):
    settings, repo, scan = evidence
    from app.control_plane_store import ControlPlaneStore
    from app.v150_store import WorkflowConflict
    import pytest
    cp = ControlPlaneStore(repo.store)
    with pytest.raises(WorkflowConflict):
        cp.create_plan_version(workspace(), 'does-not-exist', targets=[{'resource_id': 'r1'}], parameters={})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_control_plane_store.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.control_plane_store'`

- [ ] **Step 3: Implement `app/control_plane_store.py`**

Follow `app/observability_store.py`'s shape: module docstring, `_now()` helper, a `_public_plan(row)` / `_public_version(row)` row-shaping staticmethod per table, and the `ControlPlaneStore` class with the methods listed in Interfaces. Use `self.store.transaction(tid, write=True)` for writes and a plain `self.store.transaction(tid)` for reads, matching `ObservabilityStore.create`/`.connector` exactly (`app/observability_store.py:45-60`). Take an advisory lock per plan (`pg_advisory_xact_lock(hashtextextended(%s,0))` keyed on `'cp-plan-version:'+tid+':'+plan_id`, guarded by `if db.postgres:`) before computing the next version number, matching the lock pattern in `ObservabilityStore.create` (line 50).

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_control_plane_store.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/control_plane_store.py tests/test_control_plane_store.py
git commit -m "feat: add ControlPlaneStore plan and plan-version creation"
```

---

## Task 3: State transitions and approvals

**Files:**
- Modify: `app/control_plane_store.py`
- Modify: `tests/test_control_plane_store.py`

**Interfaces:**
- Consumes: `ControlPlaneStore` from Task 2; its `create_plan`/`create_plan_version`/`get_plan_version`.
- Produces:
  - Module-level `TRANSITIONS: dict[str, set[str]]` mapping each non-terminal state to its legal next states, built from `migrations/versions/0026_control_plane.py:27-28`'s `CHECK (state IN (...))` list: `draft→{evidence_required,cancelled,expired}`, `evidence_required→{assessed,cancelled,expired}`, `assessed→{review_requested,cancelled,expired}`, `review_requested→{approved,cancelled,expired}`, `approved→{queued,cancelled,expired}`, `queued→{running,cancelled,expired}`, `running→{verification_pending,failed,reconciliation_required}`, `verification_pending→{verified,failed,reconciliation_required}`. Terminal states (`verified`, `failed`, `cancelled`, `expired`, `reconciliation_required`) map to an empty set.
  - `def transition_plan_version(self, tid: str, plan_version_id: str, *, to_state: str) -> dict` — raises `ValueError` if `to_state` isn't a legal transition from the row's current `state` (including raising for any state not in `TRANSITIONS`). Raises `WorkflowConflict` if the row doesn't exist. If `to_state == 'approved'`, additionally raises `WorkflowConflict` unless an unexpired approval row exists for this exact `plan_version_id` (`cp_plan_approvals` row with `expires_at > now`). Returns the updated version dict (reuse `get_plan_version`).
  - `def record_approval(self, tenant: dict, plan_version_id: str, *, expires_at: str) -> dict` — returns `{id, plan_version_id, approver_hash, expires_at, created_at}`. Raises `WorkflowConflict` if the plan version doesn't exist. Raises `ValueError` if `expires_at` (ISO string) is not strictly after now. Raises `WorkflowConflict` if `actor(tenant) == ` the plan version's `created_by_hash` (self-approval). Always inserts `verified_human=True` (never a parameter — there is no code path to insert `false`, matching the DB `CHECK`).

- [ ] **Step 1: Write the failing tests**

```python
def _version(cp, tenant=None):
    tenant = tenant or workspace()
    plan = cp.create_plan(tenant, 'Rightsize overprovisioned VMs')
    return cp.create_plan_version(tenant, plan['id'], targets=[{'resource_id': 'r1', 'evidence_id': 'e1'}], parameters={})

def test_transition_follows_legal_path(evidence):
    settings, repo, scan = evidence
    from app.control_plane_store import ControlPlaneStore
    cp = ControlPlaneStore(repo.store)
    v = _version(cp)
    updated = cp.transition_plan_version(TID, v['id'], to_state='evidence_required')
    assert updated['state'] == 'evidence_required'

def test_transition_rejects_illegal_jump(evidence):
    settings, repo, scan = evidence
    from app.control_plane_store import ControlPlaneStore
    import pytest
    cp = ControlPlaneStore(repo.store)
    v = _version(cp)
    with pytest.raises(ValueError):
        cp.transition_plan_version(TID, v['id'], to_state='approved')  # draft -> approved skips required stages

def test_approval_rejects_self_approval(evidence):
    settings, repo, scan = evidence
    from app.control_plane_store import ControlPlaneStore
    from app.v150_store import WorkflowConflict
    from datetime import datetime, timedelta, timezone
    import pytest
    cp = ControlPlaneStore(repo.store)
    v = _version(cp)  # created_by_hash == actor(workspace())
    with pytest.raises(WorkflowConflict):
        cp.record_approval(workspace(), v['id'], expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat())

def test_transition_to_approved_requires_unexpired_approval(evidence):
    settings, repo, scan = evidence
    from app.control_plane_store import ControlPlaneStore
    from app.v150_store import WorkflowConflict
    import pytest
    cp = ControlPlaneStore(repo.store)
    v = _version(cp)
    cp.transition_plan_version(TID, v['id'], to_state='evidence_required')
    cp.transition_plan_version(TID, v['id'], to_state='assessed')
    cp.transition_plan_version(TID, v['id'], to_state='review_requested')
    with pytest.raises(WorkflowConflict):
        cp.transition_plan_version(TID, v['id'], to_state='approved')  # no approval row yet

def test_expired_approval_does_not_authorize_transition(evidence):
    settings, repo, scan = evidence
    from app.control_plane_store import ControlPlaneStore
    from app.v150_store import WorkflowConflict
    from datetime import datetime, timedelta, timezone
    import pytest
    cp = ControlPlaneStore(repo.store)
    v = _version(cp)
    other = dict(workspace(), user_id='someone-else')  # different actor so approval isn't self-approval
    cp.record_approval(other, v['id'], expires_at=(datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat())
    import time; time.sleep(1.1)
    for state in ('evidence_required', 'assessed', 'review_requested'):
        cp.transition_plan_version(TID, v['id'], to_state=state)
    with pytest.raises(WorkflowConflict):
        cp.transition_plan_version(TID, v['id'], to_state='approved')

def test_stale_version_has_no_approval_of_its_own(evidence):
    settings, repo, scan = evidence
    from app.control_plane_store import ControlPlaneStore
    from app.v150_store import WorkflowConflict
    from datetime import datetime, timedelta, timezone
    import pytest
    cp = ControlPlaneStore(repo.store)
    tenant = workspace()
    plan = cp.create_plan(tenant, 'Rightsize overprovisioned VMs')
    v1 = cp.create_plan_version(tenant, plan['id'], targets=[{'resource_id': 'r1'}], parameters={})
    other = dict(tenant, user_id='someone-else')
    cp.record_approval(other, v1['id'], expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat())
    v2 = cp.create_plan_version(tenant, plan['id'], targets=[{'resource_id': 'r1', 'evidence_id': 'new'}], parameters={})
    for state in ('evidence_required', 'assessed', 'review_requested'):
        cp.transition_plan_version(TID, v2['id'], to_state=state)
    with pytest.raises(WorkflowConflict):
        cp.transition_plan_version(TID, v2['id'], to_state='approved')  # v1's approval doesn't cover v2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_control_plane_store.py -v -k "transition or approval"`
Expected: FAIL with `AttributeError: 'ControlPlaneStore' object has no attribute 'transition_plan_version'`

- [ ] **Step 3: Implement `TRANSITIONS`, `transition_plan_version`, and `record_approval` in `app/control_plane_store.py`**

`transition_plan_version` reads the current row (`SELECT state,created_by_hash FROM cp_plan_versions WHERE tenant_id=%s AND id=%s`), validates against `TRANSITIONS`, and — only for `to_state == 'approved'` — additionally queries `SELECT 1 FROM cp_plan_approvals WHERE tenant_id=%s AND plan_version_id=%s AND expires_at > %s` (comparing against `_now().isoformat()`) before issuing `UPDATE cp_plan_versions SET state=%s, updated_at=%s WHERE tenant_id=%s AND id=%s`. `record_approval` fetches the plan version's `created_by_hash` first, compares it to `actor(tenant)`, then inserts into `cp_plan_approvals` with `verified_human` hardcoded `true`/`1`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_control_plane_store.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/control_plane_store.py tests/test_control_plane_store.py
git commit -m "feat: add plan-version state transitions and human-approval recording"
```

---

## Task 4: Action assessments

**Files:**
- Modify: `app/control_plane_store.py`
- Modify: `tests/test_control_plane_store.py`

**Interfaces:**
- Produces:
  - `def create_action_assessment(self, tenant: dict, idempotency_key: str, *, action_id: str, rule_version: str, findings: list[dict], decision: str, policy_version: str) -> dict` — `decision` must be one of `'eligible_for_review','blocked','evidence_required','unsupported','expired'` (the exact `CHECK` list at `migrations/versions/0026_control_plane.py:16`), else `ValueError`. `evidence_digest = digest(findings)`, `policy_digest = digest({'rule_policy_version': policy_version})`. If a row already exists for `(tenant_id, idempotency_key)`: if its `action_id`/`findings`/`decision` match the new call byte-for-byte (compare `evidence_digest`/`policy_digest`/`action_id`/`decision`), return the existing row unchanged (idempotent replay); otherwise raise `WorkflowConflict` (409-equivalent per spec's idempotency-conflict rule).
  - `def list_action_assessments(self, tid: str, action_id: str, *, limit: int = 50) -> list[dict]` — ordered by `created_at` descending, matching the index added at `migrations/versions/0026_control_plane.py:64`.

- [ ] **Step 1: Write the failing tests**

```python
def test_create_action_assessment_and_idempotent_replay(evidence):
    settings, repo, scan = evidence
    from app.control_plane_store import ControlPlaneStore
    cp = ControlPlaneStore(repo.store)
    key = 'replay-key-1'
    first = cp.create_action_assessment(workspace(), key, action_id='resize-vm-1', rule_version='v1',
        findings=[{'code': 'CPU_LOW'}], decision='eligible_for_review', policy_version='pol_1')
    second = cp.create_action_assessment(workspace(), key, action_id='resize-vm-1', rule_version='v1',
        findings=[{'code': 'CPU_LOW'}], decision='eligible_for_review', policy_version='pol_1')
    assert first == second
    assert cp.list_action_assessments(TID, 'resize-vm-1') == [first]

def test_create_action_assessment_rejects_invalid_decision(evidence):
    settings, repo, scan = evidence
    from app.control_plane_store import ControlPlaneStore
    import pytest
    cp = ControlPlaneStore(repo.store)
    with pytest.raises(ValueError):
        cp.create_action_assessment(workspace(), 'k1', action_id='a1', rule_version='v1', findings=[], decision='not_a_real_decision', policy_version='pol_1')

def test_create_action_assessment_rejects_changed_body_same_key(evidence):
    settings, repo, scan = evidence
    from app.control_plane_store import ControlPlaneStore
    from app.v150_store import WorkflowConflict
    import pytest
    cp = ControlPlaneStore(repo.store)
    key = 'replay-key-2'
    cp.create_action_assessment(workspace(), key, action_id='resize-vm-1', rule_version='v1', findings=[{'code': 'CPU_LOW'}], decision='eligible_for_review', policy_version='pol_1')
    with pytest.raises(WorkflowConflict):
        cp.create_action_assessment(workspace(), key, action_id='resize-vm-2', rule_version='v1', findings=[{'code': 'CPU_LOW'}], decision='eligible_for_review', policy_version='pol_1')
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_control_plane_store.py -v -k action_assessment`
Expected: FAIL with `AttributeError: 'ControlPlaneStore' object has no attribute 'create_action_assessment'`

- [ ] **Step 3: Implement `create_action_assessment` and `list_action_assessments` in `app/control_plane_store.py`**

Check-then-insert inside one `write=True` transaction: `SELECT action_id,findings,decision,evidence_digest,policy_digest,... FROM cp_action_assessments WHERE tenant_id=%s AND idempotency_key=%s`, compare, then either return the decoded existing row or `INSERT`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_control_plane_store.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/control_plane_store.py tests/test_control_plane_store.py
git commit -m "feat: add idempotent action assessments to ControlPlaneStore"
```

---

## Task 5: REST API and mounting

**Files:**
- Create: `app/control_plane_api.py`
- Modify: `app/main.py` (add the `control_plane_router` import and `api.include_router(...)` call next to the existing routers, `app/main.py:66-71`)
- Create: `tests/test_control_plane_api.py`

**Interfaces:**
- Consumes: `ControlPlaneStore` from Tasks 2–4; `app.auth.Role`, `app.auth.require_workspace_role`; the existing `current_tenant` dependency and `evidence_store` (`EnterpriseStore` instance) already built in `app/main.py`.
- Produces: `def create_router(store, current_tenant) -> APIRouter` with routes:
  - `POST /api/v1/plans` — body `{objective: str}` → 201 `create_plan` result.
  - `GET /api/v1/plans` → `{items: [...]}` from `list_plans`.
  - `GET /api/v1/plans/{id}` → plan dict or 404.
  - `POST /api/v1/plans/{id}/versions` — body `{targets: [...], parameters: {...}}` → 201 `create_plan_version` result; maps `ValueError`→422, `WorkflowConflict`→409.
  - `GET /api/v1/plans/{id}/versions` → `{items: [...]}`.
  - `POST /api/v1/plan-versions/{id}/transitions` — body `{to_state: str}` → 200 updated version; `ValueError`→422, `WorkflowConflict`→409.
  - `POST /api/v1/plan-versions/{id}/approvals` — body `{expires_at: str}` → 201 approval; `ValueError`→422, `WorkflowConflict`→409.
  - `POST /api/v1/action-assessments` — body `{idempotency_key, action_id, rule_version, findings, decision, policy_version}` → 201/200 assessment; `ValueError`→422, `WorkflowConflict`→409.
  - `GET /api/v1/action-assessments?action_id=...` → `{items: [...]}`.

  All mutating routes require `require_workspace_role(tenant, Role.TENANT_ADMIN)`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_control_plane_api.py
from fastapi.testclient import TestClient
from app.main import create_app
from app.config import Settings
from tests.test_enterprise import workspace, AUTH, TID

def client(tmp_path):
    settings = Settings('azure', str(tmp_path / 'cp.db'), (workspace(),))
    return TestClient(create_app(settings=settings))

def test_plan_lifecycle_end_to_end(tmp_path):
    c = client(tmp_path)
    plan = c.post('/api/v1/plans', json={'objective': 'Rightsize overprovisioned VMs'}, headers=AUTH).json()
    assert plan['objective'] == 'Rightsize overprovisioned VMs'
    version = c.post(f'/api/v1/plans/{plan["id"]}/versions', json={'targets': [{'resource_id': 'r1'}], 'parameters': {}}, headers=AUTH).json()
    assert version['state'] == 'draft'
    moved = c.post(f'/api/v1/plan-versions/{version["id"]}/transitions', json={'to_state': 'evidence_required'}, headers=AUTH)
    assert moved.status_code == 200 and moved.json()['state'] == 'evidence_required'

def test_illegal_transition_returns_422(tmp_path):
    c = client(tmp_path)
    plan = c.post('/api/v1/plans', json={'objective': 'x'}, headers=AUTH).json()
    version = c.post(f'/api/v1/plans/{plan["id"]}/versions', json={'targets': [{'resource_id': 'r1'}], 'parameters': {}}, headers=AUTH).json()
    response = c.post(f'/api/v1/plan-versions/{version["id"]}/transitions', json={'to_state': 'approved'}, headers=AUTH)
    assert response.status_code == 422

def test_action_assessment_conflict_returns_409(tmp_path):
    c = client(tmp_path)
    body = dict(idempotency_key='k1', action_id='a1', rule_version='v1', findings=[], decision='eligible_for_review', policy_version='p1')
    c.post('/api/v1/action-assessments', json=body, headers=AUTH)
    response = c.post('/api/v1/action-assessments', json=dict(body, action_id='a2'), headers=AUTH)
    assert response.status_code == 409
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_control_plane_api.py -v`
Expected: FAIL with 404 (route not mounted) or import error

- [ ] **Step 3: Implement `app/control_plane_api.py` and mount it in `app/main.py`**

Follow `app/finops_api.py`'s shape exactly: a `finance()`-style dependency helper (here, `admin(tenant=Depends(current_tenant))` calling `require_workspace_role(tenant, Role.TENANT_ADMIN)` then returning `tenant`), `try/except ValueError`→`HTTPException(422, str(error))` and `except WorkflowConflict`→`HTTPException(409, str(error))` around each store call. In `app/main.py`, add `from app.control_plane_api import create_router as control_plane_router` and `api.include_router(control_plane_router(evidence_store, current_tenant))` next to the other `include_router` calls.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_control_plane_api.py tests/test_control_plane_store.py -v`
Expected: PASS (all tests, both files)

- [ ] **Step 5: Run the full existing test suite to confirm no regressions**

Run: `python3 -m pytest tests/ -q -k "not multi_cloud_durable"`
Expected: PASS (same pass count as before this plan, plus the new tests; the one pre-existing `celery`-dependent failure is unrelated and already known)

- [ ] **Step 6: Commit**

```bash
git add app/control_plane_api.py app/main.py tests/test_control_plane_api.py
git commit -m "feat: add REST API for the control-plane plan lifecycle"
```

---

## Self-Review Notes

- **Spec coverage:** Appendix D's `plans`, `plan-versions`, `approvals` routes → Task 5. Appendix E's `plan`/`plan_version`/`approval` tables → Task 1 (SQLite parity; Postgres already migrated). Section H step 3 (immutable plan version with targets/evidence/policy digests) → Task 2. Section H step 5 (independent human approval, no self-approval, exact manifest/version binding) → Task 3. The rule/policy "assessment" concept (Appendix E `assessment`/`assessment_result`, Section G rule evaluation persistence) → Task 4's `cp_action_assessments`. Deliberately deferred: `cp_gitops_checks`/`cp_gitops_deliveries` (Section H step 6, the CI/PR gate), `cp_financial_scenarios` (Appendix F forecasting), `cp_commitment_reminders` (Appendix F commitments) — each is schema-ready and independently small as a follow-up plan once this foundation exists.
- **Not in scope:** anything resembling Terraform `apply`/execution (`execution`, `verification` tables/routes) — the real product has no apply step at all (confirmed: `docs/GITOPS.md` states it "never runs Terraform, applies a plan, or deletes cloud resources"), and building that is a separate, explicitly-flagged high-risk decision, not part of this plan.
