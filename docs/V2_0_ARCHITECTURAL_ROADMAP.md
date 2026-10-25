# CloudSaver v2.0: Next-generation architectural roadmap and engineering improvements

[![Status](https://img.shields.io/badge/Roadmap-v2.0_Next--Gen_Blueprint-purple.svg)](#)
[![Focus](https://img.shields.io/badge/Focus-Autonomous_FinOps_%7C_Zero--Latency_K8s_%7C_Multi--Repo_GitOps-blue.svg)](#)
[![Target](https://img.shields.io/badge/Target-Beyond_v1.7.0_Baseline-success.svg)](#)

> **Purpose of this document**  
> This is **not** a summary of the shipped v1.7.0 product. It is a **forward-looking engineering specification, gap analysis, and v2.0 improvement blueprint** for architectural bottlenecks, missing capabilities, and next-generation FinOps innovations. Nothing in the [Proposed module tree](#10-proposed-module--schema-additions-v170---v200) is implemented unless it already exists in the repository today.  
> **Shipped baseline:** v1.7.0 — see [README.md](../README.md) and [Architectural improvements](ARCHITECTURAL_IMPROVEMENTS.md). **Milestone labels** in the matrix below are proposal targets, not committed release dates.

---

## Table of contents

1. [Executive gap analysis: what the v1.7.0 baseline still lacks](#1-executive-gap-analysis-what-the-v170-baseline-still-lacks)
2. [Improvement 1: Streaming event-driven discovery (replacing poll-based scans)](#2-improvement-1-streaming-event-driven-discovery-replacing-poll-based-scans)
3. [Improvement 2: Multi-IaC and multi-repo GitOps engine (Pulumi, Bicep, Crossplane, Helm)](#3-improvement-2-multi-iac--multi-repo-gitops-engine-pulumi-bicep-crossplane-helm)
4. [Improvement 3: Predictive spot and commitment autopilot (dynamic RIs/SPs and Karpenter sync)](#4-improvement-3-predictive-spot--commitment-autopilot-dynamic-rissps--karpenter-sync)
5. [Improvement 4: FinOps for GenAI, GPU clusters, and vector databases](#5-improvement-4-finops-for-genai-gpu-clusters--vector-databases)
6. [Improvement 5: True unit economics and business telemetry attribution engine](#6-improvement-5-true-unit-economics--business-telemetry-attribution-engine)
7. [Improvement 6: eBPF zero-instrumentation network and egress flow collector](#7-improvement-6-ebpf-zero-instrumentation-network--egress-flow-collector)
8. [Improvement 7: Full provider-scoped filtering for AI and FinOps routes](#8-improvement-7-full-provider-scoped-filtering-for-ai--finops-routes)
9. [Prioritized v2.0 implementation matrix (effort vs. impact)](#9-prioritized-v20-implementation-matrix-effort-vs-impact)
10. [Proposed module and schema additions (v1.7.0 → v2.0.0)](#10-proposed-module--schema-additions-v170---v200)

---

## 1. Executive gap analysis: what the v1.7.0 baseline still lacks

v1.5.0 established keyless FOCUS-style billing sync, five-pillar blast-radius scoring, SLO-bounded rightsizing, and Terraform 1.5+ patch generation. v1.7.0 added workload assessments and continued governance hardening. **Seven architectural limitations** still block autonomous scale at large estates:

| Current limitation (v1.5.0–v1.7.0) | Operational pain point | Target v2.0 architectural improvement |
| :--- | :--- | :--- |
| **1. Batch poll-based discovery** | Scans rely on triggered or scheduled polling (`POST /api/v1/scans`, `/api/v1/scans/multi-cloud`), missing sub-minute ephemeral spikes (for example 12-minute runaway Spark or CI jobs) and creating API throttling pressure on large estates. | **Event-driven streaming ingestion** via AWS EventBridge, Azure Event Grid, and GCP Pub/Sub with sub-second delta graph updates. |
| **2. Single-tool IaC lock-in (Terraform-first)** | `app/remediation_terraform.py` and `app/agent_gitops_sync.py` emphasize Terraform 1.5+ HCL and assume a tight mapping between cloud resources and approved Git repositories. | **Multi-IaC and state-graph mapper** supporting OpenTofu, Pulumi, Azure Bicep, AWS CDK, Crossplane, and Helm/Argo CD across monorepos and polyrepos. |
| **3. Static commitment recommendations** | `app/commitment_arbitrage.py` computes a clean P10 baseline, but humans still purchase or exchange Savings Plans, RIs, or CUDs. | **Autonomous commitment and spot broker** with human-approved RI/SP marketplace exchange and live Kubernetes **Karpenter `NodePool`** weight tuning. |
| **4. Coarse GenAI and GPU visibility** | AI governance tracks high-level API tokens and PTU vs. PAYG, but is blind to **GPU fractional utilization (MIG/time-slicing)**, idle notebook workloads, and vector DB index bloat. | **DCGM GPU telemetry collector and semantic LLM router** that recommends hibernation and routes low-complexity prompts to smaller models under policy. |
| **5. Infrastructure-only cost metrics** | Reports total spend and savings in raw USD, which fails to distinguish bad waste growth from healthy traffic growth. | **Unit economics telemetry engine** correlating FOCUS-style costs against OpenTelemetry business metrics (cost per API request, per tenant, per checkout). |
| **6. Delayed flow-log network analysis** | NAT hairpin and cross-AZ analysis in `app/causal_topology_simulator.py` relies on delayed VPC/VNet flow logs (which incur storage and ingestion charges). | **Lightweight eBPF socket-level collector** (DaemonSet) capturing real-time pod-to-pod and external egress byte streams without paid flow-log ingestion. |
| **7. Coarse `full_scope` route blocking** | In `app/route_inventory.py`, many routes (`/api/v1/ai/*`, `/api/v1/finops/*`, `/api/v1/gitops/requests`, governance, outcomes) require `full_scope` keys—blocking provider-restricted teams. | **Row- and provider-scoped multi-tenant filtering** across AI, FinOps, and GitOps history endpoints (`scoped_read` everywhere safe). |

---

## 2. Improvement 1: Streaming event-driven discovery (replacing poll-based scans)

### The problem

Polling AWS APIs, Azure Resource Graph, and GCP Asset Inventory via batch jobs introduces 15-minute to 24-hour blind spots. Short-lived ephemeral workloads (GitHub Actions runners, Databricks/EMR bursts, runaway Lambda loops) can spin up, burn budget, and terminate before a scheduled scan runs.

### Proposed architecture (`app/collectors/event_stream.py`)

1. **Real-time cloud event bus listeners**
   - **AWS:** EventBridge rules streaming `RunInstances`, `CreateVolume`, `ModifyVolume`, and EKS autoscaling events via SQS/webhook.
   - **Azure:** Event Grid subscriptions capturing `Microsoft.Resources.ResourceWriteSuccess` and AKS scale events.
   - **GCP:** Cloud Pub/Sub real-time Asset Inventory feed (`temporal_asset` changes).
2. **Incremental causal graph mutation**
   - Apply incremental delta mutations to the PostgreSQL graph and Redis cache instead of rebuilding entire scan snapshots, triggering **first-hour anomaly alerts** when an unapproved high-burn SKU boots outside approved namespaces.

---

## 3. Improvement 2: Multi-IaC and multi-repo GitOps engine (Pulumi, Bicep, Crossplane, Helm)

### The problem

`app/agent_gitops_sync.py` generates Terraform 1.5+ HCL patches (`rightsize_sku`, `import` blocks). Enterprises using **Azure Bicep, AWS CDK, Pulumi, Crossplane, or Helm/Kustomize (Argo CD/Flux)** cannot consume the same automation. Mapping a live `resource_id` to file and line across many repositories remains manual.

### Proposed architecture (`app/gitops_ast_mapper.py`)

1. **Remote state and tag provenance indexer**
   - Read Terraform/OpenTofu remote state (S3, Azure Blob, GCS, Terraform Cloud) and Argo CD application metadata (read-only) to map `cloud_resource_id → git_repository + file_path + ast_node`.
2. **Pluggable multi-IaC AST patch generators**
   - **Terraform / OpenTofu:** HCL2 AST patcher plus `moved` / `import` block synthesis.
   - **Azure Bicep:** Bicep AST mutator updating `sku.name` and `properties.tier`.
   - **Kubernetes GitOps (Helm / Kustomize / Argo CD):** Emit `values.yaml` diffs or Kustomize strategic merge patches instead of raw `kubectl patch` commands Argo CD would overwrite (`SelfHeal`).
   - **GitLab and Azure DevOps:** Extend `app/gitops.py` beyond GitHub App to GitLab merge requests and Azure DevOps pull requests.

---

## 4. Improvement 3: Predictive spot and commitment autopilot (dynamic RIs/SPs and Karpenter sync)

### The problem

`app/commitment_arbitrage.py` calculates the clean-before-you-commit P10 baseline, and `app/scanner_k8s.py` detects fragmented node pools, but execution stops at human recommendations.

### Proposed architecture (`app/autopilot_commitments.py` and `app/k8s_karpenter_sync.py`)

1. **Karpenter and cluster autoscaler declarative optimizer**
   - Generate optimized **Karpenter `NodePool` and `EC2NodeClass` / `AKSNodeClass`** manifests mixing Spot and On-Demand with multi-architecture fallback (`amd64` + `arm64`) bounded by service SLO error budgets.
2. **Rolling short-term commitment ladder**
   - Integrate with AWS Savings Plans / RI APIs and Azure Reservation Exchange APIs to queue **human-approved**, ladder-staggered one-year no-upfront commitments in small increments.

---

## 5. Improvement 4: FinOps for GenAI, GPU clusters, and vector databases

### The problem

Fastest bill growth often sits in **AI/ML workloads**: underutilized GPU nodes, unmonitored fine-tuning jobs, bloated vector stores (Pinecone, pgvector, Azure AI Search), and frontier LLM calls used for trivial classification.

### Proposed architecture (`app/scanner_ai_gpu.py`)

1. **DCGM GPU hardware telemetry contract**
   - Extend `app/telemetry_contract.py` to ingest NVIDIA DCGM metrics (`DCGM_FI_DEV_GPU_UTIL`, `DCGM_FI_DEV_FB_USED`, Tensor Core active ratio).
   - Detect **CPU-bound GPU nodes** (GPU utilization under 10% with CPU/storage bottlenecks) and recommend **MIG** partitioning or time-slicing where policy allows.
2. **Semantic model downgrade and caching simulator**
   - Analyze prompt/completion token distributions and latency tolerances across Azure AI Foundry, AWS Bedrock, and Vertex AI to quantify savings from:
     - Routing classification/extraction from frontier models to small/mini models.
     - **Prompt prefix caching** and **batch API** pricing for non-interactive workloads.

---

## 6. Improvement 5: True unit economics and business telemetry attribution engine

### The problem

Finance and engineering disagree when the monthly cloud bill rises 15% while customer transactions rose 40%. Without unit economics, CloudSaver cannot separate **architectural regression** from **profitable growth**.

### Proposed architecture (`app/unit_economics.py`)

1. **OpenTelemetry and Prometheus business metric join**
   - Join daily **FOCUS-style** amortized cost records with business volume counters (`http_requests_total`, `orders_processed`, `active_tenants`, `tokens_generated`).
2. **Efficiency elasticity score**
   - Compute and alert on **marginal cost per unit**:

     ```text
     Elasticity_Ratio = (% Change in Amortized Cloud Cost) / (% Change in Business Demand Volume)
     ```

   - Releases where `Elasticity_Ratio > 1.15` trigger GitOps commit blame lookup to surface PRs that degraded unit efficiency.

---

## 7. Improvement 6: eBPF zero-instrumentation network and egress flow collector

### The problem

`analyze_cross_az_and_nat_hairpin_waste` in `app/causal_topology_simulator.py` relies on VPC/VNet flow logs. Enabling flow logs at scale adds ingestion cost and 10–15 minute aggregation lag.

### Proposed architecture (`agentic/ebpf-flow-exporter/` or top-level `ebpf-flow-exporter/`)

- Deploy an optional, read-only **eBPF DaemonSet** (low CPU overhead, no packet payload inspection) hooking `tcp_sendmsg` / `tcp_cleanup_rbuf` at the socket level.
- Map pod-to-pod cross-AZ byte counts and pod-to-external NAT hairpin traffic in near real time **without** paid cloud VPC flow log ingestion for every workload.

---

## 8. Improvement 7: Full provider-scoped filtering for AI and FinOps routes

### The problem

In `app/route_inventory.py`, many endpoints—including `/api/v1/finops/imports`, `/api/v1/finops/summary`, `/api/v1/ai/assessments`, `/api/v1/ai/usage`, and `/api/v1/gitops/requests`—are classified as `'full_scope'`. The inventory notes:

> `# Not provider-filtered yet; restricted keys are refused instead of seeing other providers' data.`

An AWS-only or Azure-only lead cannot view their own FinOps summary or GitOps history without a global `full_scope` key.

### Proposed fix (`app/route_inventory.py`, `app/focus.py`, stores)

1. Add `provider` and `scope_id` predicate pushdown to `FocusRepository.summary()`, `FocusRepository.imports()`, review repositories, and the AI assessment store.
2. Upgrade routes from `'full_scope'` to `'scoped_read'` where row-level isolation is provable, enforcing PostgreSQL RLS by `(tenant_id, provider, scope_id)` so provider-scoped workspace keys work across console tabs.

---

## 9. Prioritized v2.0 implementation matrix (effort vs. impact)

| Priority | Improvement initiative | Engineering effort | FinOps and reliability impact | Proposed milestone |
| :---: | :--- | :---: | :--- | :---: |
| **P0** | **#7: Convert `full_scope` routes to `scoped_read`** (`route_inventory.py`) | Low | **High** — Unblocks enterprise RBAC for provider-specific cloud teams. | v1.8.0 |
| **P0** | **#2: Multi-IaC GitOps (Helm/Kustomize/Bicep + GitLab/ADO)** | Medium | **Very high** — Reduces Argo CD drift; expands beyond Terraform/GitHub. | v1.8.0 |
| **P1** | **#4: GPU hardware telemetry (DCGM) and GenAI prompt caching/routing** | Medium | **Very high** — Targets fastest-growing spend categories. | v1.9.0 |
| **P1** | **#3: Karpenter `NodePool` generator and automated Spot/RI ladder** | Medium | **High** — Kubernetes bin-packing and multi-arch adoption under SLO bounds. | v1.9.0 |
| **P2** | **#1: Streaming event-driven discovery (EventBridge / Event Grid / Pub/Sub)** | High | **High** — Catches sub-hour runaway batch/CI jobs; reduces polling lag. | v1.10.0 |
| **P2** | **#5: OpenTelemetry unit economics and PR cost-regression blame** | Medium | **High** — Aligns finance and engineering on marginal cost per unit. | v1.10.0 |
| **P3** | **#6: eBPF zero-cost network flow collector DaemonSet** | High | **Medium–high** — Reduces reliance on paid VPC flow log ingestion. | v2.0.0 |

---

## 10. Proposed module and schema additions (v1.7.0 → v2.0.0)

```text
cloudsaver/
├── app/
│   ├── collectors/
│   │   ├── event_stream.py             # [NEW] EventBridge, Event Grid, Pub/Sub delta consumer
│   │   └── dcgm_gpu_collector.py       # [NEW] NVIDIA DCGM GPU utilization, VRAM, MIG scanner
│   ├── gitops_ast_mapper.py            # [NEW] State-file-to-Git locator; Bicep/Helm/Pulumi AST patcher
│   ├── k8s_karpenter_sync.py           # [NEW] SLO-bounded Karpenter NodePool and Spot/Arm64 manifests
│   ├── autopilot_commitments.py        # [NEW] Human-approved commitment ladder orchestration
│   ├── scanner_ai_gpu.py               # [NEW] GPU and vector-store waste signals
│   ├── ai_workload_optimizer.py        # [NEW] LLM tier router, batch API, prefix-cache savings model
│   ├── unit_economics.py               # [NEW] FOCUS + OpenTelemetry marginal cost and elasticity
│   └── migrations/
│       ├── 0024_provider_scoped_finops_and_ai.sql   # [PROPOSED] after current head
│       ├── 0025_gpu_telemetry_and_unit_economics.sql
│       └── 0026_multi_iac_state_provenance.sql
├── ebpf-flow-exporter/                # [NEW] Read-only eBPF socket telemetry DaemonSet
└── tests/
    ├── test_v180_scoped_routes_and_multi_iac.py
    ├── test_v190_gpu_finops_and_karpenter.py
    └── test_v200_streaming_and_unit_economics.py
```

---

## Related documentation

- [ARCHITECTURAL_IMPROVEMENTS.md](ARCHITECTURAL_IMPROVEMENTS.md) — shipped v1.7.0 positioning and five implemented differentiators
- [NEXT_GEN_CLOUDSAVER_DIFFERENTIATORS_README.md](NEXT_GEN_CLOUDSAVER_DIFFERENTIATORS_README.md) — extended module reference
- [V1_5_0_IMPLEMENTATION.md](V1_5_0_IMPLEMENTATION.md) — billing sync and GitOps agent boundaries
