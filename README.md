# CloudSaver v0.9.0

CloudSaver reviews cloud resource waste and container requests with a Next.js /
React dashboard, five FastAPI services, PostgreSQL and Redis. This development
release adds evidence-led five-pillar service analysis and optional keyless cloud AI
advisory to the v0.8.0 tenant registry and operator console. Deployment acceptance
and live integration limits are recorded in TEST_REPORT.md.

Source: https://github.com/ashokkondapuram/project

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

```bash
python scripts/setup_compose.py
# Prints a workspace access key once and writes CLOUDSAVER_TENANTS into .env.
# Refuses to overwrite an existing .env.
make build
make up
make status
export CLOUDSAVER_WORKSPACE_KEY='<key printed by setup>'
python scripts/smoke_stack.py
```

Open http://127.0.0.1:3000 and enter the workspace access key. Live scans require
authorized subscription IDs in `CLOUDSAVER_TENANTS` plus cloud credentials in Compose.
The browser keeps credentials in memory; reload/disconnect clears them.

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

## Cloud sources, Stripe and schedules

For live scanning set CLOUDSAVER_MODE=azure (the compatibility live-mode switch),
explicit authorized tenant scopes. Cloud access is keyless: an Azure managed identity
federates into Azure, AWS and GCP (see docs/CLOUD_SOURCES.md). Manage workspaces in the
operator console (/admin; issue a key with scripts/issue_operator_key.py) and scopes,
schedules and alerts in Settings.

Checkout requires STRIPE_SECRET_KEY, CLOUDSAVER_BILLING_RETURN_URL (fixed HTTPS),
trusted CLOUDSAVER_STRIPE_CUSTOMERS and STRIPE_PRICE_TIERS, plus matching persisted
organization/customer ownership. The webhook separately requires
STRIPE_WEBHOOK_SECRET. See SPRINTS_ABC.md for provisioning and webhook contracts.
Checkout accepts target_tier and a 16–128 character idempotency_key from a billing
authorized user. No Stripe session or payment was created during development.
The existing-subscription portal/upgrade experience remains future work.

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

All /api/v1 routes require bearer authentication except the Stripe webhook, which
requires a valid raw-body signature. /healthz is public. Core routes are me,
scans, scans/{id}, analytics, billing/entitlements, billing/checkout,
billing/webhook, notifications/{scan_id}, and scan-owned remediation /
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
work. Live Entra/Stripe/Azure acceptance, browser QA, dependency remediation and a
backup/restore drill remain required before shared hosting. No production status
is inferred merely from source files or mocked tests.
