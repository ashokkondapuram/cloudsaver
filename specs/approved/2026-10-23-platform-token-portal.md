# Platform portal, workspace directory and token service

**Status:** Approved
**Date:** Oct 23, 2026
**Approved:** Oct 23, 2026
**Author:** CloudSaver team
**Related:** `specs/approved/2026-10-22-tenant-settings-managed-identity.md` (tenant registry, operator console)

## Approval decisions

| Open question | Decision |
| --- | --- |
| 1. Legacy deadline | Imported legacy keys expire 90 days after cutover. Operators can extend the date per key in the portal (up to the 365-day maximum). |
| 2. Meaning of "to client" | Workspaces are managed by platform operators in the separate platform portal, as drafted. Customer self-service stays out of scope. |
| 3. Scope granularity | Keys are limited at whole-provider level only for this release. `scope_restrictions` stays in the schema and verify contract (always `null`) so scope-level limits can ship later. |
| 4. Tenant admin scope edits | Cloud scopes become operator-only in the portal. After cutover, dashboard Settings shows cloud accounts read-only. |
| 5–12 | Use the spec's recommended or default answer. Every chosen default is recorded in [Implementation notes](#implementation-notes). |

## Problem statement

Workspace keys and workspaces are managed inside the customer application stack:

- **Key verification is local and copied into every service.** `app/auth.py` `tenant_dependency` hashes the
  presented bearer key with plain SHA-256 and compares it against `api_key_sha256` on every active tenant
  (`hmac.compare_digest` in a loop). The registry lives in the shared application database
  (`public.tenant_registry`, no RLS, readable by `cloudsaver_app`) or in `CLOUDSAVER_TENANTS`. The gateway
  verifies the key, then forwards the same `Authorization` header to tenant, scanner, analytics or notification
  service. Each of those services verifies it again from its own 5-second registry cache.
- **One key per workspace, all-powerful, no lifecycle.** Every workspace key gets `TenantAdmin`,
  `BillingAdmin` and `Viewer`. Keys have no ID, name, expiry, rotation, revocation (other than replacing the
  hash or deactivating the whole tenant) or usage history. `actor_for` can only attribute changes to
  `workspace-key:<tenant_id>`.
- **Every key can reach every provider.** A key used by, for example, an AWS-only automation can still start
  Azure, GCP and Kubernetes scans and read their findings.
- **Workspace management is split across surfaces.** The `/admin` operator console (operator key,
  `CLOUDSAVER_OPERATOR_KEY_SHA256`) creates tenants and edits plan, status, identity bindings and Kubernetes
  clusters. Tenant admins edit their own Azure, AWS and GCP scopes in dashboard Settings. Key material and
  customer configuration share a database with all customer findings, so any application compromise exposes
  the authentication directory.

We need an isolated platform portal and database that own customers, workspaces and workspace keys. Every
login with a workspace key must be checked against that database, and the key decides which cloud providers
the customer can use.

## Proposed solution

Three new components plus changes to existing services:

1. **`token-db`.** A dedicated PostgreSQL 16 container (in Azure, a separate Flexible Server) with its own
   credentials. Only `identity-service` and its migration job can reach it. It holds two schemas:
   - `directory`: customers, workspaces, per-provider cloud scopes and platform settings. This becomes the
     **source of truth for workspaces**.
   - `identity`: workspace keys, key grants (roles and providers), audit events, usage rollups and
     verification failures.
2. **`identity-service`** (FastAPI, internal port 8005, no host port). It is the only reader and writer of
   `token-db` and exposes:
   - an internal **verify API** used by every service that authenticates workspace keys (service-to-service
     authentication)
   - an internal **directory change feed** that `tenant-service` projects into the application database
   - an **admin API** used only by the platform portal (operator Entra token)
3. **`platform-portal`.** A separate Next.js 15 operator web app on `127.0.0.1:3100`. It is a separate
   codebase and origin from the customer dashboard (`127.0.0.1:3000`) and replaces the `/admin` operator
   console. Operators manage customers, workspaces, cloud scopes, platform settings and keys here.

**Key-driven provider selection.** Each key carries an allowed-provider set, a subset of `azure`, `aws`, `gcp`
and `kubernetes`, and optional per-provider scope restrictions. The verify response returns the tenant ID,
roles and the resolved allowed providers. Each service narrows the workspace to that grant before any handler
runs. As a result, scans, analysis, findings and settings only ever see the providers on the key, and the
dashboard only shows those providers.

**Decisions:**

| Topic | Decision |
| --- | --- |
| Workspace source of truth | `token-db.directory`, written only by `identity-service`. The application database keeps a read-only **projection** in `public.tenant_registry`. |
| Sync direction | Before cutover: tenant registry to directory (import, registry wins). After cutover: directory to projection only. There is never two-way sync. |
| Key hashing | HMAC-SHA256 with a server-side pepper held in Key Vault (not Argon2id). See [Key hashing](#key-hashing). |
| Verification cache | In-process positive cache per service, 15 seconds by default and capped at 30 seconds, plus Redis pub/sub eviction on revoke, suspend, delete or grant change. Negative results are never cached. |
| Failure mode | Fail closed. If `identity-service` is unreachable or returns an error, the caller returns `503` and never falls back to local hashes after cutover. Cached entries are never extended during an outage. |
| Operator authentication | Microsoft Entra ID (workforce tenant) with `PlatformOperator` and `PlatformAuditor` app roles. The operator key is a local-development fallback only. |
| Workspace listing in the portal | Read directly from `directory` (the portal's own source of truth), so no sync from `tenant-service` is needed after cutover. |
| Entra bearer tokens | `CLOUDSAVER_AUTH_MODE=entra` is unaffected. Entra tokens are still validated locally by `EntraTokenValidator`, never reach the verify API, and get every provider configured for the workspace. |

### Architecture

```text
 Customer browser ── :3000 web-dashboard ── api-gateway :8000 ──┬─ tenant / scanner / analytics / notification
                                                │ verify            │ verify (cached)
                                                ▼                   ▼
 Operator browser ── :3100 platform-portal ── identity-service :8005 (internal only) ── token-db (isolated network)
                        (Entra OIDC, BFF)          │  directory change feed ▲
                                                   │  Redis pub/sub (evictions)
                                                   ▼
                                      tenant-service projector ── app Postgres public.tenant_registry (projection)
```

## Detailed design

### Data model: `token-db`

The database is managed by its own Alembic environment (`identity_migrations/`, version table
`identity.alembic_version`, first revision `i0001_directory_identity`), separate from `migrations/versions`.
All timestamps are `timestamptz` in UTC.

**Schema `directory`**

- `customers(id uuid PK, name varchar(120), status ('active'|'suspended'|'deleted'), notes varchar(500) NULL,
  version int, created_at, created_by, updated_at, updated_by, deleted_at NULL)`
- `workspaces(tenant_id uuid PK, customer_id uuid FK customers, name varchar(120), plan_tier
  ('STARTER'|'GROWTH'|'ENTERPRISE'), status ('active'|'suspended'|'deleted'), identity jsonb
  {azure_app_client_id?, gcp_service_account?}, version int, created_at, created_by, updated_at, updated_by,
  suspended_at NULL, deleted_at NULL)`
  - `tenant_id` remains the customer's Microsoft Entra tenant ID, matching today's registry key, so existing
    findings, RLS (`app.current_tenant_id`) and billing rows keep working.
- Per-provider scopes, each with `(tenant_id FK, ..., created_at, created_by)` and a uniqueness constraint per
  workspace:
  - `workspace_azure_subscriptions(tenant_id, subscription_id uuid)`
  - `workspace_aws_accounts(tenant_id, account_id char(12), region, role_arn)`
  - `workspace_gcp_projects(tenant_id, project_id, regions text[])`
  - `workspace_kubernetes_clusters(tenant_id, cluster_id, prometheus_url, bearer_token_env)`. The token
    variable stores an environment variable name, never a token.
  - Validation reuses `app/tenant_config.py` and `app/cloud_scope.py` rules, including the 100-per-list
    limits and plan subscription quotas from `app/entitlements.py`.
- `platform_settings(id=1, scheduled_scans_enabled bool, automated_alerts_enabled bool, version, updated_by,
  updated_at)`. This moves from the application database so `/admin` can retire.
- `directory_changes(seq bigserial PK, tenant_id uuid NULL, change_type
  ('workspace_upserted'|'workspace_deleted'|'platform_updated'), version int, snapshot jsonb, occurred_at)`.
  This is a transactional outbox: it is written in the same transaction as every directory write, and each
  snapshot holds the complete workspace state, so applying a change is idempotent. It is retained for 30 days.

**Schema `identity`**

- `api_keys`
  - `id uuid PK`, `key_id varchar(12) UNIQUE` (public identifier; synthetic for imported legacy keys),
    `tenant_id uuid FK directory.workspaces`, `name varchar(80)`
  - `roles text[]`: a non-empty subset of `TenantAdmin`, `BillingAdmin` and `Viewer`
  - `all_providers boolean`: when true, the key follows the workspace's current and future providers
  - `allowed_providers text[]`: a subset of `azure`, `aws`, `gcp` and `kubernetes`. It is empty when
    `all_providers` is true and otherwise non-empty.
  - `scope_restrictions jsonb NULL`: optional, keyed by provider, for example
    `{"aws": ["123456789012"], "azure": ["00000000-0000-0000-0000-000000000000"]}`. `NULL` means all scopes of
    each allowed provider. Whether this is enabled in the UI depends on Open question 3; the column exists so
    the verify contract doesn't change later.
  - `format ('v1'|'legacy')`, `hash_scheme ('hmac_sha256'|'sha256_legacy')`, `secret_digest bytea(32) UNIQUE
    NULL`, `pepper_version smallint NULL`, `legacy_sha256 char(64) UNIQUE NULL`. A check constraint enforces
    exactly one of: `hmac_sha256` with `secret_digest` and `pepper_version`, or `sha256_legacy` with
    `legacy_sha256`.
  - Lifecycle: `created_at`, `created_by`, `expires_at NULL` (required for `v1`), `revoked_at`,
    `revoked_by`, `revoke_reason`, `rotated_from uuid NULL FK`, `rotates_out_at NULL`
  - `last_used_at`, `last_used_ip inet`: written at most once per minute per key per replica
  - `source ('portal'|'registry_import'|'env_import')`, `version int`
  - **Effective validity:** `revoked_at IS NULL AND (expires_at IS NULL OR expires_at > now()) AND
    (rotates_out_at IS NULL OR rotates_out_at > now())`, and the workspace and customer are `active`.
  - A workspace can have at most 20 non-revoked keys.
- `key_events(id uuid PK, occurred_at, actor varchar(120), actor_type ('operator'|'service'|'system'),
  action, tenant_id, key_id NULL, details jsonb, request_id)`
  - Actions: `issued`, `rotated`, `rotated_out`, `revoked`, `revoked_all`, `expired`, `roles_changed`,
    `providers_changed`, `expiry_changed`, `renamed`, `imported`, `hash_upgraded`, plus directory actions:
    `customer_created`, `customer_updated`, `workspace_created`, `workspace_updated`, `scopes_changed`,
    `workspace_suspended`, `workspace_reactivated`, `workspace_deleted` and `platform_updated`.
  - The table is **append-only**. The application role has only `INSERT` and `SELECT`, and a trigger rejects
    `UPDATE` and `DELETE`. `details` never contains key material.
  - The operator actor is the Entra object ID plus display name captured at sign-in.
- `key_usage_hourly(key_id, hour, source_ip inet, success_count, failure_count, last_seen_at,
  PK(key_id, hour, source_ip))`: aggregated in memory, upserted every 30 seconds and retained for 90 days.
- `verification_failures_minute(minute, source_ip inet, key_id NULL, tenant_id NULL, reason, caller,
  count, PK(minute, source_ip, key_id, reason, caller))`
  - Reasons: `malformed`, `unknown`, `secret_mismatch`, `revoked`, `expired`, `rotated_out`,
    `workspace_suspended` and `throttled`.
  - Rows are aggregated so a brute-force flood doesn't amplify writes. They're retained for 30 days.
- Active throttling and lockout state lives in Redis (logical DB 2, prefix `cloudsaver:identity:`) and holds
  no key material.

### Data model: application database

Migration `0011_registry_projection`:

- `tenant_registry` becomes a read-only projection written only by the `tenant-service` projector. It adds
  `customer_id uuid`, `directory_version int` and `projected_at`. `api_key_sha256` becomes nullable and is
  no longer written (it's dropped in `0012`).
- Tenant-owned preferences are split out so the projector never overwrites them. A new `preferences jsonb`
  column holds `schedule` and `alerts`. `webhook_url` stays where it is. `config` keeps only directory-owned
  scopes and identity bindings.
- `platform_settings` becomes a projection of `directory.platform_settings`.
- The projector keeps using `PostgresRegistry._sync_domain` to maintain `organizations`, `tenants` and
  `subscriptions`. Workers, the scheduler, billing and the dispatcher keep reading the registry unchanged.
- New read-only role `cloudsaver_registry_export` with `SELECT` on `tenant_registry` and `platform_settings`.
  It's used only by the one-time import job and dropped in `0012`.

Migration `0012_drop_registry_keys` (removal phase): drop `api_key_sha256` and the export role.

### Key format

- New keys: `cs_live_<key_id>_<secret>` in production and `cs_test_<key_id>_<secret>` in every other
  environment.
  - `key_id`: 12 random lowercase Crockford base32 characters (60 bits). It isn't secret and is safe in logs,
    UI and audit.
  - `secret`: 43 base62 characters (about 256 bits) from `secrets`.
  - Validation regex: `^cs_(live|test)_[0-9a-hjkmnp-tv-z]{12}_[0-9A-Za-z]{43}$` (64 characters).
  - Illustrative only, not a real key: `cs_test_0example0000_XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX`.
- Legacy keys from `secrets.token_urlsafe(32)` are 43 URL-safe characters with no prefix. The different
  length makes the two formats unambiguous.
- The portal shows a key as `cs_live_<key_id>…` and shows the full key exactly once, at issue or rotation.

### Key hashing

**Decision: HMAC-SHA256 with a pepper, not Argon2id.**

- **Why not Argon2id.** Workspace keys are 256-bit machine-generated secrets, so offline brute force is
  infeasible whatever the hash speed. Slow password hashes only protect low-entropy, human-chosen secrets.
  Verification also runs on the request path, at the gateway and again downstream on cache misses. A
  memory-hard KDF (about 20–50 ms and 19 MiB per attempt) would cap throughput and give unauthenticated
  callers a cheap CPU and memory denial-of-service lever.
- **Why HMAC with a pepper over plain SHA-256.** The pepper is a 32-byte random value held in Key Vault
  (`cloudsaver-identity-key-pepper`, versioned) and never stored in `token-db`. A database dump alone
  therefore can't be used to confirm leaked or guessed candidate keys.
- **What is hashed.** `secret_digest = HMAC-SHA256(pepper[pepper_version], full_presented_key)`. The input
  includes the prefix and `key_id`, so tampering with the `key_id` fails verification.
- **Lookup.**
  - `v1` keys: look up by `key_id`, then compare with `hmac.compare_digest`. An unknown `key_id` runs a
    dummy HMAC and compare so response timing is equal.
  - Legacy keys: compute `SHA-256(key)` and look up `legacy_sha256`. If the key was already upgraded, look up
    `secret_digest` instead. Both are unique indexes on high-entropy digests, so index timing reveals nothing
    useful.
- **Upgrade on use.** On the first successful verification of a `sha256_legacy` row, the service computes the
  HMAC digest, stores it with the current `pepper_version`, sets `hash_scheme='hmac_sha256'`, clears
  `legacy_sha256` and records `hash_upgraded`. Plain SHA-256 isn't weak for these keys; the upgrade makes
  every row depend on the pepper. Legacy-format keys still get a deadline (see Rollout).
- **Pepper rotation.** `identity-service` loads the current and previous pepper versions. Rows are re-hashed
  to the current version on successful use, and an old version is retired once no rows reference it.
- **Local development.** The pepper comes from `CLOUDSAVER_KEY_PEPPER` in the untracked `.env` generated by
  `scripts/setup_compose.py`. If no pepper is available, `identity-service` refuses to start.

### Verification flow

Each service that authenticates workspace keys runs these steps.

1. **Check the local cache.** `tenant_dependency` (workspace mode) computes a cache key of `SHA-256(token)`
   (the raw token is never stored) and looks it up in an in-process LRU (10,000 entries).
2. **Call verify on a miss.** The service calls `POST /internal/v1/keys/verify`. `identity-service` then:
   1. Checks the source IP and the `(key_id, IP)` pair against the throttle.
   2. Parses the key and looks it up.
   3. Compares the digest in constant time.
   4. Only after the secret matches, checks key status, workspace status and customer status.
   5. Resolves the grant: allowed providers are the key's providers intersected with the workspace's
      configured providers (or the workspace's providers when `all_providers` is true), with scope
      restrictions applied.
   6. Records usage and responds.
3. **Narrow the workspace.** The service loads the workspace from its projection (`settings.tenants`, the
   same as Entra mode today) and builds the **effective workspace**:
   - The scope lists (`subscription_ids`, `aws_accounts`, `gcp_projects`, `kubernetes_clusters`) are filtered
     to the allowed providers and restrictions.
   - The service adds `roles`, `key_id`, `key_name`, `allowed_providers`, `key_expires_at` and `with_plan`.
   - Existing code that derives everything from the workspace dict (`configured_providers`,
     `scan_multi_cloud`, `scope_fingerprint`, `workspace_response`) is then provider-scoped automatically.
4. **Fail closed.** If the workspace isn't in the projection yet, or the projection's `directory_version` is
   older than the verify response, the service returns `503` with `Retry-After: 5` and the message "This
   workspace is still being set up. Try again in a few seconds." If `identity-service` errors or times out
   (2-second timeout), the service returns `503` with "Sign-in is temporarily unavailable. Try again in a
   few minutes."
5. **Cache the grant.** The entry TTL is `min(CLOUDSAVER_IDENTITY_CACHE_SECONDS (default 15, startup fails
   above 30), expires_at − now, rotates_out_at − now)`.
6. **Evict on change.** On revoke, revoke all, rotate-out, suspend, delete, or a change to roles, providers or
   expiry, `identity-service` publishes `{key_id | tenant_id, event}` on Redis channel
   `cloudsaver:identity:events`. Subscribers evict matching entries. The cache TTL bounds propagation at 30
   seconds even if a message is missed.

**Customer-facing errors** (UX writing rules, no oracle for unknown keys):

| Condition | Status | Message |
| --- | --- | --- |
| Malformed, unknown or wrong secret | 401 | "Invalid workspace access key" (unchanged) |
| Expired, revoked or rotated out (shown only when the secret matched) | 401 | "This workspace key has expired or was revoked. Ask your CloudSaver administrator for a new key." |
| Workspace or customer suspended | 403 | "This workspace is suspended. Contact your CloudSaver administrator." |
| Throttled | 429 | "Too many sign-in attempts. Try again in 15 minutes." with `Retry-After` |
| Provider not on key | 403 | "This workspace key doesn't include AWS." (provider display name: Azure, AWS, Google Cloud, Kubernetes) |
| Role missing | 403 | Existing `"{role} role is required"` from `require_workspace_role` |

### Provider enforcement

Every route is classified in a checked-in route inventory. A unit test fails if a route on the gateway or any
service is missing from it.

- **Provider-scoped writes**, such as `POST /api/v1/scans` (Azure), `POST /api/v1/scans/multi-cloud`,
  `POST /api/v1/scan-jobs`, remediation, Terraform export, GitOps preview and publish, and AI assessment and
  batch creation:
  - A request naming a provider outside `allowed_providers` returns `403`. This check runs before
    `scan_multi_cloud`.
  - Requests that act on an existing scan or resource require every provider involved to be allowed.
- **Provider-scoped reads**, such as scans, scan jobs, findings, resources, resource history and decisions,
  analysis, trends, analytics, AI assessments and usage, and delivery events about findings:
  - Rows whose `cloud_provider` is not allowed are filtered out, and totals and savings are recomputed over
    the filtered set.
  - A direct lookup of a single item from a disallowed provider returns `404`, so its existence isn't
    revealed.
  - A scan is listed if any of its providers is allowed, with findings filtered.
- **Provider-agnostic routes** (`/api/v1/me`, `/api/v1/providers`, billing entitlements and checkout) are
  allowed for any key with the required role. `/api/v1/providers` and the `providers` field of `/api/v1/me`
  return only the allowed providers.
- **Full-scope routes** (FinOps FOCUS imports and summary until billing data is provider-filtered):
  - These require a key whose grant covers every configured provider with no scope restrictions; otherwise
    they return `403` "This workspace key doesn't include all providers."
- **Settings:**
  - `GET /api/v1/settings` returns scopes only for allowed providers.
  - Tenant-admin scope edits (`PUT /api/v1/settings`) can change only allowed providers. Disallowed providers'
    scopes are preserved server-side and never shown. `tenant-service` forwards the scope portion to
    `identity-service` (`PUT /internal/v1/workspaces/{tenant_id}/scopes`, acting key ID attached), because
    the directory is the single writer.
  - Schedule, alerts and webhook stay in `tenant-service`.
- **Scheduled scans and the delivery dispatcher** are workspace-level, not key-level. They keep scanning every
  configured provider. Results are visible only through keys that allow those providers.
- **Entra-mode principals** receive every configured provider. Provider limits for Entra users are out of
  scope.

### APIs

#### Internal (identity-service, not published to the host)

Service-to-service authentication:

- **Azure:** each caller's managed identity gets an Entra token for audience `api://cloudsaver-identity`.
  `identity-service` validates the issuer, audience and app role (`Keys.Verify` or `Directory.Sync`) and maps
  the managed identity object ID to a caller name.
- **Local compose:** each caller has its own random service token in the untracked `.env` (generated by
  `setup_compose.py`). `identity-service` stores only SHA-256 digests in `CLOUDSAVER_IDENTITY_CALLERS`
  (JSON `{caller: digest}`).
- Network isolation is a second layer, not the only one.

| Method | Path | Callers | Purpose |
| --- | --- | --- | --- |
| POST | `/internal/v1/keys/verify` | gateway, tenant, scanner, analytics, notification | Verify a presented key |
| GET | `/internal/v1/directory/changes?after=<seq>&limit=500` | tenant-service | Change feed for the projector |
| GET | `/internal/v1/directory/snapshot` | tenant-service | Full resync, used when the cursor is older than retention |
| PUT | `/internal/v1/workspaces/{tenant_id}/scopes` | tenant-service | Tenant-admin scope edits, limited to the acting key's providers |

Verify request (the key is sent in the body, and request body logging is disabled on this route):

```json
{"key": "<presented key>", "client_ip": "203.0.113.10", "request_id": "<uuid>"}
```

Verify response, `200` (example values only):

```json
{
  "valid": true,
  "tenant_id": "00000000-0000-0000-0000-000000000000",
  "customer_id": "00000000-0000-0000-0000-000000000001",
  "key_id": "0example0000",
  "key_name": "AWS cost automation",
  "roles": ["Viewer"],
  "all_providers": false,
  "allowed_providers": ["aws"],
  "scope_restrictions": null,
  "workspace_status": "active",
  "directory_version": 42,
  "expires_at": "2027-01-21T14:00:00Z",
  "cache_ttl_seconds": 15
}
```

- **Invalid key:** `200` with `{"valid": false, "reason": "<reason>"}`. Callers map `malformed`, `unknown`
  and `secret_mismatch` to the generic 401, and map the other reasons as shown in the error table.
- **Throttled:** `429` with `Retry-After`.
- **Bad service credential:** `401` or `403`.
- **Service failure:** `5xx`, which callers turn into `503`.
- **`client_ip`:** the gateway derives it from the socket address, or from `X-Forwarded-For` only when the
  peer is in `CLOUDSAVER_TRUSTED_PROXIES` (which includes the dashboard proxy). Downstream services forward
  the value they received from the gateway.

#### Portal admin API (identity-service, called by the portal server)

The portal server forwards the operator's Entra access token for audience `api://cloudsaver-identity`.
`identity-service` enforces authorization itself:

- `PlatformOperator`: every endpoint
- `PlatformAuditor`: `GET` endpoints only

Every write requires an optimistic `version` where one applies. A stale version returns `409` "This item
changed since you loaded it. Refresh and try again." Every write records a `key_events` row. Responses use
`Cache-Control: no-store`.

| Method | Path | Purpose |
| --- | --- | --- |
| GET / POST | `/admin/v1/customers` | List (search, status filter, cursor paging) or create a customer |
| GET / PATCH / DELETE | `/admin/v1/customers/{id}` | View, rename or update notes, soft-delete (only when it has no active workspaces) |
| POST | `/admin/v1/customers/{id}/suspend`, `/reactivate` | Suspend or reactivate every workspace of the customer |
| GET / POST | `/admin/v1/workspaces` | List with key counts, last use and next expiry, or create a workspace `{tenant_id, customer_id, name, plan_tier}` |
| GET / PATCH | `/admin/v1/workspaces/{tenant_id}` | View, or change name, plan tier, customer or identity bindings |
| PUT | `/admin/v1/workspaces/{tenant_id}/scopes/{provider}` | Replace one provider's scope list (`azure`, `aws`, `gcp`, `kubernetes`) |
| POST | `/admin/v1/workspaces/{tenant_id}/suspend`, `/reactivate` | Suspend blocks verification immediately; keys are kept |
| DELETE | `/admin/v1/workspaces/{tenant_id}` | Soft delete: revokes all keys, projects `active=false`; data purge per retention |
| GET / PUT | `/admin/v1/platform-settings` | Scheduled scans and automated alerts switches |
| GET / POST | `/admin/v1/workspaces/{tenant_id}/keys` | List keys, or issue `{name, roles, all_providers, allowed_providers, scope_restrictions?, expires_at}`. Returns `{key, secret}`; `secret` is returned only here. |
| GET / PATCH | `/admin/v1/keys/{key_id}` | View, or change name, roles, providers, restrictions or expiry |
| POST | `/admin/v1/keys/{key_id}/rotate` | `{overlap_hours: 0–168 (default 24), allowed_providers?, roles?, expires_at?}`. Returns the new `{key, secret}`; the old key gets `rotates_out_at`. |
| POST | `/admin/v1/keys/{key_id}/revoke` | `{reason}`. Takes effect immediately and publishes an eviction. |
| POST | `/admin/v1/workspaces/{tenant_id}/keys/revoke-all` | `{reason}` for incident response |
| GET | `/admin/v1/keys/{key_id}/usage?from=&to=` | Hourly successes and failures by source IP |
| GET | `/admin/v1/audit?customer_id=&tenant_id=&key_id=&actor=&action=&before=&limit=` | Activity log (`key_events`) |
| GET | `/admin/v1/failures?tenant_id=&source_ip=&from=` | Failed and throttled attempts |

**Validation rules:**

- **Allowed providers:** must be a non-empty subset of the workspace's configured providers at issue time,
  unless `all_providers` is true.
- **Scope restrictions:** must reference scopes that exist in the workspace. They're rejected while Open
  question 3 is unresolved, behind the `CLOUDSAVER_KEY_SCOPE_RESTRICTIONS` flag.
- **Expiry:** required for new keys. The default is 90 days and the maximum is 365 days, and the date can't be
  in the past.
- **Rotation:** preserves the roles, providers, restrictions and expiry duration (from now, capped) unless the
  request overrides them. Rotating a key that is already rotating out returns `409`.
- **Removing a provider's last scope:** allowed. Keys listing that provider lose it from their effective
  grant, and a `providers_changed` event is recorded for each affected key.
- **Creating a workspace:** checks that `tenant_id` is a UUID and not already present. Plan quotas reuse
  `app/entitlements.py`.

#### Existing APIs that change

- `GET /api/v1/me` adds `key_id`, `key_name`, `key_expires_at` and `allowed_providers`. `providers` already
  reflects the effective workspace.
- `tenant-service` `/api/v1/admin/*` and the gateway's operator routes:
  - Writes return `410` "Workspace management has moved to the platform portal." from directory cutover.
  - Reads keep working until removal.
- `operator_dependency` and `CLOUDSAVER_OPERATOR_KEY_SHA256` are removed from the customer stack in the
  removal phase. The portal's local-development fallback keeps using the digest.

### Operator authentication (portal)

**Decision: Microsoft Entra ID** (OIDC authorization code with PKCE) on the portal server, using app roles
`PlatformOperator` and `PlatformAuditor`.

- **Why Entra.** Issuing keys and editing workspaces are the most privileged actions in the platform. A shared
  operator key gives no per-person audit trail, MFA or conditional access, and offboarding means rotating the
  key for everyone. The approved settings spec already lists Entra for operators as an open question.
- **Sessions.** Encrypted, `HttpOnly`, `Secure`, `SameSite=Strict` cookie. Tokens are never exposed to
  browser JavaScript. Sessions last at most 8 hours with a 30-minute idle timeout. Mutating routes check
  `Origin`.
- **Step-up.** Revoke all and Delete workspace require a sign-in within the last 15 minutes (`max_age`).
- **Local development fallback.** `CLOUDSAVER_PORTAL_AUTH=operator_key` accepts the operator key (verified
  against `CLOUDSAVER_OPERATOR_KEY_SHA256`) and records the actor as `operator-key`. The portal and
  `identity-service` refuse to start in this mode when `CLOUDSAVER_ENVIRONMENT=production`.

### UI changes

#### Platform portal (`127.0.0.1:3100`)

All labels follow the Zafin UX writing rules. Dates use the `Oct 23, 2026` format and times use `9:00 AM`.
Roles are displayed as Tenant admin, Billing admin and Viewer, and providers as Azure, AWS, Google Cloud and
Kubernetes.

- **Sign in:** Sign in with Microsoft. Local development shows an "Operator access key" field instead.
- **Customers:** table with Customer, Status, Workspaces, Created, and an action to Create customer.
- **Customer details:** Overview (name, notes, Edit, Suspend customer, Reactivate customer, Delete customer)
  and a Workspaces table with Create workspace.
- **Workspaces:**
  - Table columns: Workspace, Customer, Tenant ID, Plan, Providers, Status, Active keys, Last used, Next
    expiry.
  - Search and status filter (Active, Suspended, Deleted). Create workspace.
- **Workspace details** has these tabs:
  - **Overview:** name, customer, plan, status and identity bindings, with Edit, Suspend workspace,
    Reactivate workspace and Delete workspace. Delete requires typing the workspace name and shows "This
    revokes every key for this workspace. You can't undo this."
  - **Cloud accounts:** sections for Azure subscriptions, AWS accounts (account ID, region, role ARN), Google
    Cloud projects (project ID, regions) and Kubernetes clusters (cluster ID, Prometheus URL, token
    variable). Each section has Add, Remove and Save changes.
  - **Keys:**
    - Table columns: Name, Key ID (`cs_live_0example0000…`), Roles, Providers, Created, Expires, Last used,
      Status. Statuses are Active, Expiring soon (within 14 days), Rotating out, Revoked, Expired and Legacy.
    - Actions: Issue key, Rotate, Revoke and Edit.
  - **Usage:** last used (for example "Oct 23, 2026 at 9:00 AM from 203.0.113.10"), an hourly chart of
    successful and failed sign-ins, and a table with Source IP, Successful sign-ins, Failed attempts and Last
    seen.
  - **Activity:** entries such as "Rotated key AWS cost automation · Oct 23, 2026 at 9:00 AM, by Priya
    Patel".
- **Issue key dialog:**
  - **Name.**
  - **Roles:** checkboxes, with Viewer checked by default.
  - **Providers:** checkboxes showing only the workspace's configured providers, all checked by default. One
    is required ("Select at least one provider."). There's also an option to "Include providers added
    later".
  - **Expires on:** date, defaulting to 90 days from today.
  - Button: Issue key.
  - **Result:** "Copy this key now. You won't be able to see it again." Copy key, then Close once "I've
    stored this key securely" is checked.
- **Rotate dialog:**
  - Shows the current roles and providers pre-selected and editable.
  - Overlap window options: No overlap, 1 hour, 24 hours (default), 7 days. Helper text: "The current key
    keeps working until Oct 24, 2026 at 9:00 AM."
  - Button: Rotate key. The result shows the one-time reveal.
- **Revoke dialog:** "Revoke this key?" with "Apps using this key lose access within 30 seconds. You can't
  undo this." A reason is required. Destructive button: Revoke key.
- **Security:** failed and throttled attempts by source IP, with filters.
- **Platform settings:** Scheduled scans and Automated alerts switches, with Save changes.

#### Customer dashboard (`127.0.0.1:3000`)

- Sign-in is unchanged: the customer pastes a workspace key. Errors use the messages in the verification
  error table.
- The scan dialog, provider filters, findings, resources, trends, Settings > Cloud accounts and onboarding
  details show only the providers in `allowed_providers`.
- Hidden providers are never shown as disabled, so the existence of other configured scopes isn't revealed.
- If a key has no effective providers, the dashboard shows "This workspace key doesn't include any cloud
  providers. Ask your CloudSaver administrator to update it."
- Expiry banner within 14 days of expiry: "This workspace key expires on Nov 6, 2026. Ask your administrator
  for a new key."
- Viewer-only keys see read-only settings, using the existing `editable` flag.

#### Existing operator console (`/admin`)

- At directory cutover, the console becomes read-only with the banner "Workspace management has moved to the
  platform portal." and an Open platform portal link (`CLOUDSAVER_PORTAL_URL`).
- It's removed in the removal phase.

### Compose and networking (local development)

New services: `token-db`, `identity-migrate`, `identity-service` and `platform-portal`. `token-db` has no host
port, and only the portal is published, on loopback.

```yaml
networks:
  default: {}
  identity-db: {internal: true}   # token-db, identity-migrate, identity-service only
  portal: {internal: true}        # platform-portal and identity-service only

services:
  token-db:
    image: postgres:16
    networks: [identity-db]
    environment:
      POSTGRES_PASSWORD: ${TOKEN_DB_PASSWORD:?Set TOKEN_DB_PASSWORD in .env}
      IDENTITY_DB_APP_PASSWORD: ${IDENTITY_DB_APP_PASSWORD:?Set IDENTITY_DB_APP_PASSWORD in .env}
    volumes: [token-db-data:/var/lib/postgresql/data]
  identity-service:
    networks: [default, identity-db, portal]
    environment:
      CLOUDSAVER_IDENTITY_DATABASE_URL: postgresql://identity_app:${IDENTITY_DB_APP_PASSWORD}@token-db:5432/identity
      CLOUDSAVER_KEY_PEPPER: ${CLOUDSAVER_KEY_PEPPER:?Run scripts/setup_compose.py}
      CLOUDSAVER_IDENTITY_CALLERS: ${CLOUDSAVER_IDENTITY_CALLERS:?Run scripts/setup_compose.py}
  platform-portal:
    networks: [portal]
    ports: ['127.0.0.1:3100:3100']
```

- `CLOUDSAVER_IDENTITY_DATABASE_URL` and the `token-db` passwords are given only to `identity-service` and
  `identity-migrate`. The shared `x-environment` anchor never contains them.
- The existing services get `CLOUDSAVER_IDENTITY_URL=http://identity-service:8005`, their own caller token,
  and `identity-service` in `NO_PROXY`.

### Migration and import

- **One-time and repeatable import job.** `identity-import` (same image, `profiles: [migration]`) reads
  `tenant_registry` and `platform_settings` through `cloudsaver_registry_export`, and reads
  `CLOUDSAVER_TENANTS`, then upserts into `token-db`. The job is idempotent and keyed by `tenant_id` and
  `legacy_sha256`.
  - **Customers:** one per workspace, named after the workspace and editable later, unless the operator
    supplies a mapping file (Open question 7). The customer ID reuses the existing `organizations.id` when
    one exists.
  - **Workspaces:** name, plan, status (`active=false` imports as `suspended`), scopes, identity bindings
    and platform settings.
  - **Keys:** each `api_key_sha256` imports as a `legacy`/`sha256_legacy` key named "Imported workspace key"
    with all three roles, `all_providers=true` (every current and future workspace provider, matching today's
    behavior), and `source='registry_import'` or `'env_import'`.
  - **Expiry:** imported keys get `expires_at` set to the legacy deadline (Open question 1).
  - **Not imported:** schedule, alerts and webhook stay in the application database. Entra-mode random
    placeholder digests from `app/config.py` are imported as revoked so they can never authenticate.
- **Verifier modes** are set with `CLOUDSAVER_KEY_VERIFIER` on every service:
  - `local` is today's behavior.
  - `shadow` verifies locally (authoritative) and also calls verify. It logs and counts mismatches by
    `key_id` and reason only, with a 200 ms timeout that doesn't affect the request.
  - `identity` makes `identity-service` authoritative.
- **Projector.** `tenant-service` polls the change feed every 5 seconds, or sooner on a Redis nudge. It
  applies each snapshot transactionally to `tenant_registry` and `platform_settings`, runs `_sync_domain`,
  and stores the cursor in `public.directory_projection_cursor`. If the cursor falls behind retention, it
  resyncs from the snapshot endpoint.
- **Consistency model.**
  - Directory changes reach application services within about 10 seconds (5-second poll plus 5-second
    registry cache).
  - Security-relevant changes (suspend, delete, revoke, grant change) take effect at verify time from the
    authoritative database, within the cache bound of 30 seconds or less, with no wait for the projection.

### Rollout

1. **Phase 0, prerequisites.** Entra app registrations and roles, Key Vault pepper, managed identities,
   Azure Flexible Server for `token-db` with Entra authentication and private networking.
2. **Phase 1, foundation and dual-read (shadow).**
   - Deploy `token-db`, `identity-service` and the `directory` and `identity` schemas.
   - Run `identity-import`, then re-run it every 10 minutes (registry to directory, registry wins).
   - Set all services to `shadow`. Exit criterion: zero unexplained mismatches for 7 days.
3. **Phase 2, directory cutover and key management.**
   - Announce a short window and freeze `/admin` writes (`410`). Run a final import, stop the importer and
     start the projector, which reverses the sync direction.
   - Switch services to `identity`.
   - Enable the portal for customers, workspaces, scopes, platform settings and keys, including restricted
     roles. All keys still have `all_providers=true`.
   - Rollback: set `local` and restart the importer in reverse. Keys issued in the portal, and revocations,
     aren't honored in `local` mode, so rollback is an incident-only path that must be used within 7 days.
4. **Phase 3, provider-scoped keys.**
   - Ship the route inventory, effective-workspace narrowing and dashboard filtering.
   - Enable `CLOUDSAVER_PROVIDER_SCOPED_KEYS`, so the portal allows unchecking providers.
5. **Phase 4, removal.**
   - Remove the local hash path from `app/auth.py`, the `/admin` console, `tenant-service` admin APIs and the
     gateway operator routes.
   - Apply migration `0012`. `CLOUDSAVER_TENANTS` seeds only `identity-service`.
   - Update `scripts/setup_compose.py`, `scripts/scan.py` and `scripts/smoke_stack.py`, which compare
     `api_key_sha256` today, to use the verify API. Remove `scripts/issue_operator_key.py` or limit it to the
     portal fallback.
   - Legacy-format keys stop working at the deadline, and operators rotate them beforehand from the portal's
     Legacy filter.

### Security

- **Isolation.**
  - `token-db` is reachable only on the internal `identity-db` network (in Azure, private endpoint plus
    firewall allowing only the `identity-service` subnet). It has no host port, and its credentials are
    separate from the application database.
  - The application database has no copy of key digests after removal.
- **Least-privilege database roles.**
  - `identity_owner`: migrations only.
  - `identity_app`: `SELECT`, `INSERT` and `UPDATE` on directory and key tables; `INSERT` and `SELECT` only
    on `key_events`; no `DELETE` anywhere.
  - `identity_retention`: a scheduled job that deletes only expired usage and failure rows.
  - In Azure, `identity-service` authenticates to Postgres with its managed identity, so there's no database
    password.
- **No plaintext keys.**
  - A secret exists only in the issue or rotate response (`no-store`) and in the portal dialog's memory.
  - Keys are never written to the database, logs, metrics, traces or audit. The verify route disables body
    logging, and log redaction drops anything matching either key format.
  - `key_id` is the only identifier that is logged.
- **Constant-time comparison** with `hmac.compare_digest`, plus dummy work on unknown keys.
- **Brute-force protection.**
  - 30 failed verifications per source IP in 5 minutes blocks that IP for 15 minutes (`429`).
  - 5 secret mismatches per `(key_id, IP)` in 5 minutes blocks that pair for 15 minutes.
  - There's no key-wide lockout, because `key_id` is public and a key-wide lockout would let anyone lock out
    a customer. Key-wide failure spikes raise alerts instead.
  - The existing per-workspace `RedisLimiter` stays in place.
- **Append-only audit** for every directory and key change, with operator identity from Entra.
- **Secrets management.**
  - Pepper and caller identities come from Key Vault and managed identities in Azure, and from untracked
    `.env` in local development.
  - No secrets are committed or used as examples. Only `cs_test_0example0000_XXXX…`-style placeholders
    appear.
- **Provider isolation.** Narrowing happens once, centrally, in `tenant_dependency`, before any handler runs.
  The route inventory test prevents unclassified routes.
- **Portal hardening.** Separate origin and cookies from the customer dashboard, strict CSP,
  `frame-ancestors 'none'`, `no-store`, CSRF protection via `SameSite=Strict` and `Origin` checks, and
  step-up for destructive bulk actions.

### Observability

- **Metrics:**
  - `identity_verify_total{result, reason, caller}` and `identity_verify_seconds` (histogram)
  - `identity_cache_hit_ratio{service}` and `identity_throttled_total`
  - `identity_keys{status}` and `identity_legacy_keys_remaining`
  - `identity_keys_expiring_14d`
  - `directory_projection_lag_seconds` and `directory_changes_pending`
  - `key_verifier_shadow_mismatch_total{reason}`
- **Logs:** structured, with `request_id` propagated from the gateway, `key_id`, `tenant_id`, caller and
  reason. Never the key or digest.
- **Alerts:**
  - verify p99 above 50 ms, or availability below 99.95% over 1 hour
  - projection lag above 60 seconds
  - failure spike per IP or key
  - any shadow mismatch
  - legacy key use after the deadline
  - `identity-service` unreachable from any caller
- **Availability:** `identity-service` is now on the login path for every request, so it runs at least 2
  replicas.

## Acceptance criteria

- [x] `token-db` runs as its own Postgres container with its own credentials, on an internal network that
      only `identity-service` and its migration job can reach, with no host port. The portal is published only
      on `127.0.0.1:3100`.
- [x] No service other than `identity-service` has `token-db` credentials or connectivity (verified by a
      compose test).
- [x] Every service that authenticates workspace keys uses `POST /internal/v1/keys/verify` in `identity` mode,
      and calls without a valid service credential are rejected.
- [x] If `identity-service` is unavailable, workspace-key requests return `503` after cached entries expire,
      and never fall back to local hashes.
- [x] A revoked key, a key past its rotation overlap, and keys of a suspended or deleted workspace are rejected
      by every service within 30 seconds, and within 1 second when Redis is healthy.
- [x] Operators can create, edit, suspend, reactivate and delete customers and workspaces, and manage Azure,
      AWS, Google Cloud and Kubernetes scopes and platform settings in the portal, with optimistic
      concurrency and audit.
- [x] Directory changes appear in the application projection (`tenant_registry`, `organizations`, `tenants`,
      `subscriptions`) within 10 seconds, and workers and the scheduler pick them up without a restart.
- [x] `/admin` writes return `410` after cutover, and the console and the `tenant-service` admin APIs are
      removed in Phase 4.
- [x] Operators can issue a key with name, roles, providers and expiry. The full key is shown once, and only
      its HMAC digest is stored.
- [x] Rotation issues a new key and keeps the old key working for the chosen overlap (0–168 hours), preserving
      roles, providers and restrictions unless changed.
- [x] Operators can view last used, source IPs, successful and failed sign-ins, and an append-only activity
      log. `UPDATE` and `DELETE` on `key_events` fail at the database.
- [x] A key with providers `["aws"]` sees only AWS in `/api/v1/me`, `/api/v1/providers`, the scan dialog,
      filters and settings, and receives `403` when requesting an Azure, Google Cloud or Kubernetes scan.
- [x] Lists exclude other providers' findings and totals, and direct lookups of other providers' items return
      `404`.
- [x] Every route is classified in the route inventory, and the test fails for an unclassified route.
- [ ] A `Viewer`-only key can't call any route that requires `TenantAdmin` or `BillingAdmin`, and every write
      route has an explicit role check.
- [x] A tenant admin's `PUT /api/v1/settings` with a provider-scoped key changes only allowed providers and
      preserves the others.
- [x] All existing keys from `tenant_registry` and `CLOUDSAVER_TENANTS` keep working after import, with all
      roles and all providers, including providers added later.
- [x] A legacy key is upgraded to HMAC on its first successful use.
- [ ] Shadow mode reports zero unexplained mismatches for 7 days before cutover.
- [x] Entra bearer tokens (`CLOUDSAVER_AUTH_MODE=entra`) authenticate exactly as before and never call the
      verify API.
- [x] Brute-force thresholds return `429` with `Retry-After` and are recorded in failures.
- [x] Keys never appear in logs, metrics, audit details or error responses (verified by a log-scanning test
      with both key formats).
- [ ] The portal requires Entra sign-in with `PlatformOperator` for writes and `PlatformAuditor` for reads. The
      operator-key fallback is refused in production.
- [x] Portal and dashboard text follows the UX writing and date and time formatting rules.

## Out of scope

- Customer self-service workspace or key management in the customer dashboard (see Open question 2).
- Changes to Entra sign-in for customers, and provider limits for Entra principals.
- Per-key IP allowlists, per-key request quotas and usage-based billing.
- Replacing downstream re-verification with a gateway-signed internal assertion.
- GitHub secret scanning partner registration for the `cs_live_` prefix.
- Multi-region replication of `token-db`.
- Migrating webhook URLs, schedules or alerts out of the application database.
- Hard deletion and data purge automation beyond the existing `scripts/purge_workspace_scans.py`.

## Open questions

All open questions are resolved. See [Approval decisions](#approval-decisions) and
[Implementation notes](#implementation-notes).

1. **Legacy deadline.** Should imported legacy-format keys expire 90 days after cutover, or should operators
   set the date per workspace? **Resolved:** 90 days after cutover, extendable per key.
2. **Meaning of "to client".** We assumed the request means workspace management for platform operators in
   the new portal. Did the user instead mean customer self-service workspace management (and key issuance) in
   the customer dashboard, for example for `TenantAdmin`? **Resolved:** platform operators in the portal.
3. **Scope granularity.** Can keys be narrower than the workspace's scopes at the subscription, account,
   project or cluster level (`scope_restrictions`), or only at the provider level? The data model and verify
   contract support both. The UI and enforcement ship provider-level only until this is decided.
   **Resolved:** provider level only for this release.
4. **Tenant admin scope edits.** Should tenant admins keep editing their own Azure, AWS and GCP scopes from
   dashboard Settings (proxied to the directory), or should scopes become operator-only in the portal?
   **Resolved:** operator-only in the portal; dashboard Settings is read-only for scopes after cutover.
5. **Expiry policy.** Are a 90-day default and 365-day maximum right? Should long-lived automation keys allow
   "No expiry"? **Default applied:** 90-day default, 365-day maximum, no "No expiry" option.
6. **"Include providers added later."** Should this be available for new keys, or only for imported legacy
   keys? **Default applied:** available for new keys as an explicit, unchecked-by-default option.
7. **Customer mapping.** Should import create one customer per workspace, or will operators supply a
   customer-to-workspace mapping? **Default applied:** one customer per workspace.
8. **Deployment split.** Should verify and admin run as separate deployments with separate database roles
   before general availability, so a compromised verify path can't issue keys? **Default applied:** one
   deployment for this release; revisit before general availability.
9. **Throttle thresholds.** What thresholds suit customers behind shared NAT or CI egress IPs? **Default
   applied:** the thresholds in [Security](#security), configurable by environment variable.
10. **Retention.** How long should audit (proposed minimum 1 year), source IPs (90 days) and failures
    (30 days) be kept? This needs a privacy and compliance review. **Default applied:** audit kept
    indefinitely (append-only), usage 90 days, failures 30 days, change feed 30 days.
11. **Approvals.** Should Revoke all, Delete workspace and Delete customer require a second operator's
    approval? **Default applied:** no second approval; step-up sign-in only.
12. **Downstream verification.** Should downstream services trust a gateway-signed assertion instead of
    re-verifying, to remove the second verify hop? **Default applied:** no; downstream services re-verify
    through their cache.

## Dependencies

- Entra app registrations:
  - portal client
  - `api://cloudsaver-identity` with app roles `PlatformOperator`, `PlatformAuditor`, `Keys.Verify` and
    `Directory.Sync`
  - role assignments for operators and service managed identities
- Key Vault secret `cloudsaver-identity-key-pepper` with read access for the `identity-service` managed
  identity only.
- Azure Database for PostgreSQL Flexible Server for `token-db`, with Entra authentication, private endpoint
  and backups.
- Redis logical DB 2 for throttling and the `cloudsaver:identity:events` channel. In Azure, an ACL user scoped
  to the identity prefix.
- The customer dashboard proxy (`web-dashboard/app/api/[...path]/route.ts`) forwards the client IP. The
  gateway adds `CLOUDSAVER_TRUSTED_PROXIES`.
- `app/auth.py`, `services/common.py`, `services/gateway.py`, `app/settings_api.py`, `app/tenant_registry.py`
  (projection mode), `app/config.py` and the scripts listed under Rollout.
- The approved spec `2026-10-22-tenant-settings-managed-identity.md`. This spec supersedes its operator
  console and tenant-registry write paths.

## Implementation notes

Implemented and verified on the local stack on Oct 23, 2026 (version 1.2.0).

### Verification

- Tests (in Docker, `cloudsaver-test:1.0.0`): 428 passed and 5 skipped without Postgres (baseline 393 and 5).
  52 passed with the disposable Postgres 16 and Redis 7 network (baseline 46). New files:
  `tests/test_identity.py`, `tests/test_identity_api.py`, `tests/test_identity_postgres.py`,
  `tests/test_route_inventory.py`.
- Local stack: `token-db` has no host port and joins only the internal `identity-db` network. The portal is
  published on `127.0.0.1:3100` only. Every service with a healthcheck reports healthy.
- After the import and cutover, a freshly issued test key signed in through the gateway and through the
  dashboard proxy (`/api/v1/me` returned 200 with the matching tenant and key). After revocation, the same key
  returned 401 within 2 seconds. The test key was issued and revoked inside the `identity-service`
  container and was never printed. The existing workspace key couldn't be used because `.env` stores only
  its digest. Its imported record is active with all providers.
- Both Next.js images build and run on Node 24.22.1 (`node --version` inside each container returned
  `v24.22.1`). The repository root has `.nvmrc`, and both `package.json` files declare `engines.node >=24.22.1`.

### Phase 4: operator console and admin API removal

Completed on Oct 23, 2026.

- **Dashboard.** `web-dashboard/components/admin/OperatorConsole.tsx` and its styles are removed. The
  sign-in link to the console is gone, and `/admin` redirects to `/`. The dashboard proxy no longer forwards
  `/api/v1/admin/*`, so those paths return 404 at the dashboard.
- **Backend.** The `tenant-service` routes `GET/POST /api/v1/admin/tenants`,
  `PATCH /api/v1/admin/tenants/{tenant_id}` and `GET/PUT /api/v1/admin/settings` are removed, along with the
  gateway proxies, their request models, `operator_dependency` in `app/auth.py`, `portal_url()` in
  `app/config.py` and the `operator` route class. The paths now return 404 instead of 410. Only the old
  console called them; the portal uses the identity-service admin API.
- **Configuration.** `CLOUDSAVER_OPERATOR_KEY_SHA256` and `CLOUDSAVER_PORTAL_URL` are removed from the
  shared compose environment. `identity-service` and `platform-portal` keep their own
  `CLOUDSAVER_OPERATOR_KEY_SHA256` for the local operator-key fallback, and `scripts/issue_operator_key.py`
  is kept for that fallback only.
- **Registry mode.** Before cutover (`CLOUDSAVER_DIRECTORY_MODE=registry`), workspaces can no longer be
  created or edited over HTTP. They're seeded from `CLOUDSAVER_TENANTS` (and their domain rows provisioned
  with `scripts/provision_tenants.py`), or managed in the portal after cutover.
- **Tests.** The operator console API tests are replaced by tests that the removed routes return 404 or
  405, and that deactivation and platform switches still apply without a restart. 432 passed and 5 skipped
  without Postgres.
- **Still open in Phase 4.** Removing the local hash path from `app/auth.py`, migration `0012` and moving
  `scripts/setup_compose.py`, `scripts/scan.py` and `scripts/smoke_stack.py` to the verify API.

### Unchecked criteria

- `Viewer` keys are denied `PUT /api/v1/settings` (tested). There is no automated audit yet proving that
  every write route has an explicit role check.
- The 7-day shadow-mode soak needs real traffic. The local stack moved from shadow to cutover in one session.
- Portal sign-in with Entra (`PlatformOperator` and `PlatformAuditor`) is implemented, and token validation is
  unit-tested with a stubbed signing key. It hasn't been tested against a live Entra tenant. The local stack
  uses the operator-key fallback, which identity-service refuses when `CLOUDSAVER_ENVIRONMENT=production`.

### Defaults applied (open questions 5–12)

- Keys expire after 90 days by default and after at most 365 days. There is no "No expiry" option.
- "Include providers added later" is available for new keys and is off by default.
- The import creates one customer per workspace, with ID `uuid5(NAMESPACE_URL, 'cloudsaver:organization:' + tenant_id)`.
- Verify and admin run in one identity-service deployment.
- Throttling blocks for 15 minutes after 30 failures per IP or 5 secret mismatches per key and IP within 5
  minutes. The `CLOUDSAVER_IDENTITY_*` variables override these limits.
- Audit records are kept indefinitely and are append-only. Usage, failure and change-feed retention defaults
  (90, 30 and 30 days) are recorded, but the retention job isn't scheduled yet (see deviations).
- No second-operator approval is required.
- Downstream services re-verify keys through their own short cache (15 seconds by default, at most 30).

### Rollout flags

- `CLOUDSAVER_KEY_VERIFIER`: `local`, `shadow` or `identity`. The code defaults to `local` and compose defaults to `shadow`.
- `CLOUDSAVER_DIRECTORY_MODE`: `registry` or `cutover`. `cutover` requires `identity`.
- `CLOUDSAVER_PROVIDER_SCOPED_KEYS`: enables provider-limited keys in the portal and the admin API.
- `CLOUDSAVER_PORTAL_AUTH`: `entra` or `operator_key`. `operator_key` is refused in production.
- `python3 scripts/setup_compose.py --add-identity` adds any missing identity secrets to `.env` and prints only
  their names. `--cutover` sets the three cutover flags.
- `docker compose --profile migration run --rm identity-import` runs the idempotent import
  (`python -m identity.importer`).

### Deviations

- The legacy key pattern accepts 32–128 URL-safe characters, so the 64-character hex keys from
  `setup_compose.py` and the 43-character operator-console keys both import.
- `identity.api_keys` has an extra `legacy_fingerprint` column, `HMAC(pepper, 'import:' + sha256)`. It keeps
  re-imports idempotent after a legacy key has been upgraded to HMAC.
- The import doesn't read `organizations`. It derives one customer per workspace, as described above.
- The application projection merges directory fields into the registry `config` instead of adding a
  separate preferences column. `api_key_sha256` is set to `NULL` on projected rows.
- The retention command exists, but no scheduler runs it yet.
- `identity_app` has `DELETE` on the four workspace scope tables, because a scope replace deletes and
  re-inserts rows. Customers, workspaces, keys and audit can't be deleted by the runtime role.
- Verify metrics are in-memory counters exposed at `/internal/v1/metrics`. There's no Prometheus exporter.
- Services authenticate to identity-service with per-service tokens. Only SHA-256 digests are stored in
  `CLOUDSAVER_IDENTITY_CALLERS`. Managed-identity service authentication is a production follow-up.
- There's no internal scopes `PUT` endpoint. Cloud scopes change only through the portal admin API.
- Several routes are classified `full_scope` instead of being filtered by provider: AI assessments and usage,
  AI batches, resource decisions, FinOps imports and summary, GitOps request lists, and deliveries. A key
  limited to some providers gets 403 on these routes. Scan jobs require Azure.
- Migration `0011` creates the `cloudsaver_registry_export` role only when the migrating role can create
  roles. Otherwise an administrator creates it.
- `app/gitops_store.py` unwraps the provider-filtering store wrapper before checking for Postgres.
