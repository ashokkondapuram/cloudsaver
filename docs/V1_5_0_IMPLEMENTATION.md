# CloudSaver v1.5.0: automatic billing and paired agent reviews

This release integrates the supplied v1.5.0 Drive patch with the current application. It retains the restored 673c20a resource, Kubernetes, FinOps, agent, governance, platform and deployment workflows. The four replacement files in Drive were incomplete: their missing modules, APIs, persistence, worker contracts and UI destinations are implemented here without replacing the existing route safety inventory.

## Upgrade

Back up PostgreSQL. Deploy matching API, gateway, workers and dashboard images together. Run the existing migration service before starting application containers: `docker compose --env-file .env up --build migrate`, then `docker compose --env-file .env up -d --build`. The core head is **0020_billing_and_agent_gitops**, following existing 0019; no migration number is reused. Platform identity migrations remain independent. Neither database volumes nor existing credentials need to be reset.

Two new tables, `billing_sync_runs` and `agent_gitops_syncs`, enforce forced PostgreSQL RLS with transaction-local workspace identity. The application role has no bypass or superuser privileges. SQLite persists the same workflow journals for development; PostgreSQL is required for production isolation. Previous role-bootstrap and platform password recovery fixes remain intact.

## Automatic billing

Set `CLOUDSAVER_AUTO_BILLING_SYNC=true` (default). Configure `CLOUDSAVER_BILLING_CONNECTORS` as a JSON array of explicit operator-owned workspace/scope bindings. It contains no cloud secrets:

```json
[
  {"tenant_id":"11111111-1111-4111-8111-111111111111","provider":"azure","scope_id":"22222222-2222-4222-8222-222222222222"},
  {"tenant_id":"11111111-1111-4111-8111-111111111111","provider":"aws","scope_id":"123456789012"},
  {"tenant_id":"11111111-1111-4111-8111-111111111111","provider":"gcp","scope_id":"customer-project","billing_project":"billing-export-project","dataset":"billing","table":"gcp_billing_export_v1_example"}
]
```

Each binding must also be authorized in the workspace's existing cloud scope configuration. Revocation removes it from effective billing configuration. At most eight scopes run per bounded synchronization, with up to 5,000 returned rows per scope. More scopes require partitioning workspaces or a future paginated orchestration adapter; they are never silently skipped.

| Source | Identity and permission | Evidence imported | Boundary |
| --- | --- | --- | --- |
| Azure Cost Management ActualCost | Existing tenant-bound Azure credential; Cost Management Reader on subscription | Daily resource charges | ActualCost, not verified amortization. Paginated responses fail closed rather than importing a misleading partial page. |
| AWS Cost Explorer | Existing exact account/role keyless binding; `ce:GetCostAndUsage` | Daily linked-account UnblendedCost and AmortizedCost, grouped by record type | Account totals; resource attribution and CUR ingestion are not inferred. Up to ten pages, no SDK automatic retry. |
| GCP standard BigQuery billing export | Existing project impersonation; BigQuery Job User in export project and Data Viewer on export dataset | Daily project cost and effective cost including export credits | Project totals. Parameterized project/time filters; fixed approved table, 1 GB query budget, bounded result. Incomplete or paginated jobs fail closed. |

The Celery beat scheduler runs hourly across configured active workspaces, importing all returned currencies separately. The billing view can perform initial hydration and an explicit **Sync now** for its selected currency. Status comes from durable runs; unconfigured/disabled/failing sources never display a fabricated success. Gateway endpoints are `POST /api/v1/finops/sync?currency=USD` and `GET /api/v1/finops/sync-status`, restricted to finance-authorized full-scope workspace principals.

The query window is thirty closed UTC days ending two days before today. Immutable ledger entries use stable logical keys and append correction deltas when a provider revises an observed amount, including a later return to an earlier value. Repeated identical snapshots add no charges. Empty or disappearing source rows do not establish a zero charge; export completeness remains **unverified**. Existing manual imports can overlap automatic sources; inspect overlap provenance before summing data from independently supplied exports.

Missing billing, list cost, resource attribution and currency conversions remain unknown. Retail prices never become billed amounts. Forecasts and verified savings retain existing independent completeness/evidence gates. Manual normalized FOCUS JSON remains available under **Advanced: Manual FOCUS JSON Override**.

## Agent metadata and repository pairing

Keep existing human-session approval, AI data governance, workload identity and worker registration settings. Add one connector alongside a typed cloud connector:

```json
{
  "id":"infra-review",
  "tenant_id":"11111111-1111-4111-8111-111111111111",
  "provider":"azure",
  "scope_id":"22222222-2222-4222-8222-222222222222",
  "kind":"gitops_terraform",
  "target_id":"infra",
  "operations":["gitops.terraform.sync"]
}
```

`infra` must exist in `CLOUDSAVER_GITOPS_TARGETS` with exact tenant, repository name, numeric repository ID, installation ID and base branch. Enable `CLOUDSAVER_GITOPS_PUBLISH=true` and configure the existing GitHub App credentials on the API and agent gateway. Register both connector IDs for the worker. Compose passes repository metadata to the worker; GitHub App private keys stay server-side. Pairing requires the workspace's Terraform entitlement.

The validated plan contains a prior typed inspection, exactly one metadata merge, then `gitops.terraform.sync` as the final bounded call. The gateway adds the paired step deterministically when the planner omits it. Arguments must exactly match the cloud merge. Approval hashes include the complete repository binding; changing the destination invalidates approval. Unsupported resource mappings are rejected before mutation. Generic Azure VMs remain unpaired until their Linux/Windows Terraform type can be verified; no operating-system type is guessed. Existing unpaired cloud plans retain their previous hash format.

The UI displays the proposed Terraform JSON review fragment, repository and actual plan hash before approval. Only a verified human TenantAdmin session can approve. Every call requires a single-use ordered permit and unexpired saved approval. Repository publication requires recorded successful inspection and cloud action evidence; no random task ID, synthetic inspection digest or fabricated policy PASS is accepted.

The gateway publishes a draft PR and records its outcome itself. The worker cannot report a successful repository result independently. PR artifacts live under `cloudsaver/agent-reviews/`, outside active Terraform roots. They describe the exact tags, labels or Kubernetes annotations to merge into the existing configuration while preserving other metadata. Repository owners must integrate them, run real Terraform CI, review state ownership and use normal branch protection. No automatic merge or apply occurs.

A completed cloud write followed by cancellation, failed or uncertain PR publication requires reconciliation. It does not replay the cloud mutation or automatically retry the repository operation. Inspect the task audit, provider audit trail, approved destination and **Activity → Execution & IaC**. A durable once-only fence protects duplicate publication attempts. Its journal retains task/hash/repository linkage and outcome, without duplicating raw metadata attributes. An interrupted publisher may leave a running journal until an operator investigates; task uncertainty still blocks replay.

**Scope:** this release pairs metadata merges with repository review. Automated SKU resizing, resource deletion, snapshot/IaC pairing, automatic production Terraform apply, zero instantaneous drift and verified runtime/IaC parity are not implemented. They require typed provider-specific adapters, complete state ownership and additional approval contracts. A draft PR is not proof of deployment parity or financial savings.

Repository export is an explicit operator-configured connector: task/resource identifiers and approved metadata appear in its review artifacts. Use an organization-controlled repository with the required residency and access controls. Generic HTTP actions remain blocked; this workflow does not send raw resource inventories to a model or build a client-data knowledge base.

## UI and planning evidence

Four sidebar groups retain all existing workflows and add eight service families, optimization evidence and the executive report. Service matrices show only owned completed live observations, rule signals and separately labeled billed/retail costs. Planning inputs derive from actual dependency, SLO, network and commitment evidence; absent inputs remain `insufficient_evidence`. No synthetic savings, dependency completeness or purchase authorization is manufactured.

**Automation → Plan guardrails** generates repository import/review artifacts directly from the selected scan without file upload. Its `review_required` projection is distinct from the existing actual Terraform/Infracost plan evaluator, retained in the advanced offline section. Repository CI must provide the actual Terraform plan.

## Verification

Backend tests exercise correction/idempotency, disabled/revoked bindings, sanitized provider failures, persistent workflow fences, approval/repository drift, post-write cancellation and owned service/planning routes. PostgreSQL integration tests check forced RLS and cross-tenant write denial on both journals. Worker tests check gateway-only repository outcomes and exact metadata matching. Existing route compatibility, platform, browser and build checks remain release gates.
