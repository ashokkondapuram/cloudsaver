# Onboarding and access

CloudSaver separates who you are from what you can reach. Your organization is onboarded with a single-use key from a platform operator, which you exchange on the `/claim` page for an owner account and a personal key. After that, you sign in to the dashboard with a workspace access key or an Entra delegated bearer token, and every request is authorized against workspace roles, optional provider and scope restrictions, and the platform's plan state. Users, workspace memberships, service accounts and keys are client-managed: your organization's administrators maintain them from Settings, and identity-service enforces the rules on every call.

Last reviewed: Oct 25, 2026.

## Where to find it

- **Claim page**: `/claim`. [web-dashboard/app/claim/page.tsx](../../web-dashboard/app/claim/page.tsx) returns `null`; when you aren't connected, `AppShell` in [web-dashboard/components/AppShell.tsx](../../web-dashboard/components/AppShell.tsx) renders [web-dashboard/components/ClaimView.tsx](../../web-dashboard/components/ClaimView.tsx) for `/claim` and the sign-in form everywhere else.
- **Sign-in form**: the "Workspace access key or Entra Bearer token" field in `AppShell.tsx`.
- **Session handling**: [web-dashboard/components/WorkspaceProvider.tsx](../../web-dashboard/components/WorkspaceProvider.tsx).
- **Access administration**: `/settings?tab=access` (Access & API keys), implemented by [web-dashboard/components/settings/AccessSettings.tsx](../../web-dashboard/components/settings/AccessSettings.tsx).

## What you can do

### Claim your organization

1. A platform operator creates your customer and workspace in the platform portal and issues an onboarding (bootstrap) key. Bootstrap keys last 24 hours by default and at most 72 hours, and only one active bootstrap key can exist per workspace.
2. You open `/claim`, paste the onboarding key, and enter your name and work email.
3. CloudSaver calls `POST /api/v1/onboarding/claim`. On success you become the customer owner and receive a personal key, shown once in a dialog that you must confirm you've stored.
4. Select **Connect workspace** to sign in with your new personal key, then invite your team from Settings.

An invalid or expired onboarding key returns "This onboarding key is invalid or has expired. Ask your administrator for a new key."

### Sign in

- Paste a workspace access key or an Entra delegated access token into the sign-in form. The dashboard calls `/api/v1/me`, `/api/v1/scans` and `/api/v1/billing/entitlements` in parallel to verify it.
- The credential is stored in browser session storage for that tab only (`cloudsaver:session:token`), with the last-activity time in `cloudsaver:session:activity`.
- If your key expires soon, the dashboard shows a warning with the expiry date.
- You can switch workspaces by connecting another credential; the current workspace stays open until the new one is verified.

### Session idle timeout

- The dashboard signs you out after 30 minutes without activity (`IDLE_TIMEOUT_MS = 30 * 60 * 1000`).
- Activity is mouse down, key down, scroll or touch start. The check runs every 30 seconds.
- On reload, a saved session is restored only if it hasn't been idle past the timeout; otherwise it is cleared.

### Manage users and keys (client-managed)

From **Settings > Access & API keys** you can:

- Invite organization users as Administrator (`CustomerAdmin`) or Auditor (`CustomerAuditor`). Email delivery isn't configured, so share sign-in details directly.
- Suspend or reactivate users. Suspending revokes every key issued to that user.
- Transfer ownership to another active user (owner only; you stay an administrator).
- Add workspace members and edit their workspace roles. You can only assign roles you hold.
- Remove a member, which revokes their keys for that workspace.
- Create, suspend or reactivate service accounts for automation and CI.
- Issue keys to a member or service account with roles and an expiry date (90 days by default in the dialog). A user's key can't have more roles than their workspace membership.
- Rotate keys (the old key keeps working for 24 hours) and revoke keys immediately.
- Export an access review CSV (`access-review.csv`) and view recent access activity.

Auditors see users, keys and activity read-only. If you sign in with an operator-issued workspace key that has `TenantAdmin`, the tab treats you as a workspace key administrator: you can add members and issue keys, but user status is managed by your organization owner.

If your credential has no customer roles (for example, an Entra token or a local key), the tab explains that organization access isn't available with this key.

## How it works

### Authentication modes

[app/auth.py](../../app/auth.py) builds the `current_tenant` dependency (`tenant_dependency`) used by every authenticated route.

- `CLOUDSAVER_AUTH_MODE=workspace` (default): the bearer token is a workspace access key.
  - `CLOUDSAVER_KEY_VERIFIER=local`: the SHA-256 digest of the key is compared in constant time against `api_key_sha256` on each active tenant. A match grants all three workspace roles and no provider restriction.
  - `CLOUDSAVER_KEY_VERIFIER=identity`: the key is verified by identity-service through [app/identity_client.py](../../app/identity_client.py) (`POST /internal/v1/keys/verify`). The grant supplies roles, key ID and name, allowed providers, scope restrictions, customer roles, subject type and ID, expiry and the fresher plan block.
  - `CLOUDSAVER_KEY_VERIFIER=shadow`: the local result is authoritative, and identity-service verification runs in a background pool only to log mismatches.
- `CLOUDSAVER_AUTH_MODE=entra`: the bearer token is an Entra v2 delegated access token validated by `EntraTokenValidator`:
  - RS256 only, signing keys from the tenant's JWKS endpoint.
  - Audience must equal `CLOUDSAVER_ENTRA_AUDIENCE`; issuer must be `https://login.microsoftonline.com/{tid}/v2.0`; `ver` must be `2.0`.
  - The token's `tid` must be a provisioned workspace tenant ID.
  - The `scp` claim must include `access_as_user`.
  - The `roles` claim must include at least one CloudSaver application role (`TenantAdmin`, `BillingAdmin`, `Viewer`).
  - Entra sessions have `subject_type='user'`, no provider restriction, and no customer roles.

### Identity-service verification details

- **Grant cache**: `GrantCache` holds positive results for `CLOUDSAVER_IDENTITY_CACHE_SECONDS` (0 to 30, default 15), capped further by the grant's `cache_ttl_seconds`.
- **Revocation**: `EventPoller` long-polls `GET /internal/v1/events`. Events evict cached grants by key ID or tenant ID; while polling fails, caching is disabled. Directory events nudge the directory projector.
- **Rejections**: revoked, expired or rotated-out keys return 401 with "This workspace key has expired or was revoked…"; suspended workspaces return 403; throttled sign-ins return 429 with `Retry-After` (900 seconds when identity doesn't supply one); identity outages return 503 "Sign-in is temporarily unavailable…".
- **Directory freshness**: if the local projection's `directory_version` is behind the grant, CloudSaver returns 503 "This workspace is still being set up…" with `Retry-After: 5`. In production, every request also checks projection lag against `CLOUDSAVER_DIRECTORY_MAX_LAG_SECONDS`.

### Principals

[app/principals.py](../../app/principals.py) provides:

- `actor(tenant)`: a stable SHA-256 audit identity from `subject_id`, `user_id`, `key_id` or `tenant_id`, in that order.
- `visible(case, tenant)`: whether a record's provider and scope fall inside the caller's allowed providers and scope restrictions.

### Provider- and scope-restricted keys

- [app/provider_access.py](../../app/provider_access.py) narrows the effective workspace (`narrow`, `restrict`) so scopes outside the key are emptied.
- `enforce_route` runs before each handler and classifies the route with [app/route_inventory.py](../../app/route_inventory.py):

| Route class | Behavior for restricted keys |
| --- | --- |
| `public` | Rejected for restricted keys (no workspace authentication needed for others) |
| `agnostic` | Allowed for any key with the required role |
| `scoped_read` | Allowed; results are filtered to the key's providers and scopes by `ScopedStore` |
| `scan_write` | Acts on an existing scan; every provider in the scan must be allowed |
| `provider` tuple | Fixed providers that must all be allowed, for example `POST /api/v1/scans` requires Azure |
| `body` | Providers named in the request body are checked by the handler |
| `full_scope` | Rejected unless the key covers every configured provider (403 "This workspace key doesn't include all providers.") |

- `ScopedStore` filters scans, findings, inventory, rule evaluations, dependency edges, source ledgers and scope results, and recomputes opportunity totals for the visible subset. Filtered scans carry `provider_filtered` and `scope_filtered` flags.
- Unclassified routes are rejected for restricted keys; [tests/test_route_inventory.py](../../tests/test_route_inventory.py) fails when a new route isn't classified.
- Identity-service only issues provider-scoped keys when `PLATFORM_PROVIDER_SCOPED_KEYS` is `true`; otherwise it returns "Provider-scoped keys aren't enabled yet. Include all providers."

### Onboarding and customer access proxy

[app/onboarding_api.py](../../app/onboarding_api.py):

- `onboarding_router` exposes the public claim route and maps it to identity-service `POST /customer/v1/claim`. The claim body requires a display name and either a work email (stored as issuer `urn:cloudsaver:email` with the lowercased email as subject) or both an identity issuer and subject.
- `customer_access_router` proxies `/api/v1/customer/*` to `/customer/v1/*`, forwarding your `Authorization` header and client IP. Workspace-level calls are pinned to your own workspace ID. Identity-service re-verifies the key and enforces customer roles on every call.
- Upstream errors are mapped to 401, 403, 404, 409, 422 or 429 with a short detail; other statuses become 502.

### Plan suspension

When the plan block sets `access_suspended`, only `/api/v1/me`, `/api/v1/billing/*` and `/api/v1/customer/*` remain available, so security and billing administration keep working.

## API reference

Gateway paths in [services/gateway.py](../../services/gateway.py) match the core paths below. The gateway applies a 120 requests-per-minute workspace rate limit to authenticated routes.

| Method | Path | Purpose | Required role/scope |
| --- | --- | --- | --- |
| POST | `/api/v1/onboarding/claim` | Exchange an onboarding key for an owner account and personal key | Public (onboarding key in body) |
| GET | `/api/v1/me` | Current workspace, roles, key, plan and operations state | Any role; `agnostic` |
| GET | `/api/v1/customer/me` | Customer context for the current key | Any key; customer roles enforced by identity-service |
| GET | `/api/v1/customer/users` | List organization users | Customer role required by identity-service; `agnostic` |
| POST | `/api/v1/customer/users/invite` | Invite a user as `CustomerAdmin` or `CustomerAuditor` | Customer owner or administrator |
| POST | `/api/v1/customer/users/{user_id}/suspend` | Suspend a user and revoke their keys | Customer owner or administrator |
| POST | `/api/v1/customer/users/{user_id}/reactivate` | Reactivate a user | Customer owner or administrator |
| POST | `/api/v1/customer/ownership/transfer` | Transfer ownership | Customer owner |
| GET | `/api/v1/customer/members` | List members of your workspace | Customer role required |
| PUT | `/api/v1/customer/members/{user_id}` | Set a member's workspace roles (versioned) | Customer owner or administrator |
| POST | `/api/v1/customer/members/{user_id}/remove` | Remove a member (versioned) | Customer owner or administrator |
| GET | `/api/v1/customer/service-accounts` | List service accounts | Customer role required |
| POST | `/api/v1/customer/service-accounts` | Create a service account | Customer owner or administrator |
| PATCH | `/api/v1/customer/service-accounts/{account_id}` | Rename, suspend, reactivate or delete a service account | Customer owner or administrator |
| GET | `/api/v1/customer/keys` | List keys for your workspace | Customer role required |
| POST | `/api/v1/customer/keys` | Issue a key (201) | Customer owner or administrator |
| POST | `/api/v1/customer/keys/{key_id}/revoke` | Revoke a key | Customer owner or administrator |
| POST | `/api/v1/customer/keys/{key_id}/rotate` | Rotate a key with 0 to 168 hours of overlap (201) | Customer owner or administrator |
| GET | `/api/v1/customer/audit` | Customer access audit (limit 1 to 200) | Customer role required |
| GET | `/api/v1/customer/access-export` | Access review CSV | Customer role required |
| GET | `/api/v1/auth/consent-url` | Interactive consent onboarding; returns 501 | `TenantAdmin`; `agnostic` |

All `/api/v1/customer/*` routes are classified `agnostic` in [app/route_inventory.py](../../app/route_inventory.py); identity-service makes the role decision. The exact customer role required for each action is enforced in [platform/identity/customer/admin.py](../../platform/identity/customer/admin.py).

## Data and evidence

- `/api/v1/me` returns tenant ID, name, roles, `allowed_providers` (configured providers visible to you), `all_providers`, `key_id`, `key_name`, `key_expires_at`, `scope_restrictions`, `customer_roles`, `subject_type`, `subject_id`, `directory_mode`, `scopes_editable`, plan fields, configured scope count and operations state (scheduled scans, alerts, delivery).
- Claim response: `customer_id`, `tenant_id`, `secret` and `user.display_name`. The secret is shown once.
- Key list rows include name, key ID, subject, roles, scope restriction marker, status, expiry and last use.
- Audit events include `customer_claimed`, `user_invited`, `user_suspended`, `user_reactivated`, `ownership_transferred`, `workspace_membership_changed`, `workspace_membership_removed`, `service_account_created`, `service_account_updated`, `issued`, `revoked`, `rotated` and `bootstrap_issued`.
- Identity-service limits: 20 active keys per workspace, 25 service accounts and 20 invites per day ([platform/identity/domain.py](../../platform/identity/domain.py)).

## Permissions

| Role | Kind | Grants |
| --- | --- | --- |
| `TenantAdmin` | Workspace role | Everything in the workspace, including scans, settings writes and remediation exports; satisfies any workspace role check |
| `BillingAdmin` | Workspace role | Plan list, plan-change requests and FinOps billing routes |
| `Viewer` | Workspace role | Read access to scans, findings and settings |
| `CustomerOwner` | Customer role | All customer administration plus ownership transfer |
| `CustomerAdmin` | Customer role | Invite and manage users, members, service accounts and keys |
| `CustomerAuditor` | Customer role | Read-only users, keys, audit and export |

`UserClaims.has_role` also treats any assigned role as sufficient for `Viewer`. Key-level restrictions (`allowed_providers`, `scope_restrictions`) further narrow what a role can reach, as described above.

## Configuration

| Variable | Purpose | Default |
| --- | --- | --- |
| `CLOUDSAVER_AUTH_MODE` | `workspace` (keys) or `entra` (delegated tokens) | `workspace` |
| `CLOUDSAVER_KEY_VERIFIER` | `local`, `shadow` or `identity`; cutover requires `identity` | `local` |
| `CLOUDSAVER_DIRECTORY_MODE` | `registry` or `cutover` | `registry` |
| `CLOUDSAVER_ENTRA_AUDIENCE` | Expected `aud` for Entra tokens | Empty (Entra sign-in returns 503 until set) |
| `CLOUDSAVER_ENTRA_ACCESS_POLICY` | Must be `tenant_roles` for production Entra mode | Unset |
| `CLOUDSAVER_IDENTITY_URL` | identity-service base URL | `http://identity-service:8005` |
| `CLOUDSAVER_IDENTITY_TOKEN` | Service token sent as `X-Service-Token` (secret; never commit) | Unset (required for identity calls) |
| `CLOUDSAVER_IDENTITY_CACHE_SECONDS` | Positive grant cache TTL, 0 to 30 | `15` |
| `CLOUDSAVER_TENANTS` | Bootstrap workspace seed (JSON); ignored after cutover | `[]` |
| `CLOUDSAVER_ENVIRONMENT` | `production` enforces identity verification, cutover and a database registry | `development` |
| `CLOUDSAVER_DIRECTORY_MAX_LAG_SECONDS` | Production directory freshness bound, 5 to 300 | `30` |
| `PLATFORM_PROVIDER_SCOPED_KEYS` | Platform switch that allows provider-scoped key issuance | `false` |

Never put real keys or tokens in source or committed configuration. Use environment variables or a secrets manager.

## Guardrails and limitations

- Onboarding keys are single use and expire within 72 hours.
- Email invitations aren't sent; administrators share sign-in details directly.
- Entra/OIDC customer sign-in for client-managed users, SCIM provisioning and step-up authentication aren't implemented (see [CLIENT_MANAGED_USERS_AND_KEYS.md](../CLIENT_MANAGED_USERS_AND_KEYS.md)).
- Keys issued from the dashboard always include all providers. Provider-scoped keys come from the platform portal and require `PLATFORM_PROVIDER_SCOPED_KEYS`.
- Local key verification grants all roles to any matching key; use `identity` verification for role-separated keys.
- `GET /api/v1/auth/consent-url` returns 501; cloud accounts are added by platform operators. See [v2-scaffolds.md](v2-scaffolds.md).
- The idle timeout is enforced in the browser only. Server-side, a key remains valid until it expires, rotates out or is revoked.
- Provider-restricted keys can't use `full_scope` routes such as AI settings, rule overrides, scan job history and several governance and outcome writes.

## Tests

- [tests/test_auth.py](../../tests/test_auth.py): Entra validation and workspace authentication.
- [tests/test_identity_client.py](../../tests/test_identity_client.py): verify caching, eviction and rejection handling.
- [tests/test_onboarding_api.py](../../tests/test_onboarding_api.py): claim and customer access proxy.
- [tests/test_identity_api.py](../../tests/test_identity_api.py): identity-backed sign-in.
- [tests/test_route_inventory.py](../../tests/test_route_inventory.py), [tests/test_inventory_scope_security.py](../../tests/test_inventory_scope_security.py), [tests/test_scoped_finops_routes.py](../../tests/test_scoped_finops_routes.py), [tests/test_scoped_governance_outcomes.py](../../tests/test_scoped_governance_outcomes.py): provider and scope restrictions.
- [platform/tests/test_identity.py](../../platform/tests/test_identity.py): identity-service keys, claim and customer administration.

## Related docs

- [CLIENT_MANAGED_USERS_AND_KEYS.md](../CLIENT_MANAGED_USERS_AND_KEYS.md)
- [MANAGED_IDENTITY_ROLES.md](../MANAGED_IDENTITY_ROLES.md)
- [Workspace settings](settings.md)
- [Platform portal](platform-portal.md)
- [identity-v1 contract](../../platform/contracts/identity-v1.md)
- [ENVIRONMENT.md](../ENVIRONMENT.md)
