# Kubernetes workload right-sizing via Grafana and Mimir

- **Author:** Product / engineering (imported design)
- **Status:** In progress (v2 policy: ownership, safety blocks, Settings UI — Nov 7, 2026)
- **Date:** Nov 7, 2026
- **Related:** [KUBERNETES_MULTI_SOURCE_IMPLEMENTATION.md](../../docs/KUBERNETES_MULTI_SOURCE_IMPLEMENTATION.md), [kubernetes.md](../../docs/features/kubernetes.md), [FINOPS_RESIZE_METRICS.md](../../docs/FINOPS_RESIZE_METRICS.md), rules `K8S_CONTAINER_CPU_OVERREQUEST` / `K8S_CONTAINER_MEMORY_OVERREQUEST`

## Problem statement

The Kubernetes workspace and scan pipeline rightsizing today depends on **completed scans**: Prometheus reached through workspace bindings, strict series contracts, and saved evidence. Operators who already centralize Kubernetes metrics in **Grafana Cloud / Mimir** cannot get **live, cluster-wide request/limit recommendations** without a new scan and without duplicating Prometheus endpoints.

They need a **read-only** path that:

- Uses the existing Grafana service account and Mimir datasource (no Kubernetes API write access).
- Surfaces workload inventory and CPU/memory sizing suggestions with coverage and risk flags.
- Stays **advisory** in v1 (no automated `kubectl` or GitOps apply).

## Proposed solution

Add a backend **Grafana query adapter** and **recommendation engine** that queries Mimir through Grafana’s HTTP API, maps series to workloads, applies a documented policy (p95 + headroom, deadbands, safety suppressions), and exposes results to the dashboard (new section under **Kubernetes** or a dedicated **Rightsizing** view).

```text
Browser -> gateway/scanner -> Grafana HTTP API -> Mimir (Prometheus metrics)
                         |-----> Loki (optional, v2)
                         `-----> Tempo (optional, v2)
              -> recommendation engine -> JSON + UI evidence
```

Grafana tokens stay on the **server**. The browser never receives `GRAFANA_TOKEN`. URLs are allowlisted per workspace or tenant configuration.

### Relationship to existing Kubernetes analysis

| Capability | Existing scan path | This feature |
| --- | --- | --- |
| Data source | Bound Prometheus + optional K8s API | Grafana → Mimir |
| Freshness | Scan snapshot | Configurable window (default 14 days) |
| Inventory | Authoritative when API binding present | **Metrics-visible workloads only** |
| Patch preview | Saved evidence + safety gates | Out of scope v1 |
| Rules catalog | Eight published K8s rule identities | Complementary advisory output; may align policy numerically over time |

## Data model and configuration

**Workspace-level connector** (extends observability connector direction in `2026-10-25-observability-connectors-and-correlation.md`):

| Field | Description |
| --- | --- |
| `grafana_url` | HTTPS base URL (allowlisted) |
| `grafana_token_ref` | Secret reference (`CLOUDSAVER_GRAFANA_TOKEN_*` or vault key), never stored in DB plaintext |
| `mimir_datasource_uid` | Grafana datasource UID |
| `cluster_label` | PromQL label name for cluster (e.g. `cluster`) |
| `cluster_values` | One or more cluster IDs for this workspace |
| `org_id` | Optional Grafana org header |

**Logical recommendation key:** `(cluster, namespace, workload kind, workload name, container name)` with pod UID and observation timestamps when available.

### Discovery and ownership

Resolve controller ownership from kube-state-metrics:

| Pod owner | Workload identity |
| --- | --- |
| ReplicaSet | Deployment when `kube_replicaset_owner` resolves; else ReplicaSet |
| StatefulSet / DaemonSet | Direct owner |
| Job | CronJob when present; else Job |
| None | Standalone pod / unknown |

Use `kube_pod_owner`, `kube_replicaset_owner`, `kube_job_owner`. Do not treat missing telemetry as zero usage. Flag incomplete historical ownership during rollouts.

### Example metrics (validate per deployment)

| Purpose | Example metric |
| --- | --- |
| CPU usage | `container_cpu_usage_seconds_total` |
| Memory usage | `container_memory_working_set_bytes` |
| Requests/limits | `kube_pod_container_resource_requests`, `kube_pod_container_resource_limits` |
| Risk context | Restarts/OOM, CPU throttling, HPA metrics when present |

Illustrative PromQL (adapt labels and filters):

```promql
sum by (cluster, namespace, pod, container) (
  rate(container_cpu_usage_seconds_total{container!="", container!="POD"}[5m])
)
```

```promql
sum by (cluster, namespace, pod, container) (
  container_memory_working_set_bytes{container!="", container!="POD"}
)
```

## API changes (proposed)

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/api/v1/kubernetes/grafana/connectors` | Register or update Grafana connector (admin) |
| `POST` | `/api/v1/kubernetes/grafana/connectors/{id}/test` | Validate datasource UID and sample query |
| `POST` | `/api/v1/kubernetes/grafana/rightsizing:run` | Start async job (cluster, window, filters) |
| `GET` | `/api/v1/kubernetes/grafana/rightsizing/{job_id}` | Job status + paginated recommendations |
| `GET` | `/api/v1/kubernetes/grafana/rightsizing/{job_id}/items/{key}` | Evidence for one workload/container |

Responses include: query timestamp, window, coverage %, current requests/limits, suggested requests, p95/p99/peak, replica count, HPA/OOM/throttling flags, `policy_version`, confidence, rationale. Link to Grafana explore URL **without** embedding tokens.

## UI changes (proposed)

- **Settings → Observability** (or Kubernetes): connect Grafana, test, pick cluster label values.
- **Kubernetes workspace** tab or panel: **Live rightsizing (Grafana)** with filters (cluster, namespace, direction, confidence), row-level evidence drawer consistent with existing resource review patterns.
- Empty states: no connector, auth failure, partial Mimir results, retention shorter than window.

## Recommendation policy (v1 defaults — tune in pilot)

1. **Window:** 14 days, 5-minute step; respect pod active lifetime.
2. **Baseline:** Per-replica p95 CPU and memory; workload baseline = **max** replica p95.
3. **Suggested requests:** `ceil_to_10m(max_p95_cpu × 1.20)`; `ceil_to_16Mi(max_p95_mem × 1.20)` with configurable floors.
4. **Limits:** Show only; do not auto-propose limit changes from p95.
5. **Deadband:** ~10% before “meaningful change”.
6. **Suppress or “needs review”:** Low coverage (&lt;90% of expected samples while active), OOM/restarts, strong throttling, active rollout, HPA-managed CPU without review flag.

Align numerically with existing patch safety gates over time; v1 may differ but must document `policy_version`.

## Acceptance criteria

1. Workspace admin can save a Grafana connector using a secret ref; token never appears in API responses or UI.
2. Test connection validates datasource UID and returns a bounded sample frame or a clear error (401/403/empty/partial).
3. Rightsizing job returns recommendations for at least Deployments with complete kube-state-metrics and cAdvisor series in Mimir.
4. Each item shows coverage, freshness, current vs suggested requests, and explicit unknowns.
5. HPA-managed workloads are flagged; downsizes with risk signals are labeled **needs review**.
6. No Kubernetes write, no automatic patch apply, no Grafana token in logs or client bundles.
7. Load: bounded concurrency, timeouts, retries with backoff; job async for large clusters.

## Out of scope (v1)

- Direct Mimir API (bypassing Grafana).
- Applying patches or GitOps commits.
- Authoritative full-cluster inventory vs Kubernetes API.
- Cost dollars without a configured allocation model.
- Loki/Tempo correlation (optional v2).

## Open questions

1. Single global Grafana per tenant vs per-cluster connectors?
2. Reuse `observability_connectors` table vs `kubernetes_grafana_bindings`?
3. Merge advisory Grafana results with scan-based `K8S_*` rule outcomes in one table?
4. Entitlements / plan gating for Grafana rightsizing?

## Validation and rollout

- Validate PromQL and ownership in Grafana Explore; spot-check against `kubectl` and existing dashboards.
- Pilot advisory mode; record `policy_version` and query time for reproducibility.
- Test multi-cluster label discipline, rollouts, scaled-to-zero, sparse data, and datasource partial errors.

## References

- [Grafana service accounts](https://grafana.com/docs/grafana/latest/administration/service-accounts/)
- [Grafana data source HTTP API](https://grafana.com/docs/grafana/latest/developers/http_api/data_source/)
- [Grafana query API](https://grafana.com/docs/grafana/latest/panels-visualizations/query-transform-data/)
- [kube-state-metrics](https://github.com/kubernetes/kube-state-metrics/tree/main/docs/metrics)
- [Kubernetes resource management](https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/)
- [HPA](https://kubernetes.io/docs/tasks/run-application/horizontal-pod-autoscale/)
- [Grafana Mimir HTTP API](https://grafana.com/docs/mimir/latest/references/http-api/)

## Implementation notes

Source design document imported Nov 7, 2026. External doc links were not re-verified in the authoring environment; confirm against deployed Grafana/Mimir versions before build.
