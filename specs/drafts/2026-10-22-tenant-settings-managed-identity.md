# Runtime tenant settings and keyless cloud identity

**Status:** Draft (implementation in progress)
**Date:** Oct 22, 2026
**Author:** Engineering

## Problem statement

Tenants, Azure subscriptions, AWS accounts, GCP projects, Kubernetes clusters, scan schedules and alert
switches are parsed once from `CLOUDSAVER_TENANTS` and other environment variables. Changing any of them
requires editing `.env` and restarting every container, and nothing can be changed from the dashboard.

Cloud access depends on long-lived secrets: an Azure client secret (`AZURE_CLIENT_SECRET` or a Key Vault
secret), AWS named profiles backed by access keys, and GCP service-account key files. These secrets must be
rotated, can leak, and conflict with the platform's no-secrets posture.

## Proposed solution

CloudSaver runs on Azure (Container Apps, AKS or a VM) with a managed identity, which becomes the only
credential root for every cloud.

1. **Database tenant registry.** A new `tenant_registry` table holds each tenant's name, plan, access-key
   hash, status, cloud scopes, identity settings, schedule and alert preferences. `CLOUDSAVER_TENANTS` is a
   one-time bootstrap seed: rows are inserted if absent and never overwritten. All services read the registry
   through a short in-process cache (5 seconds by default).
2. **Platform settings.** A single-row `platform_settings` table holds the scheduled scans and automated alerts
   switches. The environment variables `CLOUDSAVER_SCHEDULED_SCANS` and `CLOUDSAVER_AUTOMATED_ALERTS` only
   seed the first row.
3. **Two admin surfaces.**
   - The **platform operator** authenticates with a separate operator key (`CLOUDSAVER_OPERATOR_KEY_SHA256`)
     and creates tenants, changes names and plans, activates or deactivates tenants, and changes platform
     settings.
   - **Tenant admins** (TenantAdmin role) manage their own subscriptions, cloud scopes, identity settings,
     scan schedule and alerts.
4. **Keyless identity** (`CLOUDSAVER_CLOUD_IDENTITY=managed_identity`, the default):
   - **Azure:** a multi-tenant app registration trusts the managed identity through a federated identity
     credential. CloudSaver exchanges a managed identity token (`api://AzureADTokenExchange`) for a token in
     each customer tenant with `ClientAssertionCredential`. No client secret exists. The app client ID comes
     from `CLOUDSAVER_AZURE_APP_CLIENT_ID` or a per-tenant override.
   - **AWS:** each account has a `role_arn` (and optional `external_id`). CloudSaver calls
     `AssumeRoleWithWebIdentity` with the managed identity token. With `CLOUDSAVER_AWS_HUB_ROLE_ARN` set, it
     federates into the hub role and then calls `AssumeRole` into each customer role with its external ID.
   - **GCP:** each project has a `service_account`. CloudSaver uses Workload Identity Federation
     (`CLOUDSAVER_GCP_WORKLOAD_PROVIDER`) with the managed identity token as the subject token and impersonates
     that service account.
   - **Local development** (`CLOUDSAVER_CLOUD_IDENTITY=developer`): Azure CLI sign-in, the AWS default chain
     (for example an SSO profile) followed by `AssumeRole`, and gcloud application default credentials followed
     by impersonation. Still no stored secrets.
5. Remove `AZURE_CLIENT_SECRET`, the Key Vault customer-secret provider and AWS `credential_profile` scopes.

## Detailed design

### Data model (migration `0008_tenant_registry`)

- `tenant_registry(tenant_id uuid PK, name, plan_tier, api_key_sha256 UNIQUE, active, config jsonb,
  webhook_url text NULL, version, updated_by, created_at, updated_at)`.
  - `config` holds `subscription_ids`, `aws_accounts[{account_id, region, role_arn, external_id?}]`,
    `gcp_projects[{project_id, regions, service_account?}]`,
    `kubernetes_clusters[{cluster_id, prometheus_url, bearer_token_env}]`, `identity{azure_app_client_id?}`,
    `schedule{frequency}` and `alerts{enabled, channel}`.
  - This is the authentication directory, so it is readable across tenants by the application role and has
    no row-level security. It holds no secret material except the write-only `webhook_url`, which no API ever
    returns.
- `platform_settings(id=1, settings jsonb, version, updated_by, updated_at)`.
- `settings_audit(id, tenant_id NULL, actor, action, version, created_at)`, insert-only.
- Saving a tenant also syncs the RLS-protected `organizations`, `tenants` and `subscriptions` rows (plan tier,
  connection status, active subscriptions) so workers and billing see the same state.

Registry mode is enabled with `CLOUDSAVER_TENANT_REGISTRY=database`. Without it, the environment-only
behavior is unchanged (used by unit tests and SQLite development).

### API changes

Tenant admin (workspace key or Entra TenantAdmin):

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/v1/settings` | Current scopes, identity, schedule, alerts, plan limits and identity onboarding details |
| PUT | `/api/v1/settings` | Replace scopes, identity, schedule and alerts (optimistic `version`) |

Platform operator (operator key):

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/v1/admin/tenants` | List tenants |
| POST | `/api/v1/admin/tenants` | Create a tenant; returns a new workspace key once |
| PATCH | `/api/v1/admin/tenants/{tenant_id}` | Change name, plan or active status |
| GET / PUT | `/api/v1/admin/settings` | Platform scheduled scans and automated alerts switches |

Validation: plan quota for Azure subscriptions, schedule frequency limited by plan, alerts require an
alert-enabled plan, webhook host must match the channel (Slack or Teams), stale `version` returns 409.

### UI changes

- **Settings > Cloud accounts:** editable lists for Azure subscriptions, AWS accounts (account, region, role
  ARN, external ID), GCP projects (project, regions, service account) and Kubernetes clusters, plus identity
  onboarding details for each provider. Read-only for non-admins.
- **Settings > Schedule & alerts:** scan frequency (limited by plan), alerts switch, channel and write-only
  webhook URL.
- **Operator console (`/admin`):** operator key sign-in, tenant list, create tenant (shows the workspace key
  once), change plan, activate or deactivate, and platform switches.

## Acceptance criteria

- [ ] `CLOUDSAVER_TENANTS` seeds the registry once; later UI changes survive restarts.
- [ ] A tenant admin can add and remove subscriptions and cloud scopes from the dashboard without a restart.
- [ ] The operator can create a tenant, change its plan and deactivate it from `/admin`.
- [ ] Deactivated tenants and rotated-out keys cannot authenticate.
- [ ] Schedule and alert changes take effect for the scheduler and dispatcher without a restart.
- [ ] No code path reads `AZURE_CLIENT_SECRET`, AWS access keys or GCP key files.
- [ ] Azure uses `ClientAssertionCredential` backed by a managed identity; AWS uses
      `AssumeRoleWithWebIdentity`; GCP uses Workload Identity Federation with impersonation.
- [ ] Developer mode works locally with Azure CLI, AWS SSO and gcloud sign-in.
- [ ] Unit tests cover registry validation, settings API authorization and identity selection.

## Out of scope

- Entra sign-in for the platform operator (operator key only in this release).
- Workspace access key rotation from the UI.
- Kubernetes keyless access (Prometheus bearer tokens remain environment bindings).
- Sovereign clouds (Azure Government, AWS GovCloud).

## Open questions

- Should the operator console move to Entra with a `PlatformOperator` app role before general availability?
- Should webhook URLs move to Key Vault references instead of database storage?

## Dependencies

- Azure user-assigned managed identity attached to scanner, worker and dispatcher containers.
- Multi-tenant app registration with a federated credential for that identity, consented in each customer
  tenant with Reader on the selected subscriptions.
- AWS IAM OIDC provider for the Entra tenant and per-account reader roles.
- GCP workload identity pool and provider trusting the Entra tenant, with `roles/iam.workloadIdentityUser` on
  each reader service account.
