# Multi-cloud Well-Architected — Overview & extension

This folder splits the **full provider catalogs** so agents and humans can navigate AWS, Azure, and GCP independently:

| Document | Contents |
|----------|----------|
| [well_architected_aws.md](./well_architected_aws.md) | AWS discovery, metrics, cost, CloudTrail, 5-pillar rule summary |
| [well_architected_azure.md](./well_architected_azure.md) | Azure ARG, Monitor, Cost Management, Activity Log, 5-pillar summary |
| [well_architected_gcp.md](./well_architected_gcp.md) | GCP Asset, Monitoring, BQ billing, Audit logs, 5-pillar summary |

**Cross-cutting agent brief:** `docs/MULTI_CLOUD_WELL_ARCHITECTED_AGENT_SPEC.md` (codebase map + shared ingestion principles).

---

## Adding platform-specific rules the analyzer must honor

The **AnalysisService** (`app/analysis_service/service.py`) runs deterministic evaluators over `UnifiedResourceContext`. Built-in rules live under `app/analysis_service/evaluators/`.

**Extension points (no fork required):**

1. **`app/analysis_platform_hooks.py`** (optional package module) defining:
   - `evaluate_platform(ctx: UnifiedResourceContext) -> list[PillarFinding]`
2. **Environment:** `CLOUDSAVER_ANALYSIS_PLATFORM_EVALUATORS` — comma-separated dotted import paths; each module must export **`evaluate_platform`**.

Platform evaluators run **after** built-in pillar evaluators; their findings **participate in pillar scores**.

Details, security notes, and examples: **`docs/ANALYSIS_SERVICE.md`** (section *Platform-extensible analysis rules*).

---

## Stable rule identifiers

- **Inventory / waste / UI catalog:** `app/resource_catalog.py` (`FAMILIES`, `RULE_DISPLAY_NAMES`).
- **Evidence-backed Azure contracts:** `app/analysis_rules.py` + `app/azure_evidence_contracts.py`.
- **Analysis-service findings:** `PillarFinding.rule_id` in `app/analysis_service/finding.py` — use deterministic ids; platform hooks should prefix custom ids (e.g. `PLATFORM_COST_*`) to avoid collisions.

When adding a new **first-party** rule, add the id to the catalog and an evaluator (built-in or platform hook) so **both** the scanner policy path and **pillar_analysis** stay aligned.

Platform hooks normalize **`finding_id`** and resource identity fields from the live context, dedupe **(pillar, rule_id)**, and cap volume per resource (see **`docs/ANALYSIS_SERVICE.md`**).
