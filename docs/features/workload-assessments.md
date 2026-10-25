# Workload assessments

Workload assessments group the saved five-pillar resource assessments of a scan into application and environment workloads, using the current explicit ownership mappings you maintain in **Savings & investigations**. For each workload you see how many resources are at risk, unknown or observed per pillar, and for each member resource you get non-executable review templates (VM rightsizing and network access) with prerequisites, steps, verification and recovery notes. The feature is a read-only browser projection over existing APIs: it adds no backend route, no table and no cloud action. This page reflects the code as of Oct 25, 2026.

## Where to find it

- Route: `/workloads` ([web-dashboard/app/workloads/page.tsx](../../web-dashboard/app/workloads/page.tsx) renders `WorkloadsView`).
- Navigation label: **Workload assessments** in the **DISCOVER & ANALYZE** group. You can also select **Workload assessments** in the Resources page header.
- Who can see it: the dashboard shows the page to `TenantAdmin` and `BillingAdmin` (`canBill`). A `Viewer` sees "Finance access required". The server enforces the same rule because the ownership API requires `BillingAdmin` (which `TenantAdmin` satisfies).

## What you can do

- **Pick a saved observation** from the **Saved observation** selector. Only completed live scans are eligible; synthetic and demo observations show a notice.
- **Read the assessment summary**: visible resources, unassigned resources and ambiguous mappings, plus the observation time.
- **Browse workloads** (20 per page): each card shows `<application> / <environment>`, the resource count and per-pillar counts of resources at risk, unknown and observed.
- **Open an improvement preview** for a workload: each member (20 per page) shows provider, scope, owner, team, resource ID, evidence gaps, existing protections and any matching review template:
  - **Review VM rightsizing** for Azure virtual machines with underutilization, rightsizing, oversizing or low-CPU rule signals.
  - **Review network access** for resources whose risk check codes mention network, public access, exposure, inbound, SSH or RDP.
  - Otherwise: "No supported remediation template for these findings."
- **Inspect resource evidence**: each member links to `/resources?resource=<resource_key>`.
- **Refresh saved assessments** to reload ownership and resources after changes.
- **Jump to related workflows**: **Manage application ownership** (`/outcomes`), **Resource evidence** (`/resources`), **Risk & compliance** (`/governance`) and **Reviewed remediation** (`/automation`).

To assign a resource to a workload, record its application, environment, owner and team through the application ownership workflow on `/outcomes` (`PUT /api/v1/outcomes/ownership`, `TenantAdmin` only).

## How it works

1. [web-dashboard/components/workloads/WorkloadsView.tsx](../../web-dashboard/components/workloads/WorkloadsView.tsx) mounts an `Assessment` keyed by workspace, token and scan, so any change cancels in-flight requests and discards stale results.
2. `loadWorkloadInputs` in [web-dashboard/lib/workloads.mjs](../../web-dashboard/lib/workloads.mjs):
   - Calls `GET /api/v1/outcomes/ownership` once. The backend ([app/outcome_api.py](../../app/outcome_api.py), [app/outcome_anomalies.py](../../app/outcome_anomalies.py)) returns versioned rows from `finops_ownership` with `basis: current_direct_resource_mapping`.
   - Pages through `GET /api/v1/scans/{scan_id}/resources?limit=1000&offset=<n>` until every row is loaded. It fails the whole load if `scan_id`, `total` or `observed_at` changes between pages, if a page is empty early, or if totals exceed 10,000.
3. `groupWorkloads` joins resources to mappings by exact identity: provider, scope ID and resource ID (Azure values lowercased). Names and tags are never used. For each resource it keeps the highest mapping `version`; equal-version mappings that disagree on application, environment, owner or team are counted as ambiguous and left unassigned.
4. Workloads are keyed by application and environment, sorted alphabetically, and summarized per pillar. Each workload is marked `automatic_execution: false`, `verified_savings: null` and `dependency_coverage: unknown`.
5. `remediationPreview` matches templates from rule IDs, resource type and risk check codes. Every action is returned with `executable: false`, `approval_granted: false` and `target_sku: null`.

The resource rows themselves come from the resource assessment pipeline described in [Resources](resources.md) ([app/resource_api.py](../../app/resource_api.py), [app/resource_assessment.py](../../app/resource_assessment.py)).

## API reference

This feature adds no endpoints. It reads these existing routes, which have the same paths on the core API and the API gateway ([services/gateway.py](../../services/gateway.py)):

| Method | Path | Purpose | Required role/scope |
| --- | --- | --- | --- |
| GET | `/api/v1/outcomes/ownership` | Current versioned ownership mappings | `BillingAdmin` (or `TenantAdmin`); `scoped_read` |
| GET | `/api/v1/scans/{scan_id}/resources` | Paginated resource assessments (`limit` up to 1,000, `offset`) | Any workspace role; `scoped_read` |
| PUT | `/api/v1/outcomes/ownership` | Record an ownership mapping (used from `/outcomes`, not from this page) | `TenantAdmin` (and `BillingAdmin` check); `full_scope` |
| GET | `/api/v1/outcomes/ownership/history` | Ownership versions for one resource. Query: `provider`, `scope_id`, `resource_id` | `BillingAdmin` (or `TenantAdmin`); `scoped_read` |

## Data and evidence

- **Read only**: ownership rows in `finops_ownership` (provider, scope ID, resource ID, version, payload, actor, created time) and resource assessments derived from the saved scan.
- **Nothing stored**: workload groupings, counts and previews exist only in the browser.
- **Provenance**: the summary shows the scan's `observed_at`. Membership is based on current explicit mappings, not historical ownership.
- **Not proven**:
  - Dependency coverage is unknown; a workload isn't a verified topology.
  - `observed` isn't a compliance pass, and `unknown` isn't a healthy result.
  - No money totals or verified savings are calculated.
  - Independent API reads aren't an atomic historical snapshot.

## Permissions

- Page visibility: `TenantAdmin` or `BillingAdmin` in the dashboard ([web-dashboard/components/WorkspaceProvider.tsx](../../web-dashboard/components/WorkspaceProvider.tsx) `canBill`).
- Server enforcement: `GET /api/v1/outcomes/ownership` requires `BillingAdmin` via `require_workspace_role` (a `TenantAdmin` satisfies it). Writing ownership additionally requires `TenantAdmin` and a full-scope key.
- If the ownership or resource request fails authorization, the page shows the error and no partial totals; it doesn't fall back to another data source.

## Configuration

No feature-specific variables. The page uses the shared dashboard proxy (`API_GATEWAY_URL`, default `http://127.0.0.1:8000`) and the backend storage settings described in [docs/ENVIRONMENT.md](../ENVIRONMENT.md).

## Guardrails and limitations

- Bounded to 10,000 resources and 10,000 ownership mappings; larger inputs fail visibly.
- All resource pages must load and stay consistent, or nothing is shown.
- Duplicate resource identities or incomplete mappings fail the load rather than producing a partial rollup.
- Only two review templates exist (VM rightsizing and network access). They are guidance only and require current evidence and separate approval in existing workflows.
- A smaller VM doesn't fix a vulnerability, and an access change that succeeds doesn't prove legitimate traffic still works.

## Tests

- Unit: [web-dashboard/unit/workloads.test.mjs](../../web-dashboard/unit/workloads.test.mjs) (run with `node --test web-dashboard/unit/workloads.test.mjs`).
- Dashboard: [web-dashboard/e2e/workloads.spec.ts](../../web-dashboard/e2e/workloads.spec.ts) (pillar grouping and non-executable steps, no guessed assignment, viewer gating, visible authorization errors, refresh replaces stale membership, exact account identity).
- Backend ownership routes: [tests/test_outcomes.py](../../tests/test_outcomes.py).

## Related docs

- [docs/WORKLOAD_ASSESSMENTS.md](../WORKLOAD_ASSESSMENTS.md): delivered scope, safety limits and verification steps for this increment.
- [Resources](resources.md)
- [docs/FINANCIAL_OUTCOMES.md](../FINANCIAL_OUTCOMES.md)
- [docs/RISK_AND_COMPLIANCE.md](../RISK_AND_COMPLIANCE.md)
