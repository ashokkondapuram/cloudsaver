# CloudSaver v0.4.1

CloudSaver reviews potential Azure resource waste with a Next.js 15 / React 19
dashboard, five FastAPI services, PostgreSQL and Redis. This development release
extends the v0.4.0 source found in Drive and retains the verified PostgreSQL
isolation and normalized ingestion already pushed to GitHub.

Source: https://github.com/ashokkondapuram/project

## Changes from the Drive v0.4.0 baseline

- **Verified identity:** RS256 Microsoft JWKS verification, exact issuer/audience,
  required timestamps/subject/tenant/v2 delegated scope, and assigned CloudSaver
  app roles. All services share an explicit authentication mode. Unknown tenants
  are rejected; token claims never create subscriptions or paid plans.
- **Authorization:** Viewer is read-only; TenantAdmin controls scans/exports;
  BillingAdmin or TenantAdmin controls Checkout. Subscription/resource quotas,
  Terraform export and Key Vault plan gates use server-owned entitlements.
- **Evidence-based estimates:** supported hourly estimates require an exact,
  unambiguous USD retail consumption meter. Unsupported/missing prices remain
  unknown. Demo dollars remain illustrative fixtures. No net or realized savings
  are inferred from a list price or invented snapshot reserve.
- **Reviewable exports:** Terraform contains import declarations bound to the
  authorized tenant/subscriptions, with no guessed location, storage tier or disk
  size. It contains no deletion/snapshot plan. Bash retains interactive approval
  and immediate state checks. The application executes neither export.
- **Real Checkout path:** configured Stripe SDK calls use persisted customer
  ownership, operator-controlled HTTPS return URLs and idempotency keys. Missing
  configuration fails closed; synthetic payment URLs are removed. Existing
  subscriptions require the operator upgrade workflow. Verified/deduplicated
  webhook events determine persisted plans.
- **Worker hardening:** API and Celery scans share a real Redis lease with owner
  heartbeat/renewal. Observed lease loss stops persistence. Durable job tokens
  reject a stale attempt after another attempt claims the same job. Transactional
  scheduling reservations enforce daily Growth/hourly Enterprise intervals.
- **Compatible data upgrades:** a merge migration joins both prior release
  lineages, retaining history and atomic snapshot/finding writes.

## Local demo

Use Python 3.12 and Node.js 22:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python scripts/run_demo.py
```

In a second terminal:

```bash
cd web-dashboard
npm ci
npm run dev
```

Open http://127.0.0.1:3000 and enter the private workspace key printed by the
launcher. Demo scans do not call Azure. The browser keeps credentials in memory;
reload/disconnect clears them. The standalone API uses SQLite snapshot history;
PostgreSQL supplies normalized ingestion, billing and scheduled job persistence.

## Local service stack

```bash
python scripts/setup_compose.py
# This prints a private workspace key and refuses to overwrite an existing .env.
make build
make up
make status
python scripts/smoke_stack.py
```

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

## Azure, Stripe and schedules

For live scanning set CLOUDSAVER_MODE=azure, explicit authorized tenant scopes and
credentials. The imported environment/Key Vault providers fail closed and never
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
