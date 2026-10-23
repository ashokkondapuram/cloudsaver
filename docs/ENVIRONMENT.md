# Environment variables

CloudSaver and the platform use **two untracked env files**. Nothing loads them automatically except Docker Compose (which reads the file beside each `compose.yaml`). Treat every secret as local-only: generate with the setup scripts, keep mode `0600`, and never commit real values.

| File | Project | Used by |
| --- | --- | --- |
| [`.env`](../.env.example) | CloudSaver (repo root) | `compose.yaml`, standalone API, CLI scripts |
| [`platform/.env`](../platform/.env.example) | Platform 1.0 | `platform/compose.yaml`, identity-service, platform portal |

**Related docs:** [Cloud sources and onboarding](CLOUD_SOURCES.md) · [Managed identity roles](MANAGED_IDENTITY_ROLES.md) · Annotated templates (preferred quick reference): [`.env.example`](../.env.example), [`platform/.env.example`](../platform/.env.example)

---

## Setup commands

Run from the repo root unless noted.

```bash
# CloudSaver: creates root .env (refuses to overwrite). Prints caller token digests only.
python3 scripts/setup_compose.py

# Platform: creates platform/.env (refuses to overwrite). Prints operator key once.
(cd platform && python3 scripts/setup_platform.py)

# Register CloudSaver service tokens with identity-service (digests only in platform/.env).
(cd platform && python3 scripts/setup_platform.py --add-callers ../.env)
```

**Other helpers**

| Command | Purpose |
| --- | --- |
| `python3 scripts/setup_compose.py --add-identity` | Add missing `CLOUDSAVER_IDENTITY_TOKEN_*` entries |
| `python3 scripts/setup_compose.py --caller-digests` | Print digests for `PLATFORM_IDENTITY_CALLERS` |
| `python3 scripts/setup_compose.py --cutover` | Set workspace-key verifier to identity and directory mode to cutover |
| `python3 scripts/setup_compose.py --prune-platform` | Remove platform-owned keys from root `.env` after `platform/.env` exists |
| `platform/scripts/setup_platform.py --migrate-from ../.env` | Move 1.2 platform settings from CloudSaver `.env` into `platform/.env` |

**Start order (Docker):** platform first (`make platform-up`), then CloudSaver (`make up`). The platform compose project creates the external network `platform-link`.

---

## Deprecated `CLOUDSAVER_*` and `PLATFORM_*` aliases

Platform code prefers **`PLATFORM_*`** names. For most settings, `platform/identity/config.py` still accepts the matching **`CLOUDSAVER_*`** name and logs a one-time deprecation warning (secret values are never logged).

**Renamed when splitting platform 1.0** (use `platform/scripts/setup_platform.py --migrate-from` or set `PLATFORM_*` directly):

| Legacy (root `.env`) | Current (`platform/.env`) |
| --- | --- |
| `TOKEN_DB_PASSWORD` | `PLATFORM_DB_PASSWORD` |
| `IDENTITY_DB_OWNER_PASSWORD` | `PLATFORM_DB_OWNER_PASSWORD` |
| `IDENTITY_DB_APP_PASSWORD` | `PLATFORM_DB_APP_PASSWORD` |
| `CLOUDSAVER_KEY_PEPPER` | `PLATFORM_KEY_PEPPER` |
| `CLOUDSAVER_KEY_PEPPER_VERSION` | `PLATFORM_KEY_PEPPER_VERSION` |
| `CLOUDSAVER_KEY_PEPPER_PREVIOUS` | `PLATFORM_KEY_PEPPER_PREVIOUS` |
| `CLOUDSAVER_KEYVAULT_URL` | `PLATFORM_KEYVAULT_URL` |
| `CLOUDSAVER_IDENTITY_CALLERS` | `PLATFORM_IDENTITY_CALLERS` |
| `CLOUDSAVER_IDENTITY_TOKEN_PORTAL` | `PLATFORM_PORTAL_TOKEN` |
| `CLOUDSAVER_OPERATOR_KEY_SHA256` | `PLATFORM_OPERATOR_KEY_SHA256` |
| `CLOUDSAVER_PORTAL_AUTH` | `PLATFORM_PORTAL_AUTH` |
| `CLOUDSAVER_ENVIRONMENT` | `PLATFORM_ENVIRONMENT` |
| `CLOUDSAVER_PROVIDER_SCOPED_KEYS` | `PLATFORM_PROVIDER_SCOPED_KEYS` |

**Removed from CloudSaver `.env` after platform cutover** (`setup_compose.py --prune-platform`): the rows above plus `CLOUDSAVER_IDENTITY_REDIS_URL`, `STRIPE_*`, `CLOUDSAVER_STRIPE_*`, `BILLING_RETURN_URL`, and `CLOUDSAVER_BILLING_RETURN_URL`.

**Other legacy reads**

| Legacy | Preferred |
| --- | --- |
| `CLOUDSAVER_IDENTITY_REDIS_URL` | `PLATFORM_REDIS_URL` (identity events/throttle) |
| `CLOUDSAVER_IDENTITY_TOKEN` (portal) | `PLATFORM_PORTAL_TOKEN` |
| `AZURE_MANAGED_IDENTITY_CLIENT_ID` (host) | `AZURE_CLIENT_ID` inside containers (Compose maps this) |

Stripe secret env names inside identity-service are `PLATFORM_STRIPE_SECRET_KEY` and `PLATFORM_STRIPE_WEBHOOK_SECRET` (or Key Vault via `PLATFORM_KEYVAULT_URL`).

---

## CloudSaver core (root `.env`)

| Variable | Required | Default / notes |
| --- | --- | --- |
| `CLOUDSAVER_MODE` | Yes | `azure` (only supported value) |
| `CLOUDSAVER_DB` | Standalone API | `data/cloudsaver.sqlite3` |
| `CLOUDSAVER_DATABASE_URL` | Compose / registry | Set by Compose to Postgres app role; not in `.env.example` |
| `CLOUDSAVER_TENANT_REGISTRY` | Compose | `database` in Compose; `env` in standalone `.env.example` |
| `CLOUDSAVER_TENANTS` | Bootstrap | JSON array; seeds registry once in database mode; empty after portal cutover |
| `CLOUDSAVER_AUTH_MODE` | Yes | `workspace` or `entra` |
| `CLOUDSAVER_ENTRA_AUDIENCE` | Entra mode | API application (client) ID / audience |
| `CLOUDSAVER_DIRECTORY_MODE` | Identity rollout | `registry` or `cutover` (requires `CLOUDSAVER_KEY_VERIFIER=identity`) |
| `CLOUDSAVER_KEY_VERIFIER` | Identity rollout | `local`, `shadow`, or `identity` |
| `CLOUDSAVER_PROVIDER_SCOPED_KEYS` | Portal feature gate | `true` / `false`; mirrored on platform as `PLATFORM_PROVIDER_SCOPED_KEYS` |
| `CLOUDSAVER_ENVIRONMENT` | Safety | `development` or `production` (operator-key portal auth refused in production) |
| `CLOUDSAVER_SCHEDULED_SCANS` | Scheduler | `false`; seed only in database mode—change in platform portal |
| `CLOUDSAVER_AUTOMATED_ALERTS` | Alerts | `false`; seed only in database mode |
| `CLOUDSAVER_SCHEDULER_TICK_SECONDS` | Workers | `300` |
| `CLOUDSAVER_INTERACTIVE_JOBS` | Azure async scans | `false`; needs `scheduled` profile worker + dispatcher |
| `CLOUDSAVER_DISTRIBUTED_SCAN_LOCK` | Scanner | `false` standalone; `true` in Compose scanner-service |
| `CLOUDSAVER_ALLOWED_ORIGINS` | CORS | Comma-separated origins; empty disables CORS |
| `CLOUDSAVER_TRUSTED_CALLERS` | Internal auth | Compose sets per service (e.g. gateway clears list) |
| `CLOUDSAVER_TRUSTED_PROXIES` | Gateway | e.g. `web-dashboard` in Compose |
| `CLOUDSAVER_PLAN_POLICY` | GitOps | Trusted JSON for Terraform guardrails |
| `CLOUDSAVER_DIRECTORY_POLL_SECONDS` | Directory projector | `5` |
| `CLOUDSAVER_REGISTRY_CACHE_SECONDS` | Tenant registry | `5` |

### Postgres and Redis (CloudSaver Compose)

| Variable | Required in Compose | Notes |
| --- | --- | --- |
| `POSTGRES_PASSWORD` | Yes | Superuser; migration job only |
| `CLOUDSAVER_DB_PASSWORD` | Yes | URL-safe; `cloudsaver_app` runtime role |
| `CLOUDSAVER_DB_POOL_SIZE` | No | `2` per process |
| `CLOUDSAVER_DB_MAX_OVERFLOW` | No | `3` |
| `CLOUDSAVER_DB_POOL_TIMEOUT` | No | `5` seconds |
| `CLOUDSAVER_DB_POOL_RECYCLE` | No | `1800` seconds |
| `CLOUDSAVER_REGISTRY_EXPORT_PASSWORD` | No | Optional; registry export migration (`0011`) |
| `REDIS_URL` | Compose services | Set in compose per service (`6379/0` gateway, `/1` scanner/workers) |

`CLOUDSAVER_MIGRATION_URL` and `CLOUDSAVER_DATABASE_URL` are composed in `compose.yaml`; export scripts accept either migration or app URL.

---

## Identity tokens (CloudSaver → platform)

Identity-service runs in **`platform/`** and is reached at `CLOUDSAVER_IDENTITY_URL` (default `http://identity-service:8005` on `platform-link`).

| Variable | Set in | Notes |
| --- | --- | --- |
| `CLOUDSAVER_IDENTITY_URL` | Root `.env` | Base URL for all CloudSaver callers |
| `CLOUDSAVER_IDENTITY_TOKEN_GATEWAY` | Root `.env` | Mapped to `CLOUDSAVER_IDENTITY_TOKEN` on api-gateway |
| `CLOUDSAVER_IDENTITY_TOKEN_TENANT` | Root `.env` | tenant-service |
| `CLOUDSAVER_IDENTITY_TOKEN_SCANNER` | Root `.env` | scanner-service |
| `CLOUDSAVER_IDENTITY_TOKEN_ANALYTICS` | Root `.env` | analytics-service |
| `CLOUDSAVER_IDENTITY_TOKEN_NOTIFICATION` | Root `.env` | notification-service |
| `CLOUDSAVER_IDENTITY_CACHE_SECONDS` | Root `.env` | `0`–`30`; positive verify cache (`15` default) |
| `CLOUDSAVER_IDENTITY_REDIS_URL` | Optional | Legacy; optional second Redis for identity client cache (`redis:6379/2`) |

Platform stores **SHA-256 digests only** in `PLATFORM_IDENTITY_CALLERS` (JSON: `gateway`, `tenant`, `scanner`, `analytics`, `notification`, `portal`). Setup scripts never print raw service tokens.

---

## Azure, AWS, and GCP resource access

Keyless access is configured once per stack; workspace bindings live in the platform portal. See [CLOUD_SOURCES.md](CLOUD_SOURCES.md) and [MANAGED_IDENTITY_ROLES.md](MANAGED_IDENTITY_ROLES.md).

| Variable | Required | Notes |
| --- | --- | --- |
| `CLOUDSAVER_CLOUD_IDENTITY` | Yes | `managed_identity` (Azure) or `developer` (local CLI / ADC) |
| `AZURE_MANAGED_IDENTITY_CLIENT_ID` | MI mode | User-assigned MI client ID; Compose exposes as `AZURE_CLIENT_ID` |
| `CLOUDSAVER_AZURE_ACCESS` | Azure | `federated` (default) or `direct` |
| `CLOUDSAVER_AZURE_APP_CLIENT_ID` | Federated Azure | Multi-tenant app for FIC |
| `CLOUDSAVER_AWS_HUB_ROLE_ARN` | AWS | Hub role trusted by Entra issuer |
| `CLOUDSAVER_AWS_TOKEN_AUDIENCE` | AWS | Default `api://AzureADTokenExchange` |
| `CLOUDSAVER_GCP_WORKLOAD_PROVIDER` | GCP | Full WIF provider resource name |
| `CLOUDSAVER_GCP_TOKEN_AUDIENCE` | GCP | Default `api://AzureADTokenExchange` |
| `CLOUDSAVER_INSTALL_AZURE_CLI` | Developer | `true` bakes Azure CLI into service image |
| `CLOUDSAVER_PROMETHEUS_TOKEN_*` | Kubernetes | Operator-defined; name referenced in cluster config (e.g. `CLOUDSAVER_PROMETHEUS_TOKEN_PRIMARY`) |

**Legacy client-secret path (not used with managed identity):**

| Variable | When |
| --- | --- |
| `CLOUDSAVER_CREDENTIAL_PROVIDER` | `env` (default) or `keyvault` |
| `AZURE_CLIENT_SECRET` | `env` provider only |
| `AZURE_KEYVAULT_URL` | `keyvault` provider |
| `AZURE_KEYVAULT_AUTH` | `managed_identity` (default) or `default` (local chain) |
| `AZURE_KEYVAULT_MANAGED_IDENTITY_CLIENT_ID` | Optional vault MI |
| `AZURE_KEYVAULT_CACHE_TTL_SECONDS` | `0`–`900`; default `300` |

---

## Delivery, GitOps, and AI (root `.env`)

| Variable | Default | Notes |
| --- | --- | --- |
| `CLOUDSAVER_DELIVERY_ENABLED` | `false` | Enables delivery dispatcher profile |
| `CLOUDSAVER_NOTIFICATION_TARGETS` | `[]` | JSON; each target references `CLOUDSAVER_WEBHOOK_*` env name |
| `CLOUDSAVER_WEBHOOK_*` | — | Webhook URLs; pass to scanner, dispatcher, and scan-worker via override |
| `CLOUDSAVER_GITOPS_TARGETS` | `[]` | Approved repository bindings |
| `CLOUDSAVER_GITOPS_PUBLISH` | `false` | GitHub App draft PR publishing |
| `CLOUDSAVER_GITHUB_APP_ID` | — | Numeric App ID when publish enabled |
| `CLOUDSAVER_GITHUB_APP_PRIVATE_KEY` | — | PEM; mount or env |
| `CLOUDSAVER_AI_ENABLED` | `false` | Opt-in advisory |
| `CLOUDSAVER_AI_TARGETS` | `[]` | Per-tenant model targets (see [ASSESSMENT_AI.md](ASSESSMENT_AI.md)) |
| `CLOUDSAVER_AI_HOURLY_ATTEMPTS` | `10` | Per-tenant hourly cap |
| `CLOUDSAVER_AI_BATCH_TICK_SECONDS` | `30` | Worker batch interval (Compose) |
| `CLOUDSAVER_AI_BATCH_ITEMS_PER_TICK` | `10` | Worker batch size |

---

## Platform database and Redis (`platform/.env`)

| Variable | Required | Notes |
| --- | --- | --- |
| `PLATFORM_DB_PASSWORD` | Yes | Postgres superuser |
| `PLATFORM_DB_OWNER_PASSWORD` | Yes | Migration owner (`identity_owner`) |
| `PLATFORM_DB_APP_PASSWORD` | Yes | Runtime role (`identity_app`) |
| `PLATFORM_IDENTITY_DATABASE_URL` | Compose | Built from app password in `platform/compose.yaml` |
| `PLATFORM_IDENTITY_MIGRATION_URL` | Compose | Built from owner password for `identity-migrate` |
| `PLATFORM_REDIS_URL` | Compose | `redis://platform-redis:6379/0` (throttle/events only) |
| `PLATFORM_DB_POOL_SIZE` | No | `4` |
| `PLATFORM_DB_MAX_OVERFLOW` | No | `4` |
| `PLATFORM_DB_POOL_TIMEOUT` | No | `5` (code default; not in compose env block) |
| `PLATFORM_DB_POOL_RECYCLE` | No | `1800` (code default) |

---

## Platform identity, keys, and portal auth (`platform/.env`)

| Variable | Required | Notes |
| --- | --- | --- |
| `PLATFORM_KEY_PEPPER` | Yes* | Hex pepper (≥32 bytes); or load from Key Vault |
| `PLATFORM_KEY_PEPPER_VERSION` | No | `1` |
| `PLATFORM_KEY_PEPPER_PREVIOUS` | No | Comma-separated previous peppers for rotation |
| `PLATFORM_KEYVAULT_URL` | Azure | Vault URL; secret `cloudsaver-identity-key-pepper` |
| `PLATFORM_IDENTITY_CALLERS` | Yes | JSON digests for allowed callers |
| `PLATFORM_PORTAL_TOKEN` | Yes | Portal → identity-service token (digest in `callers.portal`) |
| `PLATFORM_IDENTITY_CACHE_SECONDS` | No | `0`–`30`; verify cache |
| `PLATFORM_IDENTITY_AUDIENCE` | No | `api://cloudsaver-identity` |
| `PLATFORM_PUBLIC_URL` | Yes | e.g. `http://127.0.0.1:3100` |
| `PLATFORM_ENVIRONMENT` | No | `development` or `production` |
| `PLATFORM_PROVIDER_SCOPED_KEYS` | No | Enables provider-limited workspace keys |
| `PLATFORM_PORTAL_AUTH` | Yes | `entra` or `operator_key` (local only) |
| `PLATFORM_OPERATOR_KEY_SHA256` | operator_key | SHA-256 of operator access key |
| `PLATFORM_OPERATOR_TENANT_ID` | Entra ops | Optional operator tenant binding |
| `PORTAL_ENTRA_TENANT_ID` | Entra | Directory tenant |
| `PORTAL_ENTRA_CLIENT_ID` | Entra | App registration |
| `PORTAL_ENTRA_CLIENT_SECRET` | Entra | Client secret |
| `PORTAL_ENTRA_API_SCOPE` | No | Default `api://cloudsaver-identity/.default` |

**Throttle tuning (optional, platform identity):** `PLATFORM_IDENTITY_IP_FAILURES`, `PLATFORM_IDENTITY_PAIR_FAILURES`, `PLATFORM_IDENTITY_FAILURE_WINDOW_SECONDS`, `PLATFORM_IDENTITY_BLOCK_SECONDS` (legacy `CLOUDSAVER_*` names accepted via `env()`).

Portal container also receives `IDENTITY_SERVICE_URL`, `PORTAL_PUBLIC_URL` (from `PLATFORM_PUBLIC_URL`), and `PLATFORM_PORTAL_TOKEN`.

For a proposed (not implemented) model where customers manage their own users and keys after a one-time bootstrap credential, see [Client-managed users and access keys](CLIENT_MANAGED_USERS_AND_KEYS.md).

---

## Billing (`platform/.env` only)

Billing is **not** configured in the CloudSaver repo root `.env`. Set it only in **`platform/.env`** (loaded by `platform/compose.yaml` for `identity-service`). The portal learns billing state from `GET /admin/v1/session` (`billing_enabled`, `billing_provider`).

For what manual billing, Stripe flags, and plan-change approval actually do in the current code (versus the approved spec), see [Platform billing — operations and implementation boundaries](PLATFORM_BILLING.md).

| Variable | Default | Notes |
| --- | --- | --- |
| `PLATFORM_BILLING_ENABLED` | `false` in Compose if unset; `true` in fresh `setup_platform.py` | When true, portal operators can change plans, subscriptions, and approve plan requests |
| `PLATFORM_BILLING_PROVIDER` | `manual` | `manual` or `stripe` |
| `PLATFORM_STRIPE_SECRET_KEY` | — | Required for Stripe; Key Vault name `platform-stripe-secret-key` |
| `PLATFORM_STRIPE_WEBHOOK_SECRET` | — | Key Vault name `platform-stripe-webhook-secret` |

Identity-service refuses to start with `PLATFORM_BILLING_PROVIDER=stripe` until both Stripe secrets resolve (env or Key Vault).

---

## CLI and smoke scripts (not in Compose)

| Variable | Purpose |
| --- | --- |
| `CLOUDSAVER_WORKSPACE_KEY` | Workspace key for `scripts/smoke_stack.py`, `scripts/scan.py` |
| `CLOUDSAVER_GATEWAY_URL` | Default `http://127.0.0.1:8000` |
| `CLOUDSAVER_DASHBOARD_URL` | Default `http://127.0.0.1:3000` |
| `CLOUDSAVER_LEGACY_KEY_DEADLINE` | Identity import tooling |
| `CLOUDSAVER_REGISTRY_EXPORT_URL` | Registry export for migration |

**Web dashboard (Compose):** `API_GATEWAY_URL` → `http://api-gateway:8000`.

---

## Test-only variables

Set by `scripts/test_postgres.py` or integration tests—not for production Compose.

| Variable | Purpose |
| --- | --- |
| `CLOUDSAVER_TEST_OWNER_URL` | Schema owner connection for RLS tests |
| `CLOUDSAVER_TEST_APP_URL` | App role connection |
| `CLOUDSAVER_TEST_PRIVILEGED_URL` | Superuser / bypass |
| `CLOUDSAVER_TEST_REDIS_URL` | Isolated Redis for integration tests |

Pytest may set other vars transiently (`monkeypatch`); do not add them to committed env files.

---

## Gitignore and secrets hygiene

| Location | Rule |
| --- | --- |
| Repo root [`.gitignore`](../.gitignore) | Ignores `.env*`; allows [`.env.example`](../.env.example) |
| [`platform/portal/.gitignore`](../platform/portal/.gitignore) | Ignores `.env*` |
| [`web-dashboard/.gitignore`](../web-dashboard/.gitignore) | Ignores `.env*` |

Setup scripts create `.env` / `platform/.env` with mode **0600**. Operator keys may also be written to `cloudsaver-operator-key.txt` (gitignored). Never commit passwords, peppers, Stripe keys, GitHub App keys, or workspace keys.

---

## Local Docker checklist

1. Install Docker Desktop; ensure ports **3000**, **8000**, and **3100** are free on loopback.
2. `python3 scripts/setup_compose.py` → root `.env` with Postgres passwords and identity tokens.
3. `(cd platform && python3 scripts/setup_platform.py && python3 scripts/setup_platform.py --add-callers ../.env)` → `platform/.env` and caller digests.
4. `make platform-up` → creates **`platform-link`**, starts platform DB, Redis, identity-service, portal (**127.0.0.1:3100**).
5. Sign in to the portal (operator key from step 3), create customer/workspace, cloud accounts, and a workspace key.
6. `make up` → CloudSaver services (**127.0.0.1:3000** dashboard, **127.0.0.1:8000** gateway).
7. For live scans: set cloud identity (developer + `compose.override.example.yaml` or managed identity IDs), then open the dashboard with the workspace key.
8. Optional profiles: `docker compose --profile scheduled` (scan worker, beat, dispatcher); `delivery` profile for dispatcher-only.
9. Upgrading from 1.2: migrate platform env, export/import billing, then `setup_compose.py --prune-platform` (see [README](../README.md)).

---

## Compose-only service URLs (reference)

These are set in `compose.yaml` files, not copied into `.env.example`:

| Variable | Typical value |
| --- | --- |
| `TENANT_SERVICE_URL` | `http://tenant-service:8001` |
| `SCANNER_SERVICE_URL` | `http://scanner-service:8002` |
| `ANALYTICS_SERVICE_URL` | `http://analytics-service:8003` |
| `NOTIFICATION_SERVICE_URL` | `http://notification-service:8004` |
| `IDENTITY_SERVICE_URL` | `http://identity-service:8005` (portal) |
