# CloudSaver backend remediation (sorted backlog)

Branch: `cursor/fix-all-ingestion-analysis-083f` (ingestion → analysis through commit **`ec2f304`**). Earlier backlog from multi-agent audit against the official multi-cloud FinOps spec (inventory, metrics, actual vs retail cost, activity/drift, resilience).

**Reliability principle:** SDK and REST hit the same Azure/AWS/GCP services; CloudSaver prefers **documented REST + `provider_retry`** for Azure scan paths. Gaps below are mostly **missing APIs**, **pagination policy**, **identity/cost provenance**, and **module boundaries**—not “pick SDK vs REST.”

---

## Ingestion → analysis (completed through `ec2f304`)

| Deliverable | Status | Primary paths |
|-------------|--------|-----------------|
| Standalone **AnalysisService** (5 pillars, no live cloud HTTP) | **Done** (`eb14cf4`) | `app/analysis_service/*`, `services/analysis_service_app.py` |
| Scan jobs call **`attach_pillar_analysis`** before persist | **Done** (`4afb246`) | `workers/tasks.run_scan_job`, sync path in `app/main.py` after `materialize_scan_billing` |
| **`activity_events`** normalization (AWS/Azure/GCP collectors) | **Done** (`4ff4553`) | `app/collectors/activity_events.py`; loader prefers over `state_history` |
| **`billing_enrich`** on FOCUS attach (cost fields for evaluators) | **Done** (`8eec02b`) | `app/analysis_service/billing_enrich.py`, `app/focus.py` `attach()` |
| **Persisted `pillar_analysis`** + HTTP read APIs | **Done** (`542ce7e`) | `app/analysis_service/pipeline.py`, `app/pillar_analysis_api.py`, `app/resource_api.py`, gateway proxy |
| Azure Monitor **`metrics:getBatch`** in live enrich | **Done** (`ec2f304`) | `app/collectors/azure_monitor_batch.py`, `azure_live.enrich` prefetch + per-resource GET fallback |

**Remaining (optional / future):** AWS Trusted Advisor + GCP Recommender Stream E bodies (Azure Advisor **done** when flag on); **`scanner_pipeline.py`** orchestrator split; activity log **watermark** cursors for incremental ingest.

## “Fix rest” wave (`75033f3`)

| Deliverable | Status | Paths |
|-------------|--------|--------|
| Drift **baselines from scan** + **`drift_detected`** on evidence/API | **Done** | `app/drift/scan_baselines.py`, `workers/tasks.py`, `resource_api.py` |
| Optional **AWS Resource Explorer 2** | **Done** (flag) | `CLOUDSAVER_AWS_RESOURCE_EXPLORER`, `aws_resource_explorer.py` |
| Optional **GCP searchAllResources** | **Done** (flag) | `CLOUDSAVER_GCP_ASSET_SEARCH`, `gcp_asset_search.py` |
| **Stream E** Azure Advisor signals | **Done** (flag) | `CLOUDSAVER_CLOUD_ADVISOR_ENABLED`, `cloud_advisor.py` |
| Shared **`_pagination.py`** helper | **Done** (ARM + cloud_http) | `app/collectors/_pagination.py`, `azure_live.pages` delegate |
| **Pillar analysis-backed assessments** | **Done** | `resource_assessment.overlay_pillar_analysis` |

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
| 1 | **P0** | Single **`canonical_resource_id` + `resource_key`** module; migrate assessment, drift, GitOps, store lookups | **Done** — `app/domain/resource/identity.py`; assessment + `rule_detail` delegated |
| 2 | **P0** | **`cost_source`** enum on billing rows and financial evidence: `ACTUAL_BILLED` \| `RETAIL_ESTIMATED` \| `FOCUS_IMPORT` | **Done** — `billing_sync.py`; tests in `test_cost_source.py` |
| 3 | **P0** | **Retail price cache** (Redis, 24h TTL) for Azure Retail Prices (+ future AWS GetProducts / GCP skus.list) | **Done (Azure)** — `app/domain/pricing/retail_cache.py`; `test_retail_cache.py` |
| 4 | **P0** | **Shared pagination helper**; align CM per-resource policy with internal docs | **Partial** — per-resource CM rejects `nextLink` (`f0769b7`); shared helper still open |
| 5 | **P0** | **Drift baselines from scan** + **IaC principal allowlist** + surface **`drift_detected`** on resources | `baseline_store`, `event_drift_worker`, `resource_api.py` |
| 6 | **P1** | Thin **`scanner_pipeline`**: inventory → metrics → cost evidence → activity → persist | Split from `scanner.py` / `scan_live` |
| 7 | **P1** | **Waste engine** single entry: contracts → pricing; dedupe legacy ARG vs catalog rule IDs | `waste/engine.py`, `multicloud_rules` |
| 8 | **P2** | Golden **mocked API fixture tests** per provider (pagination + waste math + drift attribution) | `tests/fixtures/providers/` |

---

## Azure (pillar status → sorted fixes)

| Pillar | Status | Next fixes (order) |
|--------|--------|-------------------|
| **Inventory (ARG REST `2024-04-01`)** | Compliant | P2: batch ARG rule queries in `_findings`; P1: `collectors/azure_inventory.py` wrapper |
| **Metrics (Monitor REST)** | **Compliant** — batch + GET fallback | P2: move remaining inline api-versions into catalog; P2: expand batch edge-case tests beyond mocked contract |
| **Cost (CM `2023-11-01` + Retail)** | Partial | **Done:** per-resource CM fail-closed on `nextLink`; **Done:** `cost_source`; **Done:** retail Redis TTL cache |
| **Activity (Activity Log `2015-04-01`)** | Partial — **`activity_events`** on scan evidence | P2: API version review; P1: dedicated `azure_activity.py`; P0: drift watermarks + baseline bridge (Task 3) |

**P3:** Move inline ARM api-versions from `azure_live.py` into `azure_rest_catalog.py`.

---

## AWS (pillar status → sorted fixes)

| Pillar | Status | Next fixes (order) |
|--------|--------|-------------------|
| **Inventory** | Partial — no Resource Explorer 2 | **Done:** live enrich prioritizes billable catalog types (`aws_live.select_live_enrichment_targets`); **P1:** `DescribeDBInstances` in `extra_inventory`; **P2:** optional Resource Explorer collector |
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
| ~~P1~~ | Azure Monitor batch | **Done** — `tests/test_azure_monitor_batch.py` (mocked batch + prefetch grouping) |
| P1 | Activity + billing for analysis | **Done** — `test_activity_events_normalization.py`, `test_analysis_billing_enrich.py`, `test_pillar_analysis_api.py` |
| P1 | Drift baselines + IaC | Worker tests with populated baseline + allowlist |
| P2 | Identity | Cross-surface test: same resource → same `resource_key` and drift hash |

---

## E2E verification

- **Full suite:** `python3 -m pytest -q` → **1323 passed** (branch `cursor/fix-all-ingestion-analysis-083f`, Nov 2026).
- **Mocked scan pipeline:** `tests/test_backend_remediation_e2e.py` (ARG inventory + billing `cost_source` + domain `resource_key`).
- **Ingestion → analysis:** `test_analysis_service_pipeline.py`, `test_pillar_analysis_api.py`, `test_azure_monitor_batch.py`, `test_activity_events_normalization.py`, `test_analysis_billing_enrich.py`.

---

- Azure REST catalog: `app/azure_rest_catalog.py`, `GET /finops/azure-rest-catalog`
- Execution map: `docs/CODEBASE_EXECUTION_MAP.md`
- Internal collection contracts: `docs/KEYCLOAK_AND_COLLECTION.md`
