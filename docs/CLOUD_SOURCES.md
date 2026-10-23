# Cloud connections

Since v0.8.0, workspaces live in the Postgres tenant registry
(CLOUDSAVER_TENANT_REGISTRY=database, the Compose default). CLOUDSAVER_TENANTS only
seeds it on first start. After that:

- The platform operator manages workspaces, plans, identity bindings and Kubernetes
  clusters in the operator console (/admin, operator key).
- Tenant admins manage their Azure subscriptions, AWS accounts and GCP projects,
  scan schedule and alerts in Settings. Changes apply within seconds, with no restart.

Scan requests can still select only provider names. They cannot supply projects,
accounts, regions, roles, URLs, tokens or findings.

Example seed (replace identities and hash before use):

```json
{
  "tenant_id": "11111111-1111-4111-8111-111111111111",
  "name": "Customer workspace",
  "subscription_ids": [],
  "api_key_sha256": "operator-generated-SHA256-hex",
  "plan_tier": "ENTERPRISE",
  "aws_accounts": [
    {"account_id": "123456789012", "region": "us-east-1", "role_arn": "arn:aws:iam::123456789012:role/CloudSaverReader"}
  ],
  "identity": {"gcp_service_account": "cloudsaver-reader@customer-project.iam.gserviceaccount.com"},
  "gcp_projects": [
    {"project_id": "customer-project", "regions": ["us-central1"]}
  ],
  "kubernetes_clusters": [
    {"cluster_id": "customer-cluster", "prometheus_url": "https://metrics.example.com/prometheus", "bearer_token_env": "CLOUDSAVER_PROMETHEUS_TOKEN_PRIMARY"}
  ]
}
```

Use CLOUDSAVER_MODE=azure for live API execution; this compatibility setting does
not force Azure selection on the new endpoint. Azure-only scans need configured
subscription IDs. Workspace configuration allows no Azure subscriptions if at
least one other source is explicit. API and storage independently verify every
finding's provider identity and scope. The existing subscription tier limit also
bounds selected live source entries (an AWS account/region is one entry); the
resource limit applies to the combined result.

## Keyless identity

CloudSaver stores no client secrets, access keys or service-account keys. On Azure
(CLOUDSAVER_CLOUD_IDENTITY=managed_identity), one user-assigned managed identity is
the root for every cloud. Set AZURE_MANAGED_IDENTITY_CLIENT_ID to its client ID.
Each customer can see the values they need under Settings > Cloud accounts. Exact
roles, trust policies and least-privilege permissions are in
docs/MANAGED_IDENTITY_ROLES.md.

- Azure: create a multi-tenant app registration with a federated identity credential
  (issuer: your Entra tenant, subject: the managed identity's object ID, audience
  api://AzureADTokenExchange). Set CLOUDSAVER_AZURE_APP_CLIENT_ID. Each customer
  grants admin consent and assigns Reader on the selected subscriptions.
  CLOUDSAVER_AZURE_ACCESS=direct skips the app and uses the managed identity in its
  own tenant.
- AWS: create an IAM OIDC provider for
  https://login.microsoftonline.com/<entra tenant ID>/v2.0 with audience
  api://AzureADTokenExchange. Then create a hub role
  (CLOUDSAVER_AWS_HUB_ROLE_ARN) that trusts it for the managed identity's object ID
  and can call sts:AssumeRole. Each customer reader role trusts the hub role and
  requires sts:ExternalId equal to the CloudSaver tenant ID. The server always sends
  that value, so one tenant cannot use another tenant's role.
- GCP: create a workload identity pool and an OIDC provider for the same issuer and
  audience (CLOUDSAVER_GCP_WORKLOAD_PROVIDER). The operator assigns each workspace a
  reader service account. Grant roles/iam.workloadIdentityUser on it to the
  managed identity's principal, and grant the service account read access in each
  project.
- Local development (CLOUDSAVER_CLOUD_IDENTITY=developer): Azure CLI sign-in
  (build with CLOUDSAVER_INSTALL_AZURE_CLI=true), the AWS default chain such as an
  SSO profile followed by the same AssumeRole, and gcloud application default
  credentials followed by impersonation. See compose.override.example.yaml.

## Permissions

- AWS: STS caller account must match the configured account. Grant only GetCallerIdentity,
  DescribeVolumes, DescribeAddresses and DescribeDBInstances in intended regions.
  EC2/RDS pagination completes or the entire scan fails. Commercial AWS ARN/region
  formats are supported; other partitions need explicit implementation.
- GCP: read permissions to Compute, Cloud SQL and Monitoring in each explicit
  project. No project discovery is attempted. Zonal disks are inventoried across the
  project; regional disks and external addresses are limited to configured
  regions. Global addresses are excluded. Cloud SQL covers the project.
- Kubernetes: expose a read-only Prometheus HTTPS endpoint with kube-state-metrics
  and cAdvisor CPU/memory data. Bind its bearer token to the configured environment
  name beginning CLOUDSAVER_PROMETHEUS_TOKEN_. Do not place tokens in tenant JSON.
  All four metrics must carry cluster, namespace, pod and container labels. HA
  series must be deduplicated by the operator; duplicate series abort the scan.
  No Kubernetes write permissions or in-cluster deployment is required.

Prometheus token environment bindings still need an operator-reviewed Compose
override on scanner-service. Do not commit it. Scheduled worker scans remain Azure-only.

## Telemetry evidence and limits

Cloud SQL requires state RUNNABLE, an explicit environment label of dev,
development or staging, and the Monitoring metric
cloudsql.googleapis.com/database/network/connections for project:instance.
Every returned series must contain all 336 aligned hourly maxima, with zero
connections throughout. Unsupported engines/metrics, gaps and nonzero values
produce no idle finding. A permission/provider error aborts the whole scan.
Metric availability and semantics must be accepted against each intended engine.

Kubernetes queries request gauges and hourly samples of five-minute CPU rates /
memory working-set gauges over 14 days (337 endpoints). A missing sample prevents
a recommendation for that dimension/container. Requests use their minimum across
the window, conservatively handling request changes. P95 uses nearest rank; a
review candidate requires request > 1.5 × P95, with a suggested request of
1.5 × P95. This is sampled utilization, not continuous peak/SLO assurance or a
promise that node count or billing will decrease. Review zero-usage candidates
manually rather than setting resource requests to zero.

Each REST page is bounded to 8 MB, inventory is bounded, redirects are rejected,
and partial/error results are not persisted as completed scans. Very large
workspaces should use bounded provider selections. Interactive scans remain
synchronous and may exceed the proxy deadline; durable asynchronous multi-cloud
submission is future work.

## Costs, exports and trends

All live AWS/GCP/Kubernetes dollar estimates remain unknown. No fixed published
rate is silently applied across region, currency, contract or resource class.
No inference of realizable/realized savings is made. GCP Billing Catalog exact-SKU
reconciliation is pending. Synthetic fixtures exist only under tests and are never available through a
runtime scan path. Legacy synthetic history is marked and cannot be exported.

Terraform export requires TenantAdmin and Growth/Enterprise entitlement, an owned
completed live snapshot and a currently configured scope. Select one provider per
file. GCP disks use google_compute_disk or google_compute_region_disk according
to scope; addresses use google_compute_address and SQL uses
google_sql_database_instance. AWS supports EBS, EIP and RDS imports with account
constraints. Kubernetes has no generated workload mutation. No live Terraform
plan/import or cloud deletion was run during verification.

Trends inspect up to the latest 100 saved scans in a 1–365 day window, returning
only matching provider selection, mode and scope fingerprint. Legacy snapshots
without scope evidence are shown individually. Missing costs remain unknown;
absence of a finding in a subsequent complete scan is an observation change,
not proof of remediation. History is durable in SQLite or PostgreSQL; no separate
volatile scheduler cache is used for trend calculations.
