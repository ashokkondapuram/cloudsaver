# CloudSaver v0.7.0

CloudSaver reviews cloud resource waste and container requests with a Next.js /
React dashboard, five FastAPI services, PostgreSQL and Redis. This development
release implements the GitOps/CI milestone from the Drive roadmap and builds on
the latest GitHub production-dashboard changes (076c96f).

Source: https://github.com/ashokkondapuram/project

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
explicit authorized tenant scopes and credentials. See docs/CLOUD_SOURCES.md for
AWS profile, GCP ADC and Prometheus configuration. The imported environment/Key Vault providers fail closed and never
use mock credentials. Key Vault requires Enterprise entitlement.

Checkout requires STRIPE_SECRET_KEY, CLOUDSAVER_BILLING_RETURN_URL (fixed HTTPS),
trusted CLOUDSAVER_STRIPE_CUSTOMERS and STRIPE_PRICE_TIERS, plus matching persisted
organization/customer ownership. The webhook separately requires
STRIPE_WEBHOOK_SECRET. See SPRINTS_ABC.md for provisioning and webhook contracts.
Checkout accepts target_tier and a 16–128 character idempotency_key from a billing
authorized user. No Stripe session or payment was created during development.
The existing-subscription portal/upgrade experience remains future work.

Scheduled scans stay disabled by default. Explicitly provision/activate intended
subscriptions with scripts/provision_tenants.py, verify a persisted paid plan,
set CLOUDSAVER_SCHEDULED_SCANS=true and use
`docker compose --profile scheduled up -d`. Keep one Beat scheduler operationally;
transactional reservations also prevent duplicate schedules in the paid interval.
Automatic notifications stay disabled in Compose pending a durable transactional
outbox and delivery auditing. The inherited in-memory outbox is a test foundation.

## API and verification

All /api/v1 routes require bearer authentication except the Stripe webhook, which
requires a valid raw-body signature. /healthz is public. Core routes are me,
scans, scans/{id}, analytics, billing/entitlements, billing/checkout,
billing/webhook, notifications/{scan_id}, and scan-owned remediation /
remediation-terraform POST exports. Analytics/notifications need the service
stack; they are not provided by the standalone scanner API.

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
