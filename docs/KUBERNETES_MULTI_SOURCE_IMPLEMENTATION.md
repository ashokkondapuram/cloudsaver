# Kubernetes and multi-source analysis implementation

The subsequent [next-generation implementation](NEXT_GEN_IMPLEMENTATION.md) adds a mandatory fresh,
signed SLO receipt for every replica before a request-reduction patch can be generated. The original
utilization/protection gates below still apply; a planning upload cannot bypass the new SLO requirement.

Engineering source: [Kubernetes and multi-source analysis guide](https://docs.google.com/document/d/11i_KWMhkr0u1Ug1N0ZR2D_kQC_-A_FCwEURUfT2WmWE).
Baseline: `ad56ea9f6e8f8c4d0b0e3e9905bf1dcca58f794b` on GitHub `main`.

The guide audits an older baseline. Governed AI Foundry settings, the eight Azure evidence contracts, customer access screens, reviewed knowledge retrieval and commercial billing improvements already exist in the current baseline. This increment adds the Kubernetes federation path, eight Kubernetes rule identities, durable source provenance, reconciliation and a dedicated Kubernetes workspace. It does not claim every phase of the six-phase guide is complete.

## Delivered behavior

| Area | Behavior |
| --- | --- |
| Discovery | Kubernetes API inventory includes Pods, Nodes, Namespaces, Deployments, StatefulSets, DaemonSets, ReplicaSets, CronJobs, HPAs, PDBs, PVCs, PVs, StorageClasses, Services and EndpointSlices. Active regular containers receive separate canonical records. Objects without findings remain visible. |
| Collection boundaries | Missing primary Pod/Node/Namespace discovery aborts the scan. Denied secondary APIs, metrics or allocation feeds retain the base inventory and expose unavailability; they cannot create a rule pass. Responses are bounded to 8 MB/page, 200 pages and 20,000 objects/type, plus the existing total-scan quotas. |
| Source ledger | Scan JSON stores full `source_ledger` entries once per provider/scope/source. Resource observations and findings carry `data_sources` references. Entries include collector type, exact observation window, freshness, sample counts/coverage, evidence digest, status and sanitized reason codes. Runtime scope filtering also filters this ledger. Existing scan persistence and PostgreSQL tenant RLS protect it. |
| Reconciliation | Observed node `providerID` and Azure CSI disk handles create typed links only when both exact endpoints are in authorized inventory. Bound PVC versus unattached cloud disk creates `source_conflict`, retains unknown rule outcomes, removes the disputed financial opportunity and blocks destructive scripts. Missing transition evidence remains `partial_telemetry`; multiple accessible sources are not labelled verified agreement. |
| Metrics | Thirty-day five-minute CPU rates, memory working sets, CFS throttling, requests, last-termination OOM reason, restart counters, network I/O, PVC occupancy/mount series and service endpoint series. Every series needs >=95% valid intervals, <=60-minute maximum gap and a fresh end. Invalid, duplicate, nonfinite, out-of-range or ambiguous observations cannot become a sufficient series. Raw samples are hashed and reduced to summaries for persistence. |
| Request safety | CPU: P95 ×1.5 and >100m excess; throttling >2% and HPA coordination block a patch. Memory: P99 ×1.35 and >256 MiB excess; OOM, any unverified restart history and fixed runtime heap configuration block a patch. Resource age and stable request history must cover the window. |
| Reliability | Measured OOM, >10% throttling, memory >90% of a known limit and production BestEffort QoS produce review findings. New source/throttling/OOM checks feed the existing five-pillar assessment without converting units into dollars. |
| Node pools | Current node-pool reservation ratios and DaemonSet overhead use API allocatable and scheduled-pod requests, including init-container maxima and pod overhead. Restartable init-container scheduling remains unknown. Both CPU and memory must be below 45% for the pool slack review. No node-removal feasibility or cash saving is inferred. |
| Administration | The eight rule identities are published in the Platform catalog. Existing operator and delegated workspace rule controls can enable/disable each one. Safety thresholds are fixed contracts, not unrestricted user parameters. Disabled rules retain `disabled_by_policy` outcomes. |
| Workspace | `/kubernetes` provides source-health details, coverage denominators, CPU/memory reservation bars, cluster/namespace/object/QoS/review filters, a paginated explorer, all eight rule outcomes and a resource review dialog. Unknown physical capacity, cluster P95, billed costs and node savings remain explicit. |
| Patch previews | Administrators can download a strategic merge request patch when all observed replicas satisfy the same fresh safety contract, the desired replica count agrees and the rounded proposal lowers every replica's request. The preview supplies server-dry-run and `kubectl diff` commands; it never executes them. Viewers receive no mutation controls. |
| Financial isolation | OpenCost estimates stay separate from FOCUS invoices and realizable savings. Exact window and cluster/workload identities are checked. P95 used/request slack estimates exclude storage/network splits and are not additive node savings. Observed node pools share opaque opportunity groups with exact cloud resource matches and existing Azure VM/disk alternatives. AWS provider IDs omit account IDs and do not establish an exact billing match. |

## Eight published Kubernetes contracts

| ID | Detection and conservative boundaries |
| --- | --- |
| `K8S_CONTAINER_CPU_OVERREQUEST` | Stable CPU requests exceed P95 ×1.5 by >100m. Mature resource, verified controller, known HPA inventory and complete request/CPU/throttling windows required. Throttling/HPA blocks remain visible even when the review condition is detected. |
| `K8S_CONTAINER_MEMORY_OVERREQUEST` | Stable memory requests exceed P99 working set ×1.35 by >256 MiB. A zero OOM gauge does not prove no historical OOM: changed restart history also blocks patch generation. Fixed JVM/Go heap settings require coordinated runtime review. |
| `K8S_CONTAINER_UNDERPROVISIONED_RISK` | Positive observed OOM, high throttling, high working-set/limit ratio or production BestEffort QoS. Missing signals remain unknown; reliability findings have no claimed cash opportunity. |
| `K8S_HPA_PDB_CONFLICT_OR_IDLE_FLOOR` | Current-generation PDBs with zero disruption allowance and positive expected pods require review. Historical HPA min-replica/target-utilization evaluation is explicitly insufficient until its history adapter exists. A PDB is never automatically relaxed. |
| `K8S_NODE_POOL_FRAGMENTATION_WASTE` | Pool reservation slack with known allocatable/request totals. PDBs, placement constraints, real utilization, commitments and bin-packing feasibility still require independent review. |
| `K8S_ABANDONED_WORKLOAD_OR_NAMESPACE` | Mature non-system container/controller with complete zero CPU and network activity over 30 days. This is a workload-owner review signal; it is not namespace deletion approval or a completed ingress/mesh-request audit. |
| `K8S_PVC_UNMOUNTED_OR_LOW_OCCUPANCY` | Complete historical zero mounts plus current Bound/unmounted state and known CronJob inventory, or >=100 GiB with P99 occupancy <10% over 30 days. Missing mount series is not zero. Expansion support is never interpreted as shrink support; CSI migration/recovery review is mandatory. |
| `K8S_ORPHANED_LOADBALANCER_SERVICE` | Observed LoadBalancer ingress and verified zero current/historical available endpoints. Missing endpoint history remains insufficient. Exact paid-cloud LB attribution and ingress ownership remain prerequisites for any removal decision. |

All thresholds above are review signals. All evaluations preserve the eight-state outcome vocabulary. Canonical objects without an applicable rule count as unsupported, not evaluated healthy. Coverage counters describe resource sets and can overlap across different rules.

## Migration and configuration

Apply the Platform owner-role migration using the existing production secret binding:

```bash
cd platform
python -m alembic -c identity_alembic.ini upgrade head
# New Platform head: i0012_kubernetes_rules
```

No new CloudSaver table is required: the source ledger lives in the existing tenant-isolated snapshot JSON. The CloudSaver migration head remains `0015_ai_foundry_diagnostics`. The catalog migration preserves forced RLS and does not delete audit-referenced rule identities on downgrade.

Keep the cluster in the operator-owned workspace scope, using the existing scope administration workflow:

```json
{
  "kubernetes_clusters": [{
    "cluster_id": "production-cluster",
    "prometheus_url": "https://prometheus.example.internal",
    "bearer_token_env": "CLOUDSAVER_PROMETHEUS_TOKEN_PRODUCTION"
  }]
}
```

Add a matching **tenant and cluster bound** runtime binding to `CLOUDSAVER_KUBERNETES_BINDINGS`. The following IDs and endpoints are placeholders to replace with your approved deployment values:

```json
[
  {
    "tenant_id": "11111111-1111-4111-8111-111111111111",
    "cluster_id": "production-cluster",
    "api_url": "https://kubernetes.example.internal",
    "api_token_env": "CLOUDSAVER_K8S_PRODUCTION_API_TOKEN",
    "telemetry_backend": "prometheus_http",
    "opencost_url": "https://opencost.example.internal",
    "opencost_token_env": "CLOUDSAVER_K8S_PRODUCTION_COST_TOKEN"
  }
]
```

Bindings contain references, not raw credentials. URLs require HTTPS with no embedded credentials, query or fragment; redirects are refused. Actual Kubernetes/OpenCost token bindings must begin `CLOUDSAVER_K8S_`. Prometheus bearer bindings keep the existing `CLOUDSAVER_PROMETHEUS_TOKEN_` prefix. Inject those environment values through your deployment's secret store. `.env.example` is not a secret store.

Compose passes the non-secret binding JSON through the common service environment. Use a private Compose override or your Container Apps/Kubernetes secret bindings to pass the named tokens to scanner-service; dynamically named token variables are not forwarded automatically. The scanner needs network reachability to the approved API, metrics and allocation endpoints. TLS verification stays enabled.

The Kubernetes API identity needs read-only `get`/`list` for the resources listed in the discovery table. No Secret listing, workload mutation or cluster-admin privilege is needed. Secondary API denials appear as source failures; Pod/Node/Namespace list access is mandatory. Prometheus needs only query access and the required KSM/cAdvisor collectors. Keep the `cluster` label equal to the configured cluster ID and deduplicate HA scrapes at the telemetry backend. The observation window is 30 days with 300-second intervals; do not relabel hourly/downsampled averages as five-minute peaks.

Without an API binding the existing metrics-only compatibility scanner remains available. Its inventory basis is metrics-visible containers, its existing two rules are retained and it cannot satisfy the new guarded patch contracts or establish full cluster coverage.

### Managed telemetry backends

| Binding `telemetry_backend` | Additional binding fields / behavior |
| --- | --- |
| `prometheus_http` | Uses the existing workspace scope's bearer-token reference. |
| `azure_amp` | Customer-bound federated Azure credential requests the Managed Prometheus audience. The metrics hostname must end `.prometheus.monitor.azure.com`. This is the PromQL adapter, not a Container Insights KQL adapter. |
| `aws_amp_sigv4` | Requires `region` and `role_arn`. Uses the existing hub/customer role chain with workspace external ID, signs exact GET URLs with SigV4 service `aps`, and checks the `aps-workspaces.<region>.amazonaws.com` hostname. |
| `gcp_gmp` | Requires `service_account`; uses the existing configured GCP workload-federation provider and the `monitoring.googleapis.com` endpoint. Set the workspace Prometheus base URL through `/v1/projects/<project>/location/global/prometheus`, before `/api/v1/query_range`. |

Managed modes retain the scope's bearer-token *reference field* for directory-contract compatibility but do not use that token. Kubernetes API authentication in this increment is bearer-token based; custom mTLS and cloud-specific Kubernetes API token generation are not implemented. The optional `hosting_provider` binding is declarative metadata and does not unlock Kubernetes AI routing; authoritative hosting proof and step-up controls remain required.

New source transports have 15-second read timeouts and the existing response-size bound. Three consecutive failed metrics queries open a per-scan circuit and mark the remaining contracts unavailable. There is no persisted cross-scan circuit breaker or automatic model invocation.

## Read and preview APIs

```text
GET  /api/v1/scans/{scan_id}/kubernetes
POST /api/v1/scans/{scan_id}/kubernetes/patch-preview
```

The read endpoint uses the same tenant/provider/cluster-filtered snapshot store as Resource Explorer. A completed live observation is required. The POST requires TenantAdmin and full write access to the saved scan, accepts only resource identity, rule ID and evidence digest, and re-evaluates the frozen evidence. It returns a JSON strategic merge fragment, which is valid YAML, plus a readable diff and commands for a human to run. The fragment is not a complete Kubernetes manifest: render it against the current object using the provided dry-run command before `kubectl diff`.

No live write, Helm release, Kustomize mutation, GitOps PR publication, cloud deletion, paid inference or production deployment occurs during these workflows.

## Remaining engineering and provider acceptance

- Azure Monitor/CloudWatch/GCP Monitoring and authoritative Activity/CloudTrail/Audit event adapters are still required for the non-Kubernetes historical contracts. This increment adds a common provenance/reconciliation boundary, not those remote history collectors.
- Complete Kubernetes event/rollout history, historical HPA/VPA floors and targets, ingress/mesh HTTP counters, PVC inode pressure, placement/PDB-aware packing and commitment-aware node savings remain incomplete. Current unsupported evidence stays unknown. The collector does not claim an exact 30-day OOM event count from a sampled last-termination gauge.
- Current workload-controller attribution verifies live owner UIDs. Recreated pods or changing requests cannot establish a complete window from the new pod alone. Historical controller rollups across deleted replicas are not reconstructed.
- Exact FOCUS node-billing attribution, AWS account-bound providerID resolution, complete cloud VM inventory outside the currently supported resource catalog, storage/network cost splits and verified realized savings are not implemented. OpenCost is an allocation model, not proof of invoice charges. Costs require USD-aligned operator feeds; mixed or unverified currency feeds must not be configured as USD.
- Kubernetes managed adapters require live Azure/AMP/GMP, RBAC, private-network and representative load acceptance. Offline fixtures verify application contracts, not provider authorization. Azure Container Insights KQL, arbitrary telemetry schemas, custom mTLS and fully managed API-server authentication require additional adapters.
- The existing guide boundaries around OIDC/PKCE, capability envelopes, fresh human step-up, time-bounded rule exceptions and client-derived knowledge contributions remain. This increment does not enable knowledge sharing or cross-provider Kubernetes inference.

## Verification

Completed validation:

- Full application and Platform suite using disposable PostgreSQL 16 and Redis 7: **714 passed**. Migration, forced-RLS, catalog, billing, identity and worker regressions are included.
- After the final scope, source-freshness and metrics-summary refinements, Kubernetes, evidence, inventory-scope and service-boundary checks: **60 passed**, including two additional regression cases for pooled capacity and collection-time drift.
- Full dashboard browser suite: **40 passed**, including three Kubernetes workflows, viewer permissions, mobile layout and automated accessibility checks.
- Dashboard and Platform portal production builds (`npm run build -- --webpack`) passed. A final dashboard `npm run typecheck` passed after the new browser fixture typing correction.
- `git diff --check` passed.

Test data is synthetic; PostgreSQL and Redis instances are disposable. No live cluster, paid model inference, cloud mutation or production deployment was used. The temporary dashboard QA server was stopped after verification; the pre-existing local deployment was preserved.

Local Node is 24.19.0; production must use the repository's supported Node >=24.22.1. Python tests report an upstream Starlette/httpx deprecation warning.
