# Operator-managed cloud connections

v0.7.0 uses the existing workspace UUID and auth roles for every provider.
Only trusted CLOUDSAVER_TENANTS configuration selects cloud scopes; HTTP requests
can select provider names but cannot supply projects, accounts, regions, profiles,
URLs, tokens or arbitrary findings. Cloud sources are not returned by /me.

Example tenant configuration (replace identities and hash before use):

```json
{
  "tenant_id": "11111111-1111-4111-8111-111111111111",
  "name": "Customer workspace",
  "subscription_ids": [],
  "api_key_sha256": "operator-generated-SHA256-hex",
  "plan_tier": "ENTERPRISE",
  "aws_accounts": [
    {"account_id": "123456789012", "region": "us-east-1", "credential_profile": "customer-a"}
  ],
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

## Credentials and permissions

- AWS: configure each named SDK credential profile through the deployment's
  supported credential chain, preferably temporary role credentials. STS caller
  account must match the configured account. Grant only GetCallerIdentity,
  DescribeVolumes, DescribeAddresses and DescribeDBInstances in intended regions.
  EC2/RDS pagination completes or the entire scan fails. Commercial AWS ARN/region
  formats are supported; other partitions need explicit implementation.
- GCP: use application default credentials with read permissions to Compute,
  Cloud SQL and Monitoring in each explicit project. Workload Identity is
  preferred. GOOGLE_APPLICATION_CREDENTIALS may point to an operator-mounted
  credential configuration; the application never accepts credentials from HTTP.
  No project discovery is attempted. Zonal disks are inventoried across the
  project; regional disks and external addresses are limited to configured
  regions. Global addresses are excluded. Cloud SQL covers the project.
- Kubernetes: expose a read-only Prometheus HTTPS endpoint with kube-state-metrics
  and cAdvisor CPU/memory data. Bind its bearer token to the configured environment
  name beginning CLOUDSAVER_PROMETHEUS_TOKEN_. Do not place tokens in tenant JSON.
  All four metrics must carry cluster, namespace, pod and container labels. HA
  series must be deduplicated by the operator; duplicate series abort the scan.
  No Kubernetes write permissions or in-cluster deployment is required.

Compose does not automatically mount host AWS/GCP credentials or arbitrary token
environment bindings. Create an operator-reviewed Compose override for credential
configuration mounts and the referenced environment variables on scanner-service.
Preserve file permissions, read-only mounts and TLS verification. For example,
pass GOOGLE_APPLICATION_CREDENTIALS=/run/cloud/gcp-credentials.json and mount its
operator-supplied credential configuration read-only; mount AWS profile files
and select their SDK configuration paths separately. Do not commit this override
if it contains secrets. Scheduled worker services remain Azure-only.

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
