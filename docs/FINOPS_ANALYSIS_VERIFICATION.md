# FinOps analysis verification (backend)

This document records automated verification of the scan → rule evaluation → pricing → API workflow. It does not certify live cloud accuracy or production readiness.

## What was verified (automated)

| Layer | Evidence |
|--------|----------|
| **Rule catalog** | 36 resource families, 51 unique rule IDs; catalog matches control-plane bytes (`tests/test_v140.py`) |
| **Per-family evaluation** | Each catalog resource type gets exactly the rule IDs the engine selects (legacy Azure suffix, K8 kind, multicloud non-legacy family rules); valid outcomes, no auto-execution (`tests/test_finops_analysis_integrity.py`) |
| **Azure legacy rules** | All 8 rules parametrized (`tests/test_expanded_rules.py`) |
| **Multicloud rules** | No invented savings without evidence; policy disable path (`tests/test_v140.py`) |
| **Kubernetes** | Federation + full `evaluate_inventory`; all 10 K8 rule IDs in catalog after `K8S_CONTAINER_UNDERPROVISIONED_RISK` alignment |
| **Evidence / telemetry** | Contracts, scoped coverage, opportunity grouping (`tests/test_resource_evidence_contracts.py`, `tests/test_opportunity_groups.py`) |
| **Pricing** | `attribute_finding_cost`, retail client (`tests/test_pricing.py`) |
| **Assessment API** | Service summary, resource assessment, AI selection (`tests/test_assessment_api.py`, `tests/test_resource_assessment.py`) |
| **Rules preview API** | Effective rules + preview re-evaluates last scan (`tests/test_service_analysis_api.py`) |
| **FinOps autopilot** | Playbook list + planner steps (`tests/test_finops_autopilot_planner.py`); rightsizing rules mapped to playbooks in integrity tests |
| **Platform outbox / ingress** | Reliability regressions (`tests/test_platform_outbox_lease.py`, `tests/test_drift_ingress_and_ast_db.py`) |

## Per-resource analysis patterns (by design)

| Provider / domain | Pattern | Actions |
|-------------------|---------|---------|
| **Azure (legacy)** | Type-specific branches in `analysis_rules.evaluate` (disk state history, VM series, IP association, ASP sites) | Review remediation scripts; rightsizing gated by SLO/utilization |
| **AWS / GCP / Azure (catalog)** | Shared `multicloud_rules.condition()` with family-specific thresholds from `definitions()` | Destructive actions blocked by default; savings only with evidence |
| **Kubernetes** | Kind-based rules; CPU/MEM overrequest expose patch `recommendation` | Strategic-merge patch preview API (not cloud mutate) |
| **Rightsizing (compute)** | SLO / utilization gates where applicable | FinOps autopilot: inspect → `compute.resize` for six playbook types only |
| **Orphan / idle / retention** | State history + snapshots + minimum days | Remediation bash/Terraform review artifacts; no autopilot execute |

## Recommended commands

```bash
# Core FinOps / analysis suite (~200 tests)
python3 -m pytest -q \
  tests/test_finops_analysis_integrity.py \
  tests/test_expanded_rules.py \
  tests/test_v140.py \
  tests/test_kubernetes_federation.py \
  tests/test_resource_evidence_contracts.py \
  tests/test_opportunity_groups.py \
  tests/test_pricing.py \
  tests/test_assessment.py \
  tests/test_assessment_api.py \
  tests/test_resource_assessment.py \
  tests/test_service_analysis_api.py \
  tests/test_finops_autopilot_planner.py

# Full backend unit suite (excludes disposable Postgres)
python3 -m pytest -q tests --ignore=tests/test_postgres.py
```

## Known limits (not errors in code, but scope boundaries)

- Many multicloud rules rely on generic `insufficient_evidence` without dedicated behavioral fixtures beyond AWS/GCP samples in `test_v140.py`.
- FinOps autopilot covers **six resize playbooks** only; orphan cleanup, NAT bypass, DB tier reviews, and K8 rightsizing use other pathways (remediation scripts, patch preview, manual review).
- Live provider acceptance requires authorized sandbox credentials; unit tests use synthetic inventory.
- Disposable PostgreSQL suites require `pgvector/pgvector:pg16` (`scripts/test_postgres.py`).

## Change log

- **Catalog fix:** `K8S_CONTAINER_UNDERPROVISIONED_RISK` added to kubernetes `deployments` family so policy/catalog match runtime evaluation (`app/resource_catalog.py`).
- **Integrity tests:** `expected_rule_ids()` mirrors evaluation wiring; Deployment/ReplicaSet types are family grouping only (Container-scoped rules).
- **RDS playbook:** canonical type `aws:rds:db` aligned with scanner/catalog (`finops_resize_playbooks.py`).
