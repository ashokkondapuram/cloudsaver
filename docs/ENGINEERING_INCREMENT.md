# Persistent engineering reviews: implementation record

Baseline: `2937c30d52aea02d6041051db1dc861643bbf28e`. This increment preserves the existing FastAPI, PostgreSQL, gateway and Next.js contracts. It adds a review-only Azure workflow and reliability/access improvements; it does not complete every capability in the architecture proposal. Validation is local, without a connected cloud sandbox. Dashboard styling remains consistent with the existing design, with no glass treatment or additional data-flow animation.

## Working path

In **Workloads → Engineering plans**, a tenant administrator can create a workload in an authorized Azure subscription, declare an owner/team and bounded SLO/peak/recovery references, attach a resource from a completed live saved scan, and prepare an immutable VM rightsizing or disk review. Viewers can inspect authorized records. The original saved workload-assessment view remains available.

Each review records the exact resource, scan, workload version, evidence digest, evaluator digest, action, candidate and checks. A new observation or changed workload produces a new review version; it never rewrites the prior manifest. The UI exposes blockers, version history and activity, and preserves the exact idempotency key/body when retrying an uncertain command. Missing memory, insufficient raw samples, stale evidence, unknown ownership, unregistered IaC, missing trusted plan artifacts or absent sandbox proof remain unknown/blocked. Neither approvals nor infrastructure execution are enabled by this workflow.

The Overview retains coverage and evidence freshness, next actions, the most relevant review items and concise guides to subsequent sections. Existing specialist navigation remains available through its disclosure. Financial outcomes are not invented from estimated opportunity.

## API and persistence

The additive namespace is `/api/v1/engineering`:

| Method | Path | Contract |
| --- | --- | --- |
| GET | `/capabilities` | Supported actions, policy, limits and release gaps |
| GET / POST | `/workloads` | Authorized keyset list / create workload |
| GET / PATCH | `/workloads/{id}` | Read / version-checked edit |
| GET / POST | `/workloads/{id}/members` | List / attach a saved resource observation |
| GET / POST | `/workloads/{id}/plans` | List / create immutable review |
| GET | `/plans/{id}/versions` | Review history |
| POST | `/workloads/{id}/plans/{plan_id}/versions` | Create a revision bound to its parent |
| GET | `/workloads/{id}/events` | Audited activity |

Commands use strict bounded schemas and UUID `Idempotency-Key`; existing-parent changes require quoted `If-Match`. Missing/stale versions return 428/412; changed replay content returns 409. Every replay rechecks current authorization. Lists default to 50, cap at 200 and use signed, expiring cursors bound to tenant, actor, authorization, operation and page size. Set a stable secret of at least 32 bytes in `CLOUDSAVER_ENGINEERING_CURSOR_KEY`; production/staging startup requires it. Rotate it knowing existing cursors will need a fresh first page.

Core, gateway and browser proxy forward the command/precondition headers and preserve status, Location and ETag. OpenAPI declares command and response schemas. Existing route aliases and IDs are preserved; this increment does not introduce a second tenant database or silently replace routes with the proposal's `/v1/tenants/...` paths.

Migration `0027_engineering_workloads` follows `0026_control_plane`. Seven additive tables hold workloads, immutable members, links to existing `cp_plans`/`cp_plan_versions`, exact version targets, idempotent commands, events and outbox intents. They use tenant-composite foreign keys and forced RLS with the repository's existing `app.current_tenant_id` transaction-local convention. Runtime grants prohibit editing immutable history; only specific workload metadata columns are updatable. SQLite development tests enable foreign keys and append-only triggers. Tables remain unpartitioned.

Supported migration evidence includes clean installation through head, a populated 0026 upgrade preserving existing control-plane records, and empty 0027 downgrade. Downgrade refuses populated engineering history and restores forced RLS. These tests do not establish every historical upgrade or production backup/restore path. Mutations, events and outbox intentions commit in one transaction. An outbox publisher for these new events is not included; do not claim external delivery.

## Provider and integration scope

| Existing integration | Implemented data paths to validate independently | Remaining acceptance |
| --- | --- | --- |
| Azure | Resource Graph inventory; Monitor metrics; Activity Log; operational guards/recovery lookups; Cost Management Actual/Amortized queries; commitment reads | Exact resource-family permissions, public-cloud API versions, completeness, billing source semantics and scale. Sovereign endpoint profiles remain work. |
| AWS | STS account check; configured regional EC2/RDS and additional supported service inventory; CloudWatch and CloudTrail; Cost Explorer; optional CUR via Athena; commitments | Current IAM/trust policies, regional coverage, SDK limits, CUR schema and full quota coordination. No Organizations-wide automatic enrollment. |
| GCP | Configured project Compute/SQL inventory; selected Cloud Asset types; Monitoring/Logging; configured BigQuery billing export | Federation, datasets, labels, schema, quotas, source lag and endpoint-specific completeness. |
| Kubernetes | Registered API list pagination; historical Prometheus; optional OpenCost; Azure/AWS/GCP managed Prometheus authentication | Cluster RBAC, API versions, label attribution, historical coverage and verified allocation. |
| Observability | Prometheus, mapped REST metrics, Tempo, Jaeger; bearer/basic/header references and supported managed identities/SigV4 | Actual client endpoints, scopes, network boundary, rate limits and source semantics. A generic REST adapter does not establish Datadog/Dynatrace/New Relic/Wiz support. |
| GitHub | Existing registered review and workflow adapters | Trusted webhook/plan provenance, branch/environment controls and authorized sandbox execution. |
| Other tools/providers | Separate adapter contracts and explicit capability status | GitLab, Azure DevOps, ITSM, new security/APM products, OCI, Alibaba and IBM require implementation/validation per integration. |

This table inventories code paths, not a verified catalog of every industry API. [Keycloak and collection documentation](KEYCLOAK_AND_COLLECTION.md) describes retry coordination, billing deferral, health probes and the exact identity/license boundary. Provider HTTP errors, unknown evidence and financial uncertainty remain visible. Zero throttling and provider-controlled freshness are not promised.

## Remaining lifecycle gates

- Registered, verified IaC ownership and resource incarnations; trusted saved-plan/state/toolchain digests; a real reviewed Terraform change, independently approved and checked again under the backend lock.
- A complete authorization model for delegated resource-level Keycloak grants and initiating principals on queued work, plus browser PKCE/session/logout and identity migration acceptance.
- Durable page checkpoints, safe event-driven reconciliation, service-specific quotas and measured freshness SLOs per integration.
- A protected outbox publisher, tenant-safe notifications, immutable relationship/ownership correction semantics and complete cross-resource conflict detection.
- Actual technical verification and accepted financial counterfactuals from comparable complete source revisions, recovery exercises and an authorized cloud sandbox run.

## Verification

Local checks completed on 2026-10-29 (overlapping runs are not summed):

| Check | Result |
| --- | --- |
| Disposable PostgreSQL/Redis: engineering, migrations, RLS, existing database/control-plane tests, billing and shared quota coordination | 116 passed, 1 skipped |
| Auth/route inventory/worker/billing/observability regression after route classification fix | 75 passed |
| Keycloak API and worker denial, licensing, billing cancellation recovery and route contracts | 38 passed |
| Overview and engineering browser workflows, mobile layouts and accessibility in both themes | 11 passed |
| Agent TypeScript type check and unit suite | Passed; 25 tests |
| Portal type check, production build and unit suite, including health failure behavior | Passed; 13 tests |
| Dashboard production build | Passed |
| Independent platform identity suite | 36 passed |
| Undefined-name checks and high-severity Bandit checks | Passed |
| Compose worker probe mappings | Parsed and checked |
| Real local portal HTTP check | Liveness 200 without a session; readiness 503 with identity unavailable; protected page still redirects |

The broad backend run passed 955 tests with 101 environment-dependent skips and one missing public-health route classification; that classification was corrected and its suite passed in the targeted rerun above. No provider or Keycloak sandbox was contacted. Tests use fake provider responses or disposable local PostgreSQL/Redis; none authorizes or validates a real cloud apply. The tracked-source release manifest is regenerated for this increment. Full hosted CI and production acceptance remain required before merging/releasing.
