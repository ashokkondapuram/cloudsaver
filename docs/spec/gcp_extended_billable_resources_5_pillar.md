# CloudSaver — GCP extended billable resources & 5-pillar rule catalog

**Purpose:** Give the GCP subagent and **AnalysisService** a deterministic reference for **5-pillar** evaluation across **24 billable Google Cloud resource types** (compute, containers/serverless, storage/backups, databases/analytics, networking/hybrid connectivity, AI/ML, observability/security).

**Implementation note:** CloudSaver’s shipped **scanner waste catalog** uses stable ids such as `GCP_GCE_STOPPED_DISK_TAX`, `GCP_UNATTACHED_DISK` (`app/resource_catalog.py`). The rule ids below (e.g. `GCP-GCE-COST-01`) are **spec-level** labels — map them to catalog ids, **platform** `PLATFORM_*` hooks, or new first-party rules as you implement coverage.

**Related:** [well_architected_gcp.md](./well_architected_gcp.md) (concise agent brief), `app/analysis_service/*`, `app/scanner_gcp.py`, `app/collectors/gcp_live.py`, `app/collectors/cloud_advisor.py` (Recommender).

---

## 1. Foundational Google Cloud API contracts

| Concern | Primary APIs |
|--------|----------------|
| **Resource inventory & topology** | Cloud Asset Inventory [searchAllResources](https://cloud.google.com/asset-inventory/docs/reference/rest/v1/TopLevel/searchAllResources) across [supported asset types](https://cloud.google.com/asset-inventory/docs/supported-asset-types); enrich with service **aggregatedList** / **list** REST |
| **Utilization telemetry** | Cloud Monitoring [projects.timeSeries.list](https://cloud.google.com/monitoring/api/ref_v3/rest/v3/projects.timeSeries/list) with [filter syntax](https://cloud.google.com/monitoring/api/v3/filters); [GCP metrics](https://cloud.google.com/monitoring/api/metrics_gcp), Ops Agent metrics, [monitored resource types](https://cloud.google.com/monitoring/api/resources) |
| **Actual vs retail cost** | BigQuery **detailed usage cost export**: `SUM(cost) + SUM(credits.amount)` (net), `SUM(cost_at_list)` (list); join with [Cloud Billing Catalog API](https://cloud.google.com/billing/v1/how-to-catalog-api) **services.list** / **services.skus.list** |
| **Control-plane audit & drift** | Cloud Logging [entries.list](https://cloud.google.com/logging/docs/reference/v2/rest/v2/entries/list) over [Cloud Audit Logs](https://cloud.google.com/logging/docs/audit) (`protoPayload.methodName`) |
| **Native 5-pillar signals** | [Google Cloud Well-Architected](https://cloud.google.com/architecture/framework); [Active Assist Recommenders](https://cloud.google.com/recommender/docs/recommenders-overview) **recommendations.list**; align with `app/collectors/cloud_advisor.py` when enabled |

---

## 2. Compute, containers & serverless (resources 1–6)

### 2.1 Discovery, metrics, pricing & drift

| # | Billable resource | CAI type & discovery | Monitoring metrics & resource | Billing (service.id / SKUs) | Audit `methodName` (examples) |
|---|-------------------|---------------------|----------------------------------|----------------------------|------------------------------|
| 1 | **Compute Engine VMs & sole-tenant** | `compute.googleapis.com/Instance`, NodeGroup — `instances.aggregatedList`, `list`, `getEffectiveFirewalls` | **gce_instance**: `compute.googleapis.com/instance/cpu/utilization`, network received/sent bytes, disk read/write bytes, **agent** `memory/percent_used` | `6F81-5844-456A` (Compute Engine); category.resourceFamily=Compute; usageType OnDemand/Preemptible/Commit*; SKU text E2/N2/C4 etc. | `google.compute.instances.insert`, `delete`, `setMachineType`, `setLabels` |
| 2 | **Managed Instance Groups** | `InstanceGroupManager`, `RegionInstanceGroupManager`, `Autoscaler` — `instanceGroupManagers.aggregatedList`, `get` | **autoscaler**: `compute.googleapis.com/autoscaler/capacity`, `target_capacity`, `utilization`, predictive capacity | Same Compute Engine service; BQ attribution via `compute.googleapis.com/instance_group_manager_name` | `v1.compute.instanceGroupManagers.insert`, `patch`, `resize`, `setInstanceTemplate`, `delete`; `v1.compute.autoscalers.patch` |
| 3 | **Cloud Run** (services & jobs) | `run.googleapis.com/Service`, `Job`, `Revision` — `projects.locations.services.list` | **cloud_run_revision**, **cloud_run_job**: `run.googleapis.com/container/cpu/utilizations`, `memory/utilizations`, `billable_instance_time`, `instance_count` (active/idle), `request_count`, `startup_latencies` | `152E-C115-5142` (Cloud Run); CPU/memory allocation time, idle min-instance | `google.cloud.run.v2.Services.CreateService`, `UpdateService`, `DeleteService`, `SetIamPolicy`; `Jobs.CreateJob`, `UpdateJob`, `RunJob` |
| 4 | **Cloud Functions** (1st & 2nd gen) | `cloudfunctions.googleapis.com/Function`, Cloud Function v2 — `v2 functions.list`, `v1 functions.list` | **cloud_function** / **cloud_run_revision**: `execution_count`, `execution_times`, `user_memory_bytes`, `active_instances`, `instance_count` | `29E7-DA93-CA13`, `152E-C115-5142`; Invocations, CPU/memory time, idle min-instance | `google.cloud.functions.v2.FunctionService.CreateFunction`, `UpdateFunction`, `DeleteFunction`; `google.iam.v1.IAMPolicy.SetIamPolicy` |
| 5 | **GKE** (Standard & Autopilot) | `container.googleapis.com/Cluster`, `NodePool` — `projects.zones.clusters.list`, `nodePools.list` | **k8s_cluster**, **k8s_node**, **k8s_container**: request/limit utilization, `restart_count`, node allocatable utilization | `E505-1604-58F8` (GKE mgmt) + `6F81-5844-456A` (nodes); BQ labels `k8s-namespace`, `kube:unallocated` | `google.container.v1.ClusterManager.CreateCluster`, `UpdateCluster`, `DeleteCluster`, `CreateNodePool`, `UpdateNodePool`, `SetNodePoolSize`, `SetNodePoolAutoscaling` |
| 6 | **Artifact Registry** | `artifactregistry.googleapis.com/Repository`, DockerImage — `projects.locations.repositories.list` | **artifactregistry.googleapis.com/Location**; repository `sizeBytes`, `cleanupPolicies[]`, `cleanupPolicyDryRun` | `149C-F9EC-3994`; storage, egress | `google.devtools.artifactregistry.v1.ArtifactRegistry.CreateRepository`, `UpdateRepository`, `DeleteRepository`, `DeletePackage` |

### 2.2 Extended 5-pillar rules (compute & containers)

**1. GCE:** GCP-GCE-COST-01–04, GCP-GCE-PERF-01–02, GCP-GCE-REL-01–02, GCP-GCE-SEC-01–03, GCP-GCE-OPS-01–02 (idle/zombie, rightsizing/N1 migration, Spot, terminated disk+IP, CPU/RAM/egress cap, standalone prod MIG, maintenance/restart, default SA+scope, Shielded/OS Login, external IP, Ops Agent, FinOps labels).

**2. MIG:** GCP-MIG-COST-01, GCP-MIG-PERF-01, GCP-MIG-REL-01, GCP-MIG-SEC-01, GCP-MIG-OPS-01 (min replicas vs utilization, max clamp, zonal/autohealing, template SA/external IP, stuck opportunistic rollout).

**3. Cloud Run:** GCP-RUN-COST-01–03, GCP-RUN-PERF-01–02, GCP-RUN-REL-01–02, GCP-RUN-SEC-01–02, GCP-RUN-OPS-01 (idle min instances, CPU billing model, memory limits, cold start/concurrency, 429/max instances, probes, allUsers invoker, ingress, `:latest` vs digest).

**4. Cloud Functions:** GCP-CF-COST-01, GCP-CF-PERF-01, GCP-CF-REL-01, GCP-CF-SEC-01, GCP-CF-OPS-01 (memory / gen2 migration, timeout proximity, retry/crash loop, secrets in env vs Secret Manager, deprecated runtime).

**5. GKE:** GCP-GKE-COST-01–03, GCP-GKE-PERF-01–02, GCP-GKE-REL-01, GCP-GKE-SEC-01, GCP-GKE-OPS-01 (request slack/unallocated, autoscaler profile, idle non-prod fee, limit throttling/OOM, Dataplane V2, zonal/auto-repair, Workload Identity/private nodes/MAN, cost allocation/release channel).

**6. Artifact Registry:** GCP-AR-COST-01, GCP-AR-PERF-01, GCP-AR-REL-01, GCP-AR-SEC-01, GCP-AR-OPS-01 (cleanup policies, cross-region pull egress, immutable tags, public/scanning, legacy gcr.io).

*(Full formula text for each rule id matches the specification you maintain for implementation thresholds.)*

---

## 3. Storage & backup (resources 7–11)

### 3.1 Discovery, metrics, pricing & drift

| # | Resource | CAI & discovery | Monitoring | Billing | Audit |
|---|----------|-----------------|------------|---------|-------|
| 7 | **Persistent disks & Hyperdisk** | `compute.googleapis.com/Disk`, `RegionDisk` — `disks.aggregatedList` | **gce_disk** / **gce_instance**: read/write ops and bytes, `max_read_ops_count`, **agent** `disk/percent_used` | `6F81-5844-456A`; PD/Hyperdisk capacity + provisioned IOPS/MBps SKUs | `v1.compute.disks.insert`, `delete`, `resize`, `update`, `createSnapshot`; `attachDisk`, `detachDisk` |
| 8 | **Disk snapshots** | `compute.googleapis.com/Snapshot`, ResourcePolicy — `snapshots.list`, `get` | `storageBytes`, `diskSizeGb`, `snapshotType` (STANDARD/ARCHIVE), `sourceDisk`, `creationTimestamp` | `6F81-5844-456A`; PDSnapshot, archive retrieval | `v1.compute.snapshots.insert`, `delete`, `setIamPolicy` |
| 9 | **Cloud Storage buckets** | `storage.googleapis.com/Bucket` — `buckets.list` (full) | **gcs_bucket**: `storage.googleapis.com/storage/total_bytes`, `object_count`, `api/request_count`, network bytes | `95FF-2EF5-5EA1`; Standard/Nearline/Coldline/Archive, Autoclass, soft delete | `storage.buckets.create`, `update`, `delete`, `setIamPermissions` |
| 10 | **Cloud Filestore** | `file.googleapis.com/Instance`, `Backup`, `Snapshot` | **filestore_instance**: `used_bytes_percent`, `free_bytes`, read/write ops & latency | `D97E-AB26-5D95` | `google.cloud.filestore.v1.CloudFilestoreManager.CreateInstance`, `UpdateInstance`, `DeleteInstance`, `CreateBackup` |
| 11 | **Backup and DR** | `backupdr.googleapis.com/ManagementServer`, `BackupVault`, `BackupPlan` | **backupdr** vault metrics: stored bytes, backup count + failed job audit | `C346-9D39-893A` | `google.cloud.backupdr.v1.BackupDR.CreateBackupVault`, `UpdateBackupPlan`, `DeleteBackup` |

### 3.2 Extended 5-pillar rules (storage)

**7–11:** PD/Hyperdisk (unattached orphan, tier downgrade candidate, overprovisioned IOPS/throughput, I/O throttle, snapshot policy, zonal vs regional disk, CMEK, autoDelete/disk full); snapshots (stale manual, Standard→Archive tier, peak-hour schedule, multi-region, public IAM, unbounded retention); GCS (cold Standard without Autoclass/lifecycle, version/soft-delete sprawl, multi-region egress waste, small-object/prefix hotspot, deletion protection/versioning, public access/UBLA, abort MPU); Filestore & Backup DR (idle/overprovision, BASIC_HDD latency, zonal tier/backups, NO_ROOT_SQUASH, non-shrinkable capacity).

---

## 4. Databases, cache & analytics (resources 12–18)

### 4.1 Discovery, metrics, pricing & drift

| # | Resource | CAI & discovery | Monitoring | Billing | Audit |
|---|----------|-----------------|------------|---------|-------|
| 12 | **Cloud SQL** | `sqladmin.googleapis.com/Instance`, `BackupRun` — `instances.list` | **cloudsql_database**: cpu/memory/disk utilization, disk ops, `network/connections`, `replication/replica_lag` | `9662-B51E-5089`; MySQL/Postgres/SQL Server SKUs | Cloud SQL Admin API writes, failover, backup config |
| 13 | **AlloyDB** | `alloydb.googleapis.com/Cluster`, `Instance`, `Backup` | Instance CPU avg/max, memory, postgres connections, replication lag, cluster storage | `6E46-7537-50B4` | AlloyDB cluster/instance CRUD |
| 14 | **Cloud Spanner** | `spanner.googleapis.com/Instance`, `Database`, `Backup` | **spanner_instance**: cpu utilization (incl. by priority), storage used/limit, processing_units, node_count, request latencies | `2062-016F-44A2` | Spanner instance/DB ops, failover |
| 15 | **Cloud Bigtable** | `bigtableadmin.googleapis.com/Instance`, `Cluster`, `Table` | **bigtable_cluster**, **bigtable_table**: `cpu_load`, `cpu_load_hottest_node`, `storage_utilization`, `node_count`, latencies | `6972-B7C5-AD64` | Bigtable admin CRUD |
| 16 | **Memorystore** (Redis, Valkey, Memcached) | `redis.googleapis.com/Instance`, `Cluster`; `memcache.googleapis.com/Instance` | **redis_instance**, **memcache_instance**: memory usage_ratio, cpu, evictions, hits/misses, connected clients | `58CD-E7C3-72CA`, `1289-4F0F-173F` | `google.cloud.redis.v1.CloudRedis.CreateInstance`, `UpdateInstance`, `DeleteInstance`, `FailoverInstance`, `UpgradeInstance` |
| 17 | **BigQuery** | `bigquery.googleapis.com/Dataset`, `Table`; `bigqueryreservation.googleapis.com/Reservation`, `CapacityCommitment` | **bigquery_project**, **bigquery_dataset**: `slots/allocated`, `slots/total_available`, `query/scanned_bytes_billed`, `query/execution_times`, `storage/stored_bytes` | `24E6-581D-38E5`, `16B8-3BBC-9E48`, `C058-0174-9604` | `DatasetService.UpdateDataset`, `TableService.PatchTable`, `JobService.InsertJob` |
| 18 | **Dataproc & Dataflow** | `dataproc.googleapis.com/Cluster`; `dataflow.googleapis.com/Job` | **cloud_dataproc_cluster**, **dataflow_job**: YARN nodemanagers, HDFS storage, `current_num_vcpus`, `job/system_lag` | `E5F2-3832-C535`, `40C1-B96D-F578` | `ClusterController.CreateCluster`, `JobsV1Beta3.CreateJob` |

### 4.2 Extended 5-pillar rules (databases & analytics)

**12–13:** Cloud SQL & AlloyDB — GCP-SQL-COST-01–04, GCP-SQL-PERF-01–02, GCP-SQL-REL-01–02, GCP-SQL-SEC-01, GCP-SQL-OPS-01 (idle, rightsizing/disk/Enterprise Plus, saturation/replica lag/columnar, zonal vs regional HA, backups/PITR/auto-resize, public IP/SSL, deletion protection/maintenance).

**14–15:** Spanner & Bigtable — GCP-SPAN-COST-01, GCP-CBT-COST-01, GCP-SPAN-PERF-01, GCP-CBT-PERF-01, GCP-SPAN-REL-01, GCP-CBT-REL-01, GCP-SPAN-SEC-01, GCP-SPAN-OPS-01 (PU autoscaling, GC rules, priority CPU, row-key hotspot, storage limits, multi-cluster, CMEK, drop protection).

**16:** Memorystore — GCP-MEM-COST-01, GCP-MEM-PERF-01, GCP-MEM-REL-01, GCP-MEM-SEC-01, GCP-MEM-OPS-01 (idle/overprovision, eviction/CPU, BASIC vs STANDARD_HA/RDB, auth/TLS, Redis version).

**17–18:** BigQuery, Dataproc, Dataflow — GCP-BQ-COST-01–03, GCP-DPROC-COST-01, GCP-BQ-PERF-01, GCP-DFLOW-PERF-01, GCP-BQ-REL-01, GCP-BQ-SEC-01, GCP-BQ-OPS-01 (logical vs physical billing, partition/cluster recommender, idle slots/time-travel, idle Dataproc cluster, slot contention/BI Engine, streaming lag, snapshots, public/PII, `requirePartitionFilter`).

---

## 5. Networking, AI/ML & observability (resources 19–24)

### 5.1 Discovery, metrics, pricing & drift

| # | Resource | CAI & discovery | Monitoring | Billing | Audit |
|---|----------|-----------------|------------|---------|-------|
| 19 | **Cloud Load Balancing & Cloud Armor** | `ForwardingRule`, `GlobalForwardingRule`, `BackendService`, `SecurityPolicy` | **https_lb_rule**, **internal_http_lb_rule**, **network_lb_rule**: `loadbalancing.googleapis.com/https/request_count`, `total_latencies`, `backend_latencies`, L3 egress | `6F81-5844-456A`, `E5F0-FE23-7928`; forwarding rules, Armor request charges | `forwardingRules.insert`, `patch`, `delete`; `backendServices.setSecurityPolicy` |
| 20 | **Cloud NAT** | `compute.googleapis.com/Router` (`nats[]`) — `routers.list` | **nat_gateway**: allocated ports, port usage, dropped packets (OUT_OF_RESOURCES), bytes, `nat_allocation_failed` | `6F81-5844-456A`, `E5F0-FE23-7928`; NAT uptime + data processing | `v1.compute.routers.insert`, `patch`, `update`, `delete` |
| 21 | **Static external IPs** | `compute.googleapis.com/Address`, `GlobalAddress` — `addresses.aggregatedList` | status RESERVED/IN_USE, EXTERNAL, PREMIUM/STANDARD tier, `users[]` | `6F81-5844-456A`; unused static IP, VM IP hourly | `v1.compute.addresses.insert`, `delete`; `globalAddresses.insert` |
| 22 | **Cloud VPN & Interconnect** | `VpnTunnel`, `VpnGateway`, `TargetVpnGateway`, `InterconnectAttachment` | **vpn_gateway**, **interconnect_attachment**: `tunnel_established`, bytes, drops, BGP session, attachment egress/capacity | `6F81-5844-456A`, `E5F0-FE23-7928` | `vpnTunnels.insert`, `delete`; `interconnectAttachments.insert`, `patch` |
| 23 | **Vertex AI** | `aiplatform.googleapis.com/Endpoint`, `NotebookRuntime`; `notebooks.googleapis.com/Instance` | **Endpoint**, **gce_instance**: `prediction_count`, `accelerator/duty_cycle`, `accelerator/memory_bytes_used`, `cpu/utilization` | `C7E2-9256-1C43` | `EndpointService.DeployModel`, `UndeployModel`, `DeleteEndpoint`; notebook start/stop |
| 24 | **Logging, Monitoring, KMS, Secret Manager** | `logging.googleapis.com/LogBucket`, `LogSink`; `cloudkms` keys/versions; `secretmanager` secrets/versions | **logging_sink**, **prometheus_target**: `bytes_ingested`, `byte_count`; `monitoring` billing samples; KMS/Secret API metrics | `5490-F7B7-8DF6`, `58CD-5703-FD9C`, `EEA6-7228-7288`, `EE2A-25B9-31B1` | `UpdateBucket`, `UpdateSink`; KMS `CreateCryptoKeyVersion`, `DestroyCryptoKeyVersion`; `AddSecretVersion` |

### 5.2 Extended 5-pillar rules (networking & security ops)

**19:** GCP-LB-COST-01–02, GCP-LB-PERF-01, GCP-LB-REL-01, GCP-LB-SEC-01, GCP-LB-OPS-01 (orphan forwarding rules, VIP consolidation, CDN/backend latency, single-zone/draining, Armor/TLS, access logging).

**20–21:** GCP-NAT-COST-01–02, GCP-IP-COST-01, GCP-NAT-PERF-01, GCP-IP-PERF-01, GCP-NAT-REL-01, GCP-IP-SEC-01, GCP-NAT-OPS-01 (Private Google Access hairpin, idle NAT, reserved IP, SNAT drops/dynamic ports, Premium tier, manual NAT pool saturation, direct VM external IP, noisy NAT logging).

**22:** GCP-VPN-COST-01–02, GCP-VPN-PERF-01, GCP-VPN-REL-01, GCP-VPN-SEC-01, GCP-VPN-OPS-01 (down tunnels, defunct/undersized attachments, throughput/MTU, Classic VPN/HA VPN, IKEv1/unencrypted interconnect, static vs Cloud Router BGP).

**23:** GCP-AI-COST-01–02, GCP-AI-PERF-01, GCP-AI-REL-01, GCP-AI-SEC-01, GCP-AI-OPS-01 (idle endpoint/notebook, GPU duty cycle, single-replica prod, public endpoint/default SA, orphaned 0% traffic replicas).

**24:** GCP-LOG-COST-01–02, GCP-SEC-COST-01, GCP-LOG-PERF-01, GCP-SEC-REL-01, GCP-SEC-SEC-01, GCP-LOG-OPS-01 (unfiltered ingest, extended retention, KMS/Secret version sprawl, high-cardinality Prometheus, single-region crypto for multi-region apps, rotation period, Log Analytics on _Default).

---

## Implementation mapping (CloudSaver)

1. **Ingestion:** Extend `app/collectors/gcp_live.py` / Asset paths so `inventory[].evidence` carries time series, BigQuery billing joins, Catalog SKU metadata, and audit log methods required by each rule family.
2. **AnalysisService:** Add evaluators or **declarative JSON** (`CLOUDSAVER_ANALYSIS_DECLARATIVE_RULES`) + **platform hooks** for spec ids not yet first-class `GCP_*` catalog rules.
3. **Catalog:** When promoting a spec rule to product, add **`RULE_DISPLAY_NAMES`**, `FAMILIES`/`definitions()`, `ACTION_CLASS_BY_RULE`, `route_for_rule`, and regenerate **`docs/ANALYSIS_RULES_MASTER.md`** per repository process.

---

*This document is the extended GCP billable-resource & 5-pillar catalog for agents; threshold tuning belongs in implementation tickets per rule id.*
