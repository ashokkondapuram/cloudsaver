# CloudSaver roadmap after v1.0.0

Source: [Advanced Features & Product Roadmap, v0.6.0–v1.0.0](https://docs.google.com/document/d/1Z-4CAVfSpimqBaxbNGAze_SWsbWdHwFP-bG0rccKK6Y/edit).
A text snapshot is retained in docs/drive-advanced-roadmap.txt. Its release dates,
production/compliance language and savings percentages are planning targets,
not acceptance evidence. The v0.5.0 source/guide was reviewed before development.

## v1.0.0 master-guide milestone

The [v1.0.0 master guide](https://docs.google.com/document/d/1FmtfohZPlnlwZ1lbcCuu-XX0G1uc6UI3Z87svw4P0zc/edit) now maps to durable AI assessment/usage evidence, normalized billing ingestion/analytics, bounded discovery and associated console workflows. See [the feature matrix and exact contracts](docs/V1_MASTER_GUIDE.md).

Next: accept actual cloud/model identities in staging; ingest native billing exports and reconcile totals; define audit retention/restore procedures and monetary budgets; extend durable jobs to multi-cloud; implement authenticated Jira/ServiceNow status synchronization and full organizational membership. Preserve existing protected intent and independent change approval. Version 1.0.0 does not certify full blueprint completion or production readiness.

**Proposed product spec (not implemented):** [Resource analysis, rule administration, portal UX, and AI knowledge](docs/RESOURCE_ANALYSIS_AND_PORTAL_ROADMAP.md). Commercial features in that spec depend on [platform billing gaps](docs/PLATFORM_BILLING.md) being resolved first.

**Proposed product spec (not implemented):** [Client-managed users and access keys](docs/CLIENT_MANAGED_USERS_AND_KEYS.md)—bootstrap onboarding, customer admin, delegated keys, and service accounts.

## v0.11.0 assessment and enterprise AI milestone

Versioned service controls, freshness/gaps/provenance, risk-prioritized review queues and snapshot-wide current-scope enforcement extend the README's five-pillar matrix. Target context/output budgets, source-provider restrictions, citation/risk-floor validation, terminal-response checks and provider usage metadata strengthen the existing AI gateway.

Follow-up implemented in v1.0.0: durable tenant-isolated inference attempt/usage ledgers. Remaining: monetary budgets, authorized staging acceptance of provider/IAM policies, raw telemetry/dependency collection, billing reconciliation and evaluated model quality. Provider-reported tokens in a cached response are not a durable billing ledger. Existing Redis idempotency retention remains 24 hours.

## v0.10.0 console milestone

The newest [Advanced UI/UX guide](https://docs.google.com/document/d/1hETTGMG5X9zo3AuuthHQgR8cgFPrG97V694sGxve2Os/edit) is applied to current code: dark/light tokens, resource facets, protected/unpriced lenses, observed sizing, evidence radar and context-preserving comparison. [UI mapping](docs/UI_UX.md) records where missing telemetry and financial evidence remain explicit.

Next UI milestones depend on authorized raw metric/billing/dependency feeds, broader usability and assistive-technology testing, and durable identity-scoped preferences. They must preserve unknown evidence and independent approvals.

## v0.9.0 optimization and AI milestone

The [new optimization / service analysis / AI guide](https://docs.google.com/document/d/1u_9HSbjE41srku4ZjDAbkSQ39wmeENOBMn2OGVO3oYs/edit) drives the next milestones. This release implements five-pillar finding assessment, provider/service grouping, explicit protected intent, mandatory snapshot scripts, and opt-in keyless cloud AI advisory. [Implementation boundaries and activation](docs/ASSESSMENT_AI.md) separate saved evidence from unknown billing and dependency data.

Next: accept model targets and IAM in staging; add durable inference audit and usage accounting; ingest and reconcile FOCUS billing; evaluate seasonal anomaly models; expand dependency and service telemetry; add organization hierarchy and reviewed tag/retention policies. Preserve tenant RLS and independent approvals. Historical version labels below describe the original Drive plan, not a claim that their entire scope shipped.

## v0.6.0 delivered milestone

Read-only GCP inventory and evidence-gated SQL review, native Kubernetes sampled
P95 request review, scoped AWS ingestion, provider UX, truthful observation
trends, import-only GCP/AWS/Azure Terraform and atomic forced-RLS persistence.
See IMPLEMENTATION_STATUS.md and TEST_REPORT.md for exact limits and checks.

## v0.7.0 delivered milestone

Offline Terraform plan guardrails and reusable CLI/Action, optional Infracost USD
budget checks, operator-approved GitHub App draft-PR review packages and durable
request idempotency/leases/history. The latest production-only dashboard commit
076c96f is retained; historical synthetic snapshots cannot become live evidence.

## v0.7.1 operational foundation

Transactional PostgreSQL scan dispatch/notification intents, leased dispatcher,
bounded retry/dead-letter handling, broker-loss reconciliation, durable job-envelope
validation, explicit tenant integrations, runtime append-only delivery audit and
operator history/replay are implemented. Next.js/Tailwind security maintenance
replaces the inherited frontend dependency chain. See TEST_REPORT.md for executed
fault tests and acceptance limits; this is not a production certification.

## v0.7.2 workspace and backend hardening

Drive UI/UX spec implemented as six real routes, interactive evidence views,
virtual inventory and review drawers. Drive production guide adapted to durable
Azure job submission/polling, resilient bounded pools, readiness, problem responses,
correlation, CORS and atomic shared throttling. Existing lease/outbox mechanisms are
retained; live cloud acceptance, production deployment and cancellation remain open.

## Finish v0.6 acceptance and the operational foundation

1. Accept AWS profiles/STS, GCP APIs/IAM/Monitoring, cluster metric sampling,
   Entra tokens, Stripe test-mode events and Terraform against authorized test
   systems. Complete browser QA. Continuously recheck dependency advisories after the v0.7.1 frontend upgrade.
2. Add exact GCP Billing Catalog SKU/currency/period attribution and customer
   billing reconciliation. Unsupported cases stay unknown. Add OpenCost/Kubecost
   allocation and evidence-based namespace/DaemonSet audits.
3. Accept the implemented PostgreSQL outbox/dispatcher in a staging deployment:
   broker outage/restart, process termination, webhook ambiguity, throughput and
   alerting. Add durable multi-cloud jobs, progress and cooperative cancellation.
   Preserve the synchronous API deliberately; automatic alerts remain opt-in.
4. Implement browser PKCE/consent callbacks with single-use state/nonce, memberships
   and explicit cloud-scope authorization. Finish billing portal, retention, audit,
   restore drills, deployment/HTTPS, observability and load/fault tests.

## Subsequent roadmap milestones

- **Complete v0.7 GitOps:** live GitHub App acceptance, native customer OAuth,
  GitLab/Bitbucket adapters, broader plan corpus and reviewed deletion workflows;
  Terraform plan JSON cost/OPA checks. Import reviews alone do not authorize
  destruction. Require source mapping, backup evidence and independent approval.
- **v0.8 anomalies/rightsizing:** billing time series, evaluated models, baseline
  and seasonality evidence, workload compatibility and measurable confidence.
  Do not promise fixed gp2/ARM savings across contracts or workloads.
- **v0.9 tags/showback:** tenant-scoped policy definitions, compliance scorecards,
  ownership, allocation rules and customer-supplied unit economics.
- **v1.0 governance:** durable multi-stage approvals/snooze/exemption, independently
  accepted recovery plans, credential rotation and immutable audit storage before
  any separately authorized execution. SOC 2 needs a real audit; code cannot
  certify it.

Preserve original Drive documents/packages. Publish matching source/checksum and
verification artifacts to the project folder. Ordinary checks must not execute
remediation, send alerts, create payments or claim unperformed external review.
