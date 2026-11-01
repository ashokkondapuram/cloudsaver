# CloudSaver Master Architecture & Execution Plan (v1.7 → v2.0 → v3.0)

See sections below for safety invariants, service topology, phased delivery, and competitive positioning.

## Alembic chain (repository truth)

| Revision | Purpose |
|---|---|
| `0028_drift_gitops_outbox` | `platform_outbox_intents`, `gitops_remediation_requests` |
| `0029_v2_drift_baselines_gitops_ast` | Baselines, drift events, GitOps AST tables |
| `0030_v3_saas_focus_and_ebpf_flows` | SaaS FOCUS rows, eBPF flow costs |
| `0031_v3_greenops_and_merkle_audit` | Carbon metrics, Merkle audit chain |
| `0032_v3_semantic_embeddings` | Semantic embeddings (`jsonb` + optional `pgvector` HNSW) |

RLS uses `tenant_id` + `app.current_tenant_id` (workspace UUID equals tenant UUID in app code).

## Implementation status (automation snapshot)

| Phase | Modules | Status |
|---|---|---|
| **1** Drift firewall & GitOps | `event_stream`, `event_drift_worker`, `drift_manager`, `baseline_store`, `live_readers`, `gitops_vcs`, `delivery_worker`, `outbox_dispatcher`, `gitops_remediation_loaders`, `pre_mutation_drift_guard.ts` | **Scaffold + tests**; live ARM/EC2 readers stubbed; outbox dispatcher wires VCS file fetch when publish enabled |
| **2** GPU / AI / commitments / K8s | `scanner_ai_gpu`, `ai_workload_optimizer`, `autopilot_commitments`, `k8s_karpenter_sync`, `unit_economics` API | **Production math & validation**; no live DCGM bus |
| **3** eBPF / SaaS FOCUS / pre-merge | `collectors_ebpf_flow`, `finops_saas_focus_connectors`, `gitops_pre_merge_firewall`, APIs + `v3_finops_store` persistence | **Ingest persists to 0030 tables** |
| **4** GreenOps / arbitrage / Merkle | `scanner_greenops`, `finops_spot_arbitrage`, `governance_ephemeral_reaper`, `governance_merkle_audit` | **Scaffold + tests** |

Detailed Activity Log → GitOps wiring: `docs/FEATURE_IMPLEMENTATION_README.md`.

---

## 1. Executive architecture & non-negotiable safety invariants

1. Read-only discovery and telemetry — recommendations never authorize cloud writes.
2. PostgreSQL forced RLS on every workspace table; runtime uses `cloudsaver_app` only.
3. `scoped_read` vs `full_scope` API authorization.
4. Human TenantAdmin approval for agent execution; port **8006** single-use permits.
5. Zero-tolerance drift abort (drift worker + agent-worker pre-mutation guard).
6. Numeric `ctx.call(index)` agent programs; governed AI with processor guard and no cross-tenant training.

## 2. Multi-service topology

| Service | Port | Role |
|---|---|---|
| `web-dashboard/` | 3000 | Customer console |
| `services/gateway` | 8000 | Auth edge |
| `app/main` | 8002 | Scanner, FinOps, drift, GitOps |
| `services/agent_gateway` | 8006 | Permits & drift abort |
| `agent-worker/` | — | Bounded execution |
| `workers/` | — | Outbox + Redis workers |
| `platform/` | 3100 | Operator portal |

## 3. v2.0 module deep dives

### 4.1 Activity-log drift & abort

Baselines in `resource_state_baselines`; normalized Azure/AWS/GCP events; `DRIFT_INSPECT_RESOURCE` outbox; Redis lease; `cloud_drift_events`; optional `azure_ai_drift_explainer`.

### 4.2 GitOps AST & surgical PRs

AST sync (`gitops_ast_sync`), Crossplane indexer, three-tier correlation, multi-VCS PR delivery, pre-merge scorecard API.

### 4.3–4.6 GPU, K8s NAP, commitments, unit economics, Azure AI + pgvector

See module docstrings; pgvector embeddings planned as follow-on migration when extension is enabled in production Postgres.

## 4. v3.0 pillars

- SaaS FOCUS 1.1 mesh (`finops_saas_focus_connectors`)
- eBPF network attribution (`collectors_ebpf_flow`, `ebpf-flow-exporter/`)
- Pre-merge CI firewall (`gitops_pre_merge_firewall`)
- Sixth pillar GreenOps (`scanner_greenops`)
- Spot/commitment arbitrage & ephemeral lease reaper
- Merkle audit chain (`governance_merkle_audit`)

## 5. Verification gates

```bash
PYTHONPATH=.:platform python3 -m pytest \
  tests/test_master_plan_all_phases.py \
  tests/test_v2_phase1_master_plan.py \
  tests/test_drift_event_pipeline.py \
  tests/test_v2_advanced_scaffolds.py \
  tests/test_gitops_vcs_providers.py -q
```

Apply migrations through **`0031`** before enabling v3 tables in production.
