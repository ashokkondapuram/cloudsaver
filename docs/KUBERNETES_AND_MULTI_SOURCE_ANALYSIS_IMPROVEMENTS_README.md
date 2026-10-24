# Source snapshot

Source: https://docs.google.com/document/d/11i_KWMhkr0u1Ug1N0ZR2D_kQC_-A_FCwEURUfT2WmWE
Revision: AHj4eMQWpLDQZNTix4OjYK__hMNjD1yuqxEEV_7G9g6MBOBvcT3bGli2QutX-AGjRWimCgo18f_qu_0siv9b3-k86XMn03W82TYhHe5rQ5E

CloudSaver & Platform Portal: Comprehensive Code, Multi-Source Data Ingestion, Kubernetes Analysis & AI Foundry Improvement Guide

Document type: Actionable engineering specification and code-improvement blueprint.
Source baseline: https://github.com/ashokkondapuram/project, commit 6e0de85fe321aa51d97c8dfb734c3e9532e85a71.
Scope: Concrete code, API, database, and UI/UX improvements across the FastAPI backend (app/, services/), the Platform Identity & Control Plane (platform/identity/, platform/portal/), and the Customer Web Dashboard (web-dashboard/), featuring Multi-Source Cloud Telemetry Federation, Deep Kubernetes Resource & Cluster Analysis, Multi-Cloud Resource Analysis, and AI Foundry Configuration Settings (Azure AI Foundry, AWS Bedrock, GCP Vertex AI).

Contents

Baseline Audit & Current Implementation State (6e0de85)

Deep-Dive Improvement A: Multi-Source Data Ingestion & Telemetry Federation Engine

2.1 Multi-Source Collector Architecture (Inventory, Time-Series, Activity Logs, Billing & Cost)

2.2 Provider-Specific Multi-Source Pipelines (Azure, AWS, GCP, Kubernetes)

2.3 Source Provenance, Freshness & Cross-Source Reconciliation Ledger

Deep-Dive Improvement B: Extensive Kubernetes Resource, Workload & Cluster Analysis

3.1 Multi-Source Kubernetes Collector Pipeline (K8s API, KSM, cAdvisor/Prometheus, OpenCost)

3.2 Exact PromQL & Metric Contracts (CPU Rate, CFS Throttling, Working Set, OOMKills, PVC Occupancy)

3.3 Comprehensive Eight-Rule Kubernetes Analysis Catalog (Workloads, HPA/PDB, Node Pools, PVCs, LBs)

3.4 Cloud-to-Cluster Cost Reconciliation (Node Backing Costs vs. Namespace/Pod Allocation)

3.5 Dedicated Kubernetes Analysis Workspace UI (web-dashboard/app/kubernetes/)

Deep-Dive Improvement C: Multi-Cloud Resource Analysis, Evidence Contracts & Service Workspaces

4.1 Canonical Inventory Union & Seven-Counter Scan Coverage Manifest

4.2 Eight-State Rule Evaluation Outcome Taxonomy & 5-Minute Time-Series Contracts

4.3 Typed Dependency Graph, Protection Intent & Mutually Exclusive Cost Opportunity Groups

4.4 Detailed Specification of the Eight Initial Azure Rules & Service Analysis Workspaces

Deep-Dive Improvement D: Multi-Cloud AI Foundry Configuration & Governance Settings

5.1 Provider-Specific Configuration Contracts (Azure AI Foundry, AWS Bedrock, GCP Vertex AI)

5.2 Source-Provider Affinity (same_cloud_only), Token Budgets & Non-Destructive Diagnostics

5.3 Shared Knowledge Retrieval at Inference, Confidence Calibration & Citation Quality Gates

Priority 3: End-to-End Customer Access & Delegated Key Administration UI (/api/v1/customer/*)

Priority 4: Commercial Platform Billing Completion & Lapsed-Account Enforcement

Priority 5: Enterprise Entra/OIDC Sign-In, Capability Envelopes & Step-Up Authentication

Phased Implementation Sequence, Migrations & Verification Matrix

1. Baseline Audit & Current Implementation State (6e0de85)

Inspecting commit 6e0de85 across app/, services/, platform/identity/, web-dashboard/, and platform/portal/ establishes what is already shipped versus where extensive code improvements are required:

Subsystem

Shipped in Commit 6e0de85

Remaining Code & Architecture Gaps to Close

Kubernetes Resource Analysis

Basic container CPU and memory request check using 14 days of hourly Prometheus samples (requests > P95 * 1.5).

Single-source & incomplete coverage: lacks multi-source correlation across kube-state-metrics, cAdvisor CPU CFS throttling, OOMKill termination history, HPA/VPA/PDB scaling constraints, Node Pool bin-packing fragmentation, unmounted/low-occupancy PVCs, orphaned LoadBalancer services, and OpenCost-to-Cloud-Billing reconciliation.

Multi-Source Data Ingestion

Point-in-time inventory readers for Azure ARG, AWS Boto3, and GCP Cloud Asset Inventory; manual JSON billing import.

Missing multi-source telemetry & event correlation: detachment and stop durations rely on snapshot observations rather than authoritative Activity/CloudTrail/Audit logs; metric collectors lack unified source provenance and cross-source reconciliation diagnostics.

Cloud Resource Analysis & Rules

Azure live scans persist inventory rows; five-pillar deterministic checks; platform/identity/analysis/admin.py; app/effective_rules.py; operator RulesTab.tsx.

Non-Azure collectors emit only finding-backed rows; missing 7-counter coverage manifests, 5-minute time-series interval validation ($\ge 95%$ coverage), typed dependency graphs, mutually exclusive cost opportunity groups, dedicated Service Analysis Workspaces, and a customer-facing Analysis Rules UI.

Multi-Cloud AI Foundry Settings

Opt-in keyless Azure OpenAI, AWS Bedrock Converse, and GCP Vertex adapters; SQL attempt reservation & token ledger (0009_enterprise_evidence); KnowledgeView.tsx.

Missing self-service AI Foundry configuration UI & API (WorkspaceSettings.tsx / app/settings_api.py) for Azure AI Foundry, AWS Bedrock (with Guardrails), and GCP Vertex AI; missing POST /api/v1/settings/ai/test-connection diagnostics, same_cloud_only routing enforcement, and inference-time retrieval from the published knowledge store.

Customer-Managed Access & Billing

i0007_client_access migration; 18 /api/v1/customer/* routes in app/onboarding_api.py; i0002_billing–i0005; POST/PATCH /admin/v1/plans.

Zero dedicated frontend UI for the 18 /api/v1/customer/* routes; platform/identity/billing/importer.py is absent; missing Portal Plan Catalog UI, initial subscription overrides, HTTP 409 race mapping, and automated lapsed-account evaluation.

2. Deep-Dive Improvement A: Multi-Source Data Ingestion & Telemetry Federation Engine

2.1 Multi-Source Collector Architecture

Accurate resource analysis requires combining five distinct data planes per cloud and cluster environment rather than relying on a single inventory snapshot:

+------------------------------------------------------------------------------------------------------+

|                          CloudSaver Multi-Source Data Federation Engine                              |

+------------------------------------------------------------------------------------------------------+

        ^                      ^                        ^                        ^                 ^

        |                      |                        |                        |                 |

+---------------+    +-------------------+    +--------------------+    +----------------+  +--------------+

| 1. Control    |    | 2. High-Res       |    | 3. State Transition|    | 4. Protection &|  | 5. Financial |

| Plane Config  |    | Time-Series       |    | & Activity Logs    |    | Dependency APIs|  | & Cost Feeds |

+---------------+    +-------------------+    +--------------------+    +----------------+  +--------------+

| - Azure ARG   |    | - Azure Monitor   |    | - Azure Activity   |    | - ARM Locks    |  | - FOCUS 1.0  |

| - AWS Config/ |    | - AWS CloudWatch  |    | - AWS CloudTrail   |    | - Backup/ASR   |  | - Retail API |

|   EC2/RDS API |    | - GCP Monitoring  |    | - GCP Audit Logs   |    | - Target Groups|  | - OpenCost / |

| - GCP Asset   |    | - Prometheus /    |    | - K8s Event API &  |    | - K8s HPA/PDB/ |  |   Kubecost   |

| - K8s API/KSM |    |   AMP / GMP / Mimir|   |   cAdvisor Termin. |    |   EndpointSlice|  |   Allocation |

+---------------+    +-------------------+    +--------------------+    +----------------+  +--------------+

2.2 Provider-Specific Multi-Source Pipelines (app/collectors/)

Organize collectors under app/collectors/ with explicit per-source adapters and independent circuit breakers so a failure in a secondary telemetry source marks affected rules insufficient_evidence without aborting the base inventory snapshot:

Environment

Source 1: Inventory & Topology

Source 2: Time-Series Metrics (5-Min Aggregates)

Source 3: State Transition & Audit History

Source 4: Cost & Billing Attribution

Microsoft Azure

Azure Resource Graph (ARG) KQL + ARM Compute/Network/Web APIs (locks, snapshots, backend pools).

Azure Monitor Metrics REST API (interval=PT5M, aggregation=Maximum,Average,Total) + Log Analytics InsightsMetrics / Perf (guest memory & disk queue).

Azure Monitor Activity Logs (Microsoft.Compute/disks/detach, virtualMachines/deallocate/action) establishing exact detachment/stop timestamps.

Ingested FOCUS 1.0 Azure Cost Management exports + live Azure Retail Prices API (prices.azure.com) cached by (region, skuName, meterName).

Amazon Web Services

AWS EC2, EBS, RDS, ELBv2, NAT Gateway & Resource Explorer paginated APIs via STS AssumeRole.

Amazon CloudWatch GetMetricData (Period=300s) + CloudWatch Agent (mem_used_percent, disk_used_percent) + RDS Performance Insights.

AWS CloudTrail LookupEvents (DetachVolume, StopInstances, StopDBInstance) establishing exact transition durations rather than creation age.

Ingested FOCUS 1.0 AWS CUR 2.0 records + AWS Price List Service API regional SKU rates.

Google Cloud Platform

Cloud Asset Inventory (SearchAllResources, ExportAssets) + Compute Engine & Cloud SQL Admin APIs.

Google Cloud Monitoring API (monitoring.projects.timeSeries.query with 5-minute alignment windows).

Cloud Audit Logs (cloudaudit.googleapis.com/activity for disks.detach, instances.stop) establishing authoritative idle duration.

GCP BigQuery Cloud Billing Export (standard/detailed usage cost) + Cloud Billing Catalog API.

Kubernetes (AKS / EKS / GKE / Self-Hosted)

Kubernetes API Server (apps/v1, core/v1, autoscaling/v2, policy/v1, storage.k8s.io/v1) + kube-state-metrics (KSM).

Managed Prometheus (Azure AMP, AWS AMP, GCP GMP), self-hosted Prometheus/Thanos/Mimir/VictoriaMetrics, or Container Insights KQL.

kube_pod_container_status_last_terminated_reason (OOMKilled, Error), K8s Warning Events (FailedScheduling, Evicted), and rollout revision timestamps.

OpenCost / Kubecost /allocation API reconciled against underlying cloud VM/Disk FOCUS billing records.

2.3 Source Provenance, Freshness & Cross-Source Reconciliation Ledger

Every persisted resource observation and finding must attach a structured data_sources provenance manifest (app/schemas.py):

source_id & collector_type: e.g., azure_arg, azure_monitor_metrics, azure_activity_log, prometheus_range_api, opencost_allocation, focus_billing_import.

observed_window_start / observed_window_end & freshness_seconds: Exact time bounds of the fetched series.

coverage_ratio & sample_counts: valid_samples / expected_samples (e.g., 8,590 / 8,640 5-minute intervals = 99.4%).

reconciliation_status:

verified_multi_source: State, transition timestamp, and telemetry agree across inventory, logs, and metrics.

partial_telemetry: Inventory state is verified, but guest memory or transition logs are unavailable (insufficient_evidence for dependent rules).

source_conflict: E.g., KSM reports a PVC bound while cloud disk API reports unattached; flags an explicit diagnostic warning and blocks automated remediation.

3. Deep-Dive Improvement B: Extensive Kubernetes Resource, Workload & Cluster Analysis

3.1 Multi-Source Kubernetes Collector Pipeline (app/scanner_k8s.py)

Upgrade CloudSaver's Kubernetes analyzer from a single-metric container check to a full-stack cluster, node-pool, workload, autoscaler, storage, and networking analyzer:

+---------------------------------------------------------------------------------------------------+

|                        Kubernetes Multi-Source Collector (app/scanner_k8s.py)                     |

+---------------------------------------------------------------------------------------------------+

         |                                      |                                       |

         v                                      v                                       v

+------------------------------+   +---------------------------------+   +--------------------------+

| 1. K8s API & KSM Topology    |   | 2. Time-Series Telemetry        |   | 3. Cost & Cloud Backing  |

| - Workloads (Deploy/STS/DS)  |   | - PromQL / AMP / GMP / KQL      |   | - OpenCost /allocation   |

| - Requests, Limits & QoS     |   | - 5m CPU Rate & CFS Throttling  |   | - Cloud Provider Node ID |

| - HPA, VPA & PDB Constraints |   | - Working Set & RSS Memory      |   |   (AKS VMSS / EKS ASG /  |

| - Nodes, Taints & Allocatable|   | - OOMKill & Eviction Counters   |   |    GKE MIG)              |

| - PVCs, PVs & StorageClasses |   | - Kubelet Volume Used/Cap Bytes |   | - Cloud Disk & LB mapping|

| - Services & EndpointSlices  |   | - Ingress / CNI Network Bytes   |   |   via providerID / CSI   |

+------------------------------+   +---------------------------------+   +--------------------------+

Supported Telemetry Backends (settings.kubernetes_sources):

Prometheus HTTP API (prometheus_http): Queries /api/v1/query and /api/v1/query_range using bearer token, mTLS, or keyless cloud federation.

Azure Monitor Managed Prometheus & Container Insights (azure_amp_kql): Uses workspace Entra Managed Identity to query Azure Monitor Workspace PromQL endpoints and Log Analytics KubePodInventory / Perf tables.

Amazon Managed Service for Prometheus (aws_amp_sigv4): Uses STS AssumeRoleWithWebIdentity and SigV4-signed requests against aps-workspaces.<region>.amazonaws.com.

Google Cloud Managed Service for Prometheus (gcp_gmp_monitoring): Uses GCP Workload Identity Federation against monitoring.googleapis.com/v1/projects/{project}/location/global/prometheus/api/v1/*.

3.2 Exact PromQL & Metric Contracts

All Kubernetes utilization and reliability evaluations must execute standardized, unit-normalized queries over a 14-to-30 day window at 5-minute step resolution ($\ge 95%$ valid sample coverage):

Metric Signal

Canonical PromQL / Metric Expression

Unit & Analytical Purpose

Container CPU Usage (5m Rate)

sum by (cluster, namespace, pod, container) (rate(container_cpu_usage_seconds_total{container!="", image!=""}[5m]))

Cores (cores). Aggregated per workload controller via kube_pod_owner join to compute P50, P95, and P99 CPU cores.

Container CPU CFS Throttling Ratio

sum by (cluster, namespace, pod, container) (rate(container_cpu_cfs_throttled_periods_total{container!=""}[5m])) / sum by (cluster, namespace, pod, container) (rate(container_cpu_cfs_periods_total{container!=""}[5m]))

Ratio (0.0–1.0). Safety Gate: If P95 throttling $> 0.02$ ($2%$), CPU request/limit reduction is blocked and throttling remediation is surfaced instead.

Container Memory Working Set

max by (cluster, namespace, pod, container) (container_memory_working_set_bytes{container!="", image!=""})

Bytes (MiB/GiB). Used rather than container_memory_usage_bytes because working set excludes evictable page cache and matches kubelet OOM eviction decisions.

OOMKill & CrashLoop History (30d)

sum by (cluster, namespace, pod, container) (changes(kube_pod_container_status_restarts_total[30d])) paired with kube_pod_container_status_last_terminated_reason{reason="OOMKilled"}

Count. Safety Gate: Any OOMKilled event in the observation window hard-blocks memory downsizing and triggers a reliability risk finding.

Workload Configured Requests & Limits

kube_pod_container_resource_requests{resource="cpu"|"memory"} and kube_pod_container_resource_limits{resource="cpu"|"memory"}

Cores / Bytes. Joined with kube_pod_owner and kube_replicaset_owner to attribute pod specs to parent Deployment, StatefulSet, or DaemonSet.

PVC Volume Occupancy & Inodes

kubelet_volume_stats_used_bytes / kubelet_volume_stats_capacity_bytes and kubelet_volume_stats_inodes_used / kubelet_volume_stats_inodes

Ratio (0.0–1.0). Identifies over-provisioned persistent volumes ($< 15%$ used) or volumes approaching capacity exhaustion ($> 85%$).

Node Allocatable vs. Requested vs. Actual

kube_node_status_allocatable{resource="cpu"|"memory"}, sum by (node) (kube_pod_container_resource_requests), and node_cpu_seconds_total / node_memory_MemAvailable_bytes

Cores / Bytes. Separates Reservation Slack (Requested - P95 Actual) from Unallocated Node Slack (Allocatable - Requested).

3.3 Comprehensive Eight-Rule Kubernetes Analysis Catalog

Register eight first-class Kubernetes rules in platform/identity/analysis/ and app/effective_rules.py, each evaluated across all five architectural pillars (Cost, Reliability, Performance, Security, Operations):

Rule ID & Descriptive Name

Required Multi-Source Evidence

Trigger Logic, Safety Gates & Recommended Action

1. K8S_CONTAINER_CPU_OVERREQUEST

Container CPU request rightsizing review

14–30d 5-min CPU rate series ($\ge 95%$ coverage), KSM requests/limits, CFS throttling series, HPA spec (autoscaling/v2).

request_cpu > P95_cpu * 1.5 and excess $> 100\text{m}$ per replica. Blocked if P95 CFS throttling $> 2%$ or if workload is scaled by an HPA whose target CPU utilization % would constantly trigger scale-out after lowering request_cpu (calculates coordinated HPA + request adjustment).

2. K8S_CONTAINER_MEMORY_OVERREQUEST

Container memory working-set rightsizing review

14–30d 5-min container_memory_working_set_bytes ($\ge 95%$ coverage), KSM memory requests/limits, 30d OOMKilled counter.

request_memory > P99_working_set * 1.35 and excess $> 256\text{MiB}$ per replica. Hard-blocked if oom_kill_count_30d > 0 or if container command includes fixed JVM -Xmx / GOMEMLIMIT flags that match current request (warns to adjust runtime heap flag alongside K8s manifest).

3. K8S_CONTAINER_UNDERPROVISIONED_RISK

Throttled or OOM-vulnerable workload reliability review

CFS throttling series, working-set vs. limit ratio, OOMKilled / restart counts, QoS class (Guaranteed, Burstable, BestEffort).

Reliability/Performance rule (cost_opportunity = $0): flags workloads with oom_kill_count_30d > 0, P95 memory working set $> 90%$ of limit, P95 CPU throttling $> 10%$, or production workloads running as BestEffort without requests/limits.

4. K8S_HPA_PDB_CONFLICT_OR_IDLE_FLOOR

Autoscaler floor & PodDisruptionBudget lock review

kube_horizontalpodautoscaler_spec_*, kube_horizontalpodautoscaler_status_*, kube_poddisruptionbudget_status_*, workload replica series.

Flags (a) HPAs pinned at minReplicas for $14\text{d}$ where P95 utilization is $< 15%$ of target (minReplicas over-provisioned), or (b) PDBs with disruptions_allowed == 0 blocking cluster autoscaler / Karpenter node consolidation.

5. K8S_NODE_POOL_FRAGMENTATION_WASTE

Node pool bin-packing & underutilized node review

kube_node_info (provider_id), node allocatable vs. pod requests vs. node actual CPU/RAM, DaemonSet overhead, PDB blocks.

Identifies node pools where total pod requests are $< 45%$ of allocatable capacity or where stranded single-pod non-evictable workloads prevent node scale-down. Quantifies DaemonSet tax (% of node capacity consumed by cluster agents).

6. K8S_ABANDONED_WORKLOAD_OR_NAMESPACE

Zero-traffic workload & stale preview namespace review

Workload CPU/network I/O series, Ingress / Service / Istio request counters (istio_requests_total / NGINX / Envoy), last rollout age.

Flags non-system Deployment/StatefulSet or ephemeral PR/staging namespaces (env=preview-*, pr-*) with zero external/internal network requests and flatlined CPU over $14\text{d}$.

7. K8S_PVC_UNMOUNTED_OR_LOW_OCCUPANCY

Orphaned PVC & over-provisioned volume review

kube_persistentvolumeclaim_info, kube_pod_spec_volumes_persistentvolumeclaims_info, kubelet_volume_stats_used_bytes, CSI storage class.

Flags (a) Bound PVCs not mounted by any running/scheduled Pod or CronJob for $\ge 7\text{d}$, or (b) PVCs $\ge 100\text{GiB}$ with P99 occupancy $< 10%$ over $30\text{d}$ (where storage class supports volume expansion/shrinking or migration).

8. K8S_ORPHANED_LOADBALANCER_SERVICE

Empty-endpoint Kubernetes LoadBalancer service review

kube_service_info{type="LoadBalancer"}, kube_endpoint_address_available, cloud LB ARN/URI mapping.

Flags Service of type: LoadBalancer or Ingress backed by a paid cloud load balancer (AWS ALB/NLB, Azure Standard LB, GCP Forwarding Rule) that has 0 available endpoints continuously for $\ge 7\text{d}$.

3.4 Cloud-to-Cluster Cost Reconciliation (app/k8s_cost_reconciler.py)

Container rightsizing does not automatically reduce the cloud invoice until cluster nodes scale down or commitments are adjusted. CloudSaver separates Allocation Opportunity from Realizable Node Savings:

Node Backing Cost Linkage:

Maps each Kubernetes Node's spec.providerID (azure:///subscriptions/.../virtualMachineScaleSets/..., aws:///us-east-1a/i-..., gce://project/zone/instance) to its exact cloud inventory row and FOCUS 1.0 billing record (billed_cost_usd, amortized_cost_usd, pricing_category: OnDemand | Spot | SavingsPlan | Reserved).

Three-Tier Kubernetes Cost Breakdown:

Workload Used Cost: Cost of CPU/RAM/Storage actually consumed (P95/mean) by the container.

Workload Request Slack Cost: Cost of resources requested by the pod manifest (requests.cpu, requests.memory) but left idle (Request - Used).

Cluster Unallocated Slack Cost: Cost of node allocatable capacity not requested by any pod (Allocatable - Total Requests), governed by Cluster Autoscaler / Karpenter / NAP settings.

Mutually Exclusive Cluster-Cloud Opportunity Grouping:

Links Kubernetes node-pool consolidation findings and underlying cloud VMSS/ASG/MIG rightsizing findings under a shared opportunity_group_id (cluster_pool:{cluster_id}:{pool_name}) so CloudSaver never double-counts pod CPU request reductions on top of node termination savings.

3.5 Dedicated Kubernetes Analysis Workspace UI (web-dashboard/app/kubernetes/)

Add a dedicated Kubernetes & Containers workspace in web-dashboard/:

Cluster & Data Source Health Banner: Shows connected clusters (AKS, EKS, GKE, self-hosted), active telemetry sources (KSM, Prometheus/AMP/GMP, OpenCost, Cloud Node Mapping), 7-counter coverage denominators, and sample completeness %.

Three-Layer Capacity Bar: Visualizes total cluster Physical/Allocatable Capacity $\to$ DaemonSet Overhead $\to$ Workload Requested $\to$ Actual P95 Used for both CPU cores and Memory GiB.

Namespace & Workload Explorer: Filterable by Cluster, Namespace, Controller Type (Deployment, StatefulSet, DaemonSet, Job), QoS Class, HPA/PDB status, OOMKill risk, and Slack Cost.

Manifest & Helm/Kustomize Patch Drawer: Generates reviewable, non-destructive YAML diffs (resources.requests, resources.limits, coordinated HPA target adjustments) alongside kubectl diff and GitOps PR previews.

4. Deep-Dive Improvement C: Multi-Cloud Resource Analysis, Evidence Contracts & Service Workspaces

4.1 Canonical Inventory Union & Seven-Counter Scan Coverage Manifest

Across all cloud and Kubernetes collectors (app/scanner.py, app/scanner_aws.py, app/scanner_k8s.py, services/scanner.py):

Persist canonical inventory rows for every discovered resource in scope—not only resources with active findings.

Persist a ScanCoverageManifest per provider and service recording discovered_count, in_scope_count, evaluated_count, insufficient_evidence_count, excluded_count, unsupported_count, and failed_scopes.

4.2 Eight-State Rule Evaluation Outcome Taxonomy & 5-Minute Time-Series Contracts

Every rule evaluation records one of eight explicit states (condition_detected, condition_not_detected, insufficient_evidence, not_applicable, disabled_by_policy, excluded_by_exception, unsupported_by_collector, evaluation_failed).

Utilization rules enforce TimeSeriesEvidenceContract (app/telemetry_contract.py): 5-minute intervals over a 30-day window (14-day minimum for K8s), $\ge 95%$ valid sample coverage, max gap $\le 60\text{m}$, without filling missing points with zero or substituting averages for P95/P99 peaks.

4.3 Typed Dependency Graph, Protection Intent & Mutually Exclusive Cost Opportunity Groups

Persist typed relationships (vm_to_disk, nic_to_ip, ip_to_lb_or_nat, app_to_plan, pvc_to_pv_to_cloud_disk, k8s_service_to_cloud_lb, k8s_node_to_cloud_vm, resource_to_lock_or_backup) with explicit verification_state (verified, inferred, stale, unavailable).

Group overlapping recommendations under opportunity_group_id so rollup totals sum only the maximum mutually compatible opportunity.

4.4 Detailed Specification of the Eight Initial Azure Rules & Service Analysis Workspaces

Implement the eight foundational Azure rules across Managed Disks (AZURE_DISK_UNATTACHED_RETENTION, AZURE_DISK_PROVISIONED_PERFORMANCE), Public IPs (AZURE_PUBLIC_IP_UNASSOCIATED, AZURE_PUBLIC_IP_ASSOCIATED_IDLE), Virtual Machines (AZURE_VM_STOPPED_RESIDUAL_COST, AZURE_VM_RIGHTSIZING_UTILIZATION), and App Service Plans (AZURE_ASP_EMPTY_PAID_PLAN, AZURE_ASP_UNDERUTILIZED_SKU), and surface them in dedicated Service Analysis Workspaces (web-dashboard/app/services/[service]/page.tsx) with customer-delegated rule override previews (POST /api/v1/rules/preview).

5. Deep-Dive Improvement D: Multi-Cloud AI Foundry Configuration & Governance Settings

5.1 Provider-Specific Configuration Contracts (app/settings_api.py & AIFoundryConfigurationEditor.tsx)

Extend PUT /api/v1/settings and WorkspaceSettings.tsx with a versioned, keyless ai_foundry block across all three cloud AI platforms:

Cloud AI Provider

Keyless Configuration Fields (settings.ai_foundry.providers)

Validation, Security & Diagnostic Checks

Azure AI Foundry

(Azure OpenAI / AI Services)

enabled, endpoint_url (.services.ai.azure.com or .openai.azure.com), deployment_name (gpt-4o, o3-mini), api_version (2024-10-21), region, deployment_sku (Standard_PAYG | Provisioned_PTU), auth_binding (workspace_managed_identity | custom_client_id), ai_search_knowledge_endpoint

Uses federated Entra Managed Identity token exchange (https://cognitiveservices.azure.com/.default with Cognitive Services OpenAI User RBAC). Enforces Zero Data Retention (ZDR) disclosure.

AWS Bedrock

(Converse API & Guardrails)

enabled, region, model_id (Model ID or Cross-Region Inference Profile ARN, e.g., us.anthropic.claude-3-5-sonnet-20241022-v2:0), guardrail_id, guardrail_version ('DRAFT' blocked in prod), role_arn, external_id, vpc_endpoint_url

Uses keyless STS AssumeRoleWithWebIdentity with least-privilege bedrock:InvokeModel and bedrock:ApplyGuardrail permissions; rejects static AWS access keys.

GCP Vertex AI

(Gemini Enterprise)

enabled, project_id, location (us-central1, europe-west4), model_id (gemini-1.5-pro-002, gemini-1.5-flash-002), service_account_email, workload_identity_pool_provider, vpc_sc_enforced

Uses GCP STS Workload Identity Federation (roles/aiplatform.user) with VPC Service Controls boundary tracking and strict JSON schema output validation.

5.2 Source-Provider Affinity (same_cloud_only), Token Budgets & Non-Destructive Diagnostics

Source-Provider Routing (routing_mode): Defaults to same_cloud_only (Azure resource evidence is evaluated strictly by Azure AI Foundry; AWS by Bedrock; GCP by Vertex AI; Kubernetes by the cluster's hosting cloud provider).

Non-Destructive Connection Probe (POST /api/v1/settings/ai/test-connection): Validates federated token acquisition, model RBAC/IAM permissions, deployment availability, and guardrail status without sending customer telemetry, returning actionable categories (identity_federation_failed, missing_model_rbac, deployment_or_model_not_found, guardrail_not_found, quota_or_ptu_exhausted, network_or_privatelink_blocked).

5.3 Shared Knowledge Retrieval at Inference, Confidence Calibration & Citation Quality Gates

Separate Knowledge Database (KNOWLEDGE_DATABASE_URL): Isolates published guidance patterns (including Kubernetes HPA/PDB/OOMKill and cloud disk/VM patterns) with zero foreign keys to tenant tables and a dual-reviewer redaction gate (KnowledgeReviewer + PrivacyReviewer).

Strict Citation Verification & Confidence Calibration: Injects published patterns at inference time, rejects model output citing non-existent check_ids or publication_ids, and assigns deterministic confidence bands (HIGH, MEDIUM, LOW, INSUFFICIENT_EVIDENCE).

6. Priority 3: End-to-End Customer Access & Delegated Key Administration UI (/api/v1/customer/*)

Wire all 18 customer_access_router endpoints in app/onboarding_api.py to dedicated screens under web-dashboard/components/customer-access/:

CustomerUsersDirectory.tsx (invite up to 20/day, suspend, reactivate), OwnershipTransferModal.tsx, WorkspaceMembershipsTable.tsx (optimistic concurrency via membership_version), ServiceAccountsManager.tsx (up to 25 non-human principals), DelegatedKeysManager.tsx & ScopeRestrictionsBuilder.tsx (subscription/account/project/cluster scope restrictions enforced in narrow()), and CustomerAuditLogView.tsx (before-cursor pagination + CSV export).

7. Priority 4: Commercial Platform Billing Completion & Lapsed-Account Enforcement

Close the runtime billing gaps documented in PLATFORM_BILLING.md:

Implement platform/identity/billing/importer.py (exact Decimal validation, idempotent replay), accept initial entitlement overrides on POST /admin/v1/subscriptions, map i0005 partial-unique index race conditions to HTTP 409 Conflict, add the automated time-based lapsed-account evaluator (active $\to$ past_due $\to$ suspended + issuance_blocked), and build the Portal Plan Catalog CRUD UI (PlanCatalogAdmin.tsx).

8. Priority 5: Enterprise Entra/OIDC Sign-In, Capability Envelopes & Step-Up Authentication

Bind human users in directory.users by immutable (idp_issuer, idp_subject) with Authorization Code + PKCE sign-in, return fine-grained capability arrays (scans.run, resources.read, rules.override, ai.configure, ai.invoke, iac.export, users.invite, keys.issue, keys.revoke, audit.export) in /internal/v1/keys/verify, and enforce step-up authentication (max_age=300) on ownership transfer and workspace-wide key revocations.

9. Phased Implementation Sequence, Migrations & Verification Matrix

Phase

Target Modules

Key Deliverables & Completion Criteria

Phase 1: Multi-Source Collectors & Deep Kubernetes Analysis

app/collectors/*, app/scanner_k8s.py, app/k8s_cost_reconciler.py, web-dashboard/app/kubernetes/*

Multi-source provenance ledger; KSM + Prometheus/AMP/GMP + OpenCost federation; all 8 Kubernetes rules (CFS throttling, OOMKill gates, HPA/PDB, Node Pools, PVCs, LBs); three-tier K8s cost reconciliation & K8s workspace UI.

Phase 2: Multi-Cloud Resource Analysis & Eight Azure Rules

app/scanner*.py, app/telemetry_contract.py, app/pricing.py, web-dashboard/app/services/*

Full inventory union persisted across AWS/GCP/K8s/Azure; 7-counter coverage manifest; 8-state evaluation outcomes; 5-min time-series checks ($\ge 95%$); mutually exclusive opportunity_group_id; Service Analysis workspaces.

Phase 3: Multi-Cloud AI Foundry Settings & Knowledge Retrieval

app/settings_api.py, app/ai_gateway.py, platform/identity/knowledge/, AIFoundryConfigurationEditor.tsx

Versioned ai_foundry settings for Azure AI Foundry, AWS Bedrock, and GCP Vertex AI; same_cloud_only routing; POST /api/v1/settings/ai/test-connection diagnostics; separate knowledge_db retrieval & citation gates.

Phase 4: Customer Access UI (/api/v1/customer/*)

web-dashboard/components/customer-access/*, app/auth.py

All 18 /api/v1/customer/* endpoints wired to customer admin screens; server-side scope_restrictions enforced in narrow().

Phase 5: Commercial Billing Importer & Lapsed Evaluator

platform/identity/billing/importer.py, evaluator.py, platform/portal/components/billing/*

Billing importer/exporter round-trip; initial subscription overrides; HTTP 409 race mapping; automated lapsed-account evaluator and Portal Plan Catalog UI.

Phase 6: Entra/OIDC Sessions, Capabilities & Step-Up Auth

platform/identity/, app/auth.py, web-dashboard/

Human sign-in bound to (idp_issuer, idp_subject); capability subsetting enforced on keys; step-up auth on sensitive mutations.

Verification Gate Commands

# 1. Backend & disposable PostgreSQL 16 + Redis 7 integration suite

python scripts/test_postgres.py --tb=short

# 2. Platform Identity, Billing, Analysis, Knowledge & Audit coverage suite

pytest platform/tests/ tests/test_onboarding_api.py tests/test_effective_rules.py

# 3. Structural audit-event coverage gate (every mutating method on *Ops emits self._event)

pytest platform/tests/test_audit_coverage.py

# 4. Frontend production build & TypeScript verification (Customer Dashboard & Platform Portal)

cd web-dashboard && npm run typecheck && npx next build --webpack

cd ../platform/portal && npm run typecheck && npx next build --webpack

# 5. Formatting & whitespace hygiene

git diff --check
