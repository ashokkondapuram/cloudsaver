# Resource access identity settings

**Status:** Approved
**Date:** Oct 23, 2026
**Author:** Engineering
**Extends:** `specs/drafts/2026-10-22-tenant-settings-managed-identity.md`,
`specs/approved/2026-10-23-platform-separation-billing.md`, `specs/approved/2026-10-23-platform-token-portal.md`

## Problem statement

CloudSaver reaches customer clouds through one managed identity and federation, with no secrets. The
identifiers that make this work are spread across environment variables and one partly edited JSON field, and
nobody can check whether they work without running a scan:

| Setting | Scope | Read today | UI today |
| --- | --- | --- | --- |
| Managed identity client ID | Deployment | `AZURE_CLIENT_ID` (compose maps `AZURE_MANAGED_IDENTITY_CLIENT_ID`), read by `cloud_identity._managed_identity()`, `platform_credential()` and `keyvault.py` | None. `onboarding()` returns it, but nothing shows it |
| Azure multi-tenant app client ID | Deployment default | `CLOUDSAVER_AZURE_APP_CLIENT_ID` | Dashboard "Keyless access" card, read-only |
| Azure app client ID override | Workspace | `identity.azure_app_client_id` | Portal Overview tab edit dialog. No test |
| Azure access method | Deployment | `CLOUDSAVER_AZURE_ACCESS` (`federated` or `direct`) | Dashboard card, read-only |
| AWS hub role ARN and token audience | Deployment | `CLOUDSAVER_AWS_HUB_ROLE_ARN`, `CLOUDSAVER_AWS_TOKEN_AUDIENCE` | Dashboard card, read-only |
| AWS reader role ARN | AWS account | `aws_accounts[].role_arn` | Portal Cloud accounts tab |
| AWS external ID | Workspace | Always the workspace ID (`multi_cloud.py`, `ai_advisory.py`) | Dashboard card, read-only |
| GCP workload identity provider and audience | Deployment | `CLOUDSAVER_GCP_WORKLOAD_PROVIDER`, `CLOUDSAVER_GCP_TOKEN_AUDIENCE` | Dashboard card, read-only |
| GCP reader service account | Workspace | `identity.gcp_service_account` | Portal Overview tab edit dialog |

The gaps:

1. Operators can change deployment-level identifiers only by editing `.env` and restarting the scanner,
   worker and dispatcher containers.
2. The portal has no **Resource access** view, and identity fields sit in an Overview dialog that doesn't
   explain them.
3. No one can run **Test access** before a scan. Failures appear only as sanitized scan errors.
4. Customers see identifiers but not the exact consent and role-assignment commands to run.
5. The portal accepts `arn:aws-*:` partitions, but the backend accepts only `arn:aws:`.

## Proposed solution

1. **Platform resource access settings.** Add a `resource_access` object to `directory.platform_settings` in
   identity-service. It holds the managed identity client ID and the provider federation defaults. Operators
   edit it in **Platform settings > Resource access**. It reaches CloudSaver through the existing
   `platform_updated` change event and `tenant_registry.apply_platform`, so no restart is needed.
   Environment variables stay as the one-time seed and the fallback when a value is empty.
2. **Precedence, per value:** workspace override, then the platform setting, then the environment variable.
3. **Workspace overrides** stay in `identity{azure_app_client_id?, gcp_service_account?}`. They move from the
   Overview dialog to a new portal **Resource access** tab. AWS reader role ARNs stay on the AWS account rows
   in **Cloud accounts**. The AWS external ID stays fixed to the workspace ID and is never editable, because
   that prevents one workspace from assuming another workspace's role (the confused-deputy problem).
4. **The managed identity client ID applies to resource access only.** The runtime value selects which
   user-assigned identity issues federation tokens (`managed_identity_token`). Key Vault, Azure AI Foundry
   (`platform_credential()`) and service-to-service tokens keep the bootstrap `AZURE_CLIENT_ID`, because they
   run before the directory is loaded. The selected identity must already be attached to the scanner, worker
   and dispatcher containers. Settings can only choose among attached identities, not attach a new one.
5. **Test access.** A probe gets a token and makes one read-only call per provider. It returns a status per
   provider and never returns tokens or raw errors. Operators run it from the portal. Tenant admins run it
   from dashboard Settings for their own workspace.
6. **Dashboard read-only "Resource access" card.** It replaces "Keyless access" and shows identifiers,
   ready-to-copy commands prefilled with the workspace's scopes, a **View setup guide** link to
   `docs/MANAGED_IDENTITY_ROLES.md`, and **Test access** for tenant admins.

## Detailed design

### Data model

**identity-service (`token-db`), migration `i0002_resource_access`:**

- `directory.platform_settings.resource_access jsonb NOT NULL DEFAULT '{}'`, with these keys, all optional:

  | Key | Validation |
  | --- | --- |
  | `managed_identity_client_id` | UUID, normalized to lowercase |
  | `azure_access` | `federated` or `direct` |
  | `azure_app_client_id` | UUID |
  | `aws_hub_role_arn` | `^arn:aws:iam::[0-9]{12}:role/[A-Za-z0-9+=,.@_/-]{1,512}$` |
  | `aws_token_audience` | `^(api\|https)://[A-Za-z0-9._~:/-]{1,200}$`. Default `api://AzureADTokenExchange` |
  | `gcp_workload_provider` | The existing `WORKLOAD_PROVIDER` pattern in `cloud_identity.py` |
  | `gcp_token_audience` | Same rule as `aws_token_audience` |

  Unknown keys are rejected. An empty string clears the value, so the environment fallback applies again.
- `directory.access_checks(check_id uuid PK, tenant_id uuid NULL, requested_by, requested_at, claimed_by NULL,
  claimed_at NULL, completed_at NULL, result jsonb NULL)`. `tenant_id` is null for a platform-only check of
  the managed identity. Rows are kept for 7 days.
- The importer seeds `resource_access` once from the environment of the first CloudSaver import, then never
  overwrites it.
- Workspace `identity` keeps its two keys, and `platform/identity/validation.py` and
  `app/tenant_config.py` keep the same rules (UUID and service account email).

**CloudSaver (application database):** no migration. `public.platform_settings.settings` (jsonb) gains
`resource_access` through `apply_platform`. `cloud_identity` reads it through the registry's 5-second cache.
`_managed_identity()` caches one credential per client ID and closes the old one when the value changes.

### API changes

**identity-service admin API** (portal only, operator Entra token):

| Method | Path | Role | Purpose |
| --- | --- | --- | --- |
| GET | `/admin/v1/platform-settings` | Operator, Auditor | Adds `resource_access` and `resource_access_effective`. The effective values include environment fallbacks reported by the last CloudSaver check, each with a `source` of `platform`, `environment` or `unset` |
| PUT | `/admin/v1/platform-settings` | Operator | Accepts `resource_access` (partial, optimistic `version`) |
| PATCH | `/admin/v1/workspaces/{tenant_id}` | Operator | Unchanged. `identity` is accepted as today |
| POST | `/admin/v1/access-checks` | Operator | Body `{tenant_id?}`. Creates a check and emits `access_check_requested`. Returns `202 {check_id}`. Limited to 6 per workspace per minute |
| GET | `/admin/v1/access-checks/{check_id}` | Operator, Auditor | `pending`, `running` or `completed`, with the result |

**identity-service internal API** (CloudSaver service identity):

| Method | Path | Caller | Purpose |
| --- | --- | --- | --- |
| POST | `/internal/v1/access-checks/{check_id}/claim` | scanner | First caller wins (`409` otherwise), so only one replica runs the check |
| PUT | `/internal/v1/access-checks/{check_id}/result` | scanner | Stores the sanitized result |

Traffic still flows only from CloudSaver to identity-service. Scanner-service already long-polls
`/internal/v1/events`. It reacts to `access_check_requested`, claims the check and runs the probe where the
managed identity exists. Pending checks that no one claims within 60 seconds time out as `unavailable`.

**CloudSaver:**

| Method | Path | Role | Purpose |
| --- | --- | --- | --- |
| GET | `/api/v1/settings` | Any workspace role | `identity` (from `onboarding()`) adds `source` for each value and the workspace's prefilled `commands` |
| POST | `/api/v1/settings/access-test` | TenantAdmin | Runs the probe for the caller's workspace synchronously (30-second budget). Limited to 3 per workspace per minute |

**Probe** (`app/access_probe.py`). It runs per configured provider with a 10-second timeout each.

| Provider | Steps |
| --- | --- |
| Managed identity | Get a token for the federation audience |
| Azure | Get a `ClientAssertionCredential` token in the workspace's directory, then read the first configured subscription with `GET /subscriptions/{id}` |
| AWS | Federate into the hub role, assume the first account's reader role with the external ID, then call `sts:GetCallerIdentity` |
| GCP | Get a workload identity token, impersonate the service account, then call `projects.get` on the first project |

The result has the form `{provider, status, message, checked_at, target}`. `status` is one of `ok`,
`not_configured`, `identity_unavailable`, `federation_failed`, `consent_required`, `access_denied` or
`error`. Messages are fixed strings mapped from the status. Tokens, assertion claims, exception text and
response bodies are never returned or logged. `target` is the subscription, account or project ID tested.

### UI changes

**Platform portal > Platform settings > Resource access** (new section after Automation):

- Fields: **Managed identity client ID**, **Azure access method** (Federated app credential, or Managed
  identity in the same tenant), **Azure app client ID**, **AWS hub role ARN**, **AWS token audience**, **GCP
  workload identity provider** and **GCP token audience**.
- Each field shows its source under the value, for example "From environment" or "Not set".
- Buttons: **Edit**, **Save**, **Cancel** and **Test access** (managed identity only).
- Inline errors: "Enter a client ID in GUID format, such as 00000000-0000-0000-0000-000000000000.", "Enter a
  role ARN such as arn:aws:iam::123456789012:role/CloudSaverHub."
- When the managed identity client ID changes, a confirmation dialog appears: "Scans use this identity right
  away. Make sure it's attached to the scanner, worker and dispatcher containers." Buttons: **Confirm** and
  **Cancel**.

**Platform portal > Workspace > Resource access** (new tab between Cloud accounts and Keys):

- **Azure:** Azure app client ID override, with the platform default shown as a placeholder.
- **AWS:** external ID (the workspace ID, read-only with a copy action) and the trusted hub role (read-only).
  A link says "Reader role ARNs are set on each account in Cloud accounts."
- **GCP:** reader service account.
- **Test access** shows one row per provider with a status badge (Ready, Not configured, Consent required,
  Access denied, Unavailable) and the time it ran, such as "Oct 23, 2026 at 2:30 PM".
- The identity edit dialog is removed from the Overview tab. Overview keeps a read-only summary.
- Auditors see the tab read-only, without **Edit** or **Test access**.

**CloudSaver dashboard > Settings > Resource access** (replaces "Keyless access", read-only):

- One article per configured provider with identifiers, copy actions and commands prefilled with the
  workspace's subscriptions, accounts and projects:
  - **Azure:** the admin consent URL and `az role assignment create --assignee <APP_CLIENT_ID> --role Reader
    --scope /subscriptions/<id>`. In direct mode, the assignee is the managed identity.
  - **AWS:** a trust policy JSON for the hub role with the `sts:ExternalId` condition, and
    `aws iam attach-role-policy ... ReadOnlyAccess`.
  - **GCP:** `gcloud projects add-iam-policy-binding <project> --member serviceAccount:<sa> --role roles/viewer`.
- **View setup guide** links to `docs/MANAGED_IDENTITY_ROLES.md`.
- **Test access** (tenant admins) shows the same per-provider results.
- The managed identity client ID appears only in direct mode, because customers need it only there.

### Security

- Client IDs, ARNs and provider names are identifiers, not secrets. No secret, key or token is stored or
  accepted, and Pydantic models reject unknown fields.
- Only `PlatformOperator` can edit resource access settings or run portal checks. `PlatformAuditor` has read
  access. Tenant admins can't edit identity bindings, as today.
- Every change writes an identity-service audit event (`resource_access_updated`,
  `workspace_identity_updated`) with old and new values, plus `access_check_requested` and
  `access_check_completed` (statuses only). These events appear in portal Activity.
- Probe calls are read-only and rate limited. Results never include tokens or raw provider errors.
- Changing the managed identity client ID can't widen access. Customer clouds still trust only the
  configured federated credential subject.

## Acceptance criteria

- [x] An operator can set each platform resource access value in the portal, and the next scan uses it
      without a restart (within cache TTL plus feed delay, under 30 seconds).
- [ ] An empty value falls back to the environment variable, and the portal shows the source.
- [ ] The workspace override takes precedence over the platform default, which takes precedence over the
      environment variable.
- [ ] Invalid GUIDs, ARNs, provider names, audiences and unknown keys return 422 with the messages above.
- [ ] Key Vault, AI Foundry and service tokens keep using the bootstrap `AZURE_CLIENT_ID`.
- [ ] **Test access** reports a status per provider from the portal (asynchronous) and the dashboard
      (synchronous). No token, claim or raw error appears in responses or logs, and tests assert this.
- [ ] The portal workspace **Resource access** tab replaces the Overview identity dialog. Auditors can't edit.
- [ ] Dashboard Settings shows the read-only **Resource access** card with prefilled commands and the
      setup guide link.
- [ ] Every change and check appears in portal Activity with actor and time.
- [ ] Portal role ARN validation matches the backend (`arn:aws:` only).
- [ ] Contract docs (`platform/contracts/identity-v1.md`, `admin-billing-v1.md`) and fixtures are updated.

## Out of scope

- Attaching or creating managed identities, app registrations, federated credentials or IAM roles from the UI.
- An editable AWS external ID, or per-workspace hub roles or GCP workload providers.
- Kubernetes access (bearer token environment bindings are unchanged).
- Sovereign clouds (Azure Government, AWS GovCloud, `arn:aws-us-gov:`).
- Changing the identity used for Key Vault, AI Foundry or service-to-service calls.
- Scheduled or continuous access monitoring (only manual **Test access**).

## Open questions

| Question | Recommended default |
| --- | --- |
| Should the managed identity client ID be editable at all, or display-only? | Editable, used for resource access only, with a confirmation dialog. Bootstrap stays on the environment variable |
| Should **Save** require a passing **Test access** for a new managed identity client ID? | No. Show a warning and recommend running a test. Revisit if misconfiguration incidents occur |
| Should tenant admins run **Test access**? | Yes, for their own workspace, rate limited. It helps customers check their role assignments |
| Should audit events store old and new identifier values? | Yes. They aren't secrets and help investigations |
| Should the probe check every scope or only the first scope per provider? | Only the first, to keep it fast. A full check is a later option |
| Should `azure_access` be per workspace (direct mode for CloudSaver's own tenant only)? | No. Keep it platform-wide for now |
| Should the portal check run in the scanner or the worker? | Scanner-service, which already long-polls events and holds the managed identity |

## Dependencies

- The concurrent platform separation work (directory projection, `apply_platform`, the event poller).
- Container hosting attaches every selectable user-assigned identity to the scanner, worker and dispatcher.

## Implementation notes

- Migration order: `i0002_billing` (minimal billing schema required by `PostgresStore` startup) then `i0003_resource_access`.
- Platform `identity-service` is healthy after migrations; portal bind on `127.0.0.1:3100` may conflict if the legacy `cloudsaver-platform-portal` container is already running.
- Billing plan seed in `i0002_billing` uses minimal entitlements JSON; full catalog seed remains a follow-up for production billing screens.

Files to change:

- **identity-service:** `platform/identity/validation.py`, `service.py`, `app.py`, `auth.py` (rate limits),
  `store_memory.py`, `store_postgres.py`, `events.py`, `importer.py`, and the new
  `platform/identity_migrations/versions/i0002_resource_access.py`.
- **Contracts:** `platform/contracts/identity-v1.md`, `platform/contracts/admin-billing-v1.md`, and
  `platform/contracts/fixtures/directory_snapshot.json`, `directory_changes.json` and `events.json`.
- **Portal:** `platform/portal/components/settings/PlatformSettingsView.tsx`, a new
  `components/settings/ResourceAccessSection.tsx`, `components/workspaces/WorkspaceDetail.tsx`, a new
  `components/workspaces/ResourceAccessTab.tsx`, `OverviewTab.tsx`, `CloudAccountsTab.tsx`, `lib/types.ts`,
  `lib/labels.ts`, and `app/api/portal/[...path]/route.ts` (only if paths are allowlisted).
- **CloudSaver:** `app/cloud_identity.py`, a new `app/access_probe.py`, `app/tenant_registry.py`,
  `app/tenant_config.py`, `app/settings_api.py`, `app/identity_client.py` (the event hook),
  `services/scanner.py` (wiring), and `app/multi_cloud.py` (to share the resolver).
- **Dashboard:** `web-dashboard/components/settings/WorkspaceSettings.tsx` and its settings types.
- **Docs:** `docs/MANAGED_IDENTITY_ROLES.md`, `docs/CLOUD_SOURCES.md` and `.env.example` (seed and fallback
  wording).
- **Tests:** `tests/test_cloud_identity.py`, `tests/test_settings_api.py`, a new `tests/test_access_probe.py`,
  `tests/identity_fake.py`, `tests/test_identity_client.py`, `platform/tests/test_identity.py` and
  `platform/tests/test_identity_postgres.py`.
