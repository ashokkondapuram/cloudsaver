# CloudSaver Master Architecture & Execution Plan (v1.7 → v2.0 → v3.0)

This document is the code-free master plan for productionizing CloudSaver v2.0/v3.0 modules. It aligns engineering phases, safety invariants, service topology, and schema evolution.

## Repository migration truth (Alembic)

The narrative below references logical migration names `0025_v2_*`, `0026_v3_*`, and `0027_v3_*`. **This repository’s applied chain differs** because v1.7 migrations already occupy those revision numbers:

| Master plan label | Repository revision | Status |
|---|---|---|
| v2 drift + GitOps outbox | `0028_drift_gitops_outbox` | `platform_outbox_intents`, `gitops_remediation_requests` |
| v2 baselines + AST tables | `0029_v2_drift_baselines_gitops_ast` | `resource_state_baselines`, `cloud_drift_events`, `gitops_*` AST tables |
| v3 SaaS FOCUS + eBPF | `0030_v3_saas_focus_and_ebpf_flows` | planned |
| v3 GreenOps + Merkle audit | `0031_v3_greenops_and_merkle_audit` | planned |

RLS uses `tenant_id` with `app.current_tenant_id` (workspace UUID equals tenant UUID in application code).

Implemented code paths for Phase 1 include:

- `app/collectors/event_stream.py` — Azure Event Grid, AWS EventBridge (mutating-only), GCP Audit normalization; correlation-aware outbox idempotency
- `workers/event_drift_worker.py` — Redis lease + baseline comparison + `cloud_drift_events` append
- `app/drift/drift_manager.py` — zero-tolerance key compare; `ABORTED_STATE_DRIFT` agent abort
- `app/drift/baseline_store.py` — `resource_state_baselines` persistence
- `app/gitops_ast_hcl_indexer.py`, `app/gitops_vcs.py`, `workers/delivery_worker.py` — surgical PR + multi-VCS publishers
- `app/gitops_crossplane_indexer.py`, `app/gitops_resource_correlation.py` — Crossplane + 3-tier mapping scaffolds
- `agent-worker/src/runtime/pre_mutation_drift_guard.ts` — permit drift abort + expected-state gate before writes

See also `docs/FEATURE_IMPLEMENTATION_README.md` for the Activity Log → drift → GitOps PR wiring detail.

---

## 1. Executive architecture & non-negotiable safety invariants

1. **Read-only discovery** — scanners, billing connectors, live evidence, and activity streams never authorize writes from recommendations alone.
2. **Forced PostgreSQL RLS** — every workspace table uses ENABLE + FORCE RLS; runtime uses `cloudsaver_app` only.
3. **scoped_read vs full_scope** — provider-restricted keys filter FinOps, GitOps history, governance/outcomes lists.
4. **Human TenantAdmin execution** — API keys cannot approve agent plans; port **8006** issues single-use permits bound to saved expected state.
5. **Zero-tolerance drift abort** — dual inspection (drift worker + agent-worker pre-mutation) revokes permits on any operational delta, including tag-stable SKU/etag changes.
6. **Deterministic agent programs** — numeric `ctx.call(index)` only; governed AI with processor approval, allowlists, and no cross-tenant training.

## 2. Multi-service topology & customer views

| Service | Port | Role |
|---|---|---|
| `web-dashboard/` | 3000 | Customer console (`/resources`, `/agents`, `/automation`, …) |
| `services/gateway` | 8000 | Auth edge, rate limits, proxy |
| `app/main` | 8002 | Scanner, FinOps, drift, GitOps APIs |
| `services/agent_gateway` | 8006 | Permits, approvals, drift abort |
| `agent-worker/` | — | Bounded connector execution |
| `workers/` | — | Outbox + Redis leased jobs (including `event_drift_worker`, `delivery_worker`) |
| `platform/` | 3100 | Operator portal & identity |

## 3. v2.0 deep-dive modules (production targets)

### 4.1 Real-time Activity-Log drift & abort

Baseline snapshots in `resource_state_baselines`; activity events → `DRIFT_INSPECT_RESOURCE` outbox → leased re-inspect → `cloud_drift_events` + permit revocation + optional `azure_ai_drift_explainer`.

### 4.2 GitOps AST, Crossplane coexistence, surgical PRs

AST line indexing, three-tier mapping (deterministic → structural → pgvector semantic), repo block verification (`REPO_DRIFT_REINDEX_REQUIRED`), multi-VCS PR delivery (GitHub, Azure DevOps, GitLab, Bitbucket).

### 4.3–4.6 GPU validation, Karpenter/NAP, commitment ladder, unit economics, governed Azure AI + pgvector

See scaffolds: `app/scanner_ai_gpu.py`, `app/ai_workload_optimizer.py`, `app/k8s_karpenter_sync.py`, `app/autopilot_commitments.py`, `app/unit_economics.py`.

## 4. v3.0 roadmap pillars (planned)

- FOCUS 1.1+ SaaS mesh (`app/finops/saas_focus_connectors.py`)
- eBPF network attribution (`ebpf-flow-exporter/`, `app/collectors/ebpf_flow_ingestor.py`)
- Pre-merge CI firewall (`app/gitops/pre_merge_firewall.py`)
- Sixth pillar GreenOps (`app/scanners/sixth_pillar_greenops.py`)
- Spot/commitment arbitrage & ephemeral lease reaper
- Merkle tamper-evident audit chain

## 5. Phased execution & verification

**Phase 1 (v2 drift + GitOps AST foundation)**  
Apply through `0029`, wire event stream + drift worker + agent abort + GitOps mapping/PR path.  
Gate: `PYTHONPATH=.:platform python3 -m pytest tests/test_drift_event_pipeline.py tests/test_gitops_vcs_providers.py` and postgres RLS suites when available.

**Phase 2** — GPU/AI tier math, commitment ladder, Karpenter/NAP YAML drafts.  
**Phase 3** — eBPF, SaaS FOCUS 1.1, pre-merge firewall.  
**Phase 4** — GreenOps, arbitrage/reaper, Merkle audit + `scripts/release_manifest.py --check`.

---

For the full competitive landscape tables, module tree, and week-by-week checklist from the architecture workshop, extend this file in-repo as phases land; the authoritative wiring doc for drift/GitOps remains `docs/FEATURE_IMPLEMENTATION_README.md`.
