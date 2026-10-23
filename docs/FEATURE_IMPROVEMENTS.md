# Feature Improvement Opportunities

Review of the FastAPI backend (`app/`, `services/`, `platform/identity/`) and the two
frontends (`web-dashboard/`, `platform/portal/`) looking for concrete, low-effort wins —
not roadmap items, not bugs. Grouped by theme, most actionable first.

## Backend

**Knowledge publications have no pagination past the first page** — `list_knowledge_publications`
(`platform/identity/knowledge/admin.py:19`) takes only `status`/`limit`, with no `cursor`/`before`,
so callers can never retrieve rows beyond the first `limit`. Billing (`platform/identity/billing/admin.py:240`)
and customer audit (`platform/identity/customer/admin.py:480`) both support paging; this module
will silently hide older publications once the catalog grows past 50 rows.

**Customer audit uses `before`, billing uses `cursor`/`offset` — pick one** — `customer_audit`
(`platform/identity/customer/admin.py:480`) pages by timestamp while `list_billing_customers`
(`platform/identity/billing/admin.py:240`) pages by opaque cursor/offset. Two pagination idioms
in sibling admin modules means two client-side paging implementations for what should be one
shared pattern.

## Frontend / wiring

**18 customer-access routes exist with zero UI** — `app/onboarding_api.py`'s `customer_access_router`
(members, service accounts, delegated keys, audit, access-export — `app/onboarding_api.py:144-240`)
is now wired into both `app/main.py` and `services/gateway.py`, but neither `web-dashboard/` nor
`platform/portal/` has any page or fetch call referencing `/api/v1/customer/*`. This is a fully
working backend feature with no way for a user to reach it.

**Knowledge-publication proxy exists in the portal, but no screen uses it** — `platform/portal/app/api/portal/[...path]/route.ts:49-50`
allowlists `GET/POST knowledge/publications` and `PATCH .../{id}`, but there's no
`platform/portal/app/knowledge/` (or similar) page. The proxy was built ahead of the UI that
would call it.

**Analysis rule catalog has no portal admin screen** — `platform/identity/analysis/admin.py` backs
rule enable/disable per workspace, but no portal route proxies it and no page renders it; workspace
admins can't currently toggle a rule without a direct API call.

## Consistency

**Audit-event density varies for no structural reason** — `customer/admin.py` emits 12 audit events
across its ~15 mutating methods, `billing/admin.py` emits 8, `knowledge/admin.py` emits 2 for 2
mutations (consistent), `analysis/admin.py` emits 1 for its 1 mutation (consistent). The customer
and billing modules are fine; flagging only because it's worth a one-pass check that every new
mutating endpoint added to `analysis`/`knowledge` going forward also gets an `_event(...)` call —
there's no lint or test enforcing it today (see Testing below).

## Testing gaps

**Three substantial new modules have zero test coverage**:
- `app/onboarding_api.py` (241 lines, 18 routes) — not referenced in any file under `tests/`.
- `app/effective_rules.py` (new; consumed by `app/main.py:175` in the scan path) — not referenced
  in any file under `tests/`.
- `platform/identity/customer/admin.py` (523 lines), `platform/identity/analysis/admin.py`,
  `platform/identity/knowledge/admin.py` — none referenced in `platform/tests/test_identity.py`
  or any other `platform/tests/*.py`.

These are the three biggest pieces of uncommitted work this session and currently ship with no
regression protection — a refactor or dependency bump could silently break customer onboarding,
key issuance, or the scanner's rule-filtering path with no test failing.

**No test enforces that every mutating admin method emits an audit event** — given the
inconsistency noted above, a simple structural test (inspect each `*Ops` class, assert every
public method that calls `tx.update_*`/`tx.insert_*` also calls `self._event(...)`) would catch
future regressions cheaply, without needing per-endpoint test cases.
