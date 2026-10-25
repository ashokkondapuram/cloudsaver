# Workspace settings

The `/settings` page in the CloudSaver dashboard is where you configure a workspace: which cloud scopes it scans, how CloudSaver reaches them, how often it scans and where it sends alerts, which analysis rules run, how AI advisory is bound and governed, and who can sign in with which keys. Most changes are optimistic-concurrency writes against the tenant registry, are capped by your plan entitlements, and are blocked or made read-only when the platform directory owns workspace configuration (directory cutover mode).

Last reviewed: Oct 25, 2026.

## Where to find it

- Route: `/settings` ([web-dashboard/app/settings/page.tsx](../../web-dashboard/app/settings/page.tsx) renders `ConsolePage view="settings"`).
- Tab container: `SettingsView` in [web-dashboard/components/WorkspaceViews.tsx](../../web-dashboard/components/WorkspaceViews.tsx). You can deep-link a tab with `?tab=cloud`, `?tab=rules`, `?tab=ai` or `?tab=access`; the selected tab is written back to the URL.

| Tab (UI label) | `tab` value | Panels rendered |
| --- | --- | --- |
| Cloud scopes and plan | `cloud` | Cloud accounts, Authorized cloud scopes, Workspace scope, Resource access, Identity overrides, Test access, Schedule and alerts, Plan, Plan limits |
| Analysis rules | `rules` | Analysis rules table with preview and apply dialog |
| AI & data governance | `ai` | AI Foundry configuration, AI data governance |
| Access & API keys | `access` | Organization users, Workspace members, Service accounts, Access keys, Activity, Display preferences, Session & access, Keyboard shortcuts |

Component files:

- [web-dashboard/components/settings/WorkspaceSettings.tsx](../../web-dashboard/components/settings/WorkspaceSettings.tsx): `CloudScopesEditor`, `IdentityOnboardingPanel`, `ResourceAccessIdentityEditor`, `ScheduleAlertsEditor`.
- [web-dashboard/components/rules/CustomerRuleSettings.tsx](../../web-dashboard/components/rules/CustomerRuleSettings.tsx): analysis rules.
- [web-dashboard/components/settings/AIFoundryConfigurationEditor.tsx](../../web-dashboard/components/settings/AIFoundryConfigurationEditor.tsx): AI bindings, routing, budgets and consent.
- [web-dashboard/components/settings/DataGovernanceWorkspace.tsx](../../web-dashboard/components/settings/DataGovernanceWorkspace.tsx): data-use policy, processors, retention, legal holds and audit.
- [web-dashboard/components/settings/AccessSettings.tsx](../../web-dashboard/components/settings/AccessSettings.tsx): client-managed users, members, service accounts and keys.
- `CloudAccounts`, `ResourceAccessSettings`, `Plan` and `Preferences` are defined inline in `WorkspaceViews.tsx`.

## What you can do

### Cloud scopes and plan

- **See connected providers.** The Cloud accounts grid shows Azure, AWS, GCP and Kubernetes (filtered to providers your plan allows) and marks each as Available or Not configured.
- **Edit authorized cloud scopes** (`CloudScopesEditor`):
  - Azure subscription IDs, one per line (validated as UUIDs; up to 100).
  - AWS accounts: 12-digit account ID, region and reader role ARN.
  - Google Cloud projects: project ID and a comma-separated region list (at least one region).
  - Kubernetes clusters are read-only here. They reference operator-held bearer tokens, so platform operators manage them in the platform portal.
  - Only providers in your key's `allowed_providers` are shown. Scopes of providers outside your key are preserved on save and never exposed.
- **Review resource access** (`IdentityOnboardingPanel`): the resolved Azure app client ID, managed identity client ID (direct mode only), access method, AWS trusted hub role and external ID (your workspace ID), GCP service account and workload identity provider, plus copyable grant commands per provider and a link to [MANAGED_IDENTITY_ROLES.md](../MANAGED_IDENTITY_ROLES.md). When `CLOUDSAVER_CLOUD_IDENTITY=developer`, the panel shows a "Local sign-in with Azure CLI" badge.
- **Override the resource-access identity** (`ResourceAccessIdentityEditor`): point CloudSaver at your own Azure app registration (client ID UUID) or GCP service account email instead of the platform default. Hidden in cutover mode.
- **Test access**: run a short read-only probe per configured provider before you scan. Limited to 3 runs per minute per workspace.
- **Set the scan schedule and alerts** (`ScheduleAlertsEditor`): choose Manual only, Daily or Hourly (options your plan excludes are disabled), turn on scan summary alerts, pick Slack or Microsoft Teams, and save or remove a webhook URL. The webhook is write-only and never shown again.
- **Review your plan** (`Plan`): plan name, billing state, renewal date, cloud scope quota meter, included features (daily/hourly scheduled scans, Key Vault, automatic alerts), resources per scan, scan frequencies, providers, retention, and current scheduled-scan and alert state.
- **Request a plan change** (billing administrators): pick STARTER, GROWTH or ENTERPRISE and submit it for platform approval. One request can be pending at a time; the pending status shows as awaiting approval or awaiting payment. A Manage billing link appears only when the plan block carries a plain HTTPS `manage_billing_url`.

### Analysis rules

- Filter published rules by provider, service category or free-text search (rule name, ID or resource type).
- Enable or disable a rule and adjust delegated integer parameters within the published bounds shown next to each input.
- Preview changes: CloudSaver re-evaluates the latest completed saved scan with the before and after policies and reports how many resources would change evaluation state. No live cloud call is made.
- Apply changes: the policy is saved through identity-service and applies to the next scan. Historical snapshots keep the policy they were evaluated with.

### AI and data governance

- **AI Foundry configuration**: for Azure AI Foundry, Amazon Bedrock and Google Vertex AI, choose an operator-approved binding from the catalog, enable the provider, and run a non-invoking connection test. Set opt-in AI advisory, source-provider routing (`same_cloud_only`; the workspace default provider option is disabled in the UI), input/output token allowances, hourly attempt budget and monthly token cap, each bounded by the platform ceiling. Saving with advisory enabled requires an explicit external-processing acknowledgment.
- **AI data governance**: see whether the data-use policy is enforced, the permitted data boundaries, registered data processors with review references and expiry, AI content retention records, and the data-use audit. Administrators can erase AI content or place a legal hold (expiry within 30 days) with a review reference. Releasing a hold requires a full-workspace human administrator session.

### Access and API keys

- Invite organization users as Administrator (`CustomerAdmin`) or Auditor (`CustomerAuditor`), suspend or reactivate them, and transfer ownership (owner only).
- Add workspace members and edit their workspace roles (`TenantAdmin`, `BillingAdmin`, `Viewer`).
- Create, suspend or reactivate service accounts for automation.
- Issue keys to a member or service account with roles and an expiry date (default 90 days), rotate keys with a 24-hour overlap, and revoke keys. New secrets appear once in a dialog that clears after 2 minutes.
- Export an access review CSV and see recent access activity.
- Choose table density (stored in browser local storage) and review session details, including the 30-minute idle timeout.

See [onboarding-and-access.md](onboarding-and-access.md) for the full access model.

## How it works

### Dashboard data flow

- All calls go through `api()` in [web-dashboard/lib/api.ts](../../web-dashboard/lib/api.ts), which prefixes `/api/v1` and sends the session credential as a bearer token.
- The Next.js proxy at [web-dashboard/app/api/[...path]/route.ts](../../web-dashboard/app/api/[...path]/route.ts) allowlists routes, caps request bodies at 2 MB, and forwards to `API_GATEWAY_URL` (default `http://127.0.0.1:8000`).
- The gateway ([services/gateway.py](../../services/gateway.py)) authenticates, applies a Redis sliding-window limit of 120 requests per minute per workspace, and forwards settings calls to the core (scanner) service.

### Backend modules

- [app/settings_api.py](../../app/settings_api.py): `GET/PUT /api/v1/settings`, access test, billing plan list and plan-change requests, and the analysis-rule routes (`/api/v1/rules/*`).
  - `WorkspaceSettings` is a strict Pydantic model (`extra='forbid'`) with a required `version` for optimistic concurrency. A stale version returns 409 "Settings changed since you loaded them. Refresh and try again."
  - Writes require `CLOUDSAVER_TENANT_REGISTRY=database`; otherwise 503.
  - In cutover mode, any change to scopes or identity returns 403 with "Cloud accounts are managed in the platform portal…". Schedule and alerts remain editable.
  - Adding scopes calls `enforce_providers` and `enforce_subscription_quota`. A downgraded workspace can still remove scopes or edit its schedule.
  - Alerts: `enforce_automated_alerts` runs when you enable alerts; webhooks are validated by `validate_webhook` in [app/delivery_config.py](../../app/delivery_config.py) (HTTPS, and `hooks.slack.com` only for the Slack channel). Turning alerts on without a stored or new webhook returns 422.
  - When `ai_foundry` is included, `FoundryController.check_write` and `validate_configuration` in [app/foundry.py](../../app/foundry.py) run before the save.
  - Audit actors are hashed with SHA-256 (`actor_for`).
- [app/entitlements.py](../../app/entitlements.py): resolves the effective plan from the verified or projected `plan` block, falling back to `TIER_LIMITS` (STARTER, GROWTH, ENTERPRISE). Provides `enforce_*` helpers and `billing_summary` for `GET /api/v1/billing/entitlements`.
- [app/billing_plan.py](../../app/billing_plan.py): `list_plans` (from `TIER_LIMITS`), `submit_plan_change_request` and `pending_plan_change_request`, which call identity-service `/internal/v1/tenants/{tenant_id}/plan-change-requests`.
- [app/effective_rules.py](../../app/effective_rules.py): `policy_for_tenant` fetches `/internal/v1/tenants/{tenant_id}/analysis-rules/effective` from identity-service (3-second timeout) and returns `None` when identity is unavailable.
- [app/resource_access.py](../../app/resource_access.py): resolves resource-access settings per key with precedence workspace (Azure app client ID only), then platform, then environment, and reports the `source` of each value.
- [app/tenant_config.py](../../app/tenant_config.py): shared validation (`normalize_identity`, `normalize_schedule`, `normalize_alerts`, `normalize_tenant`). Default frequency is hourly for ENTERPRISE, daily for GROWTH and manual otherwise.
- [app/operations.py](../../app/operations.py): effective frequency (your choice capped by plan), scheduled interval, and alert state, combining platform flags, tenant settings and entitlements.
- [app/access_probe.py](../../app/access_probe.py): `run_probe` returns per-provider statuses such as `ok`, `not_configured`, `consent_required` or `access_denied`, never tokens or raw provider errors.
- [app/foundry_api.py](../../app/foundry_api.py) and [app/data_governance_api.py](../../app/data_governance_api.py): AI settings and data-governance routes.
- [app/onboarding_api.py](../../app/onboarding_api.py): `customer_access_router` for the Access & API keys tab.

## API reference

All paths are served by the core service and proxied by the gateway with the same `/api/v1` path. "Route class" comes from [app/route_inventory.py](../../app/route_inventory.py) and governs provider- or scope-restricted keys.

| Method | Path | Purpose | Required role/scope |
| --- | --- | --- | --- |
| GET | `/api/v1/settings` | Read settings, limits, platform flags and resource-access onboarding | Any role; `agnostic` |
| PUT | `/api/v1/settings` | Save scopes, identity, schedule, alerts and optional AI settings | `TenantAdmin`; `agnostic` |
| POST | `/api/v1/settings/access-test` | Run read-only access probes (3 per minute) | `TenantAdmin`; `agnostic` |
| GET | `/api/v1/billing/entitlements` | Effective plan and quota summary | Any role; `agnostic` |
| GET | `/api/v1/billing/plans` | Built-in plan list, current tier and pending request | `BillingAdmin` or `TenantAdmin`; `agnostic` |
| GET | `/api/v1/billing/plan-requests` | Pending plan-change request | `BillingAdmin` or `TenantAdmin`; `agnostic` |
| POST | `/api/v1/billing/plan-requests` | Submit a plan-change request (202) | `BillingAdmin` or `TenantAdmin`; workspace must have a `customer_id`; `agnostic` |
| GET | `/api/v1/rules/effective` | Effective analysis-rule policy | Any role; `agnostic` |
| POST | `/api/v1/rules/preview` | Saved-observation impact preview | `TenantAdmin`; `full_scope` |
| PUT | `/api/v1/rules/overrides` | Save rule overrides through identity-service | `TenantAdmin`; `full_scope` |
| GET | `/api/v1/settings/ai` | AI bindings, catalog, platform policy, usage and diagnostics | Any role; `full_scope` |
| PUT | `/api/v1/settings/ai` | Save AI bindings and policy | `TenantAdmin`; `full_scope` |
| POST | `/api/v1/settings/ai/test-connection` | Non-invoking connection diagnostic | `TenantAdmin`; `full_scope` |
| GET | `/api/v1/ai/governance` | Data-use policy, retention records, holds and audit | Any role; `scoped_read` |
| POST | `/api/v1/ai/governance/records/{attempt_id}/erase` | Erase stored AI content | `TenantAdmin`, human subject (not a service account); `full_scope` |
| POST | `/api/v1/ai/governance/records/{attempt_id}/hold` | Place a legal hold (201) | `TenantAdmin`, human subject; `full_scope` |
| POST | `/api/v1/ai/governance/holds/{hold_id}/release` | Release a legal hold | `TenantAdmin`, full-workspace human user session (no workspace key); `full_scope` |
| GET | `/api/v1/me` | Workspace profile, roles, plan and operations state | Any role; `agnostic` |

The `/api/v1/customer/*` routes used by the Access & API keys tab are listed in [onboarding-and-access.md](onboarding-and-access.md#api-reference).

## Data and evidence

- **Settings response**: `editable` (registry enabled and caller is `TenantAdmin`), `scopes_editable` (editable and not cutover), `directory_mode`, `settings` (tenant ID, name, plan tier, version, scopes, Kubernetes clusters with `cluster_id`, `prometheus_url` and `bearer_token_env` only, identity, schedule, AI configuration, alerts with `webhook_configured`), `limits`, `platform` flags and `identity` onboarding data.
- **Webhook secrecy**: the stored webhook URL is never returned; only `webhook_configured` is.
- **Rule preview**: returns `version`, `proposed`, `scan_id`, `resources_changed` (or `null` without a completed scan) and the message "Saved-observation preview only; no live cloud action or policy change was performed."
- **Plan entitlements source**: `entitlements_source` is `platform` when a valid plan block exists, otherwise `fallback`.
- **Access test rows**: `provider`, `status`, `message`, `checked_at`, `target`.

## Permissions

- Workspace roles are defined in [app/auth.py](../../app/auth.py): `TenantAdmin`, `BillingAdmin`, `Viewer`. `require_workspace_role` lets `TenantAdmin` satisfy any role check.
- Viewers can read settings, rules, AI settings and governance but cannot save. The dashboard disables inputs when `editable` is false.
- The analysis rules tab disables edits when your key has `scope_restrictions`, because rule changes are workspace-wide.
- Provider-restricted keys cannot use `full_scope` routes (AI settings, rule preview and overrides). See [onboarding-and-access.md](onboarding-and-access.md#permissions).
- Billing actions in the dashboard are shown when you have `TenantAdmin` or `BillingAdmin` (`canBill`).
- When the plan block sets `access_suspended`, only `/api/v1/me`, `/api/v1/billing/*` and `/api/v1/customer/*` remain available.

## Configuration

Environment variable names only. See [ENVIRONMENT.md](../ENVIRONMENT.md) for the full reference.

| Variable | Purpose | Default |
| --- | --- | --- |
| `CLOUDSAVER_TENANT_REGISTRY` | `database` enables runtime settings writes; `env` keeps the bootstrap seed read-only | `env` |
| `CLOUDSAVER_DATABASE_URL` | PostgreSQL URL; required when the registry is `database` | Unset |
| `CLOUDSAVER_DIRECTORY_MODE` | `registry` or `cutover`; cutover makes scopes and identity read-only | `registry` |
| `CLOUDSAVER_IDENTITY_URL` | identity-service base URL for rules and plan requests | `http://identity-service:8005` |
| `CLOUDSAVER_IDENTITY_TOKEN` | Service token for identity-service (secret; never commit) | Unset (required) |
| `CLOUDSAVER_SCHEDULED_SCANS` | Platform scheduled-scan switch when no registry is configured | `false` |
| `CLOUDSAVER_AUTOMATED_ALERTS` | Platform alert switch when no registry is configured | `false` |
| `CLOUDSAVER_DELIVERY_ENABLED` | Reports whether the delivery dispatcher is enabled | `false` |
| `CLOUDSAVER_CLOUD_IDENTITY` | `managed_identity` or `developer` | `managed_identity` |
| `AZURE_CLIENT_ID`, `AZURE_MANAGED_IDENTITY_CLIENT_ID` | Environment default for the managed identity client ID | Unset |
| `CLOUDSAVER_AZURE_ACCESS` | `federated` or `direct` Azure access | `federated` |
| `CLOUDSAVER_AZURE_APP_CLIENT_ID` | Environment default Azure app client ID | Unset |
| `CLOUDSAVER_AWS_HUB_ROLE_ARN` | Trusted AWS hub role | Unset |
| `CLOUDSAVER_AWS_TOKEN_AUDIENCE` | AWS federation audience | `api://AzureADTokenExchange` |
| `CLOUDSAVER_GCP_WORKLOAD_PROVIDER` | GCP workload identity provider | Unset |
| `CLOUDSAVER_GCP_TOKEN_AUDIENCE` | GCP federation audience | `api://AzureADTokenExchange` |
| `API_GATEWAY_URL` | Dashboard proxy target | `http://127.0.0.1:8000` |
| `REDIS_URL` | Gateway rate limiter | `redis://localhost:6379/0` (gateway) |

## Guardrails and limitations

- Settings writes fail with 503 unless the database registry is enabled.
- In cutover mode, cloud scopes, identity overrides and AI configuration are managed by the platform; the dashboard shows read-only notices.
- Kubernetes clusters cannot be added from the dashboard.
- Scope quotas count all four providers, including Kubernetes clusters, across the whole workspace, even for provider-scoped keys.
- The plan list always shows the three built-in tiers from `TIER_LIMITS`, even if operators define custom plan codes.
- The access test rate limit is held in process memory, so it is per API process, not global.
- Rule routes depend on identity-service. If it is unavailable, `GET /api/v1/rules/effective` returns 503, and scans by key-authenticated callers fail closed instead of using the full catalog.
- Rule preview needs a completed saved scan to estimate impact.
- Keys issued from the dashboard always include all providers (`all_providers: true`). Provider-scoped keys are issued from the platform portal.
- The workspace default provider routing option is disabled in the AI editor.

## Tests

- [tests/test_settings_api.py](../../tests/test_settings_api.py): settings read/write, cutover, quotas, alerts and identity overrides.
- [tests/test_entitlements.py](../../tests/test_entitlements.py): plan normalization and enforcement.
- [tests/test_effective_rules.py](../../tests/test_effective_rules.py): effective rule policy loading.
- [tests/test_access_probe.py](../../tests/test_access_probe.py): access test results.
- [tests/test_foundry_governance.py](../../tests/test_foundry_governance.py) and [tests/test_data_governance.py](../../tests/test_data_governance.py): AI settings and governance.
- [tests/test_route_inventory.py](../../tests/test_route_inventory.py): every route is classified.
- Dashboard end-to-end: [web-dashboard/e2e/rules-services.spec.ts](../../web-dashboard/e2e/rules-services.spec.ts), [web-dashboard/e2e/foundry.spec.ts](../../web-dashboard/e2e/foundry.spec.ts), [web-dashboard/e2e/data-governance.spec.ts](../../web-dashboard/e2e/data-governance.spec.ts).

## Related docs

- [Onboarding and access](onboarding-and-access.md)
- [Scanning and analysis rules](scanning-and-analysis-rules.md)
- [Platform portal](platform-portal.md)
- [MANAGED_IDENTITY_ROLES.md](../MANAGED_IDENTITY_ROLES.md)
- [AI_DATA_GOVERNANCE.md](../AI_DATA_GOVERNANCE.md)
- [ENVIRONMENT.md](../ENVIRONMENT.md)
- [PLATFORM_BILLING.md](../PLATFORM_BILLING.md)
