# Services

The Services page gives you a service-family view of the selected scan. At the top, **Service architecture analysis** summarizes five-pillar review signals by provider and service category across the complete snapshot. Below it, family tabs (disks, virtual machines, public IPs, app service plans, databases, load balancers, object storage and AI endpoints) list the merged resource assessments whose resource type matches that family, with rule signal counts, imported billed USD and retail estimates. Each resource links to its **Resource details** drawer. This page reflects the code as of Oct 25, 2026.

## Where to find it

- Route: `/services/[service]` ([web-dashboard/app/services/[service]/page.tsx](../../web-dashboard/app/services/%5Bservice%5D/page.tsx) renders `ServiceWorkspace`). Valid `service` values: `disks`, `virtual-machines`, `public-ips`, `app-service-plans`, `databases`, `load-balancers`, `object-storage`, `ai-endpoints`.
- Navigation label: **Services** in the **DISCOVER & ANALYZE** group (links to `/services/disks`).
- Who can see it: any workspace member with a role (`TenantAdmin`, `BillingAdmin` or `Viewer`).

## What you can do

- **Review service architecture analysis**: for each provider and service category, see findings, protected findings, observed risks, unpriced findings and the known retail portion. A coverage notice states how many finding observations and unique resources are included.
- **Switch service families** with the tabs under the analysis panel.
- **Scan a family's resources**: resource name, provider, rule signals, imported billed USD and retail estimate USD. The panel shows the total number of observed resources and the backend's evidence warning.
- **Open a resource**: select a resource name to open `/resources?resource=<resource_key>` and its **Resource details** drawer.

Per-finding architectural assessments and the optional per-finding AI risk advisory (`ArchitecturalAssessment` in [web-dashboard/components/ServiceAnalysis.tsx](../../web-dashboard/components/ServiceAnalysis.tsx)) appear in the **Findings** tab of the Resource details drawer. See [Resources](resources.md) and [AI assessments](ai-assessments.md).

## How it works

1. `ServiceWorkspace` in [web-dashboard/components/V150Views.tsx](../../web-dashboard/components/V150Views.tsx) calls `GET /api/v1/services/{service}?scan_id=<selected scan>`.
2. [app/v150_analysis.py](../../app/v150_analysis.py) (`service_matrix`):
   - Rejects unknown families with 404. Each family is a case-insensitive regular expression over `resource_type` in `SERVICES` (for example, `disks` matches `disk|volume`; `ai-endpoints` matches `cognitive|bedrock|aiplatform|ai.endpoint`).
   - Loads the requested scan, or the latest of your 10 most recent scans when `scan_id` is omitted, and requires a completed live scan (409 otherwise).
   - Attaches imported FOCUS billing (`FocusRepository.attach` in [app/focus.py](../../app/focus.py)), merges findings and inventory per resource with `assessments` from [app/resource_assessment.py](../../app/resource_assessment.py), and returns up to 1,000 matching items with `total`, the list of `families`, recent scan `history` and a `warning`.
3. `ServiceAnalysis` in [web-dashboard/components/ServiceAnalysis.tsx](../../web-dashboard/components/ServiceAnalysis.tsx) calls `GET /api/v1/scans/{scan_id}/analysis`. [app/assessment_api.py](../../app/assessment_api.py) runs `summarize` from [app/assessment.py](../../app/assessment.py), which assesses every finding, groups by provider and service category, deduplicates retail subtotals with `opportunity_totals` ([app/pricing.py](../../app/pricing.py)) and returns a review queue capped at 50 entries. It reports `full_inventory: false` because it covers resources with findings only.
4. The same module ([app/v150_analysis.py](../../app/v150_analysis.py)) also serves `GET /api/v1/optimization/scans/{scan_id}/auto-scenarios`, used by the **Optimization evidence** page (`/optimization`). It returns topology, SLO, network and commitment planning inputs from the scan, with `automatic_execution: false` and `purchase_authorized: false`.

[app/v150_store.py](../../app/v150_store.py) (`WorkflowStore`) belongs to the same release but isn't used by the Services page. It persists billing sync runs (`billing_sync_runs`, written by [app/collectors/billing_sync.py](../../app/collectors/billing_sync.py)) and paired agent and GitOps syncs (`agent_gitops_syncs`, written by [app/agent_gitops_sync.py](../../app/agent_gitops_sync.py)) with leases. These back the **Automatic cloud billing** panel and the agent and repository timeline elsewhere in [web-dashboard/components/V150Views.tsx](../../web-dashboard/components/V150Views.tsx).

## API reference

Paths are the same on the core API and the API gateway ([services/gateway.py](../../services/gateway.py)). The gateway validates the family name against `SERVICES` before forwarding and applies a 120 requests per minute per workspace limit. The dashboard proxy ([web-dashboard/app/api/[...path]/route.ts](../../web-dashboard/app/api/%5B...path%5D/route.ts)) only forwards the eight known family paths.

| Method | Path | Purpose | Required role/scope |
| --- | --- | --- | --- |
| GET | `/api/v1/services/{service}` | Resource assessments for one service family. Query: optional `scan_id` | Any workspace role; `scoped_read` |
| GET | `/api/v1/scans/{scan_id}/analysis` | Provider and service-category summary and 50-item review queue | Any workspace role; `scoped_read` |
| POST | `/api/v1/scans/{scan_id}/analysis/resource` | Five-pillar assessment and sanitized AI context for one finding. Body: `resource_id`, `rule_id` | Any workspace role; `scan_write` |
| POST | `/api/v1/scans/{scan_id}/ai-risk-evaluation` | Per-finding AI risk advisory (see [AI assessments](ai-assessments.md)) | `TenantAdmin`; `scan_write` |
| GET | `/api/v1/optimization/scans/{scan_id}/auto-scenarios` | Planning inputs for the Optimization evidence page | Any workspace role; `scoped_read` |

## Data and evidence

- **Read only**: saved scans (`scans` table, [app/store.py](../../app/store.py)) and imported FOCUS charges (`focus_imports`, `focus_charges`). The Services page stores nothing.
- **Billed vs retail**: **Imported billed USD** is the exact 30-day resource-level FOCUS import attached at read time. **Retail estimate USD** is the pricing estimate from the scan.
- **Provenance**: the analysis summary includes `policy_version`, the observation freshness and coverage counts; each item carries its `evidence_digest`.
- **Not proven**:
  - Unknown controls and missing billing aren't proof of safety or savings.
  - The analysis summary covers resources with findings only; an empty table doesn't certify the full estate.
  - Protected and risk counts overlap and must not be added together.
  - Family matching is by resource type text; it isn't a verified service catalog.

## Permissions

- All read routes need an authenticated session with any role (`TenantAdmin`, `BillingAdmin` or `Viewer`), enforced through `tenant_dependency` in [app/auth.py](../../app/auth.py).
- Keys restricted to some providers or scopes are filtered by the scoped store ([app/provider_access.py](../../app/provider_access.py)); these routes are classified in [app/route_inventory.py](../../app/route_inventory.py).
- Requesting a per-finding AI advisory requires `TenantAdmin`.

## Configuration

No feature-specific variables. The page relies on `API_GATEWAY_URL` (dashboard proxy, default `http://127.0.0.1:8000`), `SCANNER_SERVICE_URL` (gateway upstream, default `http://scanner-service:8002`) and the shared storage settings in [docs/ENVIRONMENT.md](../ENVIRONMENT.md).

## Guardrails and limitations

- A completed live scan is required; synthetic snapshots return 409.
- Each family returns at most 1,000 items, even when `total` is larger.
- The service analysis review queue is capped at 50 entries.
- Unknown family names return 404 from the gateway and the core API.
- The page doesn't paginate or filter within a family.

## Tests

- Backend: [tests/test_v150_workflows.py](../../tests/test_v150_workflows.py) (`test_service_and_optimization_views_use_owned_observations`), [tests/test_assessment_api.py](../../tests/test_assessment_api.py) (analysis, resource analysis and AI risk evaluation ownership checks), [tests/test_assessment.py](../../tests/test_assessment.py) (`summarize`), [tests/test_route_inventory.py](../../tests/test_route_inventory.py).
- Dashboard: [web-dashboard/e2e/v150.spec.ts](../../web-dashboard/e2e/v150.spec.ts) (service and optimization destinations expose observed data and evidence gaps), [web-dashboard/e2e/assessment.spec.ts](../../web-dashboard/e2e/assessment.spec.ts) (service analysis labels partial pricing and protected counts without invoking AI).

## Related docs

- [Resources](resources.md)
- [AI assessments](ai-assessments.md)
- [docs/V1_5_0_IMPLEMENTATION.md](../V1_5_0_IMPLEMENTATION.md)
- [docs/RESOURCE_ANALYSIS_AND_AI_FOUNDRY_SETTINGS_README.md](../RESOURCE_ANALYSIS_AND_AI_FOUNDRY_SETTINGS_README.md)
- [docs/CLOUD_SOURCES.md](../CLOUD_SOURCES.md)
