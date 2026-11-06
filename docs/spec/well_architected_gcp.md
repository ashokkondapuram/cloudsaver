# Google Cloud (GCP) — Well-Architected agent specification

**Audience:** GCP FinOps & Well-Architected backend subagents (Python 3.12+ / FastAPI / Pydantic / google-cloud-*).

**CloudSaver paths:** `app/scanner_gcp.py`, `app/collectors/gcp_live.py`, `app/collectors/cloud_advisor.py` (Recommender); target: `app/adapters/gcp/` + `app/rules/gcp_rules.py`. **Analysis:** `app/analysis_service/*`.

**Reliability:** Use Cloud Asset, Monitoring, Logging, Billing BQ export, and Recommender REST with `app/cloud_http.py` + pagination helpers.

---

## 1. Subagent prompt (GCP)

**Role:** GCP FinOps & Well-Architected Backend Subagent

**Objective:** Implement `app/adapters/gcp/` and `app/rules/gcp_rules.py` using **google-cloud-asset**, **google-cloud-monitoring**, **google-cloud-billing**, **google-cloud-bigquery**, **google-cloud-logging**, **google-cloud-recommender**.

### Data ingestion contracts

| Stream | Contract |
|--------|----------|
| **Discovery** | Cloud Asset **searchAllResources** + service aggregatedList/list |
| **Metrics** | Monitoring **projects.timeSeries.list** (correct monitored resource types; incl. Ops Agent) |
| **Cost** | BQ billing export: `SUM(cost)+SUM(credits.amount)`, `SUM(cost_at_list)` + **Billing Catalog** `services.skus.list` |
| **Activity** | Logging **entries.list** on **Cloud Audit Logs** (admin activity) |
| **Signals** | Recommender / Active Assist (see `fetch_gcp_recommender_recommendations` when advisor flag is on) |

---

## 2. Discovery, metrics, cost/retail & drift mapping

### 2.1 Resource catalog table

| Resource category | Asset type & discovery | Monitoring metrics / resources | Billing / catalog | Audit `protoPayload.methodName` (examples) |
|-------------------|------------------------|--------------------------------|-------------------|---------------------------------------------|
| **GCE, MIG** | `compute.googleapis.com/Instance`, InstanceGroupManager — aggregatedList | `compute.googleapis.com/instance/cpu/utilization`, network bytes, `agent.googleapis.com/memory/percent_used`, autoscaler utilization | Compute Engine service id; category.usageType OnDemand/Commit | instances.insert, delete, setMachineType, setScheduling, addAccessConfig, MIG resize/patch |
| **Cloud Run, Functions, GKE** | `run.googleapis.com/Service`, `cloudfunctions.googleapis.com/Function`, GKE Cluster/NodePool | Run/Function/GKE container metrics: CPU/memory utilizations, execution_count, request_utilization | Service ids per product; BQ labels (cluster, namespace) | UpdateService, UpdateFunction, UpdateCluster, UpdateNodePool, SetNodePoolSize |
| **Disks, snapshots, GCS, Filestore** | Disk, Snapshot, Bucket, Filestore instance | Disk read/write ops, agent disk percent_used, GCS total_bytes, request_count, Filestore used_bytes_percent | PD/Snapshot/GCS/Filestore SKUs | disks.resize, detachDisk, snapshots.insert, buckets.update, setIamPermissions, Filestore UpdateInstance |
| **Cloud SQL, AlloyDB, Spanner, Bigtable, Redis, BQ** | Per-service asset types | DB CPU/memory/connections; Spanner/Bigtable CPU; Redis memory; BQ slots/scanned bytes | Per-service billing SKUs | cloudsql.instances.update, AlloyDB update, Spanner/Bigtable/Redis/Dataset updates, InsertJob |
| **LB, NAT, static IP, VPN, interconnect** | ForwardingRule, BackendService, Router, Address, VpnTunnel, InterconnectAttachment | HTTPS request_count, backend_latencies, NAT dropped packets, VPN tunnel_established, interconnect egress | NAT/VPN/Interconnect SKUs | forwardingRules.insert, routers.patch, addresses.insert, vpnTunnels.insert |

### 2.2 GCP 5-pillar deterministic rules (summary)

| Resource group | Cost | Performance | Reliability | Security | Operational excellence |
|----------------|------|-------------|-------------|----------|------------------------|
| **Compute / Run / GKE** | Idle/rightsize VM; Run min instances with high idle ratio; GKE low request utilization | Cold starts; dataplane/throttling; MIG predictive scaling | Zonal prod without regional MIG; unhealthy Run scaling | Default SA + cloud-platform; WI disabled; public invokers | Missing Ops Agent; :latest tags; release channel |
| **Disk, GCS, Filestore** | Orphaned disk; PD tier mismatch; stale snapshots; cold data in Standard | IO saturation; Filestore latency; small object count | Unprotected stateful disks; versioning/soft delete | PPD / UBLA / KMS | Boot disk autoDelete false; disk percent_used high |
| **Data & networking** | Idle DB; BigQuery storage model; unattached IP; idle forwarding rules | Hot partitions / nodes; NAT drops | HA / regional gaps | Public paths / weak TLS / auth | Partitioning/clustering gaps on large tables |

Stable identifiers: align with `app/resource_catalog.py` and extend with new `GCP_*` / multicloud rule ids as needed.

---

## 3. Extending analysis on the platform

Custom deterministic rules: implement **`evaluate_platform(ctx) -> list[PillarFinding]`** and register via env or `app/analysis_platform_hooks.py` — see `docs/ANALYSIS_SERVICE.md`.
