# Feature Improvement Opportunities

Review of the FastAPI backend (`app/`, `services/`, `platform/identity/`) and the two
frontends (`web-dashboard/`, `platform/portal/`) looking for concrete, low-effort wins —
not roadmap items, not bugs. Grouped by theme, most actionable first.

**Status: all items below are implemented.**

## Backend

**Knowledge publications have no pagination past the first page** — ~~`list_knowledge_publications`
(`platform/identity/knowledge/admin.py:19`) takes only `status`/`limit`~~. Fixed: it now takes an
optional `cursor` and returns `next_cursor`, matching the billing list pattern
(`platform/identity/knowledge/admin.py`, `store_memory.py`, `store_postgres.py`).

**Customer audit uses `before`, billing uses `cursor`/`offset`** — kept as-is on review: these serve
different shapes of data (an append-only timestamp-ordered event log vs. a filterable/sortable
entity list), so the two idioms are each appropriate to their use. Knowledge publications, being an
entity list like billing customers, now uses the `cursor`/`offset` idiom for consistency with its
closest sibling.

## Frontend / wiring

**18 customer-access routes exist with zero UI** — `app/onboarding_api.py`'s `customer_access_router`
is wired into `app/main.py` and `services/gateway.py`. Still no dedicated CloudSaver/portal screen
calls `/api/v1/customer/*` end-to-end; this remains open (larger than a single-session UI build —
tracked here, not implemented).

**Knowledge-publication proxy exists in the portal, but no screen used it** — Fixed: added
`platform/portal/components/knowledge/KnowledgeView.tsx` and `app/knowledge/page.tsx`, linked from
the portal nav. Operators can create draft publications and publish/reject/deprecate them.

**Analysis rule catalog has no portal admin screen** — Fixed: added a "Rules" tab to the workspace
detail page (`platform/portal/components/workspaces/RulesTab.tsx`) showing the published rule
catalog with per-workspace enable/disable toggles, backed by the existing
`platform/identity/analysis/admin.py` endpoints.

## Consistency

**Audit-event density varies for no structural reason** — Verified by a new structural test
(`platform/tests/test_audit_coverage.py`) that every mutating method on `AnalysisOps`, `BillingOps`,
`CustomerOps`, and `KnowledgeOps` calls `self._event(...)`. No gaps found; the test now guards
against future regressions.

## Testing gaps

**Three substantial new modules had zero test coverage** — Fixed:
- `app/onboarding_api.py` → `tests/test_onboarding_api.py`
- `app/effective_rules.py` → `tests/test_effective_rules.py`
- `platform/identity/customer/admin.py`, `analysis/admin.py`, `knowledge/admin.py` → extended
  `platform/tests/test_identity.py` with rule-catalog and knowledge-publication lifecycle tests
  (customer admin already had partial coverage, now analysis/knowledge do too).

**No test enforced that every mutating admin method emits an audit event** — Fixed: see
`platform/tests/test_audit_coverage.py` above.

## Related: resource-access ownership change

While wiring the rule-catalog UI, a separate architectural change was made at the user's request:
per-workspace resource-access identity (Azure app client ID, GCP service account) is no longer
edited by platform operators. The platform portal's per-workspace "Resource access" tab was removed
(`platform/portal/components/workspaces/ResourceAccessTab.tsx` deleted); CloudSaver workspace admins
now edit these fields themselves from their own dashboard (`app/settings_api.py`'s `PUT /api/v1/settings`
accepts an `identity` block, enforced closed during directory cutover mode; UI in
`web-dashboard/components/settings/WorkspaceSettings.tsx`'s new `ResourceAccessIdentityEditor`).
Platform-wide default identity settings (`platform/portal/components/settings/ResourceAccessSection.tsx`)
are unaffected — that configures environment-wide fallbacks, not per-workspace overrides.
