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

### 2.2 Rules by resource type (compute, containers & serverless)

#### 1. Compute Engine VMs & Sole-Tenant Nodes
- **Cost optimization:** `GCP-GCE-COST-01` … `GCP-GCE-COST-04`
- **Performance efficiency:** `GCP-GCE-PERF-01`, `GCP-GCE-PERF-02`
- **Reliability:** `GCP-GCE-REL-01`, `GCP-GCE-REL-02`
- **Security:** `GCP-GCE-SEC-01` … `GCP-GCE-SEC-03`
- **Operational excellence:** `GCP-GCE-OPS-01`, `GCP-GCE-OPS-02`

#### 2. Managed Instance Groups (MIG)
- **Cost optimization:** `GCP-MIG-COST-01`
- **Performance efficiency:** `GCP-MIG-PERF-01`
- **Reliability:** `GCP-MIG-REL-01`
- **Security:** `GCP-MIG-SEC-01`
- **Operational excellence:** `GCP-MIG-OPS-01`

#### 3. Cloud Run (Services & Jobs)
- **Cost optimization:** `GCP-RUN-COST-01` … `GCP-RUN-COST-03`
- **Performance efficiency:** `GCP-RUN-PERF-01`, `GCP-RUN-PERF-02`
- **Reliability:** `GCP-RUN-REL-01`, `GCP-RUN-REL-02`
- **Security:** `GCP-RUN-SEC-01`, `GCP-RUN-SEC-02`
- **Operational excellence:** `GCP-RUN-OPS-01`

#### 4. Cloud Functions (1st & 2nd Gen)
- **Cost optimization:** `GCP-CF-COST-01`
- **Performance efficiency:** `GCP-CF-PERF-01`
- **Reliability:** `GCP-CF-REL-01`
- **Security:** `GCP-CF-SEC-01`
- **Operational excellence:** `GCP-CF-OPS-01`

#### 5. GKE Clusters & Node Pools
- **Cost optimization:** `GCP-GKE-COST-01` … `GCP-GKE-COST-03`
- **Performance efficiency:** `GCP-GKE-PERF-01`, `GCP-GKE-PERF-02`
- **Reliability:** `GCP-GKE-REL-01`
- **Security:** `GCP-GKE-SEC-01`
- **Operational excellence:** `GCP-GKE-OPS-01`

#### 6. Artifact Registry
- **Cost optimization:** `GCP-AR-COST-01`
- **Performance efficiency:** `GCP-AR-PERF-01`
- **Reliability:** `GCP-AR-REL-01`
- **Security:** `GCP-AR-SEC-01`
- **Operational excellence:** `GCP-AR-OPS-01`

*Per-rule formulas/thresholds: upstream FinOps spec.*

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

### 3.2 Rules by resource type (storage & backup)

#### 7. Persistent Disks & Hyperdisk
- **Cost optimization:** `GCP-PD-COST-01` … `GCP-PD-COST-03`
- **Performance efficiency:** `GCP-PD-PERF-01`
- **Reliability:** `GCP-PD-REL-01`, `GCP-PD-REL-02`
- **Security:** `GCP-PD-SEC-01`
- **Operational excellence:** `GCP-PD-OPS-01`

#### 8. Disk Snapshots
- **Cost optimization:** `GCP-SNAP-COST-01`, `GCP-SNAP-COST-02`
- **Performance efficiency:** `GCP-SNAP-PERF-01`
- **Reliability:** `GCP-SNAP-REL-01`
- **Security:** `GCP-SNAP-SEC-01`
- **Operational excellence:** `GCP-SNAP-OPS-01`

#### 9. Cloud Storage Buckets
- **Cost optimization:** `GCP-GCS-COST-01` … `GCP-GCS-COST-03`
- **Performance efficiency:** `GCP-GCS-PERF-01`
- **Reliability:** `GCP-GCS-REL-01`
- **Security:** `GCP-GCS-SEC-01`
- **Operational excellence:** `GCP-GCS-OPS-01`

#### 10. Cloud Filestore
- **Cost optimization:** `GCP-FILE-COST-01`
- **Performance efficiency:** `GCP-FILE-PERF-01`
- **Reliability:** `GCP-FILE-REL-01`
- **Security:** `GCP-FILE-SEC-01`
- **Operational excellence:** `GCP-FILE-OPS-01`

#### 11. Backup and DR Service
- **Cost / perf / rel / sec / ops:** evaluate via vault `totalStoredBytes`, failed backup audit entries, and policy hygiene *(align dedicated rule ids when promoted to `GCP_*` catalog entries)*

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

### 4.2 Rules by resource type (databases, cache & analytics)

#### 12. Cloud SQL
- **Cost optimization:** `GCP-SQL-COST-01` … `GCP-SQL-COST-04`
- **Performance efficiency:** `GCP-SQL-PERF-01`
- **Reliability:** `GCP-SQL-REL-01`, `GCP-SQL-REL-02`
- **Security:** `GCP-SQL-SEC-01`
- **Operational excellence:** `GCP-SQL-OPS-01`

#### 13. AlloyDB for PostgreSQL
- **Performance efficiency:** `GCP-SQL-PERF-02` (columnar engine)
- **Reliability / security / ops:** share Cloud SQL–family thresholds where properties overlap (HA, backup, SSL, maintenance)

#### 14. Cloud Spanner
- **Cost optimization:** `GCP-SPAN-COST-01`
- **Performance efficiency:** `GCP-SPAN-PERF-01`
- **Reliability:** `GCP-SPAN-REL-01`
- **Security:** `GCP-SPAN-SEC-01`
- **Operational excellence:** `GCP-SPAN-OPS-01`

#### 15. Cloud Bigtable
- **Cost optimization:** `GCP-CBT-COST-01`
- **Performance efficiency:** `GCP-CBT-PERF-01`
- **Reliability:** `GCP-CBT-REL-01`
- **Security:** `GCP-SPAN-SEC-01` *(upstream id covers regulated Spanner **or** Bigtable missing `kmsKeyName`)*
- **Operational excellence:** `GCP-SPAN-OPS-01` *(upstream id covers Spanner `enableDropProtection` **or** Bigtable `deletionProtection`)*

#### 16. Memorystore (Redis / Valkey / Memcached)
- **Cost optimization:** `GCP-MEM-COST-01`
- **Performance efficiency:** `GCP-MEM-PERF-01`
- **Reliability:** `GCP-MEM-REL-01`
- **Security:** `GCP-MEM-SEC-01`
- **Operational excellence:** `GCP-MEM-OPS-01`

#### 17. BigQuery
- **Cost optimization:** `GCP-BQ-COST-01` … `GCP-BQ-COST-03`
- **Performance efficiency:** `GCP-BQ-PERF-01`
- **Reliability:** `GCP-BQ-REL-01`
- **Security:** `GCP-BQ-SEC-01`
- **Operational excellence:** `GCP-BQ-OPS-01`

#### 18. Cloud Dataproc & Cloud Dataflow
- **Dataproc — cost optimization:** `GCP-DPROC-COST-01`
- **Dataflow — performance efficiency:** `GCP-DFLOW-PERF-01`

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

### 5.2 Rules by resource type (networking, AI/ML & observability)

#### 19. Cloud Load Balancing & Cloud Armor
- **Cost optimization:** `GCP-LB-COST-01`, `GCP-LB-COST-02`
- **Performance efficiency:** `GCP-LB-PERF-01`
- **Reliability:** `GCP-LB-REL-01`
- **Security:** `GCP-LB-SEC-01`
- **Operational excellence:** `GCP-LB-OPS-01`

#### 20. Cloud NAT Gateways
- **Cost optimization:** `GCP-NAT-COST-01`, `GCP-NAT-COST-02`
- **Performance efficiency:** `GCP-NAT-PERF-01`
- **Reliability:** `GCP-NAT-REL-01`
- **Security:** *(flow / logging hygiene pairs with Cloud Logging — see 24)*
- **Operational excellence:** `GCP-NAT-OPS-01`

#### 21. Static External IP Addresses
- **Cost optimization:** `GCP-IP-COST-01`
- **Performance efficiency:** `GCP-IP-PERF-01`
- **Reliability:** *(DNS / VIP stability rules in implementation)*
- **Security:** `GCP-IP-SEC-01`
- **Operational excellence:** *(ownership / labels in implementation)*

#### 22. Cloud VPN & Cloud Interconnect
- **Cost optimization:** `GCP-VPN-COST-01`, `GCP-VPN-COST-02`
- **Performance efficiency:** `GCP-VPN-PERF-01`
- **Reliability:** `GCP-VPN-REL-01`
- **Security:** `GCP-VPN-SEC-01`
- **Operational excellence:** `GCP-VPN-OPS-01`

#### 23. Vertex AI (Endpoints, Workbench) & Generative AI PTU
- **Cost optimization:** `GCP-AI-COST-01` … `GCP-AI-COST-03`
- **Performance efficiency:** `GCP-AI-PERF-01`
- **Reliability:** `GCP-AI-REL-01`
- **Security:** `GCP-AI-SEC-01`
- **Operational excellence:** `GCP-AI-OPS-01`

#### 24. Cloud Logging, Cloud Monitoring, Cloud KMS & Secret Manager
- **Logging — cost optimization:** `GCP-LOG-COST-01`, `GCP-LOG-COST-02`
- **Logging — performance efficiency:** `GCP-LOG-PERF-01` (high-cardinality Managed Prometheus samples)
- **Logging — operational excellence:** `GCP-LOG-OPS-01`
- **KMS / Secret Manager — cost optimization:** `GCP-SEC-COST-01`
- **KMS / Secret Manager — reliability:** `GCP-SEC-REL-01`
- **KMS / Secret Manager — security:** `GCP-SEC-SEC-01`

---

## Implementation mapping (CloudSaver)

1. **Ingestion:** Extend `app/collectors/gcp_live.py` / Asset paths so `inventory[].evidence` carries time series, BigQuery billing joins, Catalog SKU metadata, and audit log methods required by each rule family.
2. **AnalysisService:** Add evaluators or **declarative JSON** (`CLOUDSAVER_ANALYSIS_DECLARATIVE_RULES`) + **platform hooks** for spec ids not yet first-class `GCP_*` catalog rules.
3. **Catalog:** When promoting a spec rule to product, add **`RULE_DISPLAY_NAMES`**, `FAMILIES`/`definitions()`, `ACTION_CLASS_BY_RULE`, `route_for_rule`, and regenerate **`docs/ANALYSIS_RULES_MASTER.md`** per repository process.

---

*This document is the extended GCP billable-resource & 5-pillar catalog for agents; threshold tuning belongs in implementation tickets per rule id.*
