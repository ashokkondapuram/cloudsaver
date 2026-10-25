# Kubernetes and containers

The Kubernetes workspace shows what CloudSaver observed in your authorized clusters during a completed scan: cluster and source health, node capacity reservations, a namespace and workload explorer, the outcome of each Kubernetes review rule, and allocation estimates kept separate from billed node cost. Everything on this page is read from a saved scan. CloudSaver never writes to a cluster. A workspace administrator can generate a review-only request patch for a container, but only when the saved evidence for every replica passes all safety gates.

Last reviewed: Oct 25, 2026.

## Where to find it

- **Route:** `/kubernetes`, rendered by [`KubernetesWorkspace`](../../web-dashboard/components/kubernetes/KubernetesWorkspace.tsx) through [web-dashboard/app/kubernetes/page.tsx](../../web-dashboard/app/kubernetes/page.tsx).
- **Navigation label:** **Kubernetes**, in the **Discover & analyze** group of the sidebar ([AppShell.tsx](../../web-dashboard/components/AppShell.tsx)). Keyboard shortcut: `G K`.
- **Page heading:** "Kubernetes & containers" (eyebrow "Multi-source analysis").
- **Who can see it:** Any signed-in workspace role (`Viewer`, `BillingAdmin` or `TenantAdmin`) can open the page and read the evidence. Only `TenantAdmin` sees the patch preview buttons. The sidebar link is visible to all roles.

## What you can do

- **Check cluster and source health.** For each cluster, you see coverage counters (discovered, in scope, evaluated, insufficient evidence, excluded, unsupported), the reconciliation status, and one expandable entry per data source with its status, sample coverage and observation window.
- **Review capacity reservations.** CPU and memory bars show allocatable capacity, DaemonSet overhead and total workload requests. Actual cluster P95 and physical usage always show as Unknown, because summing container percentiles does not establish cluster-level usage.
- **See billed node cost and modeled consolidation.** Each cluster shows imported 30-day billed node cost and modeled node consolidation savings. Both show Unknown unless the underlying evidence is complete.
- **Explore namespaces and workloads.** Filter the resource table by cluster, namespace, object type, QoS class, review signal (review required, out-of-memory kill observed, HPA coordination) or free-text search on workload, pod or resource name. The table pages 50 rows at a time and includes objects with no findings.
- **Inspect one resource.** Select a resource name to open the review dialog. It shows metric evidence (P95, P99, coverage), every rule result with its safety blocks, allocation and invoice figures, and an explanation of what the costs mean.
- **Generate a review patch (administrators only).**
  1. Open a container whose CPU or memory overrequest rule detected a condition with no safety blocks.
  2. Select **Preview CPU request patch** or **Preview memory request patch**.
  3. CloudSaver rechecks the saved evidence for every observed replica of the controller and returns a unified diff, a strategic merge patch and `kubectl` dry-run commands.
  4. Select **Download review patch** to save the YAML file, then apply it through your own change process.
- **Read the rule evidence matrix.** For each of the ten Kubernetes rules, see its pillar and how many saved outcomes fall into each state.
- **Manage rules.** The info notice links to **Manage analysis rules** (`/settings?tab=rules`), where you can enable or disable rules for future scans.

If no scan is selected, the page asks you to run a scan with Kubernetes selected. If the selected scan has no Kubernetes inventory, the page explains that full discovery needs an operator API binding.

## How it works

### Configuration and discovery

1. **Cluster source.** An operator adds a `kubernetes_clusters` entry to the workspace configuration with `cluster_id`, `prometheus_url` and `bearer_token_env`. [app/cloud_scope.py](../../app/cloud_scope.py) (`normalize_sources`) requires an HTTPS URL with no credentials, query or fragment, and a token reference that matches `CLOUDSAVER_PROMETHEUS_TOKEN_*`.
2. **Scan.** A `TenantAdmin` starts a scan with `POST /api/v1/scans/multi-cloud` and the `kubernetes` provider selected. [app/multi_cloud.py](../../app/multi_cloud.py) calls `scan_cluster` in [app/scanner_kubernetes.py](../../app/scanner_kubernetes.py) for every configured cluster. Your plan must include the Kubernetes provider ([app/entitlements.py](../../app/entitlements.py)).
3. **Two discovery modes.** `scan_cluster` looks up a tenant- and cluster-bound entry in `CLOUDSAVER_KUBERNETES_BINDINGS` (`binding` in [app/collectors/kubernetes.py](../../app/collectors/kubernetes.py)):
   - **Full federation (binding present).** [app/collectors/federation.py](../../app/collectors/federation.py) reads the Kubernetes API, Prometheus and, optionally, OpenCost.
   - **Metrics-only (no binding).** `scan_cluster` runs four Prometheus range queries over 14 days at a one-hour step. It produces `K8S_CPU_OVERSIZED` and `K8S_MEMORY_OVERSIZED` findings only when the request exceeds P95 usage by more than 50% across a complete window. Inventory is limited to containers visible in metrics (`inventory_basis: metrics_visible_containers`), so this mode cannot prove cluster coverage.

### Full federation pipeline

1. **Kubernetes API inventory.** `inventory()` in [app/collectors/kubernetes.py](../../app/collectors/kubernetes.py) pages through 16 read-only list endpoints (Pods, Nodes, Namespaces, Deployments, StatefulSets, DaemonSets, ReplicaSets, Jobs, CronJobs, HPAs, PDBs, PVCs, PVs, StorageClasses, Services and EndpointSlices). It validates object identities, pagination tokens and the 20,000-object bound. If Pods, Nodes or Namespaces fail, the scan fails and nothing is saved. Other kinds that fail are recorded as `unavailable` sources.
2. **Prometheus telemetry.** `telemetry()` runs 12 range queries (CPU, memory working set, CFS throttling, CPU and memory requests, OOM kills, restarts, network, PVC occupancy, PVC mounts and service endpoints) over 30 days at a five-minute step. [app/collectors/prometheus_auth.py](../../app/collectors/prometheus_auth.py) selects the reader for each backend: `prometheus_http` (bearer token), `azure_amp` (Azure Monitor managed Prometheus), `aws_amp_sigv4` (Amazon Managed Prometheus with SigV4) or `gcp_gmp` (Google Managed Prometheus). Each series is checked against the telemetry contract ([app/telemetry_contract.py](../../app/telemetry_contract.py)). Missing points are never filled in. After three consecutive query failures, the remaining queries are skipped for that scan and recorded as `source_circuit_open_for_scan`.
3. **Projection.** `project()` in [app/kubernetes_topology.py](../../app/kubernetes_topology.py) converts objects into an allowlisted inventory. It normalizes quantities, resolves controller ownership through ReplicaSets, sums per-node requests (including DaemonSet overhead), and builds pool capacity, PVC mounts, service endpoints and StatefulSet PDB coverage. Only a small set of labels (`environment`, `env`, `app`, `team`, `retain`, `DoNotDelete`, `role`) is kept. Container commands, environment values and Secret data are not stored. The projection records only whether a fixed heap is configured.
4. **OpenCost allocation (optional).** If the binding has an `opencost_url`, the collector requests a 30-day `/allocation` window aggregated by cluster, namespace, pod and container. `allocations()` in [app/k8s_cost_reconciler.py](../../app/k8s_cost_reconciler.py) keeps only containers present in inventory and labels every value `basis: opencost_allocation_estimate`, with `billed_cost_usd` and `realizable_node_savings_usd` set to null. Shared, idle and unknown allocations are not reassigned to workloads.
5. **Rule evaluation.** `evaluate_inventory()` in [app/kubernetes_rules.py](../../app/kubernetes_rules.py) evaluates the ten contracts below (version `kubernetes-2026-10-24.1`). Detected conditions become findings through `findings_from()`.
6. **Provenance.** When the scan is saved, `compact()` in [app/collectors/provenance.py](../../app/collectors/provenance.py) builds a per-scope source ledger. Each resource keeps references to its sources. If two observations share a source ID but have conflicting digests, every affected resource is marked `source_conflict`, and its cost attribution is cleared.

### Rule contracts

| Rule ID | Object types | Pillar | What it checks |
| --- | --- | --- | --- |
| `K8S_CONTAINER_CPU_OVERREQUEST` | Container | Cost | Request exceeds P95 usage plus 50% headroom by more than 100m. Blocked by throttling above 2% or an associated HPA. |
| `K8S_CONTAINER_MEMORY_OVERREQUEST` | Container | Cost | Request exceeds P99 working set plus 35% (50% for StatefulSets) by more than 256 MiB. Blocked by OOM kills, unexplained restarts or a fixed heap. |
| `K8S_CONTAINER_UNDERPROVISIONED_RISK` | Container | Reliability | OOM kills, throttling above 10%, memory near its limit, or BestEffort QoS in production. |
| `K8S_HPA_PDB_CONFLICT_OR_IDLE_FLOOR` | HPA, PDB | Operations | PDB with zero allowed disruptions. HPA idle floors stay insufficient evidence. |
| `K8S_NODE_POOL_FRAGMENTATION_WASTE` | Node | Cost | Pool CPU and memory request ratios both below 45%. |
| `K8S_ABANDONED_WORKLOAD_OR_NAMESPACE` | Container, CronJob, Job | Operations | 30 days of zero CPU and network, retained completed jobs, or repeated backoff failures. System namespaces are excluded. |
| `K8S_PVC_UNMOUNTED_OR_LOW_OCCUPANCY` | PVC | Cost | Bound but never mounted, or 100 GiB or larger with P99 occupancy below 10%. |
| `K8S_STATEFULSET_SIZING_AND_VOLUME_TEMPLATE` | StatefulSet | Reliability | Missing PDB or topology spread constraints. |
| `K8S_DAEMONSET_CLUSTER_WIDE_OVERHEAD_TAX` | DaemonSet | Cost | Measured fleet CPU request slack across a complete set of nodes. |
| `K8S_ORPHANED_LOADBALANCER_SERVICE` | Service | Cost | LoadBalancer service with a cloud load balancer and zero endpoints over 30 days. |

Every outcome is one of `condition_detected`, `condition_not_detected`, `insufficient_evidence`, `not_applicable`, `disabled_by_policy` or `evaluation_failed`. A rule returns `insufficient_evidence` when inventory is older than 24 hours, a metric window is incomplete or stale, a workload is less than 30 days old, or the required fields are missing. Every outcome sets `automatic_execution` to false and `estimated_savings` to null (0 for the reliability risk rule).

### Reading the workspace

`GET /api/v1/scans/{scan_id}/kubernetes` ([app/kubernetes_api.py](../../app/kubernetes_api.py)) loads the saved scan. It rejects scans that are incomplete or `legacy_synthetic`. When the evidence store is available, it calls `FocusRepository.attach` ([app/focus.py](../../app/focus.py)), which:

- Attaches imported FOCUS billing to the cloud resources in the scan.
- Calls `attach_node_costs()` in [app/k8s_cost_reconciler.py](../../app/k8s_cost_reconciler.py), which maps each node's `providerID` to an Azure VM, an EC2 instance (only when exactly one scoped instance matches) or a GCE instance, and copies that machine's billed cost when its billing coverage is complete.

`workspace()` then builds the per-cluster capacity, coverage and source lists, the rule matrix, and a per-resource cost `breakdown()`. The breakdown splits OpenCost CPU and memory allocation into a used estimate and a request-slack estimate, using the ratio of P95 usage to request.

### Patch preview gates

`POST /api/v1/scans/{scan_id}/kubernetes/patch-preview` returns `409` unless every gate passes:

1. The resource is in the scan and inside the workspace cluster scope.
2. The `evidence_digest` you send matches the current saved evidence. If it differs, refresh the page and try again.
3. A fresh re-evaluation of the rule detects the condition, has a recommendation, and has no safety blocks or protection reasons.
4. The controller is a Deployment, StatefulSet or DaemonSet with a valid identity.
5. The controller's desired replica count equals the number of observed pods.
6. Every replica independently passes the same rule.
7. Every replica has saved `slo_evidence` that `evaluate_slo_bounded_rightsizing()` ([app/causal_topology_simulator.py](../../app/causal_topology_simulator.py)) rates `review_eligible`.
8. The rounded target is lower than the smallest current request across replicas.

The response contains the filename (`<controller>.requests-review.patch.yaml`), a `strategic-merge-patch`, a unified diff, `replicas_reviewed`, `automatic_execution: false` and two review commands (`kubectl patch ... --dry-run=server` and `kubectl diff`).

## API reference

The gateway ([services/gateway.py](../../services/gateway.py)) exposes these paths and forwards them to the scanner service, which mounts the router from [app/kubernetes_api.py](../../app/kubernetes_api.py). The dashboard calls them through its `/api` proxy ([web-dashboard/app/api/[...path]/route.ts](../../web-dashboard/app/api/[...path]/route.ts)).

| Method | Path | Purpose | Required role/scope |
| --- | --- | --- | --- |
| GET | `/api/v1/scans/{scan_id}/kubernetes` | Return the Kubernetes workspace view for a completed live scan. | Any workspace role. Route class `scoped_read`. |
| POST | `/api/v1/scans/{scan_id}/kubernetes/patch-preview` | Generate a review-only request patch. Body: `resource_id`, `rule_id` (CPU or memory overrequest), `evidence_digest`. | `TenantAdmin`. Route class `scan_write`. |
| POST | `/api/v1/scans/multi-cloud` | Run a scan that includes the `kubernetes` provider. Defined in [app/main.py](../../app/main.py). | `TenantAdmin`. Route class `body`. |
| GET | `/api/v1/providers` | List configured providers. Reports `kubernetes_window_days: 14` for the metrics-only scanner. | Any workspace role. Route class `agnostic`. |

Route classes come from [app/route_inventory.py](../../app/route_inventory.py) and apply to provider-limited or scope-limited workspace keys.

## Data and evidence

**What's stored with the scan**

- An inventory row for each Kubernetes object and container, with `resource_id` values of the form `k8s://<cluster>/namespaces/<ns>/pods/<pod>/containers/<container>`.
- Evidence fields for each row (requests, limits, QoS, controller, HPA presence, metric statistics with coverage and digests, and allocation), plus `rule_evaluations`, findings and the `source_ledger`.
- Source ledger entries with `source_id` (for example `kubernetes_api:Pod`, `prometheus:cpu` or `opencost`), `collector_type`, `status`, observation window, freshness, sample coverage, evidence digest and a sanitized `reason_code`. Raw provider errors and credentials are never stored.

**Provenance labels**

| Figure | Source | Meaning |
| --- | --- | --- |
| Used allocation estimate and request slack estimate | OpenCost allocation split by P95 usage | A model estimate. Not a bill. |
| Billed node cost | Imported FOCUS charges for the backing cloud VM | Shown only with complete billing coverage. Not provider-reconciled. |
| Realizable node savings | Modeled consolidation of a uniform node pool | Requires complete requests, complete billing, and verified scheduling, PDB, scale-down and commitment evidence. |
| Cluster unallocated cost | Not computed | Always Unknown. |
| Actual cluster P95 and physical usage | Not computed | Always Unknown. |

**What is NOT proven**

- Container allocation opportunities do not add up to node consolidation savings or verified bill savings. The API says so in `financial_note`.
- Reservation slack does not prove that a node can be terminated, that pods can be repacked, or that PDBs allow it.
- A `partial_telemetry` reconciliation status is the default. Having several sources available does not prove they agree.
- Metrics-only discovery cannot prove that the cluster inventory is complete.
- No current collector in this repository populates `slo_evidence`, `pdb_blocked`, `scale_down_disabled` or `scheduling_constraints_verified`. As a result, patch previews return `409` at the SLO gate, and modeled node savings show Unknown unless that evidence is added to the saved inventory.

## Permissions

| Role | Read the workspace | Generate patch previews | Run a Kubernetes scan |
| --- | --- | --- | --- |
| `Viewer` | Yes | No (the dialog says an administrator can generate eligible patches) | No |
| `BillingAdmin` | Yes | No | No |
| `TenantAdmin` | Yes | Yes | Yes |

Provider-limited keys must include `kubernetes` to read Kubernetes data. For `scan_write` routes, the key must cover every provider in the scan. Patch preview also re-validates the resource against the workspace cluster scope (`validate_finding_scope`).

## Configuration

Store secrets only in your deployment's secret store. The variables below hold references or JSON configuration, never token values.

| Variable | Purpose | Default |
| --- | --- | --- |
| `CLOUDSAVER_KUBERNETES_BINDINGS` | JSON list (up to 100) of tenant- and cluster-bound bindings with `tenant_id`, `cluster_id`, `api_url`, `api_token_env` and the optional `opencost_url`, `opencost_token_env`, `telemetry_backend`, `region`, `role_arn`, `service_account`, `hosting_provider`. URLs must be HTTPS with no credentials, query or fragment. | `[]` (metrics-only mode) |
| `CLOUDSAVER_PROMETHEUS_TOKEN_*` | Prometheus bearer token, named by the cluster's `bearer_token_env`. Used by the metrics-only scanner and the `prometheus_http` backend. | None |
| `CLOUDSAVER_K8S_*` | Kubernetes API and OpenCost tokens, named by `api_token_env` and `opencost_token_env`. | None |

The `kubernetes_clusters` list in the workspace configuration supplies `cluster_id`, `prometheus_url` and `bearer_token_env`. See [Cloud sources](../CLOUD_SOURCES.md).

## Guardrails and limitations

- CloudSaver makes no live write calls to clusters. Patch previews are files you download and review. Every response sets `automatic_execution` to false.
- Rule disablement is frozen into the scan's `rule_manifest`. Disabled rules report `disabled_by_policy` and create no findings.
- Bounds: 20,000 objects per kind, 200 pages of 500 items, 20,000 metric series per query, 20,000 OpenCost rows and 100 bindings.
- If primary inventory (Pods, Nodes or Namespaces) is unavailable, no snapshot is saved. Secondary failures keep the inventory and record unknown sources.
- Evidence older than 24 hours is treated as stale and evaluates to `insufficient_evidence`.
- The resource table shows 50 rows per page and filters in the browser.
- The gateway rate-limits each workspace to 120 requests per minute.

## Tests

- [tests/test_kubernetes_federation.py](../../tests/test_kubernetes_federation.py): quantity parsing, every rule gate, binding validation, 30-day coverage, OpenCost scope, node pool grouping, source conflicts, managed Prometheus identities, the telemetry circuit breaker, and patch preview behavior, including viewer denial and single-replica blocking.
- [tests/test_lean_core.py](../../tests/test_lean_core.py): node financials require complete billing and verified scheduling.
- [tests/test_v140.py](../../tests/test_v140.py) and [tests/test_route_inventory.py](../../tests/test_route_inventory.py): rule registration and route classification.
- [web-dashboard/e2e/kubernetes.spec.ts](../../web-dashboard/e2e/kubernetes.spec.ts): missing-source evidence and review-only patches, the viewer view on mobile, and the empty-scan state.

## Related docs

- [Kubernetes multi-source implementation](../KUBERNETES_MULTI_SOURCE_IMPLEMENTATION.md)
- [Kubernetes and multi-source analysis improvements](../KUBERNETES_AND_MULTI_SOURCE_ANALYSIS_IMPROVEMENTS_README.md)
- [Cloud sources](../CLOUD_SOURCES.md)
- [Managed identity roles](../MANAGED_IDENTITY_ROLES.md)
- [Environment reference](../ENVIRONMENT.md)
- [Cost allocation and billing](cost-allocation-and-billing.md)
