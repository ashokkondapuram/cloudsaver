# Multi-Cloud FinOps & Well-Architected — Agent Specification

**Purpose:** Instruct AI coding agents and backend worker subagents to fetch **inventory, utilization metrics, actual vs retail costs, and activity/audit logs** across **AWS, Azure, and GCP**, and evaluate resources deterministically against the **five Well-Architected pillars** (Cost Optimization, Performance Efficiency, Reliability, Security, Operational Excellence).

**Full per-provider catalogs (tables + 5-pillar summaries):**

- [spec/well_architected_aws.md](./spec/well_architected_aws.md)
- [spec/aws_extended_billable_resources_5_pillar.md](./spec/aws_extended_billable_resources_5_pillar.md) (24 types, exhaustive rule tables)
- [spec/well_architected_azure.md](./spec/well_architected_azure.md)
- [spec/azure_extended_billable_resources_5_pillar.md](./spec/azure_extended_billable_resources_5_pillar.md) (24 types, exhaustive rule tables)
- [spec/well_architected_gcp.md](./spec/well_architected_gcp.md)
- [spec/well_architected_overview.md](./spec/well_architected_overview.md) — index and **platform-specific rule hooks** the analyzer honors

**Reliability principle (CloudSaver):** Prefer **documented provider APIs + bounded pagination + `provider_retry`** over ad hoc HTTP. Align new code with `app/cloud_http.py`, `app/collectors/_pagination.py`, and `app/domain/resource/identity.py` (`canonical_resource_id`, `resource_key`).

---

## Codebase map (today vs target)

| Concern | Current location (typical) | Spec target |
|--------|----------------------------|-------------|
| AWS scan / inventory | `app/scanner_aws.py`, `app/collectors/aws_live.py`, `app/collectors/aws_resource_explorer.py` | `app/adapters/aws/` + `app/rules/aws_rules.py` |
| Azure scan / ARG / Monitor | `app/scanner.py`, `app/collectors/azure_live.py`, `app/collectors/azure_monitor_batch.py` | `app/adapters/azure/` + `app/rules/azure_rules.py` |
| GCP scan / Asset / Monitoring | `app/scanner_gcp.py`, `app/collectors/gcp_live.py` | `app/adapters/gcp/` + `app/rules/gcp_rules.py` |
| Advisor / recommender signals | `app/collectors/cloud_advisor.py` (flag `CLOUDSAVER_CLOUD_ADVISOR_ENABLED`) | Same; expand surface per matrix below |
| Activity / drift evidence | `app/collectors/activity_events.py`, `app/drift/*`, `activity_ingestion_watermark.py` | Incremental cursors + IaC attribution |
| Five-pillar analysis (offline) | `app/analysis_service/*`, `attach_pillar_analysis` via `app/scanner_pipeline.py` | Feed adapters’ normalized `UnifiedResourceContext` |
| Cost / FOCUS | `app/focus.py`, `app/collectors/billing_sync.py`, `app/domain/pricing/` | CE / CM / BQ + retail joins per provider |

Agents should **extend existing collectors first**; introduce `app/adapters/<provider>/` when moving to a clean split without breaking `scan_multi_cloud` contracts.

---

# 1. Multi-Cloud Subagent Prompts (AWS, Azure, GCP)

## 1.1 AWS Provider Subagent Prompt

**Role:** AWS FinOps & Well-Architected Backend Subagent (Python 3.12+ / FastAPI / Pydantic / boto3)

**Objective:** Implement and maintain `app/adapters/aws/` and `app/rules/aws_rules.py` using **boto3** (resource-explorer-2, ec2, rds, elbv2, s3, lambda, eks, cloudwatch, ce, pricing, cloudtrail, compute-optimizer, trustedadvisor).

### Data ingestion contracts

- **Discovery:** Resource Explorer (Search / ListResources) (supported resource types) and enrich with Describe* calls (AWS Permissions Reference).
- **Metrics:** Batch up to **500** `MetricDataQuery` items per **`GetMetricData`** (CloudWatch namespaces and dimensions per resource class).
- **Actual vs retail:** Join **14-day** resource spend from **Cost Explorer `GetCostAndUsageWithResources`** and **30-day** service/tag spend from **`GetCostAndUsage`** with **Price List Query API (`GetProducts`)**.
- **Activity & drift:** Poll **90-day** management mutations (`ReadOnly="false"`) via **CloudTrail `LookupEvents`**.
- **5-pillar evaluation:** Evaluate every resource against the **AWS 5-pillar rule matrix** in [spec/well_architected_aws.md](./spec/well_architected_aws.md), aligned with **Well-Architected**, **Trusted Advisor**, and **Compute Optimizer**.

---

## 1.2 Microsoft Azure Provider Subagent Prompt

**Role:** Azure FinOps & Well-Architected Backend Subagent (Python 3.12+ / FastAPI / Pydantic / azure-mgmt-* / httpx)

**Objective:** Implement and maintain `app/adapters/azure/` and `app/rules/azure_rules.py` using **azure-identity**, **azure-mgmt-resourcegraph**, **azure-mgmt-monitor**, **azure-mgmt-costmanagement**, **azure-mgmt-advisor**, and **httpx** (ARM REST where mgmt SDK is thin).

### Data ingestion contracts

- **Discovery & state diffs:** **Azure Resource Graph** (`Resources`) and **Resource Changes** API where applicable.
- **Metrics:** **Azure Monitor Metrics** REST; batch up to **50** resources per **Metrics List at subscription scope (POST)**.
- **Actual vs retail:** Reconcile **ActualCost** / **AmortizedCost** from **Cost Management Usage API** with **Azure Retail Prices** (`https://prices.azure.com/api/retail/prices?api-version=2023-01-01-preview`).
- **Activity & drift:** Poll **90-day** control-plane mutations from **Activity Log** REST.
- **5-pillar evaluation:** **Azure 5-pillar rule matrix** in [spec/well_architected_azure.md](./spec/well_architected_azure.md), aligned with **Azure WAF pillars** and **Advisor recommendations list**.

---

## 1.3 Google Cloud (GCP) Provider Subagent Prompt

**Role:** GCP FinOps & Well-Architected Backend Subagent (Python 3.12+ / FastAPI / Pydantic / google-cloud-*)

**Objective:** Implement and maintain `app/adapters/gcp/` and `app/rules/gcp_rules.py` using **google-cloud-asset**, **google-cloud-monitoring**, **google-cloud-billing**, **google-cloud-bigquery**, **google-cloud-logging**, **google-cloud-recommender**.

### Data ingestion contracts

- **Discovery:** **Cloud Asset Inventory v1** `searchAllResources` (supported asset types) and enrich with service **aggregatedList** / **list** REST.
- **Metrics:** **Monitoring** `projects.timeSeries.list` (GCP + Ops Agent metrics, correct **monitored resource** types).
- **Actual vs retail:** Reconcile BQ export: net spend `SUM(cost) + SUM(credits.amount)`, list `SUM(cost_at_list)` vs **Billing Catalog** `services.skus.list`.
- **Activity & drift:** **400-day** admin activity via **Logging `entries.list`** on **Cloud Audit Logs**.
- **5-pillar evaluation:** **GCP 5-pillar rule matrix** in [spec/well_architected_gcp.md](./spec/well_architected_gcp.md), aligned with **Google Cloud Well-Architected** and **Active Assist** recommenders.

---

## Execution order for agents

1. **Schema:** Ensure inventory rows carry `cloud_provider`, `resource_id`, `scope_id`, `evidence` compatible with `app/analysis_service/loader.py`.  
2. **Ingestion:** Discovery → metrics → cost → activity (with watermarks / pagination).  
3. **Rules:** Implement deterministic checks with explicit thresholds; add tests under `tests/` with mocked API fixtures.  
4. **Analysis:** Run **`finalize_scan_payload`** path so **`pillar_analysis`** and drift baselines stay consistent (`app/scanner_pipeline.py`).  
5. **Docs:** Update `docs/BACKEND_REMEDIATION_SORTED.md` when a slice is done.

---

## Related documents

- `docs/spec/well_architected_overview.md` — per-provider index + platform rule extension  
- `docs/BACKEND_REMEDIATION_SORTED.md` — sorted backlog and status  
- `docs/ANALYSIS_SERVICE.md` — AnalysisService, loader, **platform evaluators**  
- `docs/CODEBASE_EXECUTION_MAP.md` — scan execution flow  

---

*This file is the cross-provider executive brief; detailed catalog tables live under `docs/spec/well_architected_*.md`.*
