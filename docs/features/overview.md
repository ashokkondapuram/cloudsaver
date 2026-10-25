# Overview

The Overview page is your workspace landing page. It summarizes the selected scan: a deduplicated retail opportunity for resources that require review, counts of resources that require review and protected resources, a clean hourly commitment ceiling (when verified hourly evidence exists), a 30-day finding trajectory across comparable scans, a multi-cloud distribution of findings, and the top five resources in your review queue. Every figure is derived from saved scan observations; nothing on this page changes a cloud resource. This page reflects the code as of Oct 25, 2026.

## Where to find it

- Route: `/` ([web-dashboard/app/page.tsx](../../web-dashboard/app/page.tsx) renders `ConsolePage view="overview"`).
- Navigation label: **Overview** in the **DISCOVER & ANALYZE** group of the sidebar ([web-dashboard/components/AppShell.tsx](../../web-dashboard/components/AppShell.tsx)). Keyboard shortcut: `G` then `D`.
- Who can see it: any signed-in workspace member with an assigned role (`TenantAdmin`, `BillingAdmin` or `Viewer`). Only `TenantAdmin` sees the **Run new scan** and **Run first scan** buttons.

## What you can do

- **Read the headline metrics** for the selected scan:
  - **Deduplicated retail opportunity**: the sum of retail estimates for findings on resources with disposition `requires_review`. Findings that share an `opportunity_group_id`, or that sit on the same resource, count once at their maximum value. The value shows only when the complete resource result set loaded.
  - **Resources requiring review**: resources with one merged five-pillar review and disposition `requires_review`.
  - **Protected resources**: resources where recovery, retention, locks or deletion protection were detected.
  - **Clean hourly commitment ceiling**: the recommended new hourly commitment from verified hourly evidence, or `Unknown`. If you apply a scope filter, the card asks you to select all scan scopes.
- **Review the finding trajectory**: switch between **Findings** and **Retail estimate** (the estimate view needs at least two priced snapshots). The chart shows how many findings are new and how many are no longer observed compared with the previous comparable scan.
- **Drill into a provider**: select a provider in **Multi-cloud distribution** to open `/resources?provider=<provider>`.
- **Open your review queue**: select one of the top five resources to open its **Resource details** drawer on `/resources?resource=<resource_key>`, or select **View all resources**.
- **Check workspace foundations**: see how many cloud scopes are configured and when the latest snapshot was taken, with shortcuts to **Configure scopes** (`/settings`) and **Review agent tasks** (`/agents`).
- **Export the snapshot**: use **Export snapshot** in the page header to download the complete selected scan as CSV (findings) or JSON. This export runs in the browser from the loaded scan.
- **Refresh** the workspace or, as a `TenantAdmin`, **Run new scan**.

## How it works

1. A `TenantAdmin` runs a scan (`POST /api/v1/scans` or `POST /api/v1/scans/multi-cloud`). [app/main.py](../../app/main.py) collects findings and inventory, attaches retail pricing, groups overlapping opportunities, evaluates rules, computes a `scope_fingerprint` and saves the scan through the scan store ([app/store.py](../../app/store.py)).
2. The dashboard loads the selected scan and calls `GET /api/v1/scans/{scan_id}/resources?limit=1000` through `useResources` in [web-dashboard/lib/resources.ts](../../web-dashboard/lib/resources.ts). The backend ([app/resource_api.py](../../app/resource_api.py)) merges findings and inventory into one assessment per resource ([app/resource_assessment.py](../../app/resource_assessment.py)) and returns a `commitment_baseline` block computed by `planning_summary`.
3. [web-dashboard/components/Overview.tsx](../../web-dashboard/components/Overview.tsx) computes the KPI cards in the browser. It treats the result as complete only when `total` equals the number of loaded items; otherwise it shows a notice and hides totals.
4. `TrendChart` calls `GET /api/v1/trends?days=30&scan_id=<id>`. [app/trends.py](../../app/trends.py) (`calculate_trend`) reads the 100 most recent scans, keeps completed scans inside the window, and compares only scans with the same `mode`, provider set and `scope_fingerprint`. Older scans without a fingerprint are shown alone and never compared. New and resolved counts compare finding identities (provider, rule and resource ID, with Azure IDs lowercased).
5. **Commitment ceiling**: `planning_summary` in [app/resource_assessment.py](../../app/resource_assessment.py) runs only when the saved scan carries a `commitment_evidence` object with `source_verified` and `commitment_coverage_verified` set to `true`, matching hourly usage and cleanup series, and existing commitment coverage. It subtracts cleanup hour by hour, takes the nearest-rank P10 over 30–90 days of hourly samples (`hourly_p10`), and calls `calculate_clean_commitment_baseline` in [app/commitment_arbitrage.py](../../app/commitment_arbitrage.py). Otherwise it returns `status: insufficient_evidence` with a warning, which the card shows as `Unknown`.
6. `GET /api/v1/analytics` ([app/analytics.py](../../app/analytics.py)) returns a current-snapshot summary (opportunity totals, rule categories and cost basis) for the latest scan. It never sums history. The Overview page doesn't call it, and the dashboard proxy doesn't forward it; it's available to direct API clients.

The dashboard reaches the API through its proxy route [web-dashboard/app/api/[...path]/route.ts](../../web-dashboard/app/api/%5B...path%5D/route.ts), which forwards allowlisted `/api/v1/*` paths to `API_GATEWAY_URL`.

## API reference

Paths are the same on the core API ([app/main.py](../../app/main.py), [app/resource_api.py](../../app/resource_api.py)) and the API gateway ([services/gateway.py](../../services/gateway.py)), where every path is already prefixed with `/api/v1`. The gateway forwards to the scanner service and applies a limit of 120 requests per minute per workspace.

| Method | Path | Purpose | Required role/scope |
| --- | --- | --- | --- |
| GET | `/api/v1/trends` | Comparable snapshot trajectory. Query: `days` (1–365, default 30), optional `scan_id` | Any workspace role; `scoped_read` for provider- or scope-restricted keys |
| GET | `/api/v1/scans/{scan_id}/resources` | Merged resource rows, summary and `commitment_baseline` used for KPI cards | Any workspace role; `scoped_read` |
| GET | `/api/v1/analytics` | Latest-snapshot analytics summary (not used by the dashboard) | Any workspace role; `scoped_read` |
| GET | `/api/v1/scans` | Scan history for the scan selector. Query: `limit` (1–100) | Any workspace role |
| GET | `/api/v1/scans/{scan_id}` | Full saved scan, including findings used by the distribution chart | Any workspace role |
| POST | `/api/v1/scans` | Run an Azure scan | `TenantAdmin` |
| POST | `/api/v1/scans/multi-cloud` | Run a scan for selected configured providers | `TenantAdmin` |

Role and scope classifications come from `require_workspace_role` in [app/auth.py](../../app/auth.py) and the route table in [app/route_inventory.py](../../app/route_inventory.py).

## Data and evidence

- **Stored**: scans (findings, inventory, `rule_evaluations`, `scope_fingerprint`, `opportunity_summary`, coverage) in the `scans` table ([app/store.py](../../app/store.py); PostgreSQL when `CLOUDSAVER_DATABASE_URL` is set, otherwise SQLite at `CLOUDSAVER_DB`).
- **Derived on read**: trend snapshots, resource assessments, KPI totals and the commitment baseline. None of these are persisted.
- **Cost basis**: retail estimates come from pricing attached at scan time. Imported FOCUS billing (billed and effective cost) appears on resource rows, not in the Overview opportunity total.
- **Not proven**:
  - Retail opportunity is an estimate, not realized or verified savings.
  - A finding that's "no longer observed" doesn't prove remediation, deletion or savings.
  - A monthly total can't establish an hourly commitment floor. The commitment ceiling is a planning value with `purchase_authorized: false`.
  - The current scan pipeline in [app/main.py](../../app/main.py) doesn't write `commitment_evidence`, so the ceiling shows `Unknown` unless a saved scan already carries verified hourly evidence.

## Permissions

- Reading the page and its APIs requires an authenticated workspace session with at least one role: `TenantAdmin`, `BillingAdmin` or `Viewer` ([app/auth.py](../../app/auth.py)). In workspace-key mode, a locally verified key receives all three roles; with the identity service, roles come from the key grant; in Entra mode, roles come from the token's `roles` claim.
- Running scans requires `TenantAdmin`.
- Keys restricted to some providers or scopes can read `scoped_read` routes only for their grant; the trend chart asks you to clear the dashboard scope filter because history compares complete scan scopes.
- If billing policy suspends product access, all product routes return 403 except customer, billing and `/api/v1/me` routes.

## Configuration

| Variable | Purpose | Default |
| --- | --- | --- |
| `API_GATEWAY_URL` | Upstream used by the dashboard proxy route | `http://127.0.0.1:8000` |
| `CLOUDSAVER_DATABASE_URL` | PostgreSQL connection for scans and evidence (set through your secrets manager; never commit it) | Unset (SQLite) |
| `CLOUDSAVER_DB` | SQLite path when no database URL is set | `data/cloudsaver.sqlite3` |
| `CLOUDSAVER_AUTH_MODE` | `workspace` (keys) or `entra` (Entra ID tokens) | `workspace` |
| `CLOUDSAVER_DISTRIBUTED_SCAN_LOCK` | Use a Redis lease so only one scan runs per workspace across replicas | Unset (process lock only) |
| `REDIS_URL` | Redis used by the scan lease and gateway rate limiter | `redis://redis:6379/1` (core), `redis://localhost:6379/0` (gateway) |
| `SCANNER_SERVICE_URL` | Gateway upstream for scanner routes | `http://scanner-service:8002` |

## Guardrails and limitations

- KPI totals require the complete authorized result set. The dashboard loads up to 1,000 resources; larger scans show a notice instead of totals.
- Trend comparison uses at most the 100 most recent scans and only scans with matching mode, providers and scope fingerprint.
- The retail estimate chart toggle is disabled until two priced snapshots exist.
- Overview totals cover resources with disposition `requires_review` only; protected and inventory-only resources aren't included in the opportunity total.
- Opportunity totals don't add overlapping alternatives. An unknown alternative keeps a group's total unknown.

## Tests

- Backend: [tests/test_v041_api.py](../../tests/test_v041_api.py) and [tests/test_v060_api.py](../../tests/test_v060_api.py) (trends), [tests/test_services.py](../../tests/test_services.py) (analytics), [tests/test_lean_core.py](../../tests/test_lean_core.py) and [tests/test_high_impact_improvements.py](../../tests/test_high_impact_improvements.py) (clean commitment baseline), [tests/test_opportunity_groups.py](../../tests/test_opportunity_groups.py) (deduplicated totals).
- Dashboard: [web-dashboard/e2e/ui.spec.ts](../../web-dashboard/e2e/ui.spec.ts) (overview uses observed data and provider drill-down, accessibility), [web-dashboard/e2e/lean.spec.ts](../../web-dashboard/e2e/lean.spec.ts), [web-dashboard/e2e/console-experience.spec.ts](../../web-dashboard/e2e/console-experience.spec.ts), [web-dashboard/e2e/opportunity-totals.spec.ts](../../web-dashboard/e2e/opportunity-totals.spec.ts). Shared mocks live in [web-dashboard/e2e/workspace-fixture.ts](../../web-dashboard/e2e/workspace-fixture.ts).

## Related docs

- [Resources](resources.md)
- [docs/UI_UX.md](../UI_UX.md)
- [docs/LEAN_CORE_IMPLEMENTATION.md](../LEAN_CORE_IMPLEMENTATION.md)
- [docs/ENVIRONMENT.md](../ENVIRONMENT.md)
- [docs/FINANCIAL_OUTCOMES.md](../FINANCIAL_OUTCOMES.md)
