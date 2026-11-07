# CloudSaver backend improvements README

**Source:** [ashokkondapuram/cloudsaver](https://github.com/ashokkondapuram/cloudsaver) (`main`, inspected Nov 2026). Backend-only record of what the code does. UI copy, theme, and layout are out of scope. Published feature guides are dated around Oct 25, 2026 (`39def45`); the tree includes later migrations through core `0038_code_mode_runs` and identity `i0016_workspace_ui_themes`. The 1.8.1 upgrade note still names heads `0033` and `i0013`. Treat those pins as the last tagged runbook, not the full tree.

**Discovery stays read-only.** An AI suggestion, a GitOps draft, a Bash review script, a Kubernetes patch preview, and an engineering plan never authorize a cloud change by themselves.

**Companion docs:** [ENTERPRISE_BACKEND_PROGRAM.md](ENTERPRISE_BACKEND_PROGRAM.md), [BACKEND_RELIABILITY_GUIDE.md](BACKEND_RELIABILITY_GUIDE.md), [features/README.md](features/README.md).

---

## Cross-cutting backend changes

| Change | What improved | Where |
| --- | --- | --- |
| Split process model | Core API (`app.main`, 8002), edge (`services/gateway.py`, 8000), agent gateway (8006), platform identity (internal) | `services/`, `platform/` |
| Forced tenant isolation | `app.current_tenant_id`, forced RLS, `cloudsaver_app` does not bypass RLS | `app/enterprise_store.py`, `database/connection.py`, migration 0009+ |
| Scoped keys | Every `/api/v1` route classified; restricted keys are provider/scope limited; unclassified fail closed | `app/route_inventory.py`, `app/provider_access.py`, `app/data_scope.py` |
| Fail closed on identity lag | Revoked 401, suspended 403, identity outage 503, stale directory 503; cache off when poller down | `app/identity_client.py`, `app/auth.py` |
| Money as decimals | FOCUS/commitment/outcomes reject floats; NUMERIC-style decimal strings | `app/focus.py`, `app/commitment_arbitrage.py` |
| Unknown stays unknown | Missing telemetry/price/billing → `insufficient_evidence` / null, not zero/pass | assessment, rules, pricing, Kubernetes |
| Async work is leased | Jobs, delivery, billing sync, AI batches, GitOps, platform outbox: idempotency, leases, fences | `workers/`, migration 0033 |
| Three-tier route parity | Scanner, gateway, BFF match `ROUTES`; BC-01–BC-14 done | `docs/ENTERPRISE_BACKEND_PROGRAM.md` |
| 1.8.0 reliability fixes | Scoped failed_scopes; drift batch cap; fenced outbox; Redis skip releases claim; JSON number guards | `docs/BACKEND_RELIABILITY_GUIDE.md` |

Plan limits come from platform entitlement projection (`0013_billing_projection`). CloudSaver Stripe checkout/webhook return **410**; Stripe lives in identity-service.

---

## Feature-by-feature record

Sections **1–19** below follow the backend improvement narrative submitted Nov 2026 (feature guides + code inspection). **Section 5** and **§18 Observability** are updated for **Grafana/Mimir live rightsizing** on `main` after `91c01be`.

| § | Topic | Primary modules |
| --- | --- | --- |
| 1 | Overview (queue, trends, commitment ceiling) | `app/resource_assessment.py`, `app/trends.py`, `app/pricing.py`, `app/commitment_arbitrage.py` |
| 2 | Resources (pillars, digest, FOCUS, decisions) | `app/resource_assessment.py`, `app/assessment.py`, `app/focus.py`, `app/billable_resources.py` |
| 3 | Workload assessments | Browser join only; `finops_ownership` via outcomes |
| 4 | Services | `app/v150_analysis.py` |
| 5 | Kubernetes (scan path + Grafana live) | `app/scanner_kubernetes.py`, `app/kubernetes_rules.py`, `app/collectors/grafana_rightsizing.py` |
| 6 | AI assessments & governance | `app/ai_advisory.py`, `app/data_governance.py`, `app/inference_ledger.py` |
| 7 | Optimization evidence | `app/v150_analysis.py`, `app/causal_topology_simulator.py`, `app/nextgen_engines.py` |
| 8 | Cost allocation & billing | `app/focus.py`, `app/billing_jobs.py`, `workers/billing_sync.py` |
| 9 | Savings & investigations | `app/outcome_store.py`, `app/outcome_evidence.py` |
| 10 | Risk & compliance | `app/governance_store.py` |
| 11 | Agent worker | `agent-worker/`, `app/agent_contract.py`, `app/agent_workflow_routing.py` |
| 12 | Automation & GitOps | `app/gitops.py`, `app/plan_policy.py`, `app/gitops_terraform_ast_indexer.py` |
| 13 | Activity & delivery | `database/delivery.py`, `workers/dispatcher.py` |
| 14 | Settings | `app/settings_api.py`, `app/effective_rules.py` |
| 15 | Onboarding & access | `app/onboarding_api.py`, `app/offline_license.py` |
| 16 | Scanning & analysis rules | `app/multi_cloud.py`, `app/scanner.py`, `app/multicloud_rules.py` |
| 17 | Platform portal & identity | `platform/` |
| 18 | Later features (engineering, drift, code mode, observability) | migrations 0025–0038, `app/engineering/`, `app/code_mode_*.py` |
| 19 | Math not product-wired yet | `docs/features/v2-scaffolds.md` |

Detailed bullets for §§1–4, 6–17, 19 match the Nov 2026 research draft (review queue fingerprinting, five-pillar policy `2026-10-23.1`, agent permits, GitOps UUIDv5 packages, outcome three-measure chain, governance SoD, etc.). Read those modules and linked feature guides rather than duplicating every bullet here.

### 5. Kubernetes and containers (scan path)

- **Two modes:** `CLOUDSAVER_KUBERNETES_BINDINGS` → federation (API + Prometheus + optional OpenCost); without binding, metrics-only mode (`metrics_visible_containers`) cannot prove cluster coverage.
- **Inventory:** 16 kinds, caps, primary Pod/Node/Namespace failure fails scan; secondary failures → unavailable sources.
- **Prometheus:** 12 queries, 30 days, 5m step; `app/telemetry_contract.py`; circuit opens after three failures.
- **Rules:** ten contracts, `kubernetes-2026-10-24.1`; `automatic_execution` false; patch preview strategic merge + dry-run only, SLO gate via `evaluate_slo_bounded_rightsizing`.
- **Not claimed (scan path):** `slo_evidence` not collected → patch preview stops at SLO gate; cluster P95 not summed from container percentiles; modeled node consolidation Unknown without evidence.

### 5b. Grafana / Mimir live rightsizing (advisory, separate route)

**Implemented** on `main` (not scan ledger):

| Item | Detail |
| --- | --- |
| API | `GET/POST /api/v1/kubernetes/grafana/*` (`app/kubernetes_grafana_api.py`) |
| Connectors | Kind `grafana_mimir` in `observability_connectors` (0025); create via `/api/v1/observability/connectors` or kubernetes mirror routes |
| Query path | Grafana HTTP API → Mimir; token via `CLOUDSAVER_OBSERVABILITY_SECRET_*` on scanner only |
| Policy | `grafana-k8s-rightsizing-v2`: workload ownership (`kube_pod_owner` / `kube_replicaset_owner`), HPA/throttle/OOM flags, scan-aligned CPU (P95×1.5) and memory (P99×1.35) gates, `safety_blocks[]`, `patch_eligible` |
| UI | Settings → Observability (Grafana Mimir type); Kubernetes → **Live rightsizing (Grafana)** |
| Spec | [specs/drafts/2026-11-07-kubernetes-grafana-rightsizing.md](../specs/drafts/2026-11-07-kubernetes-grafana-rightsizing.md) |

**Not claimed:** no cluster write, no patch YAML, no replacement for saved-scan patch preview or federation ledger.

### 18. Observability connectors (0025)

- `/api/v1/observability`: CRUD, test, sync jobs, summaries (`app/observability_api.py`, `workers/observability_sync.py`).
- Prometheus / REST / Tempo / Jaeger run through the sync worker.
- **`grafana_mimir` is excluded from sync** (`app/observability_store.py`); used only for Kubernetes Grafana rightsizing (§5b).

---

## Persistence map (core)

| Revision | Backend change |
| --- | --- |
| 0006 | GitOps requests, forced RLS |
| 0007 | Delivery outbox |
| 0009 | Inference ledger, FOCUS, forced RLS |
| 0010 | Resource decisions, AI batches |
| 0013 | Billing projection |
| 0020–0022 | Agent GitOps journal, billing jobs, financial outcomes |
| 0023–0024 | Governance, commitment snapshots |
| 0025–0027 | Observability, control plane, engineering |
| 0028–0033 | Drift/GitOps outbox, AST index, fenced platform outbox |
| 0030–0038 | SaaS FOCUS, eBPF, embeddings, canonical rules, typed tables, Code Mode |

Identity head in tree: **i0016_workspace_ui_themes**.

---

## What this backend still does not claim

- No compliance certification, invoice reconciliation, or realized-savings guarantee.
- No seasonal anomaly model on billing Z-score.
- No interactive customer cloud-consent flow (`GET /api/v1/auth/consent-url` → 501).
- No automatic commitment purchase, Karpenter apply, or unsupervised cluster write.
- Webhook 2xx ≠ human action; model output ≠ control pass; missing edge ≠ no dependency.

---

## Representative regression entry points

`tests/test_high_impact_improvements.py`, `tests/test_resource_evidence_contracts.py`, `tests/test_enterprise_backend_contracts.py`, `tests/test_platform_outbox_lease.py`, `tests/test_finops_analysis_integrity.py`, `tests/test_engineering_zero_downtime.py`, `tests/test_agent_workflow_routing.py`, `tests/test_grafana_rightsizing.py`, `tests/test_grafana_k8s_policy.py`, `platform/tests/test_readme_improvements.py`.
