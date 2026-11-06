# CloudSaver backend remediation (sorted backlog)

Branch: `cursor/backend-remediation-sort-083f`. Generated from multi-agent audit against the official multi-cloud FinOps spec (inventory, metrics, actual vs retail cost, activity/drift, resilience).

**Reliability principle:** SDK and REST hit the same Azure/AWS/GCP services; CloudSaver prefers **documented REST + `provider_retry`** for Azure scan paths. Gaps below are mostly **missing APIs**, **pagination policy**, **identity/cost provenance**, and **module boundaries**—not “pick SDK vs REST.”

---

## Target module map (Tasks 1–4)

| Task | Responsibility | Current home (today) | Target home |
|------|----------------|----------------------|-------------|
| **1 — Canonical schema & IDs** | `canonical_id`, provider, service, SKU, tags | `resource_assessment`, `dependencies`, drift `canonical_resource_id` (4 paths) | `app/domain/resource/identity.py`, `schema.py` |
| **2 — Cost & waste engine** | Actual/amortized join, retail fallback, `cost_source`, waste rules | `billing_sync`, `pricing`, `analysis_rules`, `multicloud_rules` | `app/domain/pricing/*`, `app/domain/waste/engine.py` |
| **3 — Activity & drift** | Watermarked mutation ingest, IaC vs human, `drift_detected` | Scan: `azure_live` Activity Log; Drift: EventBridge/Pub/Sub (separate) | `app/domain/drift/*`, shared activity client |
| **4 — Resilience** | Full pagination, 429/503 backoff, mocked contract tests | `provider_retry`, per-collector loops (3 pagination styles) | `app/collectors/_pagination.py` + unified policy doc |

Collectors stay under `app/collectors/`; orchestration should shrink `app/scanner.py` / `app/main.py` into `scanner_pipeline.py` after identity is centralized.

---

## Global execution order (cross-cloud)

Do these before large provider features; each unblocks Tasks 2–4.

| Order | Priority | Item | Primary paths |
|-------|----------|------|----------------|
| 1 | **P0** | Single **`canonical_resource_id` + `resource_key`** module; migrate assessment, drift, GitOps, store lookups | New `app/domain/resource/identity.py`; replace `normalize_resource_id` call sites |
| 2 | **P0** | **`cost_source`** enum on billing rows and financial evidence: `ACTUAL_BILLED` \| `RETAIL_ESTIMATED` \| `FOCUS_IMPORT` | `billing_sync._cost_row_from_totals`, `azure_json_profile`, FOCUS import |
| 3 | **P0** | **Retail price cache** (Redis, 24h TTL) for Azure Retail Prices (+ future AWS GetProducts / GCP skus.list) | New `app/domain/pricing/retail_cache.py`; wire `AzurePricingClient` |
| 4 | **P0** | **Shared pagination helper**; align CM per-resource policy with internal docs | `collectors/_pagination.py`; `billing_sync._azure_resource_query` |
| 5 | **P0** | **Drift baselines from scan** + **IaC principal allowlist** + surface **`drift_detected`** on resources | `baseline_store`, `event_drift_worker`, `resource_api.py` |
| 6 | **P1** | Thin **`scanner_pipeline`**: inventory → metrics → cost evidence → activity → persist | Split from `scanner.py` / `scan_live` |
| 7 | **P1** | **Waste engine** single entry: contracts → pricing; dedupe legacy ARG vs catalog rule IDs | `waste/engine.py`, `multicloud_rules` |
| 8 | **P2** | Golden **mocked API fixture tests** per provider (pagination + waste math + drift attribution) | `tests/fixtures/providers/` |

---

## Azure (pillar status → sorted fixes)

| Pillar | Status | Next fixes (order) |
|--------|--------|-------------------|
| **Inventory (ARG REST `2024-04-01`)** | Compliant | P2: batch ARG rule queries in `_findings`; P1: `collectors/azure_inventory.py` wrapper |
| **Metrics (Monitor REST)** | Partial — no batch | **P0:** catalog + client for Metrics Batch (`2024-02-01` per spec); refactor `azure_live.fetch_azure_monitor_series` |
| **Cost (CM `2023-11-01` + Retail)** | Partial | **P0:** per-resource CM pagination policy; **P1:** `cost_source`; **P2:** retail TTL cache |
| **Activity (Activity Log `2015-04-01`)** | Partial — state history only | P2: API version review; P1: `azure_activity.py`; bridge to drift watermarks |

**P3:** Move inline ARM api-versions from `azure_live.py` into `azure_rest_catalog.py`.

---

## AWS (pillar status → sorted fixes)

| Pillar | Status | Next fixes (order) |
|--------|--------|-------------------|
| **Inventory** | Partial — no Resource Explorer 2 | **P0:** fix live-evidence ordering (`inventory[:limit]` starves expanded rows); **P1:** `DescribeDBInstances` in `extra_inventory`; **P2:** optional Resource Explorer collector |
| **CloudWatch** | Compliant for fixed catalog | P2: optional `ListMetrics`; **P1:** gate `LookupEvents` when history cannot apply |
| **Cost** | Partial — account CE only | **P1:** CE pagination >10 pages + retries; **P2:** `GetCostAndUsageWithResources` or document CUR mandatory |
| **Price List** | Missing | **P2:** `GetProducts` adapter (mirror Azure retail client) |
| **CloudTrail** | LookupEvents in scan; EventBridge in drift | **P3:** unify canonical IDs in `event_stream`; **P0:** align `MANAGED_IDENTITY_ROLES.md` with live collectors |

---

## GCP (pillar status → sorted fixes)

| Pillar | Status | Next fixes (order) |
|--------|--------|-------------------|
| **Asset inventory** | **ListAssets**, not `searchAllResources` | **P0:** IAM/docs align to `cloudasset.assets.listResource`; **P2:** evaluate `searchAllResources` for folder/org |
| **Monitoring** | Compliant (dual contracts) | P2: document 14d/1h vs 30d/5m; P1: expand tests |
| **Actual cost** | BigQuery export only | **P0:** BQ result **pagination** (rejecting `pageToken` fails large tenants); **P1:** export watermarks + authoritative import |
| **Billing Catalog** | Missing | **P1:** `services.skus.list` for retail attribution |
| **Audit logs** | `entries.list` in scan; Pub/Sub for drift | **P1:** harden filter (`logName` activity); **P0:** logging IAM in customer docs |

---

## Spec task checklist (definition of done)

### Task 1 — Canonical multi-cloud schema

- [ ] `CloudResource` record (or pydantic model) with `canonical_id`, `provider`, `service`, `resource_type`, `region`, `sku_or_size`, `state`, `tags`, `created_at`
- [ ] One normalization function used by scan, billing join, drift, API `resource_key`
- [ ] Retail resolver never called inside per-resource HTTP loops without cache

### Task 2 — Cost reconciliation & waste

- [ ] Join daily spend to `canonical_id` (AWS CE-with-resources or CUR, Azure CM, GCP BQ detailed export)
- [ ] Store unblended + amortized; flag `cost_source`
- [ ] Waste rules: orphan (100%), idle (14d CPU/network), rightsizing (p95 CPU/mem) with effective discount from amortized/retail ratio

### Task 3 — Activity & drift

- [ ] Checkpointed `last_ingested_event_time` per scope
- [ ] Actor + event_name + changed_parameters on drift records
- [ ] IaC principal allowlist; `drift_detected` + `estimated_cost_impact_monthly` when non-IaC mutation

### Task 4 — Resilience

- [ ] No list/query stops at page 1 (ARG, CM, CE, BQ, CloudTrail, Logging, Asset)
- [ ] 429/503 backoff with jitter (Azure CM headers, AWS ThrottlingException, GCP RESOURCE_EXHAUSTED)
- [ ] Unit tests with official-shaped mock payloads per provider

---

## Test gaps to close (by priority)

| Priority | Area | Action |
|----------|------|--------|
| P0 | AWS `aws_live` | New Stubber tests: pagination, enrich ordering |
| P0 | GCP BQ billing | Multi-page `pageToken` mock |
| P1 | Azure Monitor batch | Contract tests once batch client exists |
| P1 | Drift baselines + IaC | Worker tests with populated baseline + allowlist |
| P2 | Identity | Cross-surface test: same resource → same `resource_key` and drift hash |

---

## References

- Azure REST catalog: `app/azure_rest_catalog.py`, `GET /finops/azure-rest-catalog`
- Execution map: `docs/CODEBASE_EXECUTION_MAP.md`
- Internal collection contracts: `docs/KEYCLOAK_AND_COLLECTION.md`
