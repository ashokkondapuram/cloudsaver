# Microsoft Azure — Well-Architected agent specification

**Audience:** Azure FinOps & Well-Architected backend subagents (Python 3.12+ / FastAPI / Pydantic / azure-mgmt-* / httpx).

**CloudSaver paths:** `app/scanner.py`, `app/collectors/azure_live.py`, `app/collectors/azure_monitor_batch.py`; target: `app/adapters/azure/` + `app/rules/azure_rules.py`. **Analysis:** `app/analysis_service/*`.

**Reliability:** Prefer ARM REST + `provider_retry`; Resource Graph for discovery; retail prices via `app/domain/pricing/retail_cache.py` where applicable.

---

## 1. Subagent prompt (Azure)

**Role:** Azure FinOps & Well-Architected Backend Subagent

**Objective:** Implement `app/adapters/azure/` and `app/rules/azure_rules.py` using **azure-identity**, **azure-mgmt-resourcegraph**, **azure-mgmt-monitor**, **azure-mgmt-costmanagement**, **azure-mgmt-advisor**, **httpx**.

### Data ingestion contracts

| Stream | Contract |
|--------|----------|
| **Discovery** | Resource Graph **Resources**; optional **Resource Changes** |
| **Metrics** | Monitor Metrics — batch up to **50** resources per **Metrics List at subscription scope (POST)** |
| **Cost** | Cost Management **Usage** — ActualCost / AmortizedCost + **Retail Prices** API (`api-version=2023-01-01-preview`) |
| **Activity** | Activity Log — 90d control-plane mutations |
| **Signals** | Advisor **Recommendations - List** (see `app/collectors/cloud_advisor.py` when `CLOUDSAVER_CLOUD_ADVISOR_ENABLED`) |

---

## 2. Discovery, metrics, cost/retail & drift mapping

### 2.1 Resource catalog table

| Resource category | ARG type / ARM | Monitor namespace / metrics (examples) | CM & retail filters | Activity Log `operationName.value` (examples) |
|-------------------|----------------|----------------------------------------|---------------------|-----------------------------------------------|
| **VMs & VMSS** | `microsoft.compute/virtualmachines`, `virtualmachinescalesets` | Microsoft.Compute/virtualMachines, VMSS: Percentage CPU, Available Memory Bytes, Network In/Out, OS Disk IOPS %, VmAvailabilityMetric | MeterCategory=Virtual Machines; retail: serviceName, armSkuName, armRegionName, priceType=Consumption | …/virtualmachines/write, delete, deallocate/action, powerOff/action, VMSS write, scaleOut/action |
| **ASP, Functions, AKS** | `microsoft.web/serverfarms`, `microsoft.web/sites`, `microsoft.containerservice/managedclusters` | Serverfarms / Sites / managedClusters: CpuPercentage, MemoryPercentage, HttpQueueLength, FunctionExecutionCount, node_cpu_usage_percentage, cluster_autoscaler_unschedulable_pods_count | MeterCategory App Service, Functions, Container Service | …/serverfarms/write, sites/config/write, managedClusters/write, agentPools/write |
| **Disks, snapshots, storage** | `microsoft.compute/disks`, `snapshots`, `microsoft.storage/storageaccounts` | Disks + Blob metrics: disk read/write ops, BurstIOCreditPercentage, UsedCapacity, BlobCapacity, Transactions, SuccessServerLatency | MeterCategory=Storage; retail product/region | disks/write, beginGetAccess, snapshots/write, storage write, listKeys, managementPolicies/write |
| **SQL, Cosmos, Postgres/MySQL, Redis** | SQL DB, Cosmos DB, flexible servers, Redis | Per-resource metrics: cpu_percent, dtu_*, NormalizedRUConsumption, memory_percent, serverLoad, evictedkeys | MeterCategory per service; retail serviceName | databases/write, firewallRules/write, Cosmos throughput write, Postgres/MySQL write, Redis write, flushCache |
| **LB, App Gateway, NAT, public IP, gateways** | loadBalancers, applicationGateways, natGateways, publicIPAddresses, virtualNetworkGateways | ByteCount, UsedSnatPorts, AllocatedSnatPorts, VipAvailability, TotalRequests, CapacityUnits, HealthyHostCount | MeterCategory Load Balancer, Application Gateway, Virtual Network, VPN, ExpressRoute | corresponding /write and NSG securityRules/write |

### 2.2 Azure 5-pillar deterministic rules (summary)

| Resource group | Cost | Performance | Reliability | Security | Operational excellence |
|----------------|------|-------------|-------------|----------|------------------------|
| **Compute / PaaS / AKS** | Stopped-not-deallocated VM; idle/rightsize VM/ASP; empty paid ASP; AKS low node CPU | Disk IOPS ceiling; App Service queue/socket pressure; unschedulable pods | Non-zonal prod; AKS free tier in prod; HA gaps | Encryption-at-host; AKS API exposure; min TLS / httpsOnly | Missing Monitor Agent; AKS upgrade channel none; patch mode |
| **Disks & storage** | Unattached disk; premium vs standard when IOPS low; hot blob without lifecycle; wrong snapshot SKU | Burst depletion; throttling errors | LRS in prod; soft delete/versioning | Public blob access; shared keys; active SAS | Key rotation |
| **Data & networking** | SQL/Cosmos idle; unassociated PIP; empty LB/AppGW backends | SNAT pressure; Cosmos hot partition; Redis load/evictions | Single-zone DB; HA off on prod data paths | Open firewalls; disableLocalAuth gaps; legacy DB versions | Maintenance windows |

Stable `rule_id` values: see `app/resource_catalog.py` and `app/analysis_rules.py` contracts.

---

## 3. Platform-specific extra rules

Deploy custom **pillar** checks without forking: register **`evaluate_platform`** (see `docs/ANALYSIS_SERVICE.md`).
