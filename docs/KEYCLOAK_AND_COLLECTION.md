# Keycloak, provider collection and service health

Implementation status: opt-in code with local contract tests. This is not a declaration of production support for every provider, service or identity deployment. The approved validation environment for this change is local only. No customer cloud, Keycloak realm or infrastructure deployment was changed.

## Keycloak owns client access and licensing decisions

Set `CLOUDSAVER_AUTH_MODE=keycloak`, `CLOUDSAVER_DIRECTORY_MODE=registry` and, in production, `CLOUDSAVER_TENANT_REGISTRY=database`. The core registry continues to own explicitly authorized cloud scopes and connection configuration. Keycloak owns current users, enabled state, group membership, client roles, sessions and the protected client license record. Legacy workspace keys and Entra authentication remain available in their existing modes; Keycloak mode does not accept them as an alternative credential.

Each workspace has an operator-configured binding in `CLOUDSAVER_KEYCLOAK_BINDINGS`:

```json
[
  {
    "tenant_id": "11111111-1111-4111-8111-111111111111",
    "issuer": "https://identity.example.com/realms/customer-a",
    "audience": "cloudsaver-customer-a",
    "client_id": "cloudsaver-verifier-a",
    "client_uuid": "22222222-2222-4222-8222-222222222222",
    "secret_env": "CLOUDSAVER_KEYCLOAK_SECRET_PRIMARY",
    "group_id": "33333333-3333-4333-8333-333333333333",
    "authorized_parties": ["cloudsaver-console-a"]
  }
]
```

These identifiers are examples. `client_uuid` is the internal UUID of the resource client whose roles grant CloudSaver access; `client_id` is the confidential verifier application's client ID. They need not be the same client. Every workspace must have its own resource-client role namespace; sharing a realm/client UUID across tenant bindings is rejected. Configure exact HTTPS issuers, access-token audience, allowed `azp`, and a non-user-editable `cloudsaver_tenant_id` mapper. Access tokens must be RS256 bearer tokens with a `kid`, UUID subject and a lifetime no longer than five minutes. An ID token cannot authenticate API access.

The verifier service identity needs the deployment-specific read permissions to introspect tokens and read users, their group memberships, effective client roles, and the registered group. Grant no user/group/role-management permission to CloudSaver. Test fine-grained administrative permissions against the selected Keycloak version before rollout; a broad `realm-admin` grant is not a requirement. Protect the resource client and tenant group from delegated edits that could grant access to another client.

The registered group has exactly one `cloudsaver_license` attribute value containing JSON:

```json
{
  "schema_version": 1,
  "enabled": true,
  "expires_at": "2026-12-31T23:59:59Z",
  "plan": {
    "code": "ENTERPRISE",
    "name": "Enterprise",
    "entitlements_version": 1,
    "billing_state": "none",
    "entitlements": {
      "max_subscriptions": 10,
      "max_resources_per_scan": 2500,
      "allowed_providers": ["azure"],
      "allowed_scan_frequencies": ["manual", "daily"],
      "can_export_terraform": true,
      "can_use_keyvault": true,
      "can_dispatch_automated_alerts": false,
      "can_use_ai_advisory": false,
      "retention_days": 90
    }
  }
}
```

Only authorized licensing administrators may edit this group attribute. User profile attributes, request bodies and token role/plan claims do not supply license authority. Each API authorization verifies the JWT, live introspection, enabled user, current direct membership of the registered group, current effective resource-client roles and the current group license. Only the existing `Viewer`, `BillingAdmin` and `TenantAdmin` roles are accepted. Administrative service tokens may be cached for at most 30 seconds; user membership, roles and license results are not cached. Identity timeouts, missing/malformed license records and revoked/expired access fail closed. Responses and logs do not contain credential values or provider errors.

Billing/observability workers refresh the current license before collection and refresh current scope before committing. Scan workers check the license and configured scope at dispatch and before publication. Background collection uses an operator-configured tenant collection grant, not a stored browser access token. The current scan queue does not persist a Keycloak initiating-principal grant; per-user job revocation and delegated resource-level role bindings are further work. Service accounts remain non-human and cannot become independent human approvers.

Keycloak stores and enforces the licensing decision in this mode; it does not calculate invoices, accept payments, count seats or determine financial settlement. CloudSaver enforces resource/provider/feature limits using the validated record. If commercial billing is required, a reviewed billing integration must update the protected decision through the organization's licensing process. An expired license blocks API access; define a separate administrative recovery/export process before customer rollout.

The dashboard identifies Keycloak-managed access and stops using its legacy user/key-management forms for those sessions. The existing bearer-credential connection form can use a properly issued Keycloak access token. A browser authorization-code/PKCE login, refresh-token session, logout/backchannel integration, customer account-console links and migration of existing platform identities are **not implemented by this change**. Keep the legacy operator portal available until a separate reviewed migration replaces its remaining provisioning, billing and knowledge-management responsibilities. Do not switch production authentication modes without a tested rollout and recovery path.

Azure's Entra tenant ID may now be registered separately as `identity.azure_tenant_id`; a CloudSaver/Keycloak workspace UUID no longer has to be the Azure directory ID. Cloud federation, execution identities and native cloud IAM remain independent of Keycloak application access.

## Provider requests and freshness

`app/provider_retry.py` supplies bounded retries for JSON GET reads and explicitly classified read-only POST queries. It is used by shared cloud HTTP readers, Azure billing, BigQuery billing, commitment HTTP reads and observability reads. Mutations never use this retry path. AWS SDK callers keep their existing bounded SDK retry policy; they are not represented as participating in Redis admission control.

Configure the same `CLOUDSAVER_PROVIDER_REDIS_URL` for every collector replica; it falls back to `REDIS_URL`. Redis uses its own time and an atomic admission/cooldown operation. Production fails closed when coordination is unavailable. The process-local implementation is for development only. Keys group subscription/project reads or registered endpoint hosts; observability keys include workspace and host. A shared upstream account with several host names or credentials may require a more specific provider quota hierarchy before production acceptance.

The default HTTP read policy allows three attempts within a 30-second budget, with bounded response bodies, no redirects, and jittered delay for 429/502/503/504 and transient transport failures. Numeric and HTTP-date `Retry-After`, `x-ms-retry-after-ms` and `retry-after-ms` are respected. Long delays return a typed deferral without sleeping past the request budget. Error bodies are closed unread. Invalid JSON, size limits, authentication failures and other permanent rejections are not retried. BigQuery query submission allows one attempt because a retried query can incur another bill; it no longer incorrectly requires an Azure subscription argument.

Azure Cost Management requests share a subscription pacing budget, initially 15 seconds between calls, configurable with `CLOUDSAVER_AZURE_COST_INTERVAL_SECONDS` (0–60). This is a conservative starting setting, not a provider quota guarantee. Fixed one-minute sleeps between successful pages and cost kinds are removed. Continuations must retain the exact subscription/query endpoint and cannot repeat. A per-resource response with a continuation is rejected as incomplete instead of silently accepting its first page.

Billing deferrals retain the current scope, record `next_retry_at` and `BILLING_PROVIDER_THROTTLED`, release the lease and remain queued until due. They do not commit partial cost lines. Cancellation still works while waiting. Each scope permits five deferrals before an explicit failed result. The existing six-hour job lifetime remains. Current billing retries restart the unfinished scope; durable per-page checkpoints and incremental export ingestion remain expansion work. Observability records a throttle failure code and is retried by its configured schedule; it does not yet have the billing job's per-attempt deferred scheduling contract.

No collector can guarantee that a provider will never return 429 or delay observations. To establish a customer freshness SLO, agree separately on inventory age, metric lag/window coverage, billing export delay and allowed incompleteness. Measure provider-observed time, collection time, last complete run, queue age, retry delay and authorized scope. Alert on age and persistent deferrals before the agreed limit. Failed/partial runs preserve stale or unknown evidence; a new request time does not make old evidence fresh. The Overview and engineering checks display evidence limitations and never replace gaps with zero. `/api/v1/providers` publishes the HTTP collection policy and its acceptance boundary.

For higher-volume estates, the next collection changes are service-specific quota partitions, batched metrics where the documented operation supports them, authenticated change events plus periodic full reconciliation, durable page/export cursors, and query-cardinality budgets. These require independent acceptance per operation. No generic event subscription or provider-wide completeness is claimed.

## Service probes

| Service | Liveness | Readiness |
| --- | --- | --- |
| FastAPI core and shared API services/gateway | `/health/live`; no provider or database calls | `/health/ready` (alias `/readyz`); bounded configured DB/Redis/upstream checks |
| Legacy platform identity | `/health/live` (alias `/healthz`) | `/health/ready` (alias `/readyz`); existing database check |
| Customer Next.js dashboard | `/health/live` | `/health/ready`; gateway readiness with a three-second timeout |
| Legacy operator Next.js portal | `/health/live` | `/health/ready`; identity readiness with a three-second timeout |
| Governance, retention, billing, observability and delivery workers | Port 8099 `/health/live`; polling progress must remain within its worker bound | Port 8099 `/health/ready`; successful recent iteration, with failures reported unavailable |
| Celery scan worker and beat | Port 8099 `/health/live`; actual consumer heartbeat/scheduler progress | Port 8099 `/health/ready`; recent progress and bounded Redis ping |
| TypeScript agent worker | Port 8099 `/health/live`; event loop and recent gateway progress | Port 8099 `/health/ready`; successful gateway interaction, false on stopping/failure |
| External Keycloak | Native management `/health/live` | Native management `/health/ready`, normally port 9000; enable Keycloak health when building it |

Worker probe ports are internal, not published by Compose. Use `CLOUDSAVER_WORKER_HEALTH_HOST` and `CLOUDSAVER_WORKER_HEALTH_PORT` only when changing the deployment. Configure Kubernetes/Container Apps startup allowance separately from readiness and liveness; dependency failures should remove traffic rather than cause a restart loop. Billing currently permits a long polling-progress bound aligned with its existing long lease; per-page progress instrumentation is still needed for rapid hang detection during very large collections. Health does not establish provider completeness, entitlement correctness or cloud sandbox acceptance. PostgreSQL/Redis retain their native probes. Migration containers are one-shot completion gates.

## Official references reviewed for this increment

- [Keycloak OIDC endpoints](https://www.keycloak.org/securing-apps/oidc-layers).
- [Keycloak Admin REST API](https://www.keycloak.org/docs-api/latest/rest-api/index.html): user, group membership, group representation and effective client-role mappings; `client-id` in the role URL means the internal UUID.
- [Keycloak health configuration](https://www.keycloak.org/observability/health).
- [Azure Resource Manager throttling](https://learn.microsoft.com/en-us/azure/azure-resource-manager/management/request-limits-and-throttling).

Review date: 2026-10-29. Exact deployment permissions, regional endpoints, quotas, source retention and throughput still require an authorized sandbox. See [the engineering implementation record](ENGINEERING_INCREMENT.md) for local verification and remaining gates.
