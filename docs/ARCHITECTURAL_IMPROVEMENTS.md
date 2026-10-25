# CloudSaver: Autonomous FinOps and pre-merge GitOps firewall

[![FOCUS 1.0 compliant](https://img.shields.io/badge/FinOps-FOCUS_1.0-blue.svg)](#)
[![Clouds](https://img.shields.io/badge/Multi--Cloud-AWS_%7C_Azure_%7C_GCP_%7C_K8s-orange.svg)](#)
[![Architecture](https://img.shields.io/badge/Stack-FastAPI_%7C_Next.js_16_%7C_PostgreSQL_16_%7C_Redis-success.svg)](#)
[![Safety](https://img.shields.io/badge/Guardrails-5--Pillar_Blast_Radius-critical.svg)](#)

**Current release:** v1.7.0 (customer console, platform portal, and core services). v1.5.0 introduced keyless FOCUS billing sync and agent–GitOps synchronization; v1.7.0 adds workload assessments and continued governance hardening. For install, migration, and verification commands, use [README.md](../README.md).

**Dashboards do not cut cloud bills—engineers do.**  
CloudSaver is an enterprise multi-cloud FinOps automation platform and **pre-merge GitOps firewall** across **AWS, Microsoft Azure, Google Cloud Platform (GCP), and Kubernetes**. Instead of dumping static CSVs on engineering teams or acting as a blind execution layer that risks production outages, CloudSaver pairs deterministic multi-cloud discovery with five-pillar architectural risk assessments, pre-deletion safety evidence, reviewed Terraform 1.5+ exports, and human-approved agent execution.

---

## Why CloudSaver? (The problem with legacy FinOps tools)

Traditional cloud cost tools fail in two ways:

1. **Passive surveillance:** Finance teams see aggregated monthly bills without technical context, while engineers ignore dashboard alerts because they live outside CI/CD and IDE workflows.
2. **Operational fragility:** Automated cleanup scripts terminate resources based solely on CPU or disk thresholds—accidentally affecting DR cold standbys, quorum witness nodes, or storage under compliance hold.

CloudSaver shifts FinOps into the engineering workflow with mathematically bounded **net realizable savings** models and deterministic blast-radius protection. AI suggestions never authorize a cloud change; discovery stays read-only until reviewed GitOps, governance, or agent permits apply.

---

## System architecture and core lifecycle

```text
+-----------------------------------------------------------------------------------+
|                        CloudSaver enterprise web console                          |
|      Next.js App Router | lifecycle UI | TanStack Table | command palette         |
+-----------------------------------------------------------------------------------+
                                         | HTTPS
                                         v
+-----------------------------------------------------------------------------------+
|                             FastAPI enterprise gateway                            |
|   Redis leases | workspace limits | identity-backed keys | request-ID trace       |
+-----------------------------------------------------------------------------------+
            |                                    |                        |
            v                                    v                        v
+-----------------------+          +--------------------------+  +------------------+
|     Redis             |          |      PostgreSQL 16       |  | Multi-cloud AI   |
| - job queues          |          | - forced RLS             |  | - approved       |
| - rate limits         |          | - FOCUS imports          |  |   processors     |
| - async job state     |          | - audit & governance     |  | - purpose-bound  |
+-----------------------+          +--------------------------+  +------------------+
            ^                                    ^                        ^
            +------------------------------------+------------------------+
                                                 |
+-----------------------------------------------------------------------------------+
|            Asynchronous discovery, simulation, and GitOps remediation             |
|  - Collectors: AWS | Azure Resource Graph | GCP | Kubernetes                      |
|  - K8s: allocation slack, node billing reconciliation, gated consolidation      |
|  - Remediation: reviewed Terraform imports, plan policy, agent–GitOps sync        |
+-----------------------------------------------------------------------------------+
```

### The four connected FinOps lifecycle stages

1. **Observe and normalize:** Keyless billing synchronization (`POST /api/v1/finops/sync`) normalized toward FOCUS-style charges, alongside multi-cloud and Kubernetes inventory discovery.
2. **Simulate and assess:** Five-pillar assessment (cost, reliability, performance, security, operations), causal topology scoring, and SLO-bounded rightsizing evidence.
3. **Remediate via GitOps:** Reviewed Terraform packages, `PlanPolicy` checks (`app/plan_policy.py`), agent–GitOps synchronization (`POST /api/v1/gitops/sync-agent`), and ITSM-style governance where policy requires it.
4. **Verify and govern:** Outcome and realized-savings evidence against subsequent billing imports, with regression detection and workflow reopening where configured.

---

## Five category-defining engineering improvements

### 1. Causal topology and cascading savings simulator (`app/causal_topology_simulator.py`)

Legacy tools evaluate resources in isolation. CloudSaver builds a directed dependency graph across compute, block storage, snapshots, load balancers, and public IPs—calculating cascading savings of decommissioning an upstream service without breaking verified downstream dependencies.

### 2. SLO-bounded and tail-latency-aware rightsizing (`app/causal_topology_simulator.py`, `app/telemetry_contract.py`)

Average CPU alone causes p99 latency spikes during bursts. CloudSaver evaluates aligned telemetry contracts, memory working sets, disk IOPS bursts, and service SLO error budgets before a rightsizing recommendation becomes review-eligible.

### 3. Invisible network egress, NAT hairpin, and ephemeral batch waste analyzer (`app/causal_topology_simulator.py`)

Compute is only part of the bill. CloudSaver surfaces architectural anti-patterns that threshold scanners miss:

- Cross-AZ transfer hairpins and NAT gateway routing (VPC endpoint / Private Link candidates).
- Orphaned elastic IPs, idle load balancers, and bloated registries.
- Ephemeral CI/CD runner and batch waste patterns where evidence exists.

### 4. Clean-before-you-commit rate arbitrage and pre-merge GitOps firewall (`app/commitment_arbitrage.py`, `app/plan_policy.py`)

Do not lock in reserved capacity on top of infrastructure waste. CloudSaver sequences waste cleanup before commitment modeling and evaluates Terraform plan JSON as a **pre-merge GitOps firewall** in automation workflows.

### 5. Closed-loop realized savings verification (`app/realized_savings_verifier.py`)

Reduces phantom FinOps savings. Executed remediations are tracked against subsequent FOCUS-style billing evidence, separating modeled opportunity from verified realization and supporting regression reopening when drift returns.

---

## Architectural evolution matrix (baseline vs. enterprise platform)

| Capability | Baseline prototype (v0.1.0) | Enterprise platform (v1.5.0+) |
| --- | --- | --- |
| Cloud and K8s coverage | Single-cloud Azure (basic rules) | AWS, Azure, GCP, and deep Kubernetes analysis |
| Billing ingestion | Manual uploads and demo rates | Keyless sync + FOCUS-style imports (`/api/v1/finops/sync`) |
| Savings calculation | Gross waste estimates | Net realizable models + verified columns where evidence exists |
| Execution and concurrency | Synchronous blocking paths | HTTP 202 jobs, Celery workers, Redis-backed leases |
| Tenant isolation | Shared tables and static tokens | PostgreSQL RLS + platform identity and workspace keys |
| Change safety | Threshold-only rules | Five-pillar blast radius + governance and agent permits |
| Remediation | Ad hoc CLI strings | Reviewed Terraform 1.5+, `app/agent_gitops_sync.py`, plan policy |
| AI governance | None | Purpose-bound processors, allowlists, no cross-tenant training harvest |

---

## Safe closed-loop remediation workflow

Every optimization candidate passes through deterministic and policy guardrails before mutation:

- **Five-pillar blast radius evaluation:** Scores resources across cost, reliability, performance, security, and operations using observation freshness, topology, and compliance signals.
- **Risk-gated routing:** Low-evidence or high-risk cases route to governance workflows, ITSM integrations, or human tenant-admin approval—not silent auto-execution.
- **GenAI workload governance:** Token metering, processor policy, and workspace consent gate inference; client observation harvesting for training remains disabled.

Synchronized agent and GitOps paths bind expected operational state; drift stops execution even when tags look unchanged.

---

## Quick start and developer setup

Use the repository [README.md](../README.md) for supported setup (`scripts/setup_compose.py`, platform bootstrap, Docker Compose, and Windows PowerShell without host Python). Do not commit `.env` files or cloud credentials.

### Verification (representative)

```bash
python -m pip install -r requirements-dev.txt
make test
# Disposable PostgreSQL/Redis integration (requires Docker):
PYTHONPATH=platform python scripts/test_postgres.py tests platform/tests --tb=short
```

Category differentiator contracts are exercised in `tests/test_high_impact_improvements.py`. Live cloud permissions, pricing catalogs, and operational acceptance still require environment-specific validation.

### Key API endpoints (v1.5.0+ billing and GitOps)

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/api/v1/finops/sync` | Queue FOCUS-style billing synchronization (202 + poll URL; finance-authorized) |
| `GET` | `/api/v1/finops/sync-status` | Billing connector status and recent sync runs |
| `GET` | `/api/v1/finops/sync-jobs/{job_id}` | Poll a billing sync job |
| `POST` | `/api/v1/gitops/sync-agent` | Synchronize reviewed agent output with GitOps packages and plan policy |
| `POST` | `/api/v1/scans` | Dispatch non-blocking multi-cloud discovery (workspace-scoped) |

Gateway routes forward to the core scanner service; see `services/gateway.py` and [V1_5_0_IMPLEMENTATION.md](V1_5_0_IMPLEMENTATION.md) for authorization and idempotency rules.

---

## Related documentation

- [NEXT_GEN_CLOUDSAVER_DIFFERENTIATORS_README.md](NEXT_GEN_CLOUDSAVER_DIFFERENTIATORS_README.md) — extended module reference and phased delivery notes
- [LEAN_CORE_IMPLEMENTATION.md](LEAN_CORE_IMPLEMENTATION.md) — meter contracts, pricing boundaries, and verification limits
- [AGENTIC_WORKER.md](AGENTIC_WORKER.md) — isolated agent worker deployment and approval model
- [AI_DATA_GOVERNANCE.md](AI_DATA_GOVERNANCE.md) — processor declarations, retention, and erasure
