# CloudSaver v1.0.0

CloudSaver reviews cloud resource waste and container requests with a Next.js /
React dashboard, five FastAPI services, PostgreSQL and Redis. This development
release applies the new v1.0.0 master guide to the latest
verified code: durable AI assessment history/usage, scoped normalized billing
imports and analytics, bounded concurrent discovery and corresponding console
workflows. Activation and live integration limits are recorded in TEST_REPORT.md.

Source: https://github.com/ashokkondapuram/project

## New in v1.0.0: durable enterprise evidence and billing analytics

- SQL-backed AI attempt reservation, restart-persistent idempotency fences, saved advice, append-only runtime lifecycle events and known token usage by model/target/observed cost-center/application IDs. Pending or uncertain outcomes never retry automatically.
- Finance-authorized normalized billing imports with exact decimals, stable charge deduplication, atomic conflict handling and PostgreSQL forced RLS. Billed/effective/list costs, conditional ESR, daily coverage, provisional budget projections and Z-score signals keep missing data explicit.
- Cost allocation adds explicit JSON import/review and currency/period/budget controls. Activity adds saved AI assessment and usage inspection, without initiating inference or approving actions.
- Up to four account/region readers run concurrently. Any provider failure discards the whole snapshot; source order remains stable.

Read the [master-guide feature mapping, import contract and upgrade instructions](docs/V1_MASTER_GUIDE.md). Apply schema-owner migration **0009_enterprise_evidence** before upgrading PostgreSQL services. The original Drive ZIP is preserved; the integrated source artifact has a distinct filename.

This implements a tested milestone from the guide, not every aspirational integration. Native billing connectors/reconciliation, Jira/ServiceNow synchronization, full hierarchy, monetary AI budgets and autonomous execution remain open. AI is still opt-in; model prose and imported billing completeness are not independently verified.

## New in v0.11.0: core assessment and enterprise AI governance

- Versioned five-pillar controls, explicit evidence fields/gaps, observation freshness and content fingerprints. Complete Kubernetes collector summaries are required for utilization checks.
- Security-first bounded review queue; current workspace scope is checked for every finding before returning service summaries or requesting inference.
- Azure ARG retains explicit disk encryption and empty-plan density/zone controls; AWS retains returned minor-upgrade settings. Missing controls stay unknown.
- Per-target output/context limits and source-provider policy; pillar-specific citations, observed-risk floor, terminal-response validation and provider-reported token usage.
- Console provenance, stale-snapshot warnings, priority drill-down and token-usage disclosure. Model text stays unverified advice; no automated change approval is introduced.

Read [assessment engine rules and activation](docs/ASSESSMENT_AI.md). AI remains disabled by default. API clients must preview the resource and include its `assessment.evidence_digest` when requesting inference; stale previews return 409 before a paid attempt.

## New in v0.10.0: advanced console experience

- Default dark slate console with a persistent light preference, accessible semantic states and a 240px/64px navigation rail.
- Counted provider/category pills, protected/unpriced quick views, token search, tag existence queries, observed sizing and partial-price summaries.
- Filtered/sorted previous/next comparison in the 640px drawer, an evidence-coverage radar, keyboard pillar inspection and telemetry facts with explicit gaps.
- Existing reviewed-code, AI, billing and integration permissions remain enforced. No synthetic safety percentages or historical activity are generated.

Read [the latest UI guide mapping and interaction details](docs/UI_UX.md).

## New in v0.9.0: service analysis and AI advisory

- Resource drawers now expose cost, reliability, performance, security and operations checks with explicit observed, risk and unknown evidence. Cost allocation includes service-level protected/risk/unpriced breakdowns.
- Resource tags and returned AWS settings support disaster recovery/retention protection. Destructive Azure scripts block protected resources, re-read live tags, and require successful managed snapshots before disk deletion.
- Opt-in, tenant-bound Azure OpenAI, Bedrock Converse and Vertex Google-model adapters use the existing keyless identities. Explicit acknowledgement, context minimization, strict response validation, Redis attempt budgets and idempotency fences bound inference. AI text cannot approve or execute changes.

Read [the source mapping, API and activation guide](docs/ASSESSMENT_AI.md). AI is disabled by default. Billing normalization, complete dependency analysis and autonomous execution remain outside this milestone.

## Inherited v0.8.0: runtime settings and managed identity

The latest upstream adds a PostgreSQL tenant registry, versioned workspace settings,
an operator console and managed-identity federation into Azure, AWS and GCP.
Workspace admins edit permitted cloud scopes and scheduling; identity bindings stay
operator-owned. No cloud secret storage is required. See [onboarding](docs/CLOUD_SOURCES.md).

## New in v0.7.3: keyboard review synchronization

Table selection and workspace selection now update in the same event. Global
keyboard handlers are refreshed before paint, so Shift-R consistently opens the
current selection even in fast browser runners. Switching snapshots clears the
selection. This patch follows the first GitHub CI browser result; see TEST_REPORT.md.

## New in v0.7.2: workspace experience and backend hardening

- Six working dashboard views, persistent responsive navigation, command search,
  actual observation charts, provider/scope drill-down, a virtualized inventory
  with filters/column controls/bulk CSV/JSON, and evidence/cost/code review drawers.
- Durable interactive Azure scan submissions: HTTP 202, tenant-scoped polling,
  restart persistence, atomic outbox dispatch, idempotency conflict protection and
  a five-job unfinished backlog bound. Existing multi-cloud scans remain synchronous.
- Bounded PostgreSQL connection pools with pre-ping/recycle, clean transaction
  context on reuse, separate liveness/readiness, restricted CORS, request IDs and
  secret-free problem responses. The authenticated gateway uses an atomic Redis
  sliding window shared across instances.

Read [backend activation and acceptance](docs/PRODUCTION_HARDENING.md) and
[UI source mapping](docs/UI_UX.md). Async jobs are disabled by default; activate
trusted subscriptions and run the worker and dispatcher before enabling them.
No credentials, customer data or cloud mutation are needed for the included tests.

## New in v0.7.1: operational reliability

- PostgreSQL transactional delivery intent: scheduled job reservation and broker
  handoff cannot split across a database commit; scan completion and notification
  intent commit together. Redis message-loss recovery reuses the durable job ID.
- Concurrent dispatchers use skip-locked row claims, expiring leases, fenced
  completion, eight automatic attempts, bounded jitter/backoff and dead letters.
  Broker messages must match a committed job/subscription selection.
- Explicit tenant-bound Slack / Teams integrations, aggregate-only messages,
  endpoint fingerprints and secret-free operational responses. The legacy global
  webhook switch is no longer used. Both manual and automatic messages use the
  durable queue; HTTP 202 means queued, not sent.
- Operational APIs/dashboard: state-filtered delivery history, keyset pagination,
  last dispatcher poll/success/error timestamps, oldest due backlog and append-only
  runtime audit history. Admin-only notification replay requires duplicate-risk
  acknowledgment and is capped at three replays.
- Pinned, read-only GitHub Actions gates for backend fault tests, dependency audit,
  production build and browser workflows; weekly dependency update review.
- Frontend security maintenance: Next.js 16, React 19 and Tailwind CSS 4; the old
  Tailwind/PostCSS build chain is removed. See TEST_REPORT.md for audit evidence.

Delivery stays disabled until explicitly configured. Read [the deployment and
failure runbook](docs/DELIVERY.md) before enabling schedules or integrations.
This provides at-least-once delivery, not exactly-once notifications, a production
SLO, immutable external audit storage or completed cloud-provider acceptance.

## New in v0.7.0

- Offline Terraform JSON guardrails for supported orphan relationships, deletion /
  replacement, required ownership tags and optional Infracost USD budget checks.
  A CLI and composite GitHub Action work without cloud credentials or Python
  dependencies. Raw plan values are not included in the report.
- Owned live-scan GitOps previews and explicit GitHub App draft-PR publishing to
  operator-approved repository IDs. Packages contain import review files only in
  `.cloudsaver/reviews/`; existing infrastructure files are untouched.
- Durable PostgreSQL/SQLite request keys, bounded attempts, tenant-scoped history,
  publisher leases and stale-token rejection. Ambiguous GitHub outcomes remain
  auditable; retries reconcile the existing draft rather than force-pushing.
- Production-only execution and expanded billing/operations dashboard from the
  fetched GitHub commit. Synthetic inventory exists only under tests. Historical
  synthetic snapshots retain provenance, hide illustrative costs and cannot
  generate Bash/Terraform exports or GitOps PRs.

Publishing defaults to disabled. Configure a reviewed GitHub App installation,
repository allowlist and trusted plan policy as described in docs/GITOPS.md.
Live GitHub App/Terraform/Infracost acceptance, native OAuth onboarding, GitLab /
Bitbucket and destructive approval workflows remain pending.

## Advanced features

- Read-only **GCP** checks for unattached zonal/regional persistent disks and
  unassigned regional external IPv4 reservations. Explicit dev/staging Cloud SQL
  candidates require 336 consecutive hourly connection maxima equal to zero;
  missing telemetry means unknown, not idle.
- **Kubernetes** CPU and memory request review using 14 days of complete hourly
  Prometheus samples. Requests must exceed nearest-rank P95 usage by more than
  50%. Evidence includes sampling window, units and headroom recommendation.
  CPU samples are five-minute rates; memory samples are working-set gauges.
- **AWS** EBS/EIP/stopped-RDS ingestion carried forward from the Drive v0.5.0
  design, with STS account verification, pagination and explicit credential
  profiles. Provider errors never substitute demo findings.
- Seven Azure checks, including the Drive network rule additions. Gateway review
  checks stopped state or absence of all backend pools; one empty pool alone
  does not establish an idle gateway. NIC/NSG signals imply no direct charge.
- Provider selection/filtering, evidence inspection and finding trajectories.
  Comparisons require matching mode, provider selection and scope fingerprint.
  New/resolved observations use resource/rule identities, not count differences.
- Import-only Terraform 1.5+ review for supported Azure/AWS/GCP findings, including
  regional disks. AWS exports constrain account IDs. The application never
  executes imports, deletes resources or changes workloads.
- Atomic PostgreSQL scan and normalized finding writes with forced RLS. The new
  cloud_findings table preserves the original Azure subscription foreign keys.
  Existing histories and both earlier migration lineages remain upgradeable.

Drive's v0.5.0 ZIP contains PostgreSQL stubs, relaxed schemas and live-to-demo AWS
fallbacks. It was reviewed as a feature source rather than replacing the working
storage/authentication implementation. Its configurable scheduler and ITSM
claims are not treated as verified features here. The existing opt-in Celery
scheduler remains Azure-only. See SOURCE_CONTEXT.md and IMPLEMENTATION_STATUS.md.

Live AWS/GCP/Kubernetes prices and net savings remain unknown. GCP Billing Catalog,
customer billing reconciliation, OpenCost allocation, idle namespace/DaemonSet
analysis and autonomous remediation remain roadmap work.

## Local development (standalone API)

Use Python 3.12, explicit `CLOUDSAVER_TENANTS`, and Azure credentials for live scans.
Configure `CLOUDSAVER_MODE=azure` and run the API with Uvicorn per `app/main.py`.
The standalone API uses SQLite snapshot history; PostgreSQL supplies normalized
ingestion, billing and scheduled job persistence in Compose.

## Local service stack (Docker Desktop)

CloudSaver 1.3 depends on the platform (identity-service, the platform database and the
platform portal), which is a separate product in `platform/` with its own compose project
and `.env`. Start the platform first; it creates the shared internal network `platform-link`.

```bash
python3 scripts/setup_compose.py
# Writes a new CloudSaver .env with its five identity caller tokens. Refuses to overwrite.
(cd platform && python3 scripts/setup_platform.py && python3 scripts/setup_platform.py --add-callers ../.env)
# Writes platform/.env, allows CloudSaver's callers (digests only) and prints the operator key once.
make platform-up      # docker compose -p platform: platform-db, platform-redis, identity-service, portal
make build
make up               # starts the platform, then CloudSaver
make status
```

For the full variable reference (both `.env` files, deprecated aliases, and Compose-only settings), see [docs/ENVIRONMENT.md](docs/ENVIRONMENT.md).

Upgrading from 1.2: back up both databases, stop the old stack, then run
`python3 scripts/setup_platform.py --migrate-from ../.env` in `platform/` (the key pepper
and operator key move unchanged, and `platform-db` reuses the `cloudsaver_token-db-data`
volume). Start the platform, export billing data with `scripts/export_billing.py` and
import it with `python -m identity.billing.importer -` in identity-service, then start
CloudSaver and run `python3 scripts/setup_compose.py --prune-platform`. See
platform/README.md.

The stack starts empty: no sample customers, workspaces, findings or prices are seeded.
Sign in to the platform portal (http://127.0.0.1:3100) with the operator key, create a
customer and a workspace, add its cloud accounts (Azure subscriptions, AWS accounts,
Google Cloud projects or Kubernetes clusters), and issue a workspace key. Then open
http://127.0.0.1:3000 and enter that key; `CLOUDSAVER_WORKSPACE_KEY=<key> python
scripts/smoke_stack.py` verifies the stack. Live scans also require cloud credentials
in Compose. The browser keeps the credential in that tab's session storage; it survives a
reload but clears on disconnect or when the tab closes, and after 30 minutes of inactivity.

Only dashboard port 3000 and gateway port 8000 bind to host loopback. Tenant,
scanner, analytics and notification services use internal ports 8001–8004.
PostgreSQL 16 and Redis 7 remain internal. Python services share one built image.
A one-shot schema-owner migration job completes before scanning starts; runtime
services use restricted cloudsaver_app credentials. Pending migrations apply on
Compose startup: review and back up before upgrading an existing installation.

`make scan`, `make test`, `make test-postgres`, `make logs` and `make down` provide
other lifecycle commands. `docker compose down` retains history; removing volumes
destroys it. See docs/OPERATIONS.md for migration, backup/restore and proxy builds.

## Entra authentication

Set CLOUDSAVER_AUTH_MODE=entra, CLOUDSAVER_ENTRA_AUDIENCE to the exact API audience,
and provision CLOUDSAVER_TENANTS with authorized Azure tenant/subscription UUIDs
and names. Expose the delegated API scope access_as_user and explicitly assign
CloudSaver application roles Viewer, TenantAdmin or BillingAdmin in Entra. All
service instances must use the same configuration. Bootstrap key hashes can be
omitted in Entra mode. There is no workspace/header fallback in Entra mode, no
ID-token/app-only-token acceptance and no inferred directory-admin privileges.

The dashboard accepts an access token obtained with the configured operator's
client. Browser authorization-code/PKCE sign-in, consent callbacks with single-use
state/nonce, self-service memberships and automatic discovery remain unfinished.
The fake sign-in button is removed; authenticated consent-link requests return
501. Directory consent does not grant subscription Reader RBAC: administrators
must separately grant and verify Azure access.

## Cloud sources, plans and schedules

For live scanning set CLOUDSAVER_MODE=azure (the compatibility live-mode switch),
explicit authorized workspace scopes. Cloud access is keyless: an Azure managed identity
federates into Azure, AWS and GCP (see docs/CLOUD_SOURCES.md). Platform operators manage
customers, workspaces, cloud scopes and keys in the platform portal (http://127.0.0.1:3100;
for local operator-key sign-in, issue a key with scripts/issue_operator_key.py). Workspace
admins (TenantAdmin role) manage schedules and alerts in dashboard Settings.

Plans, subscriptions and payments live in the platform. CloudSaver applies the
entitlements it receives in the identity verify response and the directory feed; the
built-in plan table is only a logged fallback. CloudSaver has no Stripe code:
`POST /api/v1/billing/checkout` and `POST /api/v1/billing/webhook` return `410`. Stripe,
when enabled, is configured on the platform (see platform/README.md). The dashboard Plan
tab shows the plan, its limits and a Manage billing link when the platform provides one.

Scheduled scans stay disabled by default. Explicitly provision/activate intended
subscriptions with scripts/provision_tenants.py, verify a persisted paid plan,
set CLOUDSAVER_SCHEDULED_SCANS=true and CLOUDSAVER_DELIVERY_ENABLED=true and use
`docker compose --profile scheduled up -d`. Keep one Beat scheduler operationally;
transactional reservations also prevent duplicate schedules in the paid interval.
Automatic notifications remain opt-in. Configure explicit per-tenant targets and
set CLOUDSAVER_AUTOMATED_ALERTS=true only after accepting delivery behavior. The
production worker uses the PostgreSQL outbox; historical in-memory test helpers
are not connected to production delivery. See docs/DELIVERY.md.

## API and verification

All /api/v1 routes require bearer authentication except the retired billing webhook,
which returns `410`. /healthz is public. Core routes are me,
scans, scans/{id}, analytics, billing/entitlements, notifications/{scan_id}, and scan-owned remediation /
remediation-terraform POST exports. Analytics needs the service stack; notification enqueue and operational routes
are also available on the standalone scanner when PostgreSQL is configured.

v0.6 authenticated routes: GET providers, POST scans/multi-cloud with only a
providers array, and GET trends?days=30&scan_id=UUID. The original POST scans
remains Azure-only. Runtime synthetic scans are unavailable; all fixtures are test-only.

Dashboard scans remain synchronous. Completed synchronous scans return 409 to
cancellation; foreign/unknown scans return 404. The UI does not report fake
cancellation. Interactive durable submission/progress/cancellation is future work.

```bash
python test_platform.py
# After npm ci: creates/removes disposable PostgreSQL and Redis containers.
python test_platform.py --postgres --frontend
```

See TEST_REPORT.md for executed checks and IMPLEMENTATION_STATUS.md for remaining
work. Platform tests run from `platform/` (see platform/README.md), and
`scripts/test_postgres_network.sh cloudsaver|platform` runs either PostgreSQL suite on a
disposable internal Docker network. Live Entra/Stripe/Azure acceptance, browser QA, dependency remediation and a
backup/restore drill remain required before shared hosting. No production status
is inferred merely from source files or mocked tests.
