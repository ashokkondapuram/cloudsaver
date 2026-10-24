# Lean CloudSaver: implementation and upgrade guide

Source specifications:

- [README-Lean-Feature-Pruning-Spec.md](https://docs.google.com/document/d/148KG7_r2E12DWqbhz1L6_vHCSamjY8vy_5E2FGtsRtw/edit)
- [README-Existing-Feature-Improvements-Spec.md](https://docs.google.com/document/d/1TWvfN8xbr4TEpErYK5HAQB0OinWzYbKYUnB5bwAOu0c/edit)

Applied to the local v1.4 baseline `6e9a4b9`, preserving its live collectors, 36-family catalog, multi-cloud typed worker and purpose-bound data governance. The source documents describe the older `f11ccf0` baseline; existing delivered safeguards were retained rather than reimplemented.

## Product and deployment consolidation

The five main views are Overview, Resources, Kubernetes, Agent worker and Settings. Settings contains exactly four top-level tabs. Activity, delivery status, scan history and AI history are embedded in Cloud scopes & billing. AI binding configuration and processor/retention policy now appear in the same tab.

Removed customer pages, backend mounts, edge proxy routes and BFF allowlist entries:

- Findings and the four-service Azure explorer; per-finding inference endpoints.
- Optimization studio, manual scenario forms, portfolio uploads, signed-receipt ingestion and the second savings-case lifecycle.
- Automation/GitOps, Terraform plan policy and CLI/Terraform text exports.
- Standalone allocation, print report and activity pages; fragmented settings subroutes.
- Shared knowledge retrieval, candidate harvesting, publication/review APIs and portal pages. Saved legacy consent fields are ignored and omitted from normalized policy.

Resource CSV export, durable per-resource AI batches, follow-up, reviewer decisions, read-only Kubernetes patch previews, notifications and audited delivery APIs remain. Internal SLO and exact decimal commitment math remain callable by resource analysis; their removal from manual forms is not removal of safety checks.

The four service-wrapper files are deleted. Compose keeps the edge, core backend, isolated agent gateway/worker, dashboard and background processes. Settings, analytics and notification intent creation now run in the core backend. The directory projector starts/stops with the core application lifespan, including event-listener cleanup. Its identity caller needs the directory permissions previously held by the removed tenant service. Review the platform caller grants when upgrading.

No migration drops old savings/GitOps/knowledge tables or rewrites their audit records. Historical migrations and fixtures remain as upgrade history. The live application no longer reads/writes those removed products. Archive/export historical records using an independently reviewed administrator process if needed; this change does not erase them.

## Resource assessments and lifecycle

Three former unconditional unknown checks now inspect concrete evidence:

| Check | Observed / risk behavior |
| --- | --- |
| `BILLED_COST` | Exact resource-period USD billing is displayed as imported evidence. A purchase/effective-vs-billed commitment signal produces a review risk. |
| `ACCESS_AND_EXPOSURE` | Compute checks explicit admin ingress and IMDS control; network checks explicit ingress and WAF/DDoS protection; applications check HTTPS. Missing properties stay unknown. |
| `DEPENDENCY_GRAPH` | Explicit associations create a dependency risk. An empty list needs complete inventory and fresh contiguous, complete state history before it can be observed. Missing graph edges are never treated as absence. |

Healthy inventory retains evidence and receives the same checks without inventing findings or prices. Billed/effective costs remain separate from retail opportunities. Scan deltas compare an earlier completed scan with the same authorized scope fingerprint: new, persisting, regressed. A previously flagged resource still observed without findings is counted as resolved. Disappeared resources are counted separately as no longer observed; this does not establish deletion or savings.

Expired defer decisions reopen in the read projection; their original append-only decision record is preserved. Evidence changes remain visible independently of expiry. Comparison searches the retained 100-scan window and returns unknown comparison counts if no comparable baseline is available.

The unified table supports provider, service, priority, pillar, AI and decision filters. CSV uses the same server-side filters. The drawer adds saved metric windows, provenance, coverage, P95/P99 summaries and an owned-resource handoff to the agent workspace.

## Billing joins and commitment planning

`FocusRepository.resource_costs()` joins exact normalized resource identities within the currently authorized provider/account set. Azure IDs are case-insensitive; AWS/GCP IDs retain their canonical case. Only wholly contained charges in the saved scan's preceding 30 complete UTC days contribute. Long charges crossing the boundary are not prorated. Imports in another currency do not enter USD columns. Incomplete import coverage remains explicit, and account totals are never distributed across resources.

Billing attachment is shared by resource list/detail and asynchronous AI processing, so a changed import changes the resource evidence digest and stale batch work is skipped. Raw bill amounts and resource identifiers are not added to the model's allowlisted facts.

The overview calls the internal clean-before-commit engine automatically. A complete saved `commitment_evidence` contract requires verified source and commitment coverage, matching 720-hour USD usage/cleanup profiles, and an existing commitment amount. It subtracts cleanup hour by hour before calculating P10 and then applies the existing decimal baseline engine. Missing profiles leave the ceiling unknown; monthly retail opportunity divided by 730 is not a valid substitute. No purchase action is exposed.

## Regional retail pricing

Azure exact consumption-meter evidence can describe `components` named:

- `current` and `snapshot` for disk retention; snapshot overhead is subtracted.
- `current` and `target` for disk/VM rightsizing; target compatibility must be verified.
- `disks`, plus `compute` only for a stopped-but-allocated VM. A deallocated VM has no modeled compute charge.
- `gateway_fixed` and `gateway_capacity` for an idle App Gateway.

Each component contains one or more exact meter selectors (`region`, `sku_name`, `meter_name`, `product_name`, `meter_id`, `unit_of_measure`, `quantity`). Accepted monthly/hourly/GB units have explicit conversion rules. Ambiguous, missing or invalid meters leave the estimate unknown. Collectors without exact price selectors do not fabricate them from an example price.

AWS and GCP use `CLOUDSAVER_REGIONAL_PRICE_CATALOG`, a bounded JSON list of reviewed meters. Example **contract only** (replace the example rate with a rate verified for your deployment):

```json
[
  {
    "provider": "aws",
    "region": "us-east-1",
    "product": "public-ip:unassociated",
    "unit": "hour",
    "currency": "USD",
    "rate_usd": "0.005",
    "source": "https://aws.amazon.com/vpc/pricing/",
    "reviewed_at": "2026-10-24T00:00:00Z",
    "expires_at": "2026-11-24T00:00:00Z"
  }
]
```

The review must be current, last no more than 90 days and name an allowed official HTTPS pricing source. Region/product/unit/currency matches must be unique. Empty catalog, unknown region, duplicate meter, missing quantity or expired review means unknown. These estimates are explicitly marked operator-reviewed retail, not a live pricing API response or verified cash savings.

Automatic provider quantity mapping supports:

- AWS EBS `gp2`, `gp3`, `io1`, `io2`, `st1`, `sc1`: storage, billed IOPS, gp3 throughput above included capacity, and snapshot storage. Catalog products are `ebs:<type>:storage`, `ebs:<type>:iops`, `ebs:gp3:throughput`, `ebs:snapshot`.
- AWS stopped RDS: `rds:<storage-type>:storage` and provisioned `:iops`; compute is not charged for a confirmed stopped instance by this model. Regional storage-tier pricing must match the reviewed deployment; unsupported tier adjustments remain unknown.
- GCP persistent disks: `disk:<type>:storage`, `disk:<type>:iops`, `disk:<type>:throughput`, and `disk:snapshot`. Hyperdisk products must encode reviewed included-capacity/tier treatment in the supplied component quantities; do not apply a flat IOPS rate to an unverified tier.
- GCP custom Cloud SQL: observed custom vCPU/RAM, storage, explicit ZONAL/REGIONAL availability. Products are `cloud-sql:vcpu:<availability>`, `cloud-sql:memory:<availability>`, `cloud-sql:<pd_ssd|pd_hdd>:storage:<availability>`.
- Unassociated public IPv4: `public-ip:unassociated`; 730 illustrative monthly hours.

Explicit `pricing_evidence.regional_components` can supply separately reviewed quantities with `product`, `unit`, `quantity`, and `role=current|snapshot|target`. It cannot authorize execution. No guessed global price table is shipped.

## Durable multi-cloud scans

`POST /api/v1/scan-jobs` accepts either legacy `subscription_ids` or a `providers` selection, plus an idempotency key. It snapshots only provider names and authorized scope IDs into the committed outbox; role ARNs, tokens, credentials and arbitrary destinations are not broker payloads.

Dispatcher and worker reauthorize the selection. Provider entitlements, scope/resource quotas, frozen rule policy and distributed lease fencing still apply. All selected providers must succeed before a unified snapshot is saved. The completion transaction rechecks Azure connections and the current active multi-cloud registry projection, then writes Azure findings and non-Azure `cloud_findings` atomically with the job and delivery intent. Scope revocation, stale workers and modified broker selections cannot commit. Multi-cloud durable completion requires a current database registry projection; environment-only scopes must be projected before enabling jobs.

Scheduling includes configured AWS, GCP and Kubernetes scopes even when there are no Azure subscriptions. Legacy queued Azure intents remain readable. Job histories currently require full-workspace access because they are not provider-filtered. Resource and governance reads retain their scoped views.

## Kubernetes costs and EKS identity

An EKS `aws:///zone/instance` providerID is linked only when exactly one discovered, authorized EC2 ARN matches its standard region and instance ID. Multiple accounts matching the same accountless identity remain ambiguous. Azure and GCP canonical mappings remain intact.

Node billing requires a complete imported resource window. Pool consolidation modeling requires complete requests, uniform capacity, a positive candidate count, explicit verified scheduling constraints, PDB/autoscaler permission and no commitment lock. Candidate costs use the cheapest covered nodes conservatively. Missing placement/eviction proof stays unknown; OpenCost allocation is never relabeled as a bill. The live collector does not independently certify every scheduler constraint, so many real pools will correctly retain unknown physical savings.

## Execution and data governance

Approval hash schema 4 binds typed connectors, generated code and the saved expected state. New tasks derive bounded state fields from the owned scan. Models cannot replace a saved state with a different expectation. The worker independently validates expected-state keys and checks real provider metadata; Azure tag-only execution now inspects operational resource metadata as well as tags. A mismatch returns `LIVE_RESOURCE_STATE_DRIFTED` and prevents the write. Full metadata drift after inspection also blocks execution even if tags stayed identical.

Supported Azure metadata API versions are explicit in the worker. Unknown resource types fail closed; add a reviewed typed version before enabling them. AWS/GCP typed adapters retain keyless identity, scope, fingerprint and live-state checks. Kubernetes verifies namespace, UID/resourceVersion and expected generation/replica state. Human review requires an authenticated TenantAdmin user session; workspace API keys and service accounts cannot approve.

All existing purpose-bound processors, scoped data-use views, retention and audited hold-release safeguards remain. Shared knowledge retrieval and ingestion are gone, not merely hidden behind a switch. A provider processing declaration records review and is not independent proof of residency or training behavior. The upstream Azure Identity/MSAL authorization-code advisory described in `V1_4_IMPLEMENTATION.md` remains; the worker exposes only managed/workload identity flows.

## Verification

Final gate results are recorded below after implementation and regression checks complete. Tests use synthetic provider responses, real disposable PostgreSQL/Redis privileges and browser API fixtures. No customer scan, production deployment, cloud mutation, GitHub publication or Drive upload is performed by these checks.

Verified on 2026-10-24:

| Gate | Result |
| --- | --- |
| Full backend/platform suite using disposable PostgreSQL 16 and Redis 7, including RLS, migration privileges, multi-cloud atomic completion and scope revocation | 739 passed; one upstream Starlette/httpx deprecation warning |
| Retained and consolidated browser workflows, including mobile and accessibility checks | 29 passed |
| Dashboard production build and TypeScript compilation | Passed |
| Platform portal production build and TypeScript compilation | Passed |
| Worker TypeScript check and host runtime suite | Passed; 21 tests |
| Worker runtime suite in pinned Node 24.22.1 Alpine, non-root, no networking, read-only filesystem and 256 MB memory limit | 21 passed |
| Patch whitespace and staged credential-pattern checks | Passed |

Tests dedicated to deleted products were retired with those products. Core isolation, provider authorization, billing, resource assessment, SLO safety, agent fencing and governance tests remain. These results do not establish live provider acceptance, current regional prices or verified savings. The Azure Identity/MSAL advisory remains as documented; no unsupported major dependency override was installed.
