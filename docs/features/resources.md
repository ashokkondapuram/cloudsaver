# Resources

Resources is the per-resource review workspace. CloudSaver merges every finding and inventory row for a resource in the selected scan into one deterministic five-pillar assessment (cost, reliability, performance, security and operations), then adds imported billing, retail estimates, AI status, reviewer decisions and changes since the previous comparable scan. From here you can filter and search resources, open the **Resource details** drawer, record accept, dismiss or defer decisions, review history, export a CSV, print a report and, as an administrator, start an AI assessment batch. Nothing on this page changes a cloud resource. This page reflects the locally hardened code as of Oct 26, 2026. See [detailed reliability verification](../DETAIL_RELIABILITY_VERIFICATION.md) for measured checks and limits.

## Where to find it

- Route: `/resources` ([web-dashboard/app/resources/page.tsx](../../web-dashboard/app/resources/page.tsx) renders `ConsolePage view="resources"`).
- Navigation label: **Resources** in the **DISCOVER & ANALYZE** group. Keyboard shortcut: `G` then `R`.
- Printable report: `/resources/report` ([web-dashboard/app/resources/report/page.tsx](../../web-dashboard/app/resources/report/page.tsx)), opened with **Print report**.
- Legacy route: `/findings` ([web-dashboard/app/findings/page.tsx](../../web-dashboard/app/findings/page.tsx)) redirects to `/resources`, keeping valid `provider`, `category`, `intent`, `pricing` and `resource` query parameters.
- Deep links: `/resources?resource=<resource_key>` opens the drawer; `/resources?provider=<azure|aws|gcp|kubernetes>&resource_id=<id>` opens the matching resource; `category`, `intent` (`protected` or `review`) and `pricing` (`known` or `unknown`) preselect quick views.
- Who can see it: any workspace member with a role (`TenantAdmin`, `BillingAdmin` or `Viewer`). Only `TenantAdmin` can run AI assessments, ask follow-up questions, record decisions, cancel batches and generate review code.
- If the selected scan isn't a completed live scan (for example, a `legacy_synthetic` snapshot), the page falls back to the findings grid.

## What you can do

- **Scan the summary**: total resources (and the number of findings they came from), AI assessed (with stale and not-run counts), high or critical AI risk, and decisions (with deferred count). When a comparable previous scan exists, a note shows how many resources no longer have findings and how many are no longer observed.
- **Filter and search**:
  - Provider pills, category pills and quick views (**All evidence**, **Protected intent**, **Missing prices**) filter in the browser.
  - Drop-downs filter by cloud provider, service category, pillar status (`observed`, `risk`, `unknown`), review priority (`critical`, `high`, `evidence_required`), AI status (`not_run`, `queued`, `running`, `completed`, `stale`, `failed`), AI risk and decision.
  - Search matches resource names and IDs.
- **Read the table**: supported inventories are read in pages of 1,000 up to 10,000 resources per selected scan; the table displays 50 matching resources per page. Changing search or filters returns to the first table page.  each row shows findings count, priority, pillar dots, 30-day billed USD, 30-day effective USD, retail opportunity, AI risk, AI status, decision and a lifecycle badge (`new`, `persisting` or `regressed`).
- **Open Resource details**: select a row to open the drawer. Its header shows badges (provider, **Protected intent** or **Review required**, priority, AI status, decision), pillar dots and key facts: **30-day billed**, **Retail estimate**, **Evidence coverage** and **Observed**. Header actions are **Draft a tag or snapshot plan** (opens `/agents?resource=<id>`) and **AI assessment**. The drawer tabs are:
  - **Overview**: five-pillar radar and per-check explanations with evidence fields, resource identity, required guardrails, policy version and evidence fingerprint. Warnings appear for protected resources and observations older than 24 hours.
  - **Findings**: each finding with its per-finding architectural assessment and optional AI risk advisory.
  - **Evidence**: collector and schema provenance, the saved configuration snapshot (truncated at 16,000 characters), utilization telemetry windows, rule evaluations and dependency edges.
  - **Costs**: 30-day billed and effective cost, retail review estimate, modeled opportunity and overlap warnings. Modeled future cost and verified realized savings are always `Unknown`.
  - **AI**: the latest AI assessment for the resource and up to 5 follow-up questions per resource per scan. See [AI assessments](ai-assessments.md).
  - **Decision**: the current decision and a form to **Accept**, **Dismiss** or **Defer**.
  - **History**: changes across up to 10 recent scans, AI assessment history and decisions.
  - **Code**: generate review-only Bash or Terraform for the resource's findings, when the plan and finding types allow it.
- **Record a decision** (`TenantAdmin`): choose **Accept**, **Dismiss** or **Defer**. A note is required for dismiss and defer. A defer date is optional and must be within the next 365 days. When the defer date passes, the resource reopens with decision `none`.
- **Export CSV**: download `cloudsaver-resources-<scan_id>.csv` for all loaded rows matching the scope, discovery/quick-view filters, drop-down filters and search, across table pages. Unknown values stay empty and spreadsheet expressions are neutralized.
- **Print report**: open a print-friendly report of every loaded resource with pillars, AI summary, suggested actions and decisions.
- **Run AI assessment** (`TenantAdmin`): select resources (or all in the scan), choose an approved target and acknowledge external processing. A progress banner tracks the batch; you can cancel queued items.
- **Review code** for selected rows: the bulk toolbar opens the review flow (`Shift` + `R`).

## How it works

1. **Scan**: [app/main.py](../../app/main.py) saves findings, canonical inventory, rule evaluations and a `scope_fingerprint`.
2. **Ownership check**: [app/resource_api.py](../../app/resource_api.py) (`owned`) loads the scan for your workspace and rejects scans that aren't completed live observations (409) or contain findings outside your current scope (409). It then attaches imported FOCUS billing through `FocusRepository.attach` in [app/focus.py](../../app/focus.py), which sums exact resource-level USD charges over a 30-day window ending at the scan date.
3. **Per-finding assessment**: [app/assessment.py](../../app/assessment.py) (`assess`) evaluates each finding against the five pillars using saved evidence only. It detects protection signals (retention tags, recovery roles, deletion protection, management locks, backup or replication, source conflicts), sets review priority (`critical` for public databases, disabled encryption, admin ingress or snapshot exposure; `high` for other risks; otherwise `evidence_required`) and lists guardrails. Service-specific checks come from [app/assessment_policy.py](../../app/assessment_policy.py) and [app/pillar_checks.py](../../app/pillar_checks.py). Missing evidence is always `unknown`, never a pass.
4. **Per-resource merge**: [app/resource_assessment.py](../../app/resource_assessment.py) groups findings by `resource_key` (SHA-256 of provider and resource ID, with Azure IDs lowercased). Each check keeps its most severe status across findings. Inventory rows with no finding become `inventory_only` resources (or `protected` when evidence shows protection). An `evidence_digest` fingerprints the sanitized, policy-evaluated evidence and ignores wall-clock freshness, so AI results and decisions can detect evidence changes.
5. **Lifecycle deltas**: `lifecycle` compares against the most recent earlier completed live scan with the same `scope_fingerprint`. Resources are `new`, `persisting` or `regressed` (new rule IDs or new risk codes). The summary adds `comparison_scan_id`, `resolved_count` and `no_longer_observed_count`.
6. **AI and decisions**: the router joins the latest AI result per resource, batch item states for the scan and the latest decision per resource from [app/resource_store.py](../../app/resource_store.py). `ai_state` reports `stale` when the latest result's digest no longer matches.
7. **Sorting and filtering**: rows are ordered by priority, then retail estimate (highest first), then name. Filters and `q` apply server-side; `limit` and `offset` page the result.
8. **Detail**: `GET .../resources/{resource_key}` adds findings, the sanitized AI context, the latest AI response, follow-ups, the inventory observation, rule evaluations, a cost block and financial overlaps (other resources in the same opportunity group).
9. **History**: `history` re-merges the resource in each of up to 10 recent completed live scans and labels changes: `appeared`, `no_longer_flagged`, `risk_changed`, `priority_changed`, `<pillar>_changed`, `findings_changed` and `evidence_changed`.
10. **AI batches**: queued items are processed in the background by [app/resource_batches.py](../../app/resource_batches.py). See [AI assessments](ai-assessments.md).

Dashboard modules: [web-dashboard/components/resources/ResourcesView.tsx](../../web-dashboard/components/resources/ResourcesView.tsx) (page, batch dialog, banner and `ResourceReport`), [web-dashboard/components/resources/ResourceDrawer.tsx](../../web-dashboard/components/resources/ResourceDrawer.tsx) (drawer and tabs), [web-dashboard/components/resources/ResourceParts.tsx](../../web-dashboard/components/resources/ResourceParts.tsx) (`PillarDots`, `AIStatusBadge`, `AIRisk`, `DecisionBadge`, `Actions`) and [web-dashboard/lib/resources.ts](../../web-dashboard/lib/resources.ts) (types, `useResources`, `useActiveBatch`, `identityOf`, `resourceKeyOf`).

## API reference

Paths are the same on the core API ([app/resource_api.py](../../app/resource_api.py), [app/main.py](../../app/main.py)) and the API gateway ([services/gateway.py](../../services/gateway.py)). The gateway forwards these to the scanner service with a 120 requests per minute per workspace limit. Scope classifications are from [app/route_inventory.py](../../app/route_inventory.py).

| Method | Path | Purpose | Required role/scope |
| --- | --- | --- | --- |
| GET | `/api/v1/scans/{scan_id}/resources` | Merged resource rows and summary. Query: `provider`, `service_category`, `review_priority`, `ai_status`, `ai_risk`, `decision`, `pillar_status`, `q`, `limit` (1–1,000, default 100), `offset` | Any workspace role; `scoped_read` |
| GET | `/api/v1/scans/{scan_id}/resources/export` | CSV content for matching rows (same filters and `q`, no paging). Returns `filename`, `rows`, `content` | Any workspace role; `scoped_read` |
| GET | `/api/v1/scans/{scan_id}/resources/{resource_key}` | Full detail for one resource | Any workspace role; `scoped_read` |
| GET | `/api/v1/resources/{resource_key}/history` | Up to 10 scan entries, AI result history and the last 20 decisions | Any workspace role; `scoped_read` |
| GET | `/api/v1/resources/{resource_key}/decisions` | Decision history for scans visible to your key | Any workspace role; `scoped_read` |
| POST | `/api/v1/resources/{resource_key}/decisions` | Record `accept`, `dismiss` or `defer`. Body: `scan_id`, `decision`, `note`, `defer_until`, `evidence_digest` | `TenantAdmin`; `scan_write` |
| POST | `/api/v1/scans/{scan_id}/ai-batches` | Queue an AI assessment batch | `TenantAdmin`; `scan_write` |
| GET | `/api/v1/ai-batches` | Recent batches. Query: `scan_id`, `limit` (1–50) | Any workspace role; `scoped_read` |
| GET | `/api/v1/ai-batches/{batch_id}` | One batch with item states | Any workspace role; `scoped_read` |
| POST | `/api/v1/ai-batches/{batch_id}/cancel` | Cancel queued items | `TenantAdmin` |
| POST | `/api/v1/scans/{scan_id}/resources/{resource_key}/questions` | Ask a follow-up question | `TenantAdmin`; `scan_write` |
| POST | `/api/v1/scans/{scan_id}/remediation` | Review-only Bash script for selected resource IDs (Code tab) | `TenantAdmin` |
| POST | `/api/v1/scans/{scan_id}/remediation-terraform` | Review-only Terraform for selected resource IDs (Code tab) | `TenantAdmin` and a plan that includes Terraform export |

## Data and evidence

- **Scan data**: findings, inventory, `rule_evaluations` and `scope_fingerprint` in the `scans` table ([app/store.py](../../app/store.py)).
- **Billing**: imported FOCUS charges in `focus_imports` and `focus_charges` ([app/focus.py](../../app/focus.py)). Billed and effective values are exact resource-period USD imports with `billing_basis: imported_FOCUS_not_provider_reconciled`. Effective cost above billed cost, or a `Purchase` charge, marks the resource `commitment_locked`.
- **Decisions**: append-only rows in `resource_decisions` (`resource_key`, `scan_id`, `decision`, `note`, `defer_until`, `evidence_digest`, `actor`, `created_at`). The `actor` is a SHA-256 hash of the user ID or workspace key reference, not a name.
- **AI**: batches in `ai_batches` and `ai_batch_items`, follow-ups in `ai_followups`, results in `ai_inference_attempts` (see [AI assessments](ai-assessments.md)).
- **Provenance**: each assessment carries `policy_version` (currently `2026-10-23.1` in [app/assessment_policy.py](../../app/assessment_policy.py)), `observation.observed_at`, `evidence_coverage` and `evidence_digest`. The Evidence tab shows `collector_version` and `evidence_schema_version` when the collector recorded them.
- **CSV columns**: `provider`, `scope_id`, `resource_name`, `resource_type`, `resource_group`, `resource_id`, `service_category`, `rule_ids`, `review_priority`, `disposition`, the five pillars, `billed_cost_usd`, `effective_cost_usd`, `retail_estimate_usd`, `lifecycle_delta`, `ai_status`, `ai_risk`, `ai_summary`, `decision`, `decision_at`, `evidence_digest`. Cells that start with `=`, `+`, `-`, `@`, tab or carriage return are prefixed with `'`, and the file starts with a UTF-8 byte order mark.
- **Not proven**:
  - An `observed` check isn't a safety certification, and an `unknown` check isn't healthy.
  - A missing dependency edge doesn't prove there's no dependency.
  - Retail opportunity is an estimate; `realizable_savings_usd`, `modeled_future_cost_usd` and `verified_realized_savings_usd` are always empty.
  - "Resolved" and "no longer observed" counts don't prove deletion or savings.
  - A decision doesn't change any cloud resource.

## Permissions

- Read routes need any assigned role. `Viewer` and `BillingAdmin` can inspect every tab but see "A workspace administrator can…" instead of the AI question, decision and code controls.
- `TenantAdmin` is required for decisions, AI batches, batch cancellation, follow-up questions and review code generation ([app/auth.py](../../app/auth.py) `require_workspace_role`).
- Keys restricted to some providers or scopes can use `scoped_read` and `scan_write` routes only within their grant ([app/provider_access.py](../../app/provider_access.py)). Batch and decision lists hide rows for scans outside the grant (`scan_visible` in [app/data_scope.py](../../app/data_scope.py)).
- Terraform export also requires the plan entitlement `can_export_terraform` ([app/entitlements.py](../../app/entitlements.py)).

## Configuration

| Variable | Purpose | Default |
| --- | --- | --- |
| `API_GATEWAY_URL` | Upstream for the dashboard proxy route | `http://127.0.0.1:8000` |
| `CLOUDSAVER_DATABASE_URL` | PostgreSQL for scans, decisions, billing and AI evidence (store in a secrets manager) | Unset (SQLite) |
| `CLOUDSAVER_DB` | SQLite path when no database URL is set | `data/cloudsaver.sqlite3` |
| `CLOUDSAVER_AI_ENABLED` | Enables AI targets and the background batch worker | Unset (off) |
| `CLOUDSAVER_AI_HOURLY_ATTEMPTS` | Deployment hourly AI attempt ceiling per workspace (1–100) | `10` |

AI-specific configuration is described in [AI assessments](ai-assessments.md).

## Guardrails and limitations

- Only completed live scans can be analyzed; synthetic snapshots return 409.
- The dashboard loads up to 1,000 resources per scan (`limit=1000`). The printable report covers those loaded rows only.
- CSV export applies the drop-down filters and search, but not the browser-only provider pills, category pills or quick views.
- Decisions and follow-up questions require the current `evidence_digest`; if evidence changed, the API returns 409 and asks you to refresh.
- Observations older than 24 hours add the `REFRESH_OBSERVATION` guardrail and a drawer warning.
- Protected resources add `NO_DESTRUCTIVE_RECOMMENDATION`. The Code tab blocks review Bash for protected findings, and Bash is available only for supported Azure rules.
- The Code tab accepts up to 50 unique resources from one provider per request.
- Resource history checks findings only, so inventory-only resources show as "Not flagged".

## Tests

- Backend: [tests/test_resource_assessment.py](../../tests/test_resource_assessment.py) (identity merge and digest, history changes, CSV formula escaping, resources, batches, decisions, questions, export, inventory-only rows, viewer restrictions), [tests/test_assessment.py](../../tests/test_assessment.py), [tests/test_lean_core.py](../../tests/test_lean_core.py) (billing join, scan deltas, expired defer reopening), [tests/test_resource_evidence_contracts.py](../../tests/test_resource_evidence_contracts.py), [tests/test_opportunity_groups.py](../../tests/test_opportunity_groups.py), [tests/test_route_inventory.py](../../tests/test_route_inventory.py), [tests/test_postgres.py](../../tests/test_postgres.py).
- Dashboard: [web-dashboard/e2e/lean.spec.ts](../../web-dashboard/e2e/lean.spec.ts) (billing separate from retail estimates, scan deltas, agent handoff, mobile explorer), [web-dashboard/e2e/assessment.spec.ts](../../web-dashboard/e2e/assessment.spec.ts) (stale evidence provenance in the drawer), [web-dashboard/e2e/foundry.spec.ts](../../web-dashboard/e2e/foundry.spec.ts) (drawer separates evidence, rules, dependencies and unknown financial fields), [web-dashboard/e2e/ui.spec.ts](../../web-dashboard/e2e/ui.spec.ts), [web-dashboard/e2e/opportunity-totals.spec.ts](../../web-dashboard/e2e/opportunity-totals.spec.ts).

## Related docs

- [AI assessments](ai-assessments.md)
- [Workload assessments](workload-assessments.md)
- [Services](services.md)
- [docs/RESOURCE_ANALYSIS_FOUNDRY_IMPLEMENTATION.md](../RESOURCE_ANALYSIS_FOUNDRY_IMPLEMENTATION.md)
- [docs/RESOURCE_ANALYSIS_AND_PORTAL_ROADMAP.md](../RESOURCE_ANALYSIS_AND_PORTAL_ROADMAP.md)
- [docs/LEAN_CORE_IMPLEMENTATION.md](../LEAN_CORE_IMPLEMENTATION.md)
- [docs/FINANCIAL_OUTCOMES.md](../FINANCIAL_OUTCOMES.md)
- [docs/UI_UX.md](../UI_UX.md)

## Loading and status recovery

Inventory loading is bound to the active credential and selected scan. Incomplete or changing pages show an evidence error instead of a partial complete-looking report. During initial AI batch status loading, or when its counters/status cannot be verified, new assessment submission is disabled. **Check assessment status** retries the status read; it does not invoke a model or replay existing work. A credential rejection clears the workspace session; a scope denial keeps the authenticated session and displays the access error.
