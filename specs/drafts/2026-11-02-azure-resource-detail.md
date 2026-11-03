# Azure resource detail and per-type inventory schema

- **Author:** CloudSaver engineering (with workspace operator)
- **Status:** Draft — phase 1 implemented locally; phases 2–4 pending review
- **Date:** Nov 2, 2026

## Problem statement

CloudSaver inventory comes primarily from **Azure Resource Graph** with a fixed Kusto projection. That gives broad coverage but not a consistent, type-aware view of each resource:

- There is **no first-class schema per ARM resource type** in the database or in scan evidence.
- **Full ARM properties** are not fetched for most types; only ARG-selected columns and a capped live-evidence pass (~25 resources) exist.
- Finance and FinOps rules in the expanded catalog often see **`insufficient_evidence`** or **`unsupported_by_collector`** because telemetry and configuration contracts are incomplete.
- Operators cannot inspect **what CloudSaver knows** about a resource without reading raw scan JSON.

Without typed ARM detail, scans cannot reliably support rightsizing, security posture, commitment adjacency, or AI assessment for the full subscription inventory.

## Proposed solution

Treat each scan as the system of record, and layer three mechanisms:

1. **Resource-type catalog** — canonical list of Azure `Microsoft.*/…` types CloudSaver understands, each with an ARM `api-version` and a normalized field map (no secrets).
2. **ARM GET enrichment** — after ARG inventory, read-only `GET https://management.azure.com{resourceId}?api-version=…` for catalogued types, merge into inventory `evidence.typed_configuration`.
3. **Evidence schema versioning** — bump to **`evidence_schema_version: '3'`** when typed ARM configuration is present; expose detail on resource APIs and a catalog API.

Later phases (not blocking phase 1) add optional relational storage and auto-discovery for types outside the catalog.

## Data model changes

### Phase 1 (implemented)

| Artifact | Purpose |
| --- | --- |
| **`public.resource_type_catalog`** | `(provider, resource_type)` PK, `arm_api_version`, `evidence_schema_version`, `normalized_fields` JSONB. Migration `0035_resource_type_catalog`. Read-only for `cloudsaver_app`. |
| **`scans.payload.inventory[]`** | Each observation may include `evidence.typed_configuration`, `arm_api_version`, `arm_fetched_at`, `arm_detail` (`collected` \| `unsupported_type` \| `resource_budget_exceeded` \| live_sources failure). |
| **`evidence_schema_version`** | `'2'` legacy ARG-only; `'3'` when `typed_configuration` is set on canonical inventory rows. |

### Phase 2 (implemented — relational per-type tables)

Each supported ARM type gets a **dedicated PostgreSQL table** with columns aligned to [Azure REST](https://learn.microsoft.com/en-us/rest/api/) property paths (snake_case). Every typed table shares the same **cost block** (not USD-only):

| Column group | Columns |
| --- | --- |
| Identity | `tenant_id`, `scan_id`, `resource_id`, `subscription_id`, `resource_group`, `name`, `location`, `tags`, `observed_at`, `arm_api_version`, `provisioning_state` |
| Type-specific | e.g. `disk_size_gb`, `vm_size`, `sku_name`, … per table |
| Costs (reporting currency) | `reporting_currency`, `cost_period_*`, `azure_*` (auto-sync / Azure Cost Management path), `cost_center_*` (FOCUS imports excluding `auto-sync:` sources) |

| Table | ARM type | Migration |
| --- | --- | --- |
| `azure_compute_disks` | `microsoft.compute/disks` | `0036_typed_resource_tables` |
| `azure_compute_virtual_machines` | `microsoft.compute/virtualmachines` | same |
| `azure_storage_storage_accounts` | `microsoft.storage/storageaccounts` | same |
| `azure_network_public_ip_addresses` | `microsoft.network/publicipaddresses` | same |
| `azure_containerservice_managed_clusters` | `microsoft.containerservice/managedclusters` | same |
| `aws_ec2_instances` | AWS EC2 pattern (same cost columns) | same |

**Ingestion:** `PostgresStore.save` calls `app.typed_resources.persist.persist_typed_resources` after findings insert when migration 0036 is applied.

**Reporting currency:** `scan.billing_currency` → workspace `billing_currency` → `CLOUDSAVER_DEFAULT_BILLING_CURRENCY` → `USD`. Only `focus_charges` rows matching that currency are summed.

**Provider parity:** New cloud types add a table spec in `app/typed_resources/azure_schemas.py` (or sibling module) plus Alembic revision; cost columns stay identical.

### Phase 2 (planned — follow-on)

| Artifact | Purpose |
| --- | --- |
| **`public.scan_resource_details`** | Deprecated in favor of per-type tables; do not implement unless JSON fallback needed. |
| **Catalog sync job** | Upsert `resource_type_catalog` from `app/azure_resource_registry.py` on deploy (or Alembic seed revision per release). |
| **Remaining ARM catalog types** | Add tables for NICs, App Service, PostgreSQL, SQL DB, Cosmos, Redis, Cognitive Services, etc. |

### Phase 3 (planned)

| Artifact | Purpose |
| --- | --- |
| **Auto type discovery** | ARG `distinct type` per workspace subscription; suggest catalog entries with default api-version from Azure Resource Manager metadata (read-only). |
| **Per-type JSON Schema** | Publish machine-readable schema for dashboard/forms (stored in catalog or identity analysis DB). |

## API changes

| Method | Path | Purpose | Role | Phase |
| --- | --- | --- | --- | --- |
| GET | `/api/v1/catalog/azure-resource-types` | List catalog entries (types, api-versions, field names) | Scoped read | 1 ✅ |
| GET | `/api/v1/catalog/typed-resource-tables` | List relational tables, ARM types, shared cost column names | Scoped read | 2 ✅ |
| GET | `/api/v1/scans/{scan_id}/resources/{resource_key}` | Adds `configuration_detail`, `evidence_schema_version` | Scoped read | 1 ✅ |
| GET | `/api/v1/scans/{scan_id}/resources` | Optional filter `arm_detail=collected` (future) | Scoped read | 2 |
| GET | `/api/v1/admin/resource-type-catalog` | Operator CRUD on catalog (future) | Platform operator | 3 |

No write API for ARM data; scans remain read-only against Azure.

## UI changes

| Screen | Change | Phase |
| --- | --- | --- |
| Resource detail | Show **Configuration** panel from `configuration_detail.typed_configuration` with schema version badge | 1 (API ready; dashboard wiring optional) |
| Settings / cloud status | Link to catalog API for supported types | 2 |
| Scan progress | Indicate ARM detail progress / budget exceeded count | 2 |

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `CLOUDSAVER_AZURE_ARM_DETAIL_ENABLED` | `true` | Master switch for ARM GET pass |
| `CLOUDSAVER_AZURE_ARM_DETAIL_MAX` | `500` | Max resources enriched per scan (hard cap 5000) |
| `CLOUDSAVER_CLOUD_IDENTITY` | `developer` / `managed_identity` | Must reach `management.azure.com` with Reader |
| `CLOUDSAVER_LIVE_EVIDENCE_ENABLED` | `false` | Separate pass for metrics/activity log (unchanged) |

Local dev: mount Azure CLI cache or sign in inside `scanner-service` (`CLOUDSAVER_AZURE_CONFIG_DIR`).

## Permissions (customer Azure)

- **Reader** on each scanned subscription (existing).
- ARM GET uses the same credential as Resource Graph; no additional RBAC beyond read on resource types returned by ARG.

## Acceptance criteria

### Phase 1 — typed ARM detail in scans (target: local + CI)

- [x] Catalog defines at least **15** Azure types with pinned `arm_api_version` values in code and seed rows in `resource_type_catalog`.
- [x] Scan pipeline calls ARM GET for catalogued types when `CLOUDSAVER_AZURE_ARM_DETAIL_ENABLED=true`.
- [x] Sanitization removes property names matching secret patterns (`password`, `secret`, `token`, etc.).
- [x] Inventory rows with successful fetch use **`evidence_schema_version: '3'`** after canonicalization.
- [x] `GET /api/v1/catalog/azure-resource-types` returns the catalog.
- [x] Resource detail API returns **`configuration_detail`** for observations with typed configuration.
- [x] Unit tests cover normalization and enrichment (`tests/test_azure_arm_detail.py`).
- [x] **`analysis_readiness`** on inventory evidence after ARG, ARM detail, and live enrichment (`app/collectors/azure_configuration_evidence.py`).
- [x] Per-type configuration fields projected into evidence for assessment and static analysis rules.
- [x] Live telemetry pass prioritizes resources with **`telemetry_pending_rule_ids`**.
- [x] Unit tests for configuration contracts (`tests/test_azure_configuration_evidence.py`).
- [ ] Integration test: mocked scan end-to-end with ARM reader (CI).
- [ ] Documented operator steps in README or feature guide (ARM detail section).

### Phase 1.5 — analysis-ready evidence (implemented locally)

Each inventory row carries **`evidence.analysis_readiness`**:

| Field | Meaning |
| --- | --- |
| `configuration` | `complete` \| `partial` \| `missing` for type-specific configuration fields |
| `configuration_observed` / `configuration_total` | Count of collected vs expected configuration fields |
| `telemetry_pending_rule_ids` | Analysis rules still requiring Monitor / Activity Log |

**`unsupported_rule_ids`** lists only telemetry-dependent rules (not configuration-only rules such as unattached disk or unassociated public IP).

Operator settings:

| Variable | Recommended local | Purpose |
| --- | --- | --- |
| `CLOUDSAVER_AZURE_ARM_DETAIL_ENABLED` | `true` | Typed ARM configuration (`evidence_schema_version: 3`) |
| `CLOUDSAVER_AZURE_ARM_DETAIL_MAX` | `0` or high cap | `0` = enrich all catalog types (slower) |
| `CLOUDSAVER_LIVE_EVIDENCE_ENABLED` | `true` | Metrics and state history for utilization rules |
| `CLOUDSAVER_LIVE_EVIDENCE_MAX_RESOURCES` | `0` or pilot cap | Prioritized by pending telemetry rules when capped |

Acceptance:

- [x] After scan, disk rows with ARM detail include `disk_state`, `target_disk`, and readiness when typed configuration is present.
- [x] Public IP rows set `association_verified` from ARG or ARM without live telemetry.
- [x] Resource detail API exposes `analysis_readiness` and typed `configuration_detail`.
- [ ] Pilot: ≥90% of billable VM/disk/storage rows in subscription `93ca908b-5732-440d-b712-f6d7951951c0` reach `configuration: complete` or documented `arm_detail` skip reason.

### Phase 2 — scale and observability

- [ ] Per-type budgets (e.g. enrich all disks/VMs, sample long tail) instead of single global cap.
- [x] Scan summary fields: `items_arm_detail_collected`, `items_arm_detail_processed` on running/completed scans.
- [ ] Optional `scan_resource_details` table + migration with RLS.
- [ ] Dashboard resource detail panel renders `typed_configuration`.

### Phase 3 — catalog completeness

- [ ] Cover **all billable catalog families** in `app/resource_catalog.py` (target: ≥80% of resources by count in pilot subscription).
- [ ] Workspace-specific type discovery report for operators.
- [ ] Align identity `analysis.rule_catalog.resource_type` strings with ARM canonical types where mismatched.

### Phase 4 — performance and production hardening

- [ ] Scan latency SLO: ARM pass adds ≤ **N minutes** per 500 resources (set N with pilot data).
- [ ] Rate limiting aligned with `app/provider_retry` / Azure cost interval settings.
- [ ] Feature flag default **`false`** in production until pilot sign-off (env doc update).

## Out of scope

- Mutating Azure resources (start/stop/resize/delete).
- Storing raw ARM JSON blobs without sanitization.
- Replacing Resource Graph as the inventory listing source.
- Non-Azure providers in this epic (AWS/GCP have separate collector patterns).
- Billing/charge import (covered by FinOps billing spec).

## Open questions

1. **Pilot subscription resource mix** — export ARG `distinct type` for `93ca908b-5732-440d-b712-f6d7951951c0` to prioritize catalog entries?
2. **Global cap vs per-type cap** — default 500 total acceptable for first production tenant?
3. **Relational table** — required for SQL reporting in v1.8.x or defer until dashboard-only consumption is insufficient?
4. **Production default** — keep `CLOUDSAVER_AZURE_ARM_DETAIL_ENABLED=true` in development only until latency validated?

## Dependencies

- Workspace **authorized Azure subscriptions** and developer or managed-identity credential (see local stack docs).
- Migration **`0035_resource_type_catalog`** applied before relying on DB catalog reads.
- Scanner image rebuild after registry changes.

## Implementation notes (phase 1)

| Component | Path |
| --- | --- |
| Type registry | `app/azure_resource_registry.py` |
| ARM enrichment | `app/collectors/azure_arm_detail.py` |
| Configuration → analysis evidence | `app/collectors/azure_configuration_evidence.py` |
| Live telemetry (prioritized) | `app/collectors/azure_live.py` |
| Scan wiring | `app/scanner.py` |
| Canonical version | `app/dependencies.py` |
| Migration | `migrations/versions/0035_resource_type_catalog.py` |
| APIs | `app/resource_api.py` |
| Tests | `tests/test_azure_arm_detail.py`, `tests/test_azure_configuration_evidence.py` |

**Next engineering steps after spec approval:**

1. Move this file to `specs/approved/` after team review.
2. Run pilot scan on subscription `93ca908b-5732-440d-b712-f6d7951951c0`; collect `distinct type` gaps.
3. Extend registry for top missing types; adjust `CLOUDSAVER_AZURE_ARM_DETAIL_MAX` if needed.
4. Add integration test + dashboard configuration panel (phase 2).
