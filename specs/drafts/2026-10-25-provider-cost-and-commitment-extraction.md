# Provider cost and commitment extraction

- **Author:** CloudSaver engineering
- **Status:** Draft, implemented (pending team review)
- **Date:** Oct 25, 2026

## Problem statement

CloudSaver imports billed charges from each provider, but the detail is uneven and commitment data is missing:

- Azure imports ActualCost per resource. Amortized cost isn't read, and large scopes fail because pagination isn't followed.
- AWS imports Cost Explorer totals per account. Per-resource costs aren't available.
- Google Cloud imports the standard BigQuery export per project. Per-resource costs aren't available.
- Reservations, savings plans and committed use discounts aren't read from any provider. Finance teams can't see commitment inventory, utilization, coverage, expiry or unused commitment cost, so commitment planning relies on manual inputs.

## Proposed solution

Extend the existing keyless billing worker so each billing scope also collects, read-only:

| Provider | Costs | Commitments |
| --- | --- | --- |
| Azure | Cost Management Query API: ActualCost and AmortizedCost per resource per day, following `nextLink` pagination | Reservations (`Microsoft.Capacity/reservations`) and savings plans (`Microsoft.BillingBenefits/savingsPlans`) with 1, 7 and 30-day utilization |
| AWS | Cost Explorer per account (existing), or CUR 2.0 through Athena per resource when the connector names a workgroup, database and table | Reserved Instance utilization per subscription and Savings Plans utilization per plan from Cost Explorer, plus coverage totals |
| Google Cloud | BigQuery standard export per project (existing), or the detailed export per resource when `export_type` is `detailed` | Committed use discounts from the Compute Engine aggregated commitments API, plus 30-day committed use discount credits from the billing export |

CloudSaver never purchases, exchanges, renews or cancels a commitment.

## Detailed design

### Data model

- New table `cloud_commitment_snapshots`: `id`, `tenant_id`, `provider`, `scope_id`, `job_id`, `status`, `payload` (normalized commitments, coverage and warnings), `observed_at`. It has forced row-level security, its own tenant isolation policy, and `SELECT, INSERT` for `cloudsaver_app`. It's append-only.
- `CLOUDSAVER_BILLING_CONNECTORS` entries accept optional keys:
  - `export_type` (`standard` or `detailed`) for Google Cloud.
  - `athena_region`, `athena_workgroup`, `athena_database` and `athena_table` for AWS CUR 2.0. All four are required together.
- Normalized commitment fields: `provider`, `scope_id`, `commitment_id`, `kind` (`reservation`, `savings_plan`, `committed_use_discount`), `name`, `sku`, `region`, `term`, `quantity`, `status`, `start`, `end`, `utilization_percent`, `utilization_window_days`, `commitment_amount`, `commitment_grain`, `unused_amount`, `net_savings`, `currency`.

### API

| Method | Path | Purpose | Role |
| --- | --- | --- | --- |
| GET | `/api/v1/finops/commitments` | Latest commitment snapshot per billing scope, with a summary of utilization, expiry and unused commitment cost | `BillingAdmin` |

Commitments refresh with each billing sync job (`POST /api/v1/finops/sync`). No new write endpoint exists.

### UI

The Cost allocation page gets a Commitments panel showing:

- Summary cards: active commitments, average utilization, commitments expiring within 90 days, and unused commitment cost over the last 30 days.
- A table of commitments with provider, kind, name, region, term, utilization, end date and status.
- Per-scope collection status and warnings.

### Permissions required in customer clouds

- **Azure:** Cost Management Reader on the subscription, plus Reservations Reader and Savings plan Reader at the tenant or billing scope.
- **AWS:** `ce:GetCostAndUsage`, `ce:GetReservationUtilization`, `ce:GetReservationCoverage`, `ce:GetSavingsPlansUtilizationDetails` and `ce:GetSavingsPlansCoverage`. For CUR 2.0: `athena:StartQueryExecution`, `athena:GetQueryExecution`, `athena:GetQueryResults`, Glue read on the database and table, and S3 read on the export and results buckets.
- **Google Cloud:** `bigquery.jobs.create` on the billing project, BigQuery Data Viewer on the export dataset, and `compute.commitments.list` on each project.

## Acceptance criteria

- [x] Azure imports AmortizedCost as effective cost and follows pagination, up to 10 pages.
- [x] AWS imports per-resource daily costs from CUR 2.0 through Athena when configured, with amortized effective cost.
- [x] Google Cloud imports per-resource costs from the detailed export when configured.
- [x] Each billing job stores one commitment snapshot per scope, and a commitment read failure never fails the billed-cost import.
- [x] `GET /api/v1/finops/commitments` requires `BillingAdmin` and returns only the caller's tenant data.
- [x] The Cost allocation page shows commitment inventory, utilization, expiry and unused cost.
- [x] Unit tests cover Azure, AWS and Google Cloud normalization, the merge of actual and amortized cost, snapshot storage and API authorization.
- [x] No code path calls a purchase, exchange or cancellation API.

## Implementation notes

- Azure utilization uses the longest daily window the provider reports (usually 30 days) rather than showing all three windows.
- Unused commitment cost covers the billing job's period (the 30 days ending two days before the job), grouped by currency.
- Google Cloud committed use discount credits are stored as coverage keys per currency (`committed_use_discount_credits_usd`).
- `CLOUDSAVER_COMMITMENT_SYNC=false` turns commitment reads off without affecting billed-cost sync.
- Provider reads are capped at 20,000 cost rows and 2,000 commitments per scope.

## Out of scope

- Purchasing, exchanging, renewing or canceling commitments.
- Commitment recommendations from providers (a future addition).
- Reconciling commitment amortization against invoices.
- Currency conversion between billing currencies.

## Open questions

- Should commitment snapshots have a retention limit like other billing evidence?
- Should the detailed Google Cloud export join to scanner resource IDs, which use names rather than numeric IDs?

## Dependencies

- Migration `0024_cloud_commitments`.
- Customer cloud roles listed above.
