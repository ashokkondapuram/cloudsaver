# Cost allocation and billing

The cost allocation page groups resource findings by provider and account, shows how many findings have a retail price estimate, and reports how many observations carry tag or label evidence. It also includes the cloud billing ledger, where you can import or automatically sync provider-reported charges in a strict subset of the FOCUS billing format. CloudSaver keeps three kinds of cost separate and never substitutes one for another: billed cost (what the provider charged), effective cost (after discounts and amortization), and retail estimates (list-price models attached to findings).

Last reviewed: Oct 25, 2026.

## Where to find it

- **Route:** `/allocation`, rendered by `ConsolePage` with `view="allocation"` ([web-dashboard/app/allocation/page.tsx](../../web-dashboard/app/allocation/page.tsx), [ConsolePage.tsx](../../web-dashboard/components/ConsolePage.tsx)). The page body is `Allocation` in [WorkspaceViews.tsx](../../web-dashboard/components/WorkspaceViews.tsx), and the billing panel is `BillingEvidencePanel` in [EnterpriseEvidence.tsx](../../web-dashboard/components/EnterpriseEvidence.tsx).
- **Navigation label:** **Cost allocation**, in the **Model & attribute** sidebar group ([AppShell.tsx](../../web-dashboard/components/AppShell.tsx)).
- **Page heading:** "Cost allocation". Description: "See billed costs, pricing coverage and ownership evidence by account and scope."
- **Who can see it:** Any signed-in role can see the scope breakdown and tag evidence. The **Cloud billing data** panel requires `BillingAdmin` or `TenantAdmin`. Other roles see "Finance access required."

## What you can do

**Review the scope breakdown (all roles)**

- Read the summary cards: observed accounts and scopes, the priced portion (the known retail opportunity across findings, excluding unknown costs), and tag evidence coverage (the percentage of findings whose evidence includes `tags` or `labels`).
- Search the **Account & scope breakdown** table by account, scope or provider. Each row shows the finding count, pricing coverage (priced findings out of total), and the known retail portion.
- Select the arrow on a row to focus the workspace on that scope and open `/findings` filtered by provider.
- Review **Ownership & tag evidence**, which lists up to 12 observed tag keys and how many observations carry each one. If no tags are present, the page reports an evidence gap, not a compliance score.
- Use the page actions to refresh the workspace, export the selected snapshot as CSV or JSON, or (as `TenantAdmin`) run a new scan.

**Work with the billing ledger (`BillingAdmin` or `TenantAdmin`)**

- **Sync automatically.** Under **Automatic cloud billing**, select **Sync now**. The button is enabled only when an operator has configured a connector for your workspace and automatic sync is on. The job runs in the background, and the page checks its status every 3 seconds. Closing the page does not cancel the job. Select **Cancel billing sync** to stop it. Already committed charges are kept.
- **Choose a billing period.** Set **From (UTC)**, **Until, exclusive (UTC)**, a three-letter **Billing currency**, and an optional **Monthly budget**, then select **Apply billing period**. Periods can be 1 to 366 days long.
- **Read the totals.** You see imported billed cost, effective cost with effective savings rate (ESR), and a provisional month-end forecast. A Z-score notice appears when there is enough daily history.
- **Compare providers.** A table shows charge count, billed cost and effective cost for each provider.
- **Inspect daily coverage.** Expand the daily table to see which UTC days are "Operator-declared complete" and which are "Incomplete or unverified".
- **Review recent imports.** Each import shows its source ID, currency, new and submitted record counts, completeness declaration and time, for example "Oct 25, 2026 at 9:00 AM".
- **Import FOCUS JSON manually.**
  1. Expand **Advanced: import FOCUS billing JSON manually**.
  2. Choose a JSON file smaller than 2 MB that contains `source_id` and a `records` array.
  3. Confirm that you reviewed the account scope, amounts and completeness declaration.
  4. Select **Import cloud billing data**. The result reports how many new charges were saved. Duplicate charges are not counted again.

## How it works

### Scope breakdown

The breakdown runs entirely in the browser from the selected scan's findings (`useScopedFindings`). Findings are grouped by `[provider, scope]`. The known retail portion uses `opportunityTotals` in [web-dashboard/lib/finops.ts](../../web-dashboard/lib/finops.ts), which mirrors `opportunity_totals` in [app/pricing.py](../../app/pricing.py): findings in the same `opportunity_group_id`, or on the same resource, are alternatives, so only the largest value counts. Tag evidence comes from `observedTags`, which reads string values from `evidence.tags` or `evidence.labels`. No allocation rules or shared-cost splits are applied.

### FOCUS import

`POST /api/v1/finops/imports` ([app/finops_api.py](../../app/finops_api.py)) validates the body with `ImportRequest` in [app/focus.py](../../app/focus.py).

- **Import fields:** `source_id`, `provider` (`azure`, `aws` or `gcp`), `sub_account_id`, `billing_currency`, `period_start`, `period_end` (1 to 366 days), `complete` (a strict boolean), and `records` (up to 5,000).
- **Record fields (`Charge`):** `x_ChargeId`, `ProviderName` (`Azure`, `AWS` or `Google Cloud`), `BillingAccountId`, `SubAccountId`, `BillingCurrency`, `ChargePeriodStart` and `ChargePeriodEnd` (timezone-aware), optional `ResourceId`, `ChargeCategory` (`Usage`, `Purchase`, `Tax`, `Credit` or `Adjustment`), `BilledCost`, `EffectiveCost`, and optional `ListCost`.
- **Amounts** must be decimal strings with up to 15 integer digits and 8 fractional digits. Floats, booleans and exponent notation are rejected.

`FocusRepository.import_records` then:

1. Checks that the sub-account belongs to the workspace and to any provider or scope restriction on your key, and that every `ResourceId` belongs to the declared account (`validate_scope`).
2. Fingerprints the canonical import. Re-sending the same `source_id` with identical content returns `cached: true`. Re-sending it with different content returns `409`.
3. Fingerprints each charge by `(BillingAccountId, x_ChargeId)`. A conflicting fingerprint for an existing charge rejects the whole import with `409`.
4. Inserts the import into `focus_imports` and the new charges into `focus_charges` in one transaction.

### Billing summary

`FocusRepository.summary` reads charges for the period and currency, keeping only scopes your key is authorized for. The calculations work as follows:

- **Totals:** sum of billed, effective and list cost, plus a per-provider breakdown. Charges that extend beyond the selected window are excluded and counted as `excluded_overlapping_records`.
- **Daily coverage:** a day counts as complete only when every in-scope account has a complete import covering it, the day is closed, and no non-daily charge overlaps it.
- **ESR:** `(1 − effective ÷ list) × 100`. It is calculated only when every record has a list cost and the total list cost is positive.
- **Forecast:** a provisional value equal to the billed total plus the 7-day average multiplied by the remaining days in the month. It appears only when the window starts on the first of the month, ends after the last closed day, and every closed day is complete. If you supply a budget, `projected_budget_overrun` compares the forecast to it.
- **Z-score:** a population Z-score of the latest closed day against the previous 30 complete days. It is flagged as a spike at 3 or higher and is not seasonally adjusted.

### Automatic billing sync

1. **Submit.** `POST /api/v1/finops/sync` requires a UUID `idempotency_key`. `BillingJobs.submit` in [app/billing_jobs.py](../../app/billing_jobs.py) reads the connectors bound to your workspace through `bindings()` in [app/collectors/billing_sync.py](../../app/collectors/billing_sync.py). A workspace can have at most 8 scopes and one active job at a time. The job is queued for the 30 days ending two days ago, and the API returns `202` with a `poll_url`.
2. **Worker.** `workers/billing_sync.py` ([workers/billing_sync.py](../../workers/billing_sync.py)) runs as the `billing-sync-worker` service in [compose.yaml](../../compose.yaml). One worker is elected through a PostgreSQL advisory lock and polls every 5 seconds. It claims one scope at a time with a 10-minute lease. Jobs older than 6 hours expire.
3. **Provider readers.** Each reader uses the workspace's existing keyless cloud identity:

   | Provider | Source | Billed cost | Effective cost | Granularity |
   | --- | --- | --- | --- | --- |
   | Azure | Cost Management `ActualCost` and `AmortizedCost` queries (up to 10 pages each) | `ActualCost` `PreTaxCost` | `AmortizedCost` `PreTaxCost` | Resource |
   | AWS (default) | Cost Explorer `GetCostAndUsage` | `UnblendedCost` | `AmortizedCost` | Account |
   | AWS (CUR 2.0) | Athena query over your CUR 2.0 table, when `athena_*` keys are set | `line_item_unblended_cost` | Savings Plans and Reserved Instance effective-cost fields | Resource |
   | Google Cloud | BigQuery standard billing export | `cost` | `cost` plus credits | Project |
   | Google Cloud (detailed) | BigQuery detailed billing export, when `export_type` is `detailed` | `cost` | `cost` plus credits | Resource (`resource.global_name`) |

   Each provider read is capped at 20,000 rows. The Athena query binds the account and dates as parameters, waits up to 120 seconds and stops the query on timeout.

4. **Fenced commit.** Provider reads happen outside database locks. Before committing, the worker re-checks its lease, whether you requested cancellation, and whether the connector and workspace are still authorized. A lost lease or a revoked scope commits nothing.
5. **Correction deltas.** `_import_snapshot` groups provider rows by day, resource and category. It compares them with earlier `auto:` charges and appends only the difference as new charges. Existing charges are never overwritten. Auto-sync imports are always marked `complete: false`. Charge groups that were seen before but are now absent are reported as `unresolved_absent_groups` rather than zeroed.

### Commitments

The same worker job also reads commitments for each scope, using [app/collectors/commitments.py](../../app/collectors/commitments.py). These reads are read-only and best-effort: if one fails, the billed-cost import still completes and the snapshot is stored as `failed` with a fixed error code. Provider error text is never stored.

| Provider | Commitments | Utilization and unused cost | Coverage |
| --- | --- | --- | --- |
| Azure | Reservations (`Microsoft.Capacity/reservations`) and savings plans (`Microsoft.BillingBenefits/savingsPlans`) that apply to the subscription | Longest daily utilization window the provider reports | Not available |
| AWS | Reserved Instances (`GetReservationUtilization`) and Savings Plans (`GetSavingsPlansUtilizationDetails`) for the linked account | Utilization percent, unused commitment, net savings | `GetReservationCoverage` hours and `GetSavingsPlansCoverage` spend |
| Google Cloud | Compute Engine committed use discounts (`aggregated/commitments`) | Not reported per commitment | Committed use discount credits from the billing export |

Snapshots are append-only rows in `cloud_commitment_snapshots`. The Commitments panel on Cost allocation shows the latest snapshot per scope. Set `CLOUDSAVER_COMMITMENT_SYNC=false` to turn commitment reads off. Commitment purchases, exchanges and renewals are out of scope.

### Resource-level billing

`FocusRepository.resource_costs` attaches exact USD charges to resources over a 1–90 day window. It matches resource ID, scope and currency exactly and never spreads account totals across resources. It sets:

- `billing_coverage: true` only when every day in the window is covered by a complete import.
- `commitment_locked` when a `Purchase` charge exists or effective cost exceeds billed cost.

`FocusRepository.attach` merges these values into scan evidence for the Resources, Kubernetes and Optimization views.

### Unit economics preview

`compute_elasticity_ratio` in [app/unit_economics.py](../../app/unit_economics.py) divides the cost change ratio by the volume change ratio. It flags `unit_efficiency_regression` when the result is above 1.15 and always returns `advisory_only: true`. This endpoint is available through the API only. The dashboard does not call it.

## API reference

All paths are served by [app/finops_api.py](../../app/finops_api.py) and proxied by the gateway ([services/gateway.py](../../services/gateway.py)). Every route depends on `finance()`, which requires `BillingAdmin` (`TenantAdmin` also passes).

| Method | Path | Purpose | Required role/scope |
| --- | --- | --- | --- |
| POST | `/api/v1/finops/imports` | Import a normalized FOCUS billing file. | `BillingAdmin`. Route class `scoped_read`, so a scoped key can import within its scope. |
| GET | `/api/v1/finops/imports` | List recent imports (`limit` 1–100, default 25). | `BillingAdmin`. `scoped_read`. |
| GET | `/api/v1/finops/summary` | Billed, effective and list totals, daily coverage, forecast, Z-score and provider breakdown. Query: `start`, `end`, `currency`, `budget`. | `BillingAdmin`. `scoped_read`. |
| POST | `/api/v1/finops/sync` | Queue an automatic billing sync job. Query: `currency`. Body: `{"idempotency_key": "<uuid>"}`. | `BillingAdmin`. `full_scope`. |
| GET | `/api/v1/finops/sync-jobs/{job_id}` | Poll a billing job. Returns `Retry-After: 3` while it is active. | `BillingAdmin`. `full_scope`. |
| POST | `/api/v1/finops/sync-jobs/{job_id}/cancel` | Cancel a queued job, or request cancellation of a running one. | `BillingAdmin`. `full_scope`. |
| GET | `/api/v1/finops/sync-status` | Connector configuration, recent syncs and the last successful sync. | `BillingAdmin`. `full_scope`. |
| GET | `/api/v1/finops/commitments` | Latest reservations, savings plans and committed use discounts per scope, with a summary (active, expiring in 90 days, average utilization, unused cost by currency). | `BillingAdmin`. `full_scope`. |
| GET | `/api/v1/finops/unit-economics/preview` | Cost-to-volume elasticity. Query: `prior_cost`, `current_cost`, `prior_volume`, `current_volume`. | `BillingAdmin`. `scoped_read`. |

## Data and evidence

**What's stored**

- `focus_imports`: one row per import, with source ID, fingerprint, provider, sub-account, currency, period, completeness declaration, record and inserted counts, a hashed actor and the creation time.
- `focus_charges`: one row per charge, with provider, billing account, sub-account, charge ID, fingerprint, currency, period, resource ID, category, and billed, effective and list cost.
- `billing_sync_jobs`: queued and running jobs with per-scope results, lease and request key. Older `billing_sync_runs` workflow records also appear in the sync history.

**Billed, effective and retail costs**

| Measure | Where it comes from | Use it for | Do not use it as |
| --- | --- | --- | --- |
| Billed cost | `BilledCost` in imports, or the provider's actual or unblended cost | What the provider charged in the period | Verified savings |
| Effective cost | `EffectiveCost` in imports, or the provider's amortized cost or cost plus credits | Cost after discounts and commitment amortization, where available | Proof of amortization for Azure, where it equals billed cost |
| List cost and ESR | `ListCost` in imports | Effective savings rate, when every record has list cost | A retail estimate |
| Retail estimate | Exact Azure retail meters or the operator-reviewed regional catalog ([app/pricing.py](../../app/pricing.py)) | Sizing a finding's opportunity | A billed or effective cost |

**What is NOT proven**

- Imported billing is not reconciled with the provider (`billing_reconciled: false`, `realized_savings: null`). Completeness is what the operator declares.
- Without a CUR 2.0 Athena table or a detailed BigQuery export, AWS and Google Cloud automatic sync return account-level and project-level rows only. CloudSaver does not invent per-resource charges.
- Azure reservations and savings plans with a shared scope appear on every bound subscription they can apply to.
- Forecasts are provisional, and Z-scores are review signals, not diagnosed anomalies.
- The scope breakdown is not chargeback or showback. Billing-based allocation needs a connected allocation feed, and tags are observed evidence only.

## Permissions

| Role | Scope breakdown and tags | View billing summary and imports | Import billing | Run or cancel a sync |
| --- | --- | --- | --- | --- |
| `Viewer` | Yes | No | No | No |
| `BillingAdmin` | Yes | Yes | Yes | Yes, with a full-scope key |
| `TenantAdmin` | Yes | Yes | Yes | Yes, with a full-scope key |

Provider-limited and scope-limited keys see only charges for their authorized providers and accounts (`authorized()` in [app/focus.py](../../app/focus.py)). Sync routes require a key that covers every configured provider.

## Configuration

| Variable | Purpose | Default |
| --- | --- | --- |
| `CLOUDSAVER_AUTO_BILLING_SYNC` | Turns automatic billing sync on or off. Any value other than `true` disables submission and execution. | `true` |
| `CLOUDSAVER_BILLING_CONNECTORS` | JSON list (up to 200) of operator-owned bindings: `tenant_id`, `provider`, `scope_id`, and, for GCP, `billing_project`, `dataset`, `table` and optional `export_type` (`standard` or `detailed`). For AWS CUR 2.0, set all of `athena_region`, `athena_workgroup`, `athena_database` and `athena_table`. It contains no cloud secrets. Scopes must already belong to the workspace. | `[]` |
| `CLOUDSAVER_COMMITMENT_SYNC` | Reads reservations, savings plans and committed use discounts during billing sync. Any value other than `true` turns it off. | `true` |
| `CLOUDSAVER_REGIONAL_PRICE_CATALOG` | Operator-reviewed AWS and GCP retail meters used for retail estimates on findings. | `[]` |

Automatic sync uses the workspace's existing keyless cloud identity, so that identity needs billing-read access. See [Managed identity roles](../MANAGED_IDENTITY_ROLES.md).

## Guardrails and limitations

- Imports: up to 5,000 records per file, and the dashboard accepts files up to 2 MB. Summaries and coverage are capped at 50,000 records and 50,000 imports per window, so narrow the period if you reach the cap.
- Provider responses are capped at 4 MB and 5,000 rows per scope. Azure pagination is refused, so narrow the window. The AWS reader stops after 10 pages.
- Provider errors are never stored. Failed scopes record only `BILLING_SOURCE_UNAVAILABLE_OR_INVALID`, `BILLING_SCOPE_REVOKED` or `BILLING_IMPORT_UNCERTAIN_OR_INVALID`.
- Currencies are never combined. Each summary uses a single currency.
- Every charge is append-only, and corrections are added as new adjustment charges.
- The gateway rate-limits each workspace to 120 requests per minute.

## Tests

- [tests/test_enterprise.py](../../tests/test_enterprise.py): atomic, deduplicated, decimal-exact imports, schema rejection, scope binding, empty complete imports, and viewer denial.
- [tests/test_scoped_finops_routes.py](../../tests/test_scoped_finops_routes.py): scoped route classes, and summaries and imports that exclude other providers.
- [tests/test_billing_jobs.py](../../tests/test_billing_jobs.py): `202` enqueue and key reuse, crash and lost-lease safety, cancellation and revocation, and handling of missing groups.
- [tests/test_v150_workflows.py](../../tests/test_v150_workflows.py): honest sync status, correction deltas without double counting, sanitized provider errors, and exact keyless reader scopes.
- [tests/test_lean_core.py](../../tests/test_lean_core.py): exact resource billing joins.
- [tests/test_unit_economics.py](../../tests/test_unit_economics.py): elasticity math.
- [web-dashboard/e2e/enterprise.spec.ts](../../web-dashboard/e2e/enterprise.spec.ts): explicit import, decimal preservation, currency isolation, and viewer restrictions.
- [web-dashboard/e2e/v150.spec.ts](../../web-dashboard/e2e/v150.spec.ts): configured automatic billing sync.
- [web-dashboard/e2e/console-experience.spec.ts](../../web-dashboard/e2e/console-experience.spec.ts) and [web-dashboard/e2e/lean.spec.ts](../../web-dashboard/e2e/lean.spec.ts): **Cost allocation** navigation.

## Related docs

- [v1.5.0 implementation](../V1_5_0_IMPLEMENTATION.md) (automatic billing connectors)
- [Lean core implementation](../LEAN_CORE_IMPLEMENTATION.md) (regional price catalog)
- [Managed identity roles](../MANAGED_IDENTITY_ROLES.md)
- [Environment reference](../ENVIRONMENT.md)
- [Financial outcomes](../FINANCIAL_OUTCOMES.md)
- [Savings and investigations](savings-and-investigations.md)
- [Optimization evidence](optimization-evidence.md)
