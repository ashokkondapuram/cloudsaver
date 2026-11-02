# Deployment environment reference (Compose, Container Apps, Helm)

Use this with [ENVIRONMENT.md](ENVIRONMENT.md) (local `.env` generation) and the external deployment repos:

| Deployment | Repository | Secrets | Non-secret config |
| --- | --- | --- | --- |
| Docker Compose | `ashokkondapuram/cloudsaver` | Root `.env` + `platform/.env` | `compose.yaml` anchors |
| Azure Container Apps | [cloudsaver-containerapps](https://github.com/ashokkondapuram/cloudsaver-containerapps) | Azure Key Vault (`secretNames` + `extraSecrets`) | `backendConfig` in `production.json` |
| Kubernetes / AKS | [cloudsaver-helm](https://github.com/ashokkondapuram/cloudsaver-helm) | Kubernetes Secrets (`runtimeSecret`, `identitySecret`, …) | Helm `values.config` ConfigMap |

**Application target:** CloudSaver **1.8.1** (pin immutable image digests in ACA/Helm; tags alone are not sufficient for production).

---

## 1. Secret-backed variables (never in ConfigMap / `backendConfig`)

| Variable | Value contract | Compose | Container Apps KV key | Helm runtime secret key |
| --- | --- | --- | --- | --- |
| `CLOUDSAVER_DATABASE_URL` | `postgresql://cloudsaver_app:…` TLS verify-full | Composed in compose | `cloudDatabaseUrl` | `database-url` |
| `CLOUDSAVER_MIGRATION_URL` | Postgres schema owner DSN | Migration job only | `cloudMigrationUrl` | `cloudsaver-migration` / `database-url` |
| `REDIS_URL` | Gateway: logical **DB 0**; workers: logical **DB 1** | Per-service in compose | `cloudRedisGatewayUrl` / `cloudRedisWorkerUrl` | `redis-gateway-url` / `redis-worker-url` |
| `CLOUDSAVER_PROVIDER_REDIS_URL` | Same URL as worker `REDIS_URL` (DB 1) when set | `redis://redis:6379/1` | Bind same KV secret as worker Redis to each Python workload | Duplicate `redis-worker-url` mapping (Helm template) |
| `CLOUDSAVER_IDENTITY_TOKEN` | Random caller token per service | `CLOUDSAVER_IDENTITY_TOKEN_*` in `.env` | `*CallerToken` per workload | `gateway-token`, `scanner-token`, … |
| `CLOUDSAVER_ENGINEERING_CURSOR_KEY` | ≥32 bytes hex; rotating invalidates engineering cursors | Root `.env` (required in production) | `extraSecrets` → `CLOUDSAVER_ENGINEERING_CURSOR_KEY` | `secretEnv` or `engineering-cursor-key` in runtime secret |
| `CLOUDSAVER_GITHUB_APP_PRIVATE_KEY` | PEM for GitOps | Private override | `extraSecrets` on `scanner` | `components.*.secretEnv` |
| `CLOUDSAVER_DRIFT_WEBHOOK_SECRET` | HMAC for drift ingress | `.env` | `extraSecrets` on `gateway` | `secretEnv` on gateway |
| `CLOUDSAVER_EVIDENCE_KEY_OUTCOMES` | ≥32 chars; core only | `.env` | `extraSecrets` on `scanner` | `secretEnv` |
| `CLOUDSAVER_GOVERNANCE_KEY_PRIMARY` | ≥32 chars; core + monitor | `.env` | `extraSecrets` on `scanner` | `secretEnv` |
| `CLOUDSAVER_WEBHOOK_*` | HTTPS webhook URLs | `.env` | `extraSecrets` on worker/dispatcher | `secretEnv` |
| `PLATFORM_IDENTITY_DATABASE_URL` | `identity_app` DSN | `platform/.env` | `identityDatabaseUrl` | `platform-identity` / `database-url` |
| `PLATFORM_REDIS_URL` | Identity Redis | `PLATFORM_REDIS_URL` | `identityRedisUrl` | `redis-url` |
| `PLATFORM_KEY_PEPPER` | ≥32 byte hex | `PLATFORM_DB_PASSWORD` pepper | `workspaceKeyPepper` | `key-pepper` |
| `PLATFORM_IDENTITY_CALLERS` | JSON SHA-256 digests of caller tokens | `PLATFORM_IDENTITY_CALLERS` | `identityCallerDigests` | `caller-digests` |
| `PLATFORM_PORTAL_TOKEN` | Portal caller token | `PLATFORM_PORTAL_TOKEN` | `portalCallerToken` | `caller-token` |
| `PORTAL_ENTRA_CLIENT_SECRET` | Entra app secret | `platform/.env` | `portalEntraClientSecret` | `entra-client-secret` |

Platform migration DSN: `PLATFORM_IDENTITY_MIGRATION_URL` / KV `identityMigrationUrl` / `platform-migration` secret.

---

## 2. Structural variables (set by deployment templates)

These are injected by Compose anchors, ACA `main.bicep`, or Helm ConfigMap `$fixed` merges. Do **not** put them in `backendConfig` or Helm `values.config` overrides (validators reject overrides in ACA).

| Variable | Production value | Purpose |
| --- | --- | --- |
| `CLOUDSAVER_ENVIRONMENT` | `production` | Refuses dev-only auth paths |
| `CLOUDSAVER_MODE` | `azure` | Product mode |
| `CLOUDSAVER_AUTH_MODE` | `workspace` or `entra` | API authentication |
| `CLOUDSAVER_TENANT_REGISTRY` | `database` | Postgres workspace registry |
| `CLOUDSAVER_TENANTS` | `[]` | Bootstrap only; portal owns workspaces |
| `CLOUDSAVER_KEY_VERIFIER` | `identity` | Workspace key verification |
| `CLOUDSAVER_DIRECTORY_MODE` | `cutover` | Directory projector |
| `CLOUDSAVER_PROVIDER_SCOPED_KEYS` | `true` | Provider-limited keys |
| `CLOUDSAVER_CLOUD_IDENTITY` | `managed_identity` | Keyless cloud reads |
| `CLOUDSAVER_DISTRIBUTED_SCAN_LOCK` | `true` | Redis scan leases |
| `CLOUDSAVER_IDENTITY_URL` | Platform identity internal URL | All Python services |
| `CLOUDSAVER_TRUSTED_CALLERS` | `''` on gateway; service list elsewhere | Internal auth |
| `CLOUDSAVER_TRUSTED_PROXIES` | Dashboard hostname / ACA proxy CIDRs | Client IP trust |
| `SCANNER_SERVICE_URL` / `TENANT_SERVICE_URL` / … | Internal ACA/K8s URLs | Gateway routing |
| `API_GATEWAY_URL` | Gateway URL | Dashboard only |
| `AZURE_CLIENT_ID` | Scanning user-assigned MI client ID | Scanner + worker (ACA attaches MI) |
| `PLATFORM_ENVIRONMENT` | `production` | Platform safety |
| `PLATFORM_PORTAL_AUTH` | `entra` | Portal sign-in |
| `PLATFORM_OPERATOR_TENANT_ID` | Entra tenant UUID | Workforce operator tenant |
| `PLATFORM_IDENTITY_AUDIENCE` | Access token audience | Identity API |
| `PLATFORM_PROVIDER_SCOPED_KEYS` | `true` | Matches CloudSaver |
| `PLATFORM_BILLING_ENABLED` | `false` until billing path verified | Stripe/manual |
| `PLATFORM_BILLING_PROVIDER` | `manual` | Billing backend |

---

## 3. Feature flags (deployment + portal)

| Variable | Default (prod template) | When `true` |
| --- | --- | --- |
| `CLOUDSAVER_SCHEDULED_SCANS` | `false` | Requires scan worker + scheduler + dispatcher (ACA `workers.*`) |
| `CLOUDSAVER_AUTOMATED_ALERTS` | `false` | Requires `CLOUDSAVER_DELIVERY_ENABLED=true` |
| `CLOUDSAVER_INTERACTIVE_JOBS` | `false` | Requires scan worker + dispatcher |
| `CLOUDSAVER_DELIVERY_ENABLED` | `false` | Notification delivery dispatcher |
| `CLOUDSAVER_AI_ENABLED` | `false` | AI advisory + data governance |
| `CLOUDSAVER_GITOPS_PUBLISH` | `false` | GitHub App draft PRs |
| `CLOUDSAVER_PLATFORM_OUTBOX_DISPATCH` | `false` | Celery drift/GitOps outbox (`0033` migration) |
| `CLOUDSAVER_FINOPS_AUTOPILOT` | `false` | `/api/v1/finops/autopilot/*` |
| `CLOUDSAVER_AGENT_ENABLED` | `false` | Agent execution worker |

Helm: map booleans under `features:` in `values.yaml`. ACA: `features` and `workers` objects in `production.json`.

---

## 4. Operator `backendConfig` / `values.config` (safe to tune)

Recommended defaults for **1.8.1** (also in ACA `examples/production.json` and Helm `values.yaml`):

| Variable | Example value | Notes |
| --- | --- | --- |
| `CLOUDSAVER_DB_POOL_SIZE` | `2` | Per process |
| `CLOUDSAVER_DB_MAX_OVERFLOW` | `3` | |
| `CLOUDSAVER_DB_POOL_TIMEOUT` | `5` | Seconds |
| `CLOUDSAVER_DB_POOL_RECYCLE` | `1800` | Seconds |
| `CLOUDSAVER_IDENTITY_CACHE_SECONDS` | `15` | 0–30 |
| `CLOUDSAVER_SCHEDULER_TICK_SECONDS` | `300` | Scheduler beat |
| `CLOUDSAVER_AI_HOURLY_ATTEMPTS` | `10` | AI budget |
| `CLOUDSAVER_AI_BATCH_TICK_SECONDS` | `30` | Worker batching |
| `CLOUDSAVER_AZURE_COST_INTERVAL_SECONDS` | `15` | Cost API cooldown |
| `CLOUDSAVER_DIRECTORY_MAX_LAG_SECONDS` | `30` | Directory freshness |
| `CLOUDSAVER_AUTO_BILLING_SYNC` | `true` | Disable if billing not granted |
| `CLOUDSAVER_COMMITMENT_SYNC` | `true` | Reservation/SP reads |
| `CLOUDSAVER_LIVE_EVIDENCE_ENABLED` | `false` | Expensive live metrics |
| `CLOUDSAVER_LIVE_EVIDENCE_MAX_RESOURCES` | `25` | Cap per scan |
| `CLOUDSAVER_AI_TARGETS` | `[]` | JSON advisory targets |
| `CLOUDSAVER_GITOPS_TARGETS` | `[]` | JSON repo bindings |
| `CLOUDSAVER_PLAN_POLICY` | `{}` | Terraform guardrails JSON |
| `CLOUDSAVER_NOTIFICATION_TARGETS` | `[]` | Delivery routing JSON |
| `CLOUDSAVER_BILLING_CONNECTORS` | `[]` | Workspace billing scopes |
| `CLOUDSAVER_KUBERNETES_BINDINGS` | `[]` | K8s federation |
| `CLOUDSAVER_REGIONAL_PRICE_CATALOG` | `[]` | USD meter catalog |
| `CLOUDSAVER_AZURE_ACCESS` | `federated` | Azure token exchange |
| `CLOUDSAVER_AZURE_APP_CLIENT_ID` | `<app-id>` | Federated Azure |
| `CLOUDSAVER_AWS_HUB_ROLE_ARN` | `arn:aws:iam::…` | AWS hub role |
| `CLOUDSAVER_GCP_WORKLOAD_PROVIDER` | `//iam.googleapis.com/…` | GCP WIF provider |
| `CLOUDSAVER_ENTRA_AUDIENCE` | `<api-app-id>` | When `CLOUDSAVER_AUTH_MODE=entra` |
| `CLOUDSAVER_ENTRA_ACCESS_POLICY` | JSON policy | Entra app-role gate |
| `CLOUDSAVER_GITOPS_AST_INDEX` | `{}` | Resource→repo map (or use AST sync API) |
| `CLOUDSAVER_GITOPS_AST_INDEX_FROM_GITHUB` | `false` | Index from GitHub App |
| `CLOUDSAVER_DRIFT_INGEST_URL` | Public gateway URL | EventGrid/EventBridge wiring |
| `CLOUDSAVER_SEMANTIC_EMBEDDINGS_PIPELINE` | `false` | pgvector backfill job |

Empty JSON arrays `{}` / `[]` are valid “disabled” values.

---

## 5. Container Apps–specific

- **Config file:** `examples/production.json` validated by `scripts/configuration.py`.
- **Structural env:** `infra/main.bicep` `cloudBaseEnv` + per-app secrets.
- **Extra integrations:** `extraSecrets[]` with `workload`, `appSecretName`, `keyVaultSecretName`, `envName`.
- **Engineering cursors (required in prod):** bind KV secret to `analytics`, `scanner`, and `gateway` workloads:

```json
{
  "workload": "analytics",
  "appSecretName": "engineering-cursor-key",
  "keyVaultSecretName": "csprod-engineering-cursor-key",
  "envName": "CLOUDSAVER_ENGINEERING_CURSOR_KEY"
}
```

- **Application gate:** set `application.sourceRevision` to the tested Git SHA and fill `application.acceptanceRecord` before `deployRuntime=true` (see containerapps `docs/COMPATIBILITY.md`).

---

## 6. Helm-specific

- **Charts:** `charts/cloudsaver` (Python + dashboard + workers), `charts/cloudsaver-platform` (identity + portal).
- **Runtime secret keys:** `examples/secrets/cloudsaver-runtime.env.example` → Kubernetes Secret.
- **Per-component secrets:** `components.<name>.secretEnv` in values (engineering cursor, webhooks, governance keys).
- **Provider Redis:** chart template sets `CLOUDSAVER_PROVIDER_REDIS_URL` from the same key as worker `REDIS_URL`.
- **Production example:** `values-production.example.yaml` (update host, Entra IDs, image registry).

---

## 7. Verification commands

```bash
# Application (from cloudsaver repo)
python3 scripts/setup_compose.py --caller-digests   # after editing .env tokens

# Container Apps repo
python3 -m pytest -q tests
python3 scripts/deploy.py validate examples/production.json

# Helm repo
python3 scripts/test_charts.py
helm template cloudsaver charts/cloudsaver -f charts/cloudsaver/values-production.example.yaml
```

---

## 8. Related application docs

- [ENVIRONMENT.md](ENVIRONMENT.md) — full Compose / platform `.env` catalog  
- [releases/1.8.1-UPGRADE.md](releases/1.8.1-UPGRADE.md) — current release; migration head still `0033`  
- [releases/1.8.0-UPGRADE.md](releases/1.8.0-UPGRADE.md) — backend reliability baseline  
- [ENGINEERING_INCREMENT.md](ENGINEERING_INCREMENT.md) — engineering API + zero-downtime policy  
- [FINOPS_ANALYSIS_VERIFICATION.md](FINOPS_ANALYSIS_VERIFICATION.md) — analysis and agent workflow channels  
- [RESOURCE_ANALYSIS_RULES.md](RESOURCE_ANALYSIS_RULES.md) — every rule evaluated per resource type (generated catalog matrix)
- [ANALYSIS_RULES_MASTER.md](ANALYSIS_RULES_MASTER.md) — evidence, pillars, tiers, and action paths for all catalog rules
- [RULE_MATCHING_STRATEGY.md](RULE_MATCHING_STRATEGY.md) — Turbonomic-style primary match and overlap policy
- [FINOPS_RESIZE_METRICS.md](FINOPS_RESIZE_METRICS.md) — resize metrics API (`GET /api/v1/finops/autopilot/resize-metrics`)
