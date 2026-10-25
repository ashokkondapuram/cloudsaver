# Scanning and analysis rules

A scan reads your configured Azure subscriptions, AWS accounts, GCP projects and Kubernetes clusters with read-only credentials, builds a canonical inventory, evaluates every in-scope resource against a versioned rule catalog, and saves one immutable scan result with findings, rule outcomes, coverage and evidence provenance. Scans never receive cloud identifiers, roles, URLs or tokens from the request: you only choose which configured providers to include. Costs are attributed only from exact price evidence, so a finding without verified pricing keeps an unknown savings value instead of an estimate.

Last reviewed: Oct 25, 2026.

## Where to find it

- **Run a scan**: the scan action in the dashboard header calls `runScan` in [web-dashboard/components/WorkspaceProvider.tsx](../../web-dashboard/components/WorkspaceProvider.tsx), which posts the selected providers to `/api/v1/scans/multi-cloud`.
- **Scan results**: Overview, Resources, Workloads and Kubernetes views read the latest scan from `/api/v1/scans`.
- **Rules**: Settings > Analysis rules (see [settings.md](settings.md)).
- **Scan schedule**: Settings > Cloud & schedule.
- **Backend**: [app/main.py](../../app/main.py) (`perform_scan`), [app/multi_cloud.py](../../app/multi_cloud.py), the `app/scanner*.py` modules, [app/jobs_api.py](../../app/jobs_api.py) and the Celery worker in [workers/tasks.py](../../workers/tasks.py).

## What you can do

- Run a synchronous scan across one or more configured providers (`azure`, `aws`, `gcp`, `kubernetes`).
- Run an Azure-only scan of every configured subscription.
- Queue an asynchronous scan job and poll its status, when interactive jobs are enabled.
- Review scan history (up to 100 scans), trends over 1 to 365 days, and per-scan coverage.
- Download a review-only remediation shell script or a Terraform file for selected resources.
- Enable or disable rules and tune bounded rule parameters, if your platform operator allows it.
- Turn on scheduled scans, when your plan and the platform allow them.

## How it works

### Scan pipeline

`perform_scan` in [app/main.py](../../app/main.py) runs these steps:

1. **Authorization and quotas**: requires `TenantAdmin`, then enforces the plan's providers and scope quota (`enforce_providers`, `enforce_subscription_quota` in [app/entitlements.py](../../app/entitlements.py)).
2. **Concurrency**: a per-workspace lock returns 409 "A scan is already running for this workspace". With `CLOUDSAVER_DISTRIBUTED_SCAN_LOCK=true`, a Redis lease (`RedisLease`) and `LeaseHeartbeat` extend the lock across API replicas.
3. **Rule policy**: `policy_for_tenant` in [app/effective_rules.py](../../app/effective_rules.py) loads the workspace's effective rules from identity-service. Key-authenticated callers fail closed with "Analysis policy is unavailable; no scan was saved." when the policy can't be read.
4. **Collection**: `scan_multi_cloud` for a provider list, or `scan_live` in [app/scanner.py](../../app/scanner.py) for the Azure-only route.
5. **Validation**: `enforce_resource_quota`, then `validate_finding_scope` rejects any finding outside your configured scopes.
6. **Pricing**: `attribute_finding_cost` in [app/pricing.py](../../app/pricing.py).
7. **Inventory and provenance**: `canonical_inventory` and `group_opportunities` in [app/dependencies.py](../../app/dependencies.py); `compact` in [app/collectors/provenance.py](../../app/collectors/provenance.py) builds the source ledger.
8. **Rule evaluation**: `evaluate_inventory` in [app/analysis_rules.py](../../app/analysis_rules.py), with policies for the Azure rules, Kubernetes rules and catalog definitions. `materialize` in [app/multicloud_rules.py](../../app/multicloud_rules.py) turns detected outcomes into findings.
9. **Coverage**: `coverage` and `coverage_manifest` in [app/inventory.py](../../app/inventory.py); `completed_scopes` in [app/scan_scope_manifest.py](../../app/scan_scope_manifest.py).
10. **Save**: the result is validated as `ScanSummary` and stored.

A `ScanError` returns 422 with a short reason. Any other failure returns 502 "Scan failed. Check cloud credentials, cloud account access and server configuration". Nothing is saved for a failed scan.

### Multi-cloud collection

[app/multi_cloud.py](../../app/multi_cloud.py):

- Runs one collection task per configured scope in a thread pool of at most 4 workers.
- Any scope failure aborts the whole scan; partial results aren't saved.
- Caps a scan at 100,000 findings and 100,000 resources and rejects duplicate findings.
- Credentials come from [app/cloud_identity.py](../../app/cloud_identity.py):
  - **Azure**: a platform managed identity (`ManagedIdentityCredential`).
  - **AWS**: assumes the configured reader role with the workspace tenant ID as the external ID. The caller account must match the configured account.
  - **GCP**: impersonates the workspace's `gcp_service_account` identity.
  - **Kubernetes**: an approved tenant binding in `CLOUDSAVER_KUBERNETES_BINDINGS` uses the federated collector ([app/collectors/federation.py](../../app/collectors/federation.py), [app/collectors/kubernetes.py](../../app/collectors/kubernetes.py)); otherwise `scan_cluster` in [app/scanner_kubernetes.py](../../app/scanner_kubernetes.py) reads Prometheus with the bearer token from the environment variable named by the cluster's `bearer_token_env`.

### Provider coverage

| Provider | Module | Inventory and detections |
| --- | --- | --- |
| Azure | [app/scanner.py](../../app/scanner.py) | Azure Resource Graph queries: `ORPHANED_DISK`, `UNASSOCIATED_PUBLIC_IP`, `STOPPED_VM`, `EMPTY_APP_SERVICE_PLAN`, `ORPHANED_NIC`, `ORPHANED_NSG`, `IDLE_APP_GATEWAY`. Pages of 1,000 rows; an incomplete page set fails the scan. |
| AWS | [app/scanner_aws.py](../../app/scanner_aws.py) | EC2 and RDS read-only APIs: `AWS_UNATTACHED_EBS`, `AWS_UNASSOCIATED_EIP`, `AWS_IDLE_RDS` |
| GCP | [app/scanner_gcp.py](../../app/scanner_gcp.py) | Compute and Cloud SQL: `GCP_UNATTACHED_DISK`, `GCP_UNASSIGNED_ADDRESS`, `GCP_IDLE_CLOUD_SQL` (with Cloud Monitoring evidence) |
| Kubernetes | [app/collectors/federation.py](../../app/collectors/federation.py), [app/scanner_kubernetes.py](../../app/scanner_kubernetes.py) | Pods, nodes, namespaces, workloads, autoscalers, disruption budgets, volumes, storage classes, services and endpoint slices from the Kubernetes API, with a 14-day (336-hour) Prometheus window and optional OpenCost allocations |

`GET /api/v1/providers` reports your configured providers, `execution: read_only_synchronous` and `kubernetes_window_days: 14`.

### Rule catalog

- **Azure analysis rules** ([app/analysis_rules.py](../../app/analysis_rules.py), version 1.4.0). Parameters are bounded:

| Rule | Parameter | Default (range) |
| --- | --- | --- |
| `AZURE_DISK_UNATTACHED_RETENTION` | `minimum_days` | 14 (7 to 90) |
| `AZURE_DISK_PROVISIONED_PERFORMANCE` | `headroom_percent` | 30 (20 to 100) |
| `AZURE_PUBLIC_IP_UNASSOCIATED` | `minimum_days` | 7 (7 to 90) |
| `AZURE_PUBLIC_IP_ASSOCIATED_IDLE` | `maximum_bytes` | 0 (0 to 1,024) |
| `AZURE_VM_STOPPED_RESIDUAL_COST` | `minimum_days` | 14 (7 to 90) |
| `AZURE_VM_RIGHTSIZING_UTILIZATION` | `cpu_percent` | 10 (1 to 20) |
| `AZURE_ASP_EMPTY_PAID_PLAN` | `minimum_days` | 7 (7 to 90) |
| `AZURE_ASP_UNDERUTILIZED_SKU` | CPU and memory percent | 15 (1 to 30) and 30 (1 to 40) |

- **Kubernetes rules** ([app/kubernetes_rules.py](../../app/kubernetes_rules.py), version `kubernetes-2026-10-24.1`), 10 rules: `K8S_CONTAINER_CPU_OVERREQUEST`, `K8S_CONTAINER_MEMORY_OVERREQUEST`, `K8S_CONTAINER_UNDERPROVISIONED_RISK`, `K8S_HPA_PDB_CONFLICT_OR_IDLE_FLOOR`, `K8S_NODE_POOL_FRAGMENTATION_WASTE`, `K8S_ABANDONED_WORKLOAD_OR_NAMESPACE`, `K8S_PVC_UNMOUNTED_OR_LOW_OCCUPANCY`, `K8S_STATEFULSET_SIZING_AND_VOLUME_TEMPLATE`, `K8S_DAEMONSET_CLUSTER_WIDE_OVERHEAD_TAX`, `K8S_ORPHANED_LOADBALANCER_SERVICE`. These rules have no tunable parameters.
- **Resource catalog** ([app/resource_catalog.py](../../app/resource_catalog.py), version 1.4.0): resource families for Azure, AWS, GCP and Kubernetes, each mapped to rule IDs. `definitions()` derives catalog rule definitions and their delegated parameter bounds.
- **Multi-cloud rules** ([app/multicloud_rules.py](../../app/multicloud_rules.py)): conservative conditions per family, with an SLO gate that blocks savings findings where reliability evidence is missing or at risk.

Every evaluated rule records one of these outcomes: `condition_detected`, `condition_not_detected`, `insufficient_evidence`, `not_applicable`, `disabled_by_policy`, `excluded_by_exception`, `unsupported_by_collector`, `evaluation_failed`.

### Live evidence enrichment

When `CLOUDSAVER_LIVE_EVIDENCE_ENABLED=true`, provider collectors add read-only telemetry for up to `CLOUDSAVER_LIVE_EVIDENCE_MAX_RESOURCES` resources per scope:

- [app/collectors/azure_live.py](../../app/collectors/azure_live.py): Azure Monitor metrics, Activity Log, protection guards and backup state.
- [app/collectors/aws_live.py](../../app/collectors/aws_live.py): CloudWatch metrics, CloudTrail activity and additional inventory.
- [app/collectors/gcp_live.py](../../app/collectors/gcp_live.py): Cloud Asset Inventory, Cloud Monitoring and audit logs.

Each source is recorded in the source ledger as available or unavailable. Missing telemetry yields `insufficient_evidence`, not a finding.

### Pricing

[app/pricing.py](../../app/pricing.py):

- `AzurePricingClient` queries the Azure Retail Prices API (`prices.azure.com`) and accepts only an exact, unambiguous match on region, SKU, meter, product and meter ID for USD consumption pricing in the primary region. Ambiguous or missing matches return no price.
- `regional_attribution` uses an operator-reviewed catalog from `CLOUDSAVER_REGIONAL_PRICE_CATALOG`. Entries must come from approved source hosts and have been reviewed within 90 days; monthly values use a 730-hour model.
- Without exact evidence, `estimated_monthly_waste_usd` stays `null` and the opportunity is reported as unknown.

### Scan jobs and scheduled scans

- **Interactive jobs** ([app/jobs_api.py](../../app/jobs_api.py)): `POST /api/v1/scan-jobs` returns 202 with a job ID. It needs a PostgreSQL store, `CLOUDSAVER_INTERACTIVE_JOBS=true` and `CLOUDSAVER_DELIVERY_ENABLED=true`. The body has either `subscription_ids` or `providers` (not both) and an `idempotency_key`. Status responses include `Retry-After: 3`.
- **Scheduler** ([workers/tasks.py](../../workers/tasks.py)): Celery Beat runs `scheduled_scan_all` every `CLOUDSAVER_SCHEDULER_TICK_SECONDS`. For each workspace with an active interval (hourly or daily, from [app/operations.py](../../app/operations.py)), it reserves an outbox job with `reserve_scheduled_job`; [workers/dispatcher.py](../../workers/dispatcher.py) publishes committed jobs to the broker.
- **Worker**: `execute_subscription_scan` verifies the job matches its durable delivery intent, runs the scan and sends alerts if enabled. Transient failures retry up to 3 times with backoff (at most 300 seconds). Scope authorization failures are permanent and never retried.
- Other beat tasks: hourly cloud billing sync (`CLOUDSAVER_AUTO_BILLING_SYNC`) and AI batch processing (`CLOUDSAVER_AI_ENABLED`).

## API reference

| Method | Path | Purpose | Required role/scope |
| --- | --- | --- | --- |
| GET | `/api/v1/providers` | Configured providers and execution mode | Any role; `agnostic` |
| GET | `/api/v1/scans` | Scan history (`limit` 1 to 100, default 50) | Any role; `scoped_read` |
| GET | `/api/v1/scans/{scan_id}` | One scan result | Any role; `scoped_read` |
| GET | `/api/v1/trends` | Savings and finding trends (`days` 1 to 365) | Any role; `scoped_read` |
| POST | `/api/v1/scans` | Azure-only synchronous scan (201) | `TenantAdmin`; key must allow Azure |
| POST | `/api/v1/scans/multi-cloud` | Synchronous scan of selected providers (201) | `TenantAdmin`; key must allow each provider (`body`) |
| POST | `/api/v1/scans/{scan_id}/cancel` | Always returns 409: synchronous scans can't be cancelled | `TenantAdmin`; `scan_write` |
| POST | `/api/v1/scans/{scan_id}/remediation` | Review-only remediation shell script | `TenantAdmin`; `scan_write` |
| POST | `/api/v1/scans/{scan_id}/remediation-terraform` | Terraform file for selected resources (plan-gated) | `TenantAdmin`; `scan_write` |
| POST | `/api/v1/scan-jobs` | Queue an asynchronous scan (202) | `TenantAdmin`; `body` |
| GET | `/api/v1/scan-jobs` | List scan jobs | Any role; `full_scope` |
| GET | `/api/v1/scan-jobs/{job_id}` | Scan job status | Any role; `full_scope` |

## Data and evidence

A saved scan (`ScanSummary`) includes:

- `scan_id`, `timestamp`, `status`, `mode`, `cloud_providers` and a `scope_fingerprint`.
- `findings` with rule ID, severity, provider, scope, region, resource identity, evidence and cost attribution.
- `inventory`: every collected resource, including those without findings.
- `rule_evaluations`: one outcome per rule and resource.
- `rule_manifest`: rule version, enabled rule IDs, workspace policy version, policies and `policy_source` (`identity` or `local_catalog`).
- `coverage` and `coverage_manifest`: discovered, evaluated, insufficient-evidence, excluded and unsupported counts, per provider and service.
- `scope_results`: per-scope completion and supported resource types.
- `source_ledger`: provenance for every collector source.
- `total_monthly_waste_usd`, `realizable_monthly_savings_usd` and `opportunity_summary`.

## Permissions

- Running scans, queuing jobs and exporting remediation require `TenantAdmin`.
- Reading scans, trends and providers needs any workspace role. Provider- or scope-restricted keys see only their providers and scopes.
- Scan job history is `full_scope`: restricted keys can't read it.

## Configuration

| Variable | Purpose | Default |
| --- | --- | --- |
| `CLOUDSAVER_MODE` | Compatibility setting; must be `azure` | `azure` |
| `CLOUDSAVER_DISTRIBUTED_SCAN_LOCK` | Use a Redis lease to serialize scans across replicas | Unset (off) |
| `REDIS_URL` | Redis for leases and Celery | `redis://redis:6379/1` in the scan lease |
| `CLOUDSAVER_KUBERNETES_BINDINGS` | Approved tenant-to-cluster federation bindings (JSON list, at most 100) | `[]` |
| `CLOUDSAVER_LIVE_EVIDENCE_ENABLED` | Turn on live telemetry enrichment | `false` |
| `CLOUDSAVER_LIVE_EVIDENCE_MAX_RESOURCES` | Resources enriched per scope | `25` |
| `CLOUDSAVER_REGIONAL_PRICE_CATALOG` | Operator-reviewed regional price catalog | Unset |
| `CLOUDSAVER_INTERACTIVE_JOBS` | Allow `POST /api/v1/scan-jobs` | Off |
| `CLOUDSAVER_DELIVERY_ENABLED` | Allow durable job delivery | Off |
| `CLOUDSAVER_SCHEDULER_TICK_SECONDS` | Beat interval for scheduled scans, 60 to 3,600 | `300` |
| `CLOUDSAVER_SCHEDULED_SCANS` | Platform flag fallback for scheduled scans | Off |
| `CLOUDSAVER_AUTOMATED_ALERTS` | Platform flag fallback for alerts | Off |
| `CLOUDSAVER_AUTO_BILLING_SYNC` | Hourly cloud billing sync | `true` |
| `CLOUDSAVER_TENANT_REGISTRY` | `env` or `database` workspace registry | `env` |

Prometheus bearer tokens and cluster API tokens are read from the environment variables named in the workspace configuration. Never commit token values.

## Guardrails and limitations

- Scans are read-only and synchronous. A scan in progress can't be cancelled.
- One scope failure fails the whole scan; nothing partial is saved.
- Requests can't widen scope: findings outside configured scopes are rejected.
- Savings values are unknown unless exact price evidence exists. AWS, GCP and Kubernetes findings have no live pricing (`live_cost_support` reports exact Azure meters only).
- The Kubernetes rules module docstring says "Eight", but the catalog defines 10 rules.
- Scheduled scans need the platform flag, a plan that allows them, and an interval set in Settings.
- Event-driven scans (EventBridge, Event Grid, Pub/Sub) aren't wired. See [v2-scaffolds.md](v2-scaffolds.md).

## Tests

- [tests/test_scanner.py](../../tests/test_scanner.py), [tests/test_aws_ingestion.py](../../tests/test_aws_ingestion.py), [tests/test_cloud_ingestion.py](../../tests/test_cloud_ingestion.py), [tests/test_kubernetes_federation.py](../../tests/test_kubernetes_federation.py): collectors.
- [tests/test_expanded_rules.py](../../tests/test_expanded_rules.py), [tests/test_opportunity_groups.py](../../tests/test_opportunity_groups.py), [tests/test_resource_evidence_contracts.py](../../tests/test_resource_evidence_contracts.py): rule outcomes and evidence.
- [tests/test_pricing.py](../../tests/test_pricing.py): price attribution.
- [tests/test_worker.py](../../tests/test_worker.py), [tests/test_outbox_lease.py](../../tests/test_outbox_lease.py), [tests/test_redis_integration.py](../../tests/test_redis_integration.py): jobs, scheduler and leases.
- [platform/tests/test_kubernetes_catalog.py](../../platform/tests/test_kubernetes_catalog.py): Kubernetes rule catalog in identity-service.
- `web-dashboard/e2e/kubernetes.spec.ts` and `web-dashboard/e2e/rules-services.spec.ts`.

## Related docs

- [CLOUD_SOURCES.md](../CLOUD_SOURCES.md)
- [Workspace settings](settings.md)
- [Onboarding and access](onboarding-and-access.md)
- [ENVIRONMENT.md](../ENVIRONMENT.md)
