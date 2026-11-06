# CloudSaver — Azure extended billable resources & 5-pillar rule catalog

**Purpose:** Give the Azure subagent and **AnalysisService** a deterministic reference for **5-pillar** evaluation across **24 billable Microsoft Azure resource types** (compute, containers/serverless, storage/backups, databases/analytics, networking/hybrid connectivity, AI/ML, observability/security).

**Implementation note:** CloudSaver’s shipped **scanner waste catalog** uses stable ids such as `AZURE_VM_STOPPED_RESIDUAL_COST`, `AZURE_DISK_UNATTACHED_RETENTION` (`app/resource_catalog.py`). The rule ids below (e.g. `AZ-VM-COST-01`) are **spec-level** labels — map them to catalog ids, **platform** `PLATFORM_*` hooks, or new first-party rules as you implement coverage.

**Related:** [well_architected_azure.md](./well_architected_azure.md) (concise agent brief), `app/analysis_service/*`, `app/scanner.py`, `app/collectors/azure_live.py`, `app/collectors/azure_monitor_batch.py`.

---

## 1. Foundational Microsoft Azure API contracts

| Concern | Primary APIs |
|--------|----------------|
| **Resource inventory & state diffs** | Resource Graph **Resources** (`api-version=2024-04-01`) over [supported tables](https://learn.microsoft.com/en-us/azure/governance/resource-graph/reference/supported-tables-resources); [Resource Changes](https://learn.microsoft.com/en-us/azure/governance/resource-graph/how-to/get-resource-changes) for before/after diffs |
| **Utilization telemetry** | Azure Monitor [Metrics REST API](https://learn.microsoft.com/en-us/rest/api/monitor/metrics/list-at-subscription-scope-post); batch subscription queries; [supported metrics index](https://learn.microsoft.com/en-us/azure/azure-monitor/metrics/metrics-supported) |
| **Actual / amortized vs retail** | Cost Management [Usage / Query](https://learn.microsoft.com/en-us/rest/api/cost-management/) — **ActualCost** and **AmortizedCost** grouped by **ResourceId**, **PricingModel**, **BenefitId**, **ReservationId**; [Retail Prices API](https://learn.microsoft.com/en-us/rest/api/cost-management/retail-prices/azure-retail-prices) `GET https://prices.azure.com/api/retail/prices?api-version=2023-01-01-preview` |
| **Control-plane audit & drift** | [Activity Log](https://learn.microsoft.com/en-us/azure/azure-monitor/essentials/activity-log) (Azure Monitor) |
| **Native 5-pillar signals** | [Azure Well-Architected](https://learn.microsoft.com/en-us/azure/well-architected/); [Advisor Recommendations - List](https://learn.microsoft.com/en-us/rest/api/advisor/); align with `app/collectors/cloud_advisor.py` when `CLOUDSAVER_CLOUD_ADVISOR_ENABLED` |

---

## 2. Compute, containers & serverless (resources 1–6)

### 2.1 Discovery, metrics, pricing & drift

| # | Billable resource | ARG type & ARM | Monitor namespace & metrics (examples) | Cost / retail filters | Activity Log `operationName.value` (examples) |
|---|-------------------|----------------|------------------------------------------|------------------------|------------------------------------------------|
| 1 | **Virtual Machines** | `microsoft.compute/virtualmachines` — Virtual Machines Get/List/Instance View | **Microsoft.Compute/virtualMachines**: Percentage CPU, Available Memory Bytes, Network In/Out Total, OS/Data Disk IOPS Consumed %, CPU Credits Remaining, VmAvailabilityMetric | MeterCategory=Virtual Machines; retail: `serviceName eq 'Virtual Machines'`, `armSkuName`, `armRegionName`, `priceType eq 'Consumption'` (DevTestConsumption for Windows AHB base rates) | `Microsoft.Compute/virtualMachines/write`, `delete`, `start/action`, `deallocate/action`, `powerOff/action`, `restart/action`, `extensions/write` |
| 2 | **VM Scale Sets** | `microsoft.compute/virtualmachinescalesets` — VMSS Get/List All, VMSS VMs List | **Microsoft.Compute/virtualMachineScaleSets** (VMSS + VMSS VMs): Percentage CPU, Available Memory Bytes, OS/Data Disk IOPS % — Dim **VMName** | MeterCategory=Virtual Machines; ResourceId matches VMSS URI; retail × `sku.capacity` | `Microsoft.Compute/virtualMachineScaleSets/write`, `delete`, `scaleOut/action`, `deallocate/action`, `manualUpgrade/action` |
| 3 | **App Service Plans** | `microsoft.web/serverfarms` — App Service Plans REST List | **Microsoft.Web/serverfarms**: CpuPercentage, MemoryPercentage, DiskQueueLength, HttpQueueLength, BytesReceived/Sent, SocketInboundAll/OutboundAll — Dim **Instance** | MeterCategory=Azure App Service; retail: B1–B3, S1–S3, P0v3–P5mv3, I1v2–I6v2 | `Microsoft.Web/serverfarms/write`, `delete`, `restartSites/action`, `workers/reboot/action` |
| 4 | **Azure Functions** (Function Apps) | `microsoft.web/sites` (`kind` contains `functionapp`) | **Microsoft.Web/sites** (Sites/Slots): FunctionExecutionCount, FunctionExecutionUnits, AlwaysReadyUnits, OnDemandFunctionExecutionCount, MemoryWorkingSet, Requests, Http5xx | MeterCategory in (Functions, Azure App Service); retail: Consumption, Flex Consumption, Premium EP1–EP3 | `Microsoft.Web/sites/write`, `delete`, `start/action`, `stop/action`, `restart/action`, `config/write` |
| 5 | **AKS** | `microsoft.containerservice/managedclusters` | **Microsoft.ContainerService/managedClusters**: node_cpu_usage_percentage, node_memory_working_set_percentage, node_disk_usage_percentage, kube_pod_status_ready, cluster_autoscaler_unschedulable_pods_count — Dim node, nodepool, namespace | MeterCategory=Container Service (Standard vs Premium LTS) + MC_* node RG spend | `Microsoft.ContainerService/managedClusters/write`, `delete`, `start/action`, `stop/action`, `agentPools/write`, `agentPools/delete` |
| 6 | **ACR & Container Apps** | `microsoft.containerregistry/registries`, `microsoft.app/containerapps`, `microsoft.app/managedenvironments` | **Microsoft.ContainerRegistry/registries**, **Microsoft.App/containerApps**: StorageUsed, TotalPull/PushCount, UsageNanoCores, WorkingSetBytes, Replicas, Requests | MeterCategory in (Container Registry, Azure Container Apps); retail ACR SKUs; ACA Consumption vs workload profiles | `Microsoft.ContainerRegistry/registries/write`, `webhooks/write`; `Microsoft.App/containerApps/write`, `managedEnvironments/write` |

### 2.2 Rules by resource type (compute, containers & serverless)

#### 1. Virtual Machines
- **Cost optimization:** `AZ-VM-COST-01` … `AZ-VM-COST-04`
- **Performance efficiency:** `AZ-VM-PERF-01` … `AZ-VM-PERF-03`
- **Reliability:** `AZ-VM-REL-01` … `AZ-VM-REL-03`
- **Security:** `AZ-VM-SEC-01` … `AZ-VM-SEC-03`
- **Operational excellence:** `AZ-VM-OPS-01` … `AZ-VM-OPS-03`

#### 2. Virtual Machine Scale Sets
- **Cost optimization:** `AZ-VMSS-COST-01`, `AZ-VMSS-COST-02`
- **Performance efficiency:** `AZ-VMSS-PERF-01`, `AZ-VMSS-PERF-02`
- **Reliability:** `AZ-VMSS-REL-01`, `AZ-VMSS-REL-02`
- **Security:** `AZ-VMSS-SEC-01`, `AZ-VMSS-SEC-02`
- **Operational excellence:** `AZ-VMSS-OPS-01`

#### 3. App Service Plans
- **Cost optimization:** `AZ-ASP-COST-01` … `AZ-ASP-COST-03`
- **Performance efficiency:** `AZ-ASP-PERF-01`
- **Reliability:** `AZ-ASP-REL-01`, `AZ-ASP-REL-02`
- **Security:** `AZ-ASP-SEC-01`
- **Operational excellence:** `AZ-ASP-OPS-01`

#### 4. Azure Functions (Function Apps)
- **Cost optimization:** `AZ-FUNC-COST-01`, `AZ-FUNC-COST-02`
- **Performance efficiency:** `AZ-FUNC-PERF-01`
- **Reliability:** `AZ-FUNC-REL-01`, `AZ-FUNC-REL-02`
- **Security:** `AZ-FUNC-SEC-01`
- **Operational excellence:** `AZ-FUNC-OPS-01`

#### 5. Azure Kubernetes Service (AKS)
- **Cost optimization:** `AZ-AKS-COST-01` … `AZ-AKS-COST-03`
- **Performance efficiency:** `AZ-AKS-PERF-01`, `AZ-AKS-PERF-02`
- **Reliability:** `AZ-AKS-REL-01`, `AZ-AKS-REL-02`
- **Security:** `AZ-AKS-SEC-01`, `AZ-AKS-SEC-02`
- **Operational excellence:** `AZ-AKS-OPS-01`

#### 6a. Azure Container Registry (ACR)
- **Cost optimization:** `AZ-ACR-COST-01`
- **Performance efficiency:** *(use cross-region / pull metrics in implementation)*
- **Reliability:** `AZ-ACR-REL-01`
- **Security:** `AZ-ACR-SEC-01`
- **Operational excellence:** `AZ-ACR-OPS-01`

#### 6b. Azure Container Apps (ACA)
- **Cost optimization:** `AZ-ACA-COST-01`
- **Performance efficiency:** `AZ-ACA-PERF-01`
- **Reliability:** *(probe / replica rules pair with App Service patterns in implementation)*
- **Security:** *(ingress + identity rules pair with Functions/App Service patterns in implementation)*
- **Operational excellence:** *(revision and env rules in implementation)*

---

## 3. Storage & backup (resources 7–10)

### 3.1 Discovery, metrics, pricing & drift

| # | Resource | ARG & ARM | Monitor | Cost / retail | Activity Log |
|---|----------|-----------|---------|---------------|--------------|
| 7 | **Managed disks** | `microsoft.compute/disks` — Create/Get | **Microsoft.Compute/disks**: Composite Disk Read/Write Bytes/sec & Ops/sec, DiskPaidBurstIOPS, BurstIOCreditPercentage | MeterCategory=Storage; Premium/Standard SSD/Ultra meters; retail Storage + product/region | `Microsoft.Compute/disks/write`, `delete`, `beginGetAccess/action`, `endGetAccess/action` |
| 8 | **Snapshots & restore points** | `microsoft.compute/snapshots`, `microsoft.compute/restorepointcollections` | Size, incremental, SKU (Premium_LRS vs Standard), `timeCreated` | MeterCategory=Storage; snapshots meters; retail | `Microsoft.Compute/snapshots/write`, `delete`, `beginGetAccess/action`, `endGetAccess/action` |
| 9 | **Storage accounts** (Blob, ADLS Gen2, Files) | `microsoft.storage/storageaccounts` | **Microsoft.Storage/storageAccounts**, **blobServices**, **fileServices**: UsedCapacity, BlobCapacity, BlobCount, Transactions, Ingress/Egress, SuccessServerLatency, Availability | MeterCategory=Storage (General Block Blob v2, Files v2, Premium Files); retail | `Microsoft.Storage/storageAccounts/write`, `delete`, `listKeys/action`, `regenerateKey/action`, `blobServices/write`, `managementPolicies/write` |
| 10 | **Recovery Services & Backup vaults** | `microsoft.recoveryservices/vaults`, `microsoft.dataprotection/backupvaults` | **Microsoft.RecoveryServices/vaults**: BackupHealthEvent, RestoreHealthEvent; protected instance counts; GRS vs LRS/ZRS bytes | MeterCategory=Backup; retail Backup + region | `Microsoft.RecoveryServices/vaults/write`, `backupPolicies/write`, `protectedItems/delete` |

### 3.2 Rules by resource type (storage & backup)

#### 7. Managed Disks
- **Cost optimization:** `AZ-DISK-COST-01` … `AZ-DISK-COST-04`
- **Performance efficiency:** `AZ-DISK-PERF-01`
- **Reliability:** `AZ-DISK-REL-01`
- **Security:** `AZ-DISK-SEC-01`
- **Operational excellence:** `AZ-DISK-OPS-01`

#### 8. Disk Snapshots & Restore Points
- **Cost optimization:** `AZ-SNAP-COST-01` … `AZ-SNAP-COST-03`
- **Performance efficiency:** `AZ-SNAP-PERF-01`
- **Reliability:** `AZ-SNAP-REL-01`
- **Security:** `AZ-SNAP-SEC-01`
- **Operational excellence:** `AZ-SNAP-OPS-01`

#### 9. Storage Accounts (Blob, ADLS Gen2, Files)
- **Cost optimization:** `AZ-STG-COST-01` … `AZ-STG-COST-03`
- **Performance efficiency:** `AZ-STG-PERF-01`
- **Reliability:** `AZ-STG-REL-01`, `AZ-STG-REL-02`
- **Security:** `AZ-STG-SEC-01`
- **Operational excellence:** `AZ-STG-OPS-01`

#### 10. Recovery Services Vaults & Backup Vaults
- **Cost optimization:** `AZ-BKP-COST-01`, `AZ-BKP-COST-02`
- **Performance efficiency:** `AZ-BKP-PERF-01`
- **Reliability:** `AZ-BKP-REL-01`
- **Security:** `AZ-BKP-SEC-01`
- **Operational excellence:** `AZ-BKP-OPS-01`

---

## 4. Databases, cache & analytics (resources 11–16)

### 4.1 Discovery, metrics, pricing & drift

| # | Resource | ARG & ARM | Monitor | Cost / retail | Activity Log |
|---|----------|-----------|---------|---------------|--------------|
| 11 | **Azure SQL** (DB, elastic pools, MI) | `microsoft.sql/servers/databases`, `elasticpools`, `managedinstances` | **Microsoft.Sql/servers/databases**: cpu_percent, dtu_consumption_percent, storage_percent, allocated_data_storage_percent, workers_percent, sessions_percent, deadlock, connection_failed, app_cpu_billed | MeterCategory SQL Database / SQL MI; retail LicenseIncluded vs BasePrice (AHB) | `Microsoft.Sql/servers/databases/write`, `delete`, `pause/action`, `resume/action`, `failover/action`, `firewallRules/write`, `securityAlertPolicies/write` |
| 12 | **Cosmos DB** | `microsoft.documentdb/databaseaccounts` | **Microsoft.DocumentDB/databaseAccounts**: TotalRequestUnits, ProvisionedThroughput, AutoscaleMaxThroughput, NormalizedRUConsumption, DataUsage, IndexUsage, TotalRequests, ServerSideLatency — Dim DatabaseName, CollectionName, Region, StatusCode, PartitionKeyRangeId | MeterCategory=Azure Cosmos DB; retail | `Microsoft.DocumentDB/databaseAccounts/write`, `delete`, `failoverPriorityChange/action`, `listKeys/action`, `regenerateKey/action`, `throughputSettings/write` |
| 13 | **PostgreSQL Flexible Server** | `microsoft.dbforpostgresql/flexibleservers` | **Microsoft.DBforPostgreSQL/flexibleServers**: cpu_percent, memory_percent, storage_percent, iops, disk_queue_depth, active_connections, connections_failed, maximum_used_transaction_ids, physical_replication_delay_in_seconds | MeterCategory=Azure Database for PostgreSQL; retail Flexible Server | `Microsoft.DBforPostgreSQL/flexibleServers/write`, `delete`, `start/action`, `stop/action`, `restart/action`, `failover/action`, `configurations/write` |
| 14 | **MySQL Flexible Server** | `microsoft.dbformysql/flexibleservers` | **Microsoft.DBforMySQL/flexibleServers**: cpu_percent, memory_percent, storage_percent, io_consumption_percent, active_connections, aborted_connections, Innodb_row_lock_time, replication_lag | MeterCategory=Azure Database for MySQL; retail Flexible Server | `Microsoft.DBforMySQL/flexibleServers/write`, `delete`, `start/action`, `stop/action`, `restart/action`, `failover/action`, `configurations/write` |
| 15 | **Azure Cache for Redis** | `microsoft.cache/redis`, `microsoft.cache/redisenterprise` | **Microsoft.Cache/redis**: percentProcessorTime, usedmemorypercentage, usedmemoryRss, serverLoad, connectedclients, cachehits/misses, evictedkeys, cacheLatency — Dim ShardId, PrimaryOrReplica | MeterCategory=Azure Cache for Redis; retail Redis SKUs | `Microsoft.Cache/redis/write`, `delete`, `forceReboot/action`, `flushCache/action`, `listKeys/action`, `regenerateKey/action`, `import/action` |
| 16 | **Synapse & Databricks** | `microsoft.synapse/workspaces/sqlpools`, `bigdatapools`, `microsoft.databricks/workspaces` | **Microsoft.Synapse/workspaces/sqlPools**: DWUUsedPercent, CPU, MemoryUsedPercent, ActiveQueries, Connections | MeterCategory Azure Synapse Analytics / Azure Databricks; DWU/DBU retail | `Microsoft.Synapse/workspaces/sqlPools/write`, `pause/action`, `resume/action`; `Microsoft.Databricks/workspaces/write` |

### 4.2 Rules by resource type (databases, cache & analytics)

#### 11. Azure SQL (databases, elastic pools, managed instance)
- **Cost optimization:** `AZ-SQL-COST-01` … `AZ-SQL-COST-03`
- **Performance efficiency:** `AZ-SQL-PERF-01`
- **Reliability:** `AZ-SQL-REL-01`
- **Security:** `AZ-SQL-SEC-01`
- **Operational excellence:** `AZ-SQL-OPS-01`

#### 12. Azure Cosmos DB
- **Cost optimization:** `AZ-COS-COST-01` … `AZ-COS-COST-04`
- **Performance efficiency:** `AZ-COS-PERF-01`
- **Reliability:** `AZ-COS-REL-01`, `AZ-COS-REL-02`
- **Security:** `AZ-COS-SEC-01`
- **Operational excellence:** `AZ-COS-OPS-01`

#### 13 & 14. Azure Database for PostgreSQL / MySQL (Flexible Server)
- **Cost optimization:** `AZ-PGMY-COST-01`, `AZ-PGMY-COST-02`
- **Performance efficiency:** `AZ-PGMY-PERF-01`
- **Reliability:** `AZ-PGMY-REL-01`
- **Security:** `AZ-PGMY-SEC-01`
- **Operational excellence:** `AZ-PGMY-OPS-01`

#### 15. Azure Cache for Redis
- **Cost optimization:** `AZ-REDIS-COST-01`
- **Performance efficiency:** `AZ-REDIS-PERF-01`
- **Reliability:** `AZ-REDIS-REL-01`
- **Security:** `AZ-REDIS-SEC-01`
- **Operational excellence:** `AZ-REDIS-OPS-01`

#### 16. Azure Synapse & Azure Databricks
- **Cost optimization:** `AZ-SYN-COST-01`, `AZ-SYN-COST-02`
- **Performance efficiency:** `AZ-SYN-PERF-01`
- **Reliability:** `AZ-SYN-REL-01`
- **Security:** `AZ-SYN-SEC-01`
- **Operational excellence:** `AZ-SYN-OPS-01`

---

## 5. Networking, AI/ML & observability (resources 17–24)

### 5.1 Discovery, metrics, pricing & drift

| # | Resource | ARG & ARM | Monitor | Cost / retail | Activity Log |
|---|----------|-----------|---------|---------------|--------------|
| 17 | **Load Balancers** | `microsoft.network/loadbalancers` | **Microsoft.Network/loadBalancers**: ByteCount, PacketCount, SnatConnectionCount, AllocatedSnatPorts, UsedSnatPorts, VipAvailability, DipAvailability | MeterCategory=Load Balancer; retail | `Microsoft.Network/loadBalancers/write`, `delete`, `backendAddressPools/write`, `inboundNatRules/write` |
| 18 | **Application Gateways & WAF** | `microsoft.network/applicationgateways` | **Microsoft.Network/applicationGateways**: TotalRequests, FailedRequests, Throughput, CurrentConnections, Healthy/UnhealthyHostCount, CapacityUnits, EstimatedBilledCapacityUnits, BackendLastByteResponseTime | MeterCategory=Application Gateway; retail Standard_v2, WAF_v2, Basic | `Microsoft.Network/applicationGateways/write`, `delete`, `start/action`, `stop/action`; `ApplicationGatewayWebApplicationFirewallPolicies/write` |
| 19 | **NAT Gateways** | `microsoft.network/natgateways` | **Microsoft.Network/natGateways**: ByteCount, PacketCount, DroppedPackets, TotalConnectionCount, SNATConnectionCount (Failed) | MeterCategory Virtual Network, NAT Gateway meters; retail | `Microsoft.Network/natGateways/write`, `delete`; `Microsoft.Network/virtualNetworks/subnets/write` |
| 20 | **Public IPs & prefixes** | `microsoft.network/publicipaddresses`, `publicipprefixes` | **Microsoft.Network/publicIPAddresses**: ByteCount, PacketCount, VipAvailability, DDoSAttack, TCPBytesForwardedDDoS | MeterCategory Virtual Network, IP Addresses; retail | `Microsoft.Network/publicIPAddresses/write`, `delete`, `join/action` |
| 21 | **VPN/ExpressRoute gateways & Private Endpoints** | `microsoft.network/virtualnetworkgateways`, `expressroutecircuits`, `privateendpoints` | **Microsoft.Network/virtualNetworkGateways**: TunnelAverageBandwidth, TunnelIngress/EgressBytes, TunnelIngressPacketDropCount, ExpressRouteGatewayCpuUtilization | MeterCategory VPN Gateway, ExpressRoute, Virtual Network; retail gateways + Private Endpoint hourly + data | `Microsoft.Network/virtualNetworkGateways/write`, `connections/write`, `expressRouteCircuits/write`, `privateEndpoints/write` |
| 22 | **Front Door & Azure Firewall** | `microsoft.cdn/profiles` (Front Door), `microsoft.network/azurefirewalls` | **Microsoft.Cdn/profiles**, **Microsoft.Network/azureFirewalls**: RequestCount, ResponseSize, OriginHealthPercentage, FirewallHealth, Throughput, SNATPortUtilization | MeterCategory Azure Front Door Service, Azure Firewall; retail | `Microsoft.Cdn/profiles/write`, `afdEndpoints/purge/action`; `Microsoft.Network/azureFirewalls/write` |
| 23 | **Azure ML & Azure OpenAI (PTU)** | `microsoft.machinelearningservices/workspaces/computes`, `onlineendpoints`, `microsoft.cognitiveservices/accounts/deployments` | **Microsoft.MachineLearningServices/workspaces**, **Microsoft.CognitiveServices/accounts**: CpuUtilization, GpuUtilization, GpuMemoryUtilization, ActiveNodes, ProvisionedManagedUtilizationV2 | MeterCategory Azure Machine Learning, Cognitive Services, Virtual Machines; retail | `Microsoft.MachineLearningServices/workspaces/computes/write`, `stop/action`; `Microsoft.CognitiveServices/accounts/deployments/write` |
| 24 | **Log Analytics & Key Vault** | `microsoft.operationalinsights/workspaces`, `microsoft.keyvault/vaults`, `managedhsms` | **Microsoft.OperationalInsights/workspaces**, **Microsoft.KeyVault/vaults**: DataExportBytes, ServiceApiHit, ServiceApiLatency, SaturationShoebox | MeterCategory Log Analytics, Azure Monitor, Key Vault; retail tiers + HSM key charges | `Microsoft.OperationalInsights/workspaces/write`, `tables/write`; `Microsoft.KeyVault/vaults/write`, `accessPolicies/write` |

### 5.2 Rules by resource type (networking, AI/ML & observability)

#### 17. Load Balancers (Standard SKU)
- **Cost optimization:** `AZ-NET-COST-01`
- **Performance efficiency:** `AZ-NET-PERF-01`
- **Reliability:** `AZ-NET-REL-01`, `AZ-NET-REL-02`
- **Security:** *(TLS/WAF are Application Gateway concerns; LB often paired with NSG / Azure Firewall — see 18, 22)*
- **Operational excellence:** `AZ-NET-OPS-01` (Basic / retiring SKU)

#### 18. Application Gateways & WAF
- **Cost optimization:** `AZ-NET-COST-02`
- **Performance efficiency:** `AZ-NET-PERF-02`
- **Reliability:** `AZ-NET-REL-01`, `AZ-NET-REL-02`
- **Security:** `AZ-NET-SEC-01`
- **Operational excellence:** `AZ-NET-OPS-01` (legacy v1)

#### 19. Azure NAT Gateway
- **Cost optimization:** `AZ-NAT-COST-01`, `AZ-NAT-COST-02`
- **Performance efficiency:** `AZ-NAT-PERF-01`
- **Reliability:** `AZ-NAT-REL-01`
- **Security:** `AZ-NAT-SEC-01`
- **Operational excellence:** `AZ-NAT-OPS-01`

#### 20. Public IP Addresses & Prefixes
- **Cost optimization:** `AZ-PIP-COST-01`
- **Performance efficiency:** `AZ-PIP-PERF-01`
- **Reliability:** `AZ-EIP-REL-01` *(hardcoded / ephemeral public VIP in upstream matrix)*
- **Security:** `AZ-PIP-SEC-01`
- **Operational excellence:** `AZ-PIP-OPS-01`

#### 21. Virtual Network Gateways (VPN & ExpressRoute) & Private Endpoints
- **Gateways — cost optimization:** `AZ-GW-COST-01`, `AZ-GW-COST-02`
- **Gateways — performance efficiency:** `AZ-GW-PERF-01`
- **Gateways — reliability:** `AZ-GW-REL-01`
- **Gateways — security:** `AZ-GW-SEC-01`
- **Gateways — operational excellence:** `AZ-GW-OPS-01`
- **Private endpoints — cost optimization:** `AZ-PE-COST-01`
- **Private endpoints — operational excellence:** `AZ-PE-OPS-01`

#### 22. Azure Front Door & Azure Firewall
- **Azure Firewall — cost optimization:** `AZ-FW-COST-01`
- **Azure Firewall — security:** `AZ-FW-SEC-01`
- **Front Door:** CDN / origin / routing rules — align with Application Gateway & load balancer evaluators and billing lines for the SKU *(no separate `AZ-FD-*` ids in the upstream matrix)*

#### 23. Azure Machine Learning & Azure OpenAI (PTU)
- **Cost optimization:** `AZ-AI-COST-01` … `AZ-AI-COST-03`
- **Performance efficiency:** `AZ-AI-PERF-01`
- **Reliability:** `AZ-AI-REL-01`
- **Security:** `AZ-AI-SEC-01`
- **Operational excellence:** `AZ-AI-OPS-01`

#### 24. Log Analytics Workspaces & Azure Key Vault (incl. Managed HSM)
- **Log Analytics — cost optimization:** `AZ-LOG-COST-01`, `AZ-LOG-COST-02`
- **Log Analytics — operational excellence:** `AZ-LOG-OPS-01`
- **Key Vault — cost optimization:** `AZ-KV-COST-01`
- **Key Vault — performance efficiency:** `AZ-KV-PERF-01`
- **Key Vault — reliability:** `AZ-KV-REL-01`
- **Key Vault — security:** `AZ-KV-SEC-01`

---

## Implementation mapping (CloudSaver)

1. **Ingestion:** Extend `app/collectors/azure_live.py` / ARG paths so `inventory[].evidence` carries metrics series, Cost Management joins, retail lookups, and Activity events required by each rule family.
2. **AnalysisService:** Add evaluators or **declarative JSON** (`CLOUDSAVER_ANALYSIS_DECLARATIVE_RULES`) + **platform hooks** for spec ids not yet first-class `AZURE_*` catalog rules.
3. **Catalog:** When promoting a spec rule to product, add **`RULE_DISPLAY_NAMES`**, `FAMILIES`/`definitions()`, `ACTION_CLASS_BY_RULE`, `route_for_rule`, and regenerate **`docs/ANALYSIS_RULES_MASTER.md`** per repository process.

---

*This document is the extended Azure billable-resource & 5-pillar catalog for agents; threshold tuning belongs in implementation tickets per rule id.*
