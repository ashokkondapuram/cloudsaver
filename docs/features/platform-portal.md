# Platform portal and operator stack

The `platform/` stack is the operator side of CloudSaver. It runs identity-service (the source of truth for customers, workspaces, keys, plans, billing, rule policy, AI policy and knowledge publications), the platform portal that operators use to manage it, a dedicated PostgreSQL database, a Redis instance for sign-in throttling, and an egress proxy that limits outbound identity traffic to approved hosts. CloudSaver itself only calls identity-service through authenticated internal routes; customers never reach the operator API.

Last reviewed: Oct 25, 2026.

## Where to find it

- **Compose stack**: [platform/compose.yaml](../../platform/compose.yaml).
- **Identity API**: [platform/identity/app.py](../../platform/identity/app.py), with authentication in [platform/identity/auth.py](../../platform/identity/auth.py) and configuration in [platform/identity/config.py](../../platform/identity/config.py).
- **Billing**: [platform/identity/billing/](../../platform/identity/billing/).
- **Knowledge publications**: [platform/identity/knowledge/](../../platform/identity/knowledge/).
- **Egress proxy**: [platform/egress/proxy.py](../../platform/egress/proxy.py).
- **Portal (Next.js)**: [platform/portal/](../../platform/portal/), published at `http://127.0.0.1:3100`.
- **Migrations**: [platform/identity_migrations/](../../platform/identity_migrations/) (identity `i0001` to `i0013`) and [platform/knowledge_migrations/](../../platform/knowledge_migrations/) (`k0001_publications`).

## What you can do

As a platform operator in the portal:

- **Customers** (`/customers/[id]`): create, edit, suspend, reactivate and delete customers; issue a single-use onboarding key (`BootstrapKeyDialog`); view subscriptions, payments and entitlements.
- **Workspaces** (`/workspaces/[tenantId]`): manage workspaces, cloud accounts per provider (`CloudAccountsTab`), keys (`KeysTab`), resource access (`ResourceAccessTab`), analysis rules (`RulesTab`) and usage (`UsageTab`); suspend, reactivate or delete a workspace; revoke all keys.
- **Plans** (`/plans`): list, create, edit and retire plans.
- **Billing** (`/billing`): billing settings, customer billing, subscriptions (update or cancel) and the plan-change request queue (`PlanChangeQueue`) to approve or reject requests.
- **Knowledge** (`/knowledge`): create and edit knowledge publications and view knowledge metrics (`KnowledgeView`).
- **Settings** (`/settings`): platform settings such as scheduled scans and alerts (`PlatformSettingsView`), AI policy (`AIPolicySection`), billing settings (`BillingSettingsSection`), data governance policy (`DataGovernancePolicyEditor`) and resource access defaults (`ResourceAccessSection`).
- **Activity** (`/activity`) and **Security** (`/security`): audit events, failures and access checks.

## How it works

### Services

| Service | Role |
| --- | --- |
| `platform-db` | PostgreSQL for the identity and knowledge databases |
| `identity-migrate` | Runs Alembic migrations before identity-service starts |
| `identity-service` | FastAPI identity API on port 8005 (internal network only) |
| `identity-egress` | CONNECT-only TLS pass-through proxy on port 3128 for approved identity hosts |
| `platform-redis` | Sign-in throttling state |
| `platform-portal` | Operator portal, published only on `127.0.0.1:3100` |

The `platform-db` and `platform-internal` networks are marked `internal: true`, so the database and identity-service aren't reachable from public networks.

### Identity API

- Version 1.2.0, with OpenAPI docs disabled, a 1 MB request body limit and `application/problem+json` errors.
- **Service callers** authenticate with a service token whose SHA-256 digest is listed in `PLATFORM_IDENTITY_CALLERS`. Each caller name is limited to certain routes:
  - Key verification: `gateway`, `tenant`, `scanner`, `analytics`, `notification`, `agent`.
  - Directory routes: `scanner`, `tenant`.
  - Admin routes: `portal`.
- **Operators** authenticate through the portal. `PLATFORM_PORTAL_AUTH` is `entra` (tokens for `PLATFORM_IDENTITY_AUDIENCE` from `PLATFORM_OPERATOR_TENANT_ID`) or `operator_key` (compared with `PLATFORM_OPERATOR_KEY_SHA256`). `operator_key` is rejected in production.
- **Operator roles**: `PlatformOperator`, `PlatformAuditor`, `KnowledgeReviewer`, `PrivacyReviewer`. Any non-GET request needs `PlatformOperator`, except knowledge review posts by reviewers. Knowledge-only roles can reach only knowledge routes and the session endpoint.
- [platform/identity/config.py](../../platform/identity/config.py) `env()` reads `PLATFORM_<NAME>` and falls back to the deprecated `CLOUDSAVER_<NAME>`.

### Portal

- Sign-in uses Entra (`/api/auth/login`, `/api/auth/callback`) or an operator key (`/api/auth/operator-key`), with `/api/auth/session` and `/api/auth/logout`.
- Sessions are HTTP-only, `SameSite=Strict` cookies that last up to 8 hours.
- `/api/portal/[...path]` forwards only allowlisted method and path pairs to `/admin/v1/*`, checks the request origin, and attaches the portal service token.
- **Step-up**: revoking all workspace keys and deleting a workspace require a sign-in within the last 15 minutes (`StepUpPrompt`).
- `/api/webhooks/stripe` is public, limited to 60 requests per minute per IP and 1 MB per request, and forwards to identity `/billing/v1/webhooks/stripe`.
- `/api/healthz` is used by the Compose health check.

### Billing

- Billing is on when `PLATFORM_BILLING_ENABLED` is true. `PLATFORM_BILLING_PROVIDER` is `manual` or `stripe`.
- [platform/identity/billing/evaluator.py](../../platform/identity/billing/evaluator.py) `BillingEvaluator` re-evaluates subscription state every 60 seconds.
- [platform/identity/billing/stripe_webhook.py](../../platform/identity/billing/stripe_webhook.py) records Stripe events idempotently and handles plan-change checkout completion, subscription and invoice events.
- CloudSaver reads the resulting plan block through key verification and the directory projection. Its own checkout and billing webhook routes return 410.
- See [PLATFORM_BILLING.md](../PLATFORM_BILLING.md) for what is and isn't implemented.

### Knowledge publications

- Stored in a separate database (`PLATFORM_KNOWLEDGE_DATABASE_URL`). Without it, a disabled store is used.
- Statuses: `draft`, `published`, `deprecated`, `rejected`.
- [platform/identity/knowledge/privacy.py](../../platform/identity/knowledge/privacy.py) `screen()` rejects content containing identifiers or secrets. Sources must be `synthetic` or `public_documentation` from `learn.microsoft.com`, `docs.aws.amazon.com`, `cloud.google.com` or `kubernetes.io`.
- Publishing requires independent technical and privacy reviews by two people other than the author; reviews expire after 90 days.
- `retrieve_knowledge` returns at most 5 published items. It isn't exposed as a route.

### Egress proxy

[platform/egress/proxy.py](../../platform/egress/proxy.py) accepts only `CONNECT host:443` to exact hostnames in `PLATFORM_IDENTITY_EGRESS_HOSTS` (no wildcards, no IP literals, at most 20 hosts). Destinations must resolve only to public addresses. The proxy never decrypts or logs payloads.

## API reference

Representative identity-service routes. All `/admin/v1/*` routes are reached through the portal proxy.

| Method | Path | Purpose | Required role/scope |
| --- | --- | --- | --- |
| POST | `/internal/v1/keys/verify` | Verify a workspace key and return its grant | Service caller (verify callers) |
| GET | `/internal/v1/directory/changes` | Directory change feed | Service caller `scanner` or `tenant` |
| GET | `/internal/v1/directory/snapshot` | Full directory snapshot | Service caller `scanner` or `tenant` |
| GET | `/internal/v1/events` | Long-poll cache invalidation events | Service caller |
| GET | `/internal/v1/metrics` | Service metrics | Service caller |
| POST | `/internal/v1/access-checks/{id}/claim` | Claim a queued cloud access check | Service caller |
| POST | `/internal/v1/access-checks/{id}/result` | Report an access check result | Service caller |
| POST | `/internal/v1/tenants/{id}/plan-change-requests` | Submit a plan-change request | Service caller |
| GET | `/internal/v1/tenants/{id}/plan-change-requests/pending` | Pending plan change | Service caller |
| GET | `/internal/v1/tenants/{id}/analysis-rules/effective` | Effective workspace rule policy | Service caller |
| GET | `/internal/v1/ai-policy` | Platform AI policy | Service caller |
| POST | `/billing/v1/webhooks/stripe` | Stripe webhook receiver | Service caller `portal` |
| POST | `/customer/v1/claim` | Claim an onboarding key | Onboarding key |
| * | `/customer/v1/*` | Customer users, members, service accounts, keys, audit and export | Customer key and customer role |
| GET | `/admin/v1/session` | Operator session details | Any operator role |
| * | `/admin/v1/customers`, `/admin/v1/customers/{id}` | Customer CRUD, bootstrap key, suspend and reactivate | `PlatformOperator` for writes |
| * | `/admin/v1/workspaces`, `/admin/v1/workspaces/{id}` | Workspace CRUD, scopes per provider, keys, revoke all, usage | `PlatformOperator` for writes |
| * | `/admin/v1/keys/{id}` | Get, update, rotate, revoke and usage for one key | `PlatformOperator` for writes |
| * | `/admin/v1/plans` | List, get, create, update and retire plans | `PlatformOperator` for writes |
| * | `/admin/v1/billing/settings`, `/admin/v1/billing/customers` | Billing settings and customer billing | `PlatformOperator` for writes |
| * | `/admin/v1/subscriptions/{id}` | Get, update or cancel a subscription | `PlatformOperator` for writes |
| * | `/admin/v1/plan-change-requests` | List, approve and reject plan changes | `PlatformOperator` for writes |
| * | `/admin/v1/platform-settings`, `/admin/v1/ai-policy` | Platform settings and AI policy | `PlatformOperator` for writes |
| * | `/admin/v1/analysis/rules`, `/admin/v1/workspaces/{id}/analysis-rules` | Platform and workspace rule policy | `PlatformOperator` for writes |
| GET | `/admin/v1/audit`, `/admin/v1/failures`, `/admin/v1/access-checks` | Audit, failures and access checks | Any operator role |
| GET | `/admin/v1/knowledge/metrics` | Knowledge metrics | Operator or knowledge reviewer |
| GET, POST | `/admin/v1/knowledge/publications` | List or create publications | `PlatformOperator` for writes |
| PATCH | `/admin/v1/knowledge/publications/{id}` | Edit a publication | `PlatformOperator` |

## Data and evidence

- Directory: customers, workspaces, cloud scopes and Kubernetes clusters, projected to CloudSaver through the directory feed.
- Identity: keys (peppered hashes), invalidation events and audit events.
- Billing: plans, settings, subscriptions, payments, provider events and plan-change requests.
- Knowledge: publications with source, review and status history.
- Every operator write is audited with the operator identity and request ID.

## Permissions

| Role | Access |
| --- | --- |
| `PlatformOperator` | Full read and write on admin routes |
| `PlatformAuditor` | Read-only admin routes |
| `KnowledgeReviewer` | Knowledge routes and session only; technical reviewer |
| `PrivacyReviewer` | Knowledge routes and session only; privacy reviewer |

## Configuration

Names only. Keep secret values in `platform/.env` or a secrets manager and never commit them.

| Variable | Purpose | Default |
| --- | --- | --- |
| `PLATFORM_IDENTITY_DATABASE_URL` | Identity database connection | Unset |
| `PLATFORM_KNOWLEDGE_DATABASE_URL` | Knowledge database connection | Unset (knowledge disabled) |
| `PLATFORM_KEY_PEPPER`, `PLATFORM_KEY_PEPPER_VERSION`, `PLATFORM_KEY_PEPPER_PREVIOUS` | Key hashing pepper and rotation | Unset (secret) |
| `PLATFORM_KEYVAULT_URL` | Optional Key Vault for secrets | Unset |
| `PLATFORM_IDENTITY_CALLERS` | SHA-256 digests of service tokens per caller | Unset |
| `PLATFORM_PORTAL_AUTH` | `entra` or `operator_key` | `entra` |
| `PLATFORM_OPERATOR_TENANT_ID` | Entra tenant for operators | Unset |
| `PLATFORM_IDENTITY_AUDIENCE` | Expected operator token audience | `api://cloudsaver-identity` |
| `PLATFORM_OPERATOR_KEY_SHA256` | Operator key digest (non-production only) | Unset |
| `PLATFORM_REDIS_URL` | Throttling Redis | `platform-redis` in Compose |
| `PLATFORM_IDENTITY_CACHE_SECONDS` | Grant cache hint returned to callers, 0 to 30 | `15` |
| `PLATFORM_PROVIDER_SCOPED_KEYS` | Allow provider-scoped keys | `false` |
| `PLATFORM_ENVIRONMENT` | `production` enforces stricter checks | `development` |
| `PLATFORM_PUBLIC_URL` | Public portal URL | `http://127.0.0.1:3100` |
| `PLATFORM_BILLING_ENABLED`, `PLATFORM_BILLING_PROVIDER` | Billing switch and provider (`manual` or `stripe`) | Off, `manual` |
| `PLATFORM_STRIPE_SECRET_KEY`, `PLATFORM_STRIPE_WEBHOOK_SECRET` | Stripe credentials | Unset (secret) |
| `PLATFORM_DB_POOL_SIZE`, `PLATFORM_DB_MAX_OVERFLOW` | Database pool sizing | Pool size `4` (1 to 20) |
| `PLATFORM_IDENTITY_EGRESS_HOSTS` | Approved egress hosts | `login.microsoftonline.com` |
| `IDENTITY_SERVICE_URL` | Portal's identity-service URL | `http://identity-service:8005` in Compose |
| `PLATFORM_PORTAL_TOKEN` | Portal service token (secret) | Unset |
| `PORTAL_PUBLIC_URL` | Portal URL for redirects | `PLATFORM_PUBLIC_URL` |
| `PORTAL_ENTRA_TENANT_ID`, `PORTAL_ENTRA_CLIENT_ID`, `PORTAL_ENTRA_CLIENT_SECRET` | Portal Entra sign-in app | Unset |
| `PORTAL_ENTRA_API_SCOPE` | Scope requested for identity-service | `api://cloudsaver-identity/.default` |

## Guardrails and limitations

- The portal proxy allows `POST knowledge/publications/{id}/review`, `PATCH payments/{id}` and `POST payments/{id}/void`, but identity-service registers no matching routes. Knowledge review, and therefore publishing, isn't reachable over HTTP, and payment updates and voids fail.
- `retrieve_knowledge` has no route, so published knowledge isn't yet used by CloudSaver.
- Manual payments don't become Stripe operations when the provider changes; see [PLATFORM_BILLING.md](../PLATFORM_BILLING.md).
- `operator_key` sign-in is for local development only and is rejected in production.
- The portal is bound to `127.0.0.1`; expose it only behind authenticated, TLS-protected access.

## Tests

- [platform/tests/test_identity.py](../../platform/tests/test_identity.py) and [platform/tests/test_identity_postgres.py](../../platform/tests/test_identity_postgres.py): identity API and storage.
- [platform/tests/test_billing_stripe.py](../../platform/tests/test_billing_stripe.py) and [platform/tests/test_billing_improvements.py](../../platform/tests/test_billing_improvements.py): billing.
- [platform/tests/test_ai_policy.py](../../platform/tests/test_ai_policy.py), [platform/tests/test_audit_coverage.py](../../platform/tests/test_audit_coverage.py), [platform/tests/test_feature_restoration.py](../../platform/tests/test_feature_restoration.py), [platform/tests/test_readme_improvements.py](../../platform/tests/test_readme_improvements.py).
- [platform/portal/tests/finance.test.mjs](../../platform/portal/tests/finance.test.mjs): portal finance helpers.
- [tests/test_identity_egress.py](../../tests/test_identity_egress.py), [tests/test_platform_boundary.py](../../tests/test_platform_boundary.py), [tests/test_billing_removed.py](../../tests/test_billing_removed.py): CloudSaver-side boundaries.

## Related docs

- [PLATFORM_BILLING.md](../PLATFORM_BILLING.md)
- [identity-v1 contract](../../platform/contracts/identity-v1.md)
- [admin-billing-v1 contract](../../platform/contracts/admin-billing-v1.md)
- [Onboarding and access](onboarding-and-access.md)
- [MANAGED_IDENTITY_ROLES.md](../MANAGED_IDENTITY_ROLES.md)
- [ENVIRONMENT.md](../ENVIRONMENT.md)

## Local UI reliability verification

The [detail verification report](../DETAIL_RELIABILITY_VERIFICATION.md) records the added customer-directory browser journeys, request-generation guards, explicit uncertain-write messages, list-response checks and keyboard focus recovery. These checks use synthetic browser fixtures; they are not evidence of real operator authentication or complete portal acceptance.
