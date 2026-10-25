# Savings and investigations

The savings and investigations workspace tracks financial outcomes from an observed resource to a verified result. You open an optimization case from a scan, assign an owner, record review and human approval, and bind signed collector evidence of the provider action, post-change health and comparable billing. CloudSaver reports three measures separately: estimated opportunity, validated run-rate reduction, and reconciled financial benefit. The same workspace runs cost investigations on imported daily billing and maintains versioned application ownership mappings for routing. Nothing in this workflow executes infrastructure changes.

Last reviewed: Oct 25, 2026.

## Where to find it

- **Route:** `/outcomes`, rendered by [`OutcomesWorkspace`](../../web-dashboard/components/outcomes/OutcomesWorkspace.tsx) through [web-dashboard/app/outcomes/page.tsx](../../web-dashboard/app/outcomes/page.tsx).
- **Navigation label:** **Savings & investigations**, in the **Model & attribute** sidebar group ([AppShell.tsx](../../web-dashboard/components/AppShell.tsx)).
- **Tabs:** **Verified savings**, **Cost investigations** and **Application ownership**. Use the arrow keys, Home and End to move between tabs.
- **Who can see it:** `BillingAdmin` or `TenantAdmin`. Viewers see "Finance access required," and the page makes no outcome requests for them.

## What you can do

### Verified savings

- **Read the three measures** for a reporting currency you choose: estimated opportunity (saved retail opportunity per 30 days), validated run-rate reduction (demand-normalized recurring cost per 30 days) and reconciled financial benefit (supported observation windows, not an annual forecast). A count of validated and implemented cases appears alongside them.
- **Create a case** (`TenantAdmin`): expand **Start an optimization case**, search the selected scan, choose a resource (up to 500 are listed), pick **Rightsizing** or **Retirement**, describe the proposed change and expected benefit (10 to 1,000 characters), then select **Create case**.
- **Move a case through its lifecycle.** Open **Review case** and add a review note of at least 5 characters for every action:

  | Stage | Action | Who | Requirement |
  | --- | --- | --- | --- |
  | Detected | **Assign owner** | `TenantAdmin` | An owner ID |
  | Assigned | **Mark reviewed** | `TenantAdmin` | None |
  | Reviewed | **Approve proposed change** | `TenantAdmin`, verified human session | A change reference (3 to 200 characters) and the acknowledgment checkbox |
  | Approved | **Record signed implementation** | `TenantAdmin` | A signed audit receipt for a matching provider action |
  | Implemented or validated | **Validate outcome evidence** | Finance role | Select a post-change scan that differs from the baseline scan |
  | Validated or reconciled | **Reconcile financial benefit** | Finance role, verified human who is not the approver | Signed billing receipt that matches the local ledger |
  | Implemented, validated or reconciled | **Reopen for investigation** | `TenantAdmin` | Returns the case to Assigned |

- **Inspect evidence** in the case drawer: the accountable owner, baseline observation, original imported billing, expected opportunity, evidence status (audit, health and billing receipts), the financial calculation, claim revision history, partial baseline configuration and the immutable review history.

### Cost investigations

- **Run detection.** Optionally choose a closed UTC billing day and a currency, then select **Investigate imported cost changes**.
- **Work the queue.** Open an investigation to see the same-weekday baseline, observed daily cost, increase, charge-category contributions, mapped application and team, and any agent tasks created near the billing window. Record **Acknowledge**, **Assign**, **Investigate**, **Add note** or **Resolve**. Resolving requires an owner, an acknowledgment and one of these classifications: actionable, not actionable, planned change or duplicate investigation.
- **Track response metrics:** total and unassigned investigations, mean acknowledgment time, mean resolution time, and the percentage of resolved investigations classified as actionable.
- **Approve a planned exception** (`TenantAdmin`, verified human session): choose a resource and enter start, end, change reference and reason. The window can last at most 30 days and cannot start in the past. Charges stay visible. The exception only suppresses the investigation workflow.

### Application ownership

- **Save an ownership version** (`TenantAdmin`): choose a resource from the selected scan and enter application, team, owner, environment and cost center. Each value must start with a letter or digit and be at most 80 characters (letters, digits, `_`, `.`, `:` and `-`).
- **Inspect ownership history** for a mapped resource.
- **Browse current mappings.** These are direct resource mappings only, with no shared-cost split.

## How it works

### Modules

- [app/outcome_api.py](../../app/outcome_api.py): the FastAPI router under `/api/v1/outcomes`. It enforces roles, validates scan and resource ownership (`validate_finding_scope`), and maps conflicts to `409` and invalid input to `422`.
- [app/outcome_contracts.py](../../app/outcome_contracts.py): strict request models (`CaseCreate`, `CaseAction`, `Ownership`, `Detection`, `AnomalyAction`, `Suppression`), signed receipt models (`Envelope`, `AuditProof`, `HealthProof`, `BillingProof`), the `human()` session check, and the configuration and utilization projections.
- [app/outcome_store.py](../../app/outcome_store.py): `Outcomes`, which manages case creation, the lifecycle state machine, receipts, financial claims and the summary.
- [app/outcome_evidence.py](../../app/outcome_evidence.py): collector grants, HMAC receipt validation, local ledger windows and the verification math.
- [app/outcome_anomalies.py](../../app/outcome_anomalies.py): `Investigations`, which manages ownership mappings, suppressions, detection, the investigation lifecycle and metrics.

### Case creation

`Outcomes.create` checks that the resource is in an authorized scope and enforces a limit of 1,000 cases per workspace. It is idempotent on `request_key`: the same key with different content returns `409`. It saves:

- The resource name, type and region.
- An allowlisted configuration snapshot (for example `sku_name`, `vm_size`, `size_gb` or `desired_replicas`) and its digest.
- P95 utilization summaries for CPU, memory and disk, when present.
- The baseline rule IDs.
- The estimated opportunity: the largest `estimated_monthly_waste_usd` among the resource's findings, recorded only for USD cases.
- The baseline billing: a 30-day ledger window from `focus_charges`, ending on the scan date.

### Signed evidence receipts

Trusted collectors post receipts to `POST /api/v1/outcomes/evidence/receipts` with an `X-Evidence-Signature` header. `validate_receipt` checks that:

1. The envelope's `tenant_id` matches your workspace.
2. `issued_at` falls between 60 seconds in the future and 5 minutes in the past.
3. The collector (`source_id`) has exactly one grant in `CLOUDSAVER_EVIDENCE_SOURCES` covering this tenant, provider, scope and kind.
4. The signature is the hex HMAC-SHA256 of the canonical JSON body (sorted keys, compact separators), computed with the secret in that grant's `key_env`. The secret must be at least 32 characters, and the canonical body must be 16,000 bytes or less.

Receipt kinds are `audit` (provider action: `delete` or `resize`, `Succeeded`, with before and after configuration digests), `slo` (health and utilization acceptance over a window) and `billing` (baseline and post-change windows, recurring and billed costs, business units and reconciliation flags). Each receipt must bind an owned v2 case and its exact resource. Re-posting the same `receipt_id` from the same source is idempotent.

### Verification math

`evaluate()` in [app/outcome_evidence.py](../../app/outcome_evidence.py) stops at the first missing requirement and returns its reason code:

| Requirement | Reason code if missing |
| --- | --- |
| Audit, billing and health receipts are all present | `AUDIT_BILLING_AND_HEALTH_RECEIPTS_REQUIRED` |
| The provider action happened after the saved human approval | `ACTION_MUST_FOLLOW_SAVED_HUMAN_APPROVAL` |
| The post-change scan is completed, less than 24 hours old and later than the action | `FRESH_COMPLETED_POST_CHANGE_SCAN_REQUIRED` |
| The scan's `scope_results` show complete supported inventory for the resource type (and region for AWS and GCP) | `COMPLETE_SCOPE_OBSERVATION_REQUIRED` |
| Retirement: the resource is gone. Rightsizing: the observed configuration changed and matches both the audit and health digests | `RETIRED_RESOURCE_STILL_PRESENT`, `RIGHTSIZED_RESOURCE_NOT_OBSERVED`, `OBSERVED_CONFIGURATION_CHANGE_NOT_PROVEN`, `BASELINE_CONFIGURATION_REQUIRED` |
| The audit baseline digest and operation match the case | `AUDIT_BASELINE_CONFIGURATION_MISMATCH`, `AUDIT_OPERATION_MISMATCH` |
| Health and utilization were accepted over at least 7 days after the action | `ACCEPTED_POST_CHANGE_HEALTH_AND_UTILIZATION_REQUIRED` |
| The baseline and post-change billing windows are each 30 closed days, before approval and after the action respectively | `COMPARABLE_CLOSED_30_DAY_WINDOWS_REQUIRED` |
| Currency matches, coverage is complete and commitments are accounted for | `COMPLETE_CURRENCY_AND_COMMITMENT_EVIDENCE_REQUIRED` |
| Business volume is positive, and the demand ratio is between 0.25 and 4 | `POSITIVE_BUSINESS_VOLUME_REQUIRED`, `DEMAND_CHANGE_EXCEEDS_COMPARABILITY_LIMIT` |

When all of these pass, the result has `status: run_rate_validated` and:

- **Validated run-rate reduction** = baseline recurring cost × demand ratio − post recurring cost − added recurring cost − retained commitment cost.

The financial benefit additionally requires `provider_reconciled`, `credits_accounted_for` and an `invoice_reference` (otherwise `PROVIDER_RECONCILIATION_AND_CREDIT_ACCOUNTING_REQUIRED`). The receipt's `ledger_digest` and billed costs must also match the local ledger for both windows (otherwise `LOCAL_BILLING_LEDGER_MUST_MATCH_SIGNED_RECONCILIATION`).

- **Reconciled financial benefit** = baseline billed cost × demand ratio − post billed cost − added recurring cost − retained commitment cost − transition cost + counterfactual adjustment.

Results can be negative. For example, a baseline recurring cost of $1,200.00 with a demand ratio of 1.10, a post recurring cost of $1,400.00 and no other costs gives a run-rate reduction of -$80.00.

### Reconciliation and claims

Reconciling writes an append-only `savings_financial_claims` row with a revision number. A claim for the same resource and currency is rejected with `409` if its period overlaps another case's claim or a different period. One provider action (`event_id`) can fund only one case.

When you open a case, `Outcomes.detail` re-checks the saved conclusions:

- If a receipt or collector grant has changed, run-rate evidence is marked not current (`COLLECTOR_GRANT_OR_EVIDENCE_CHANGED`).
- If the billing ledger has changed, financial evidence is marked not current (`BILLING_LEDGER_CHANGED_RECONCILIATION_REQUIRED`).
- Withheld claims are excluded from the supported total.

### Summary

`Outcomes.summary` reports each currency separately. Estimates and run rates use the most recently updated case for each resource and currency. The financial benefit sums supported claims only, and current but unsupported claims are counted in `unsupported_financial_claims`. `validated_outcome_pct` is the number of validated cases divided by the number of implemented cases.

### Cost investigation detection

`Investigations.detect` (rule `daily-same-weekday-median-v1`) works as follows:

1. It uses the day you choose, or the last closed day with imported charges. The day must fall within the last 90 closed UTC days.
2. It reads daily `focus_charges` for that day and the 28 days before it, grouped by provider, scope and resource. Non-daily charges are skipped and counted.
3. It requires at least three of the four prior same-weekday values. The median of those values is the baseline, and MAD is the median absolute deviation from it.
4. A group is active when the increase exceeds the largest of 5 currency units, 20% of the baseline, or 3 × MAD. For example, with a baseline of $100.00 and a MAD of $4.00, the threshold is $20.00.
5. It records category deltas (usage, credit, adjustment, tax and purchase), billing lag, freshness (`delayed_billing`, or `stale` after 7 days), current ownership, and agent tasks created on that resource from the day before through the billing day.
6. It publishes at most 200 candidates. A planned exception saved before detection marks the investigation `suppressed`.

If corrected billing changes the evidence, the investigation is updated. A resolved investigation reopens, and one that no longer exceeds the threshold moves to `review_required`.

## API reference

All paths are served by [app/outcome_api.py](../../app/outcome_api.py) and proxied by [services/gateway.py](../../services/gateway.py). Every route requires `BillingAdmin`. `TenantAdmin` always passes. Some actions additionally require `TenantAdmin`.

| Method | Path | Purpose | Required role/scope |
| --- | --- | --- | --- |
| GET | `/api/v1/outcomes/summary` | Per-currency estimate, run rate, financial benefit and validation rate. | `BillingAdmin`. `scoped_read`. |
| GET | `/api/v1/outcomes/cases` | List cases (up to 1,000). | `BillingAdmin`. `scoped_read`. |
| POST | `/api/v1/outcomes/cases` | Create a case from a completed live scan. | `BillingAdmin` and `TenantAdmin`. `full_scope`. |
| GET | `/api/v1/outcomes/cases/{case_id}` | Case detail with events, evidence, claims and current-evidence flags. | `BillingAdmin`. `scoped_read`. |
| POST | `/api/v1/outcomes/cases/{case_id}/actions` | Lifecycle action. `assign`, `review`, `approve`, `implement` and `reopen` require `TenantAdmin`. `approve` and `reconcile` require a verified human session. | `BillingAdmin`. `full_scope`. |
| GET | `/api/v1/outcomes/cases/{case_id}/billing-evidence` | Preview local ledger windows. Query: `baseline_start`, `baseline_end`, `post_start`, `post_end`, `currency`. | `BillingAdmin`. `scoped_read`. |
| POST | `/api/v1/outcomes/evidence/receipts` | Ingest a signed collector receipt. Header: `X-Evidence-Signature`. | `BillingAdmin`. `full_scope`. |
| GET | `/api/v1/outcomes/ownership` | Current direct ownership mappings. | `BillingAdmin`. `scoped_read`. |
| PUT | `/api/v1/outcomes/ownership` | Save a new ownership version, using optimistic `version`. | `BillingAdmin` and `TenantAdmin`. `full_scope`. |
| GET | `/api/v1/outcomes/ownership/history` | Ownership versions. Query: `provider`, `scope_id`, `resource_id`. | `BillingAdmin`. `scoped_read`. |
| GET | `/api/v1/outcomes/anomalies` | List investigations. | `BillingAdmin`. `scoped_read`. |
| POST | `/api/v1/outcomes/anomalies/detect` | Run detection. Body: optional `day`, `currency`. | `BillingAdmin`. `full_scope`. |
| GET | `/api/v1/outcomes/anomalies/metrics` | Investigation response metrics. | `BillingAdmin`. `scoped_read`. |
| GET | `/api/v1/outcomes/anomalies/{anomaly_id}` | Investigation detail with events. | `BillingAdmin`. `scoped_read`. |
| POST | `/api/v1/outcomes/anomalies/{anomaly_id}/actions` | `acknowledge`, `assign`, `investigate`, `note` or `resolve`. | `BillingAdmin`. `full_scope`. |
| POST | `/api/v1/outcomes/suppressions` | Approve a planned exception. | `BillingAdmin`, `TenantAdmin` and a verified human session. `full_scope`. |

The page also calls `GET /api/v1/scans/{scan_id}/resources` to populate the resource picker.

## Data and evidence

**What's stored** (enterprise evidence store, scoped to each tenant)

- `savings_cases` and `savings_case_events`: case state, version, payload, verification, and an immutable event history with hashed actors.
- `savings_evidence_receipts`: signed receipts with their fingerprint, kind and binding.
- `savings_verified_actions`: the one-to-one binding between a provider action and a case.
- `savings_financial_claims`: append-only claim revisions with ledger digest and receipt IDs.
- `finops_ownership`, `finops_anomalies`, `finops_anomaly_events` and `finops_suppressions`.

**Provenance**

- The estimated opportunity is a retail-based scan estimate (`estimate_basis: saved_retail_opportunity_not_billing_or_realized_savings`).
- The run rate and financial benefit rely on authorized collector attestations plus exact imported charges.
- Investigations are based on delayed imported billing only (`provider_reconciled: false`, `causation: not_established`).

**What is NOT proven**

- CloudSaver does not independently audit invoices.
- Category changes are not a diagnosis of whether usage or price caused a change (`usage_vs_price: unavailable_without_usage_quantity_and_rate_evidence`).
- Nearby agent tasks are not proof of a deployment or cause.
- Ownership mappings route accountability. They do not retroactively allocate bills or establish shared-cost chargeback.
- Regular billing imports and workflow clicks cannot self-attest an outcome. Missing receipts leave values unknown, never zero.

## Permissions

| Capability | `Viewer` | `BillingAdmin` | `TenantAdmin` |
| --- | --- | --- | --- |
| Open the page and read cases, investigations and ownership | No | Yes | Yes |
| Create cases, assign, review, implement, reopen | No | No | Yes |
| Approve a case | No | No | Yes, verified human session |
| Validate a case | No | Yes | Yes |
| Reconcile a case | No | Yes, verified human who is not the approver | Yes, verified human who is not the approver |
| Run detection and act on investigations | No | Yes | Yes |
| Save ownership | No | No | Yes |
| Approve planned exceptions | No | No | Yes, verified human session |

A verified human session (`human()` in [app/outcome_contracts.py](../../app/outcome_contracts.py)) has no workspace `key_id`, is not a service account, and has a `user_id`, or `subject_type: user` with a `subject_id`. Shared workspace keys cannot approve, reconcile or suppress. All records are filtered to the providers and scopes your key is authorized for (`scope_allowed` in [app/outcome_store.py](../../app/outcome_store.py)).

## Configuration

| Variable | Purpose | Default |
| --- | --- | --- |
| `CLOUDSAVER_EVIDENCE_SOURCES` | JSON list (up to 100) of collector grants: `tenant_id`, `source_id`, `providers`, `kinds` (`audit`, `billing`, `slo`), `scope_ids` and `key_env`. Leave empty to disable receipt ingestion. | `[]` |
| `CLOUDSAVER_EVIDENCE_KEY_*` | Collector signing secret (at least 32 characters), named by the grant's `key_env`. `.env.example` uses `CLOUDSAVER_EVIDENCE_KEY_OUTCOMES`. Map it only to the core verifier service. | Empty |
| `CLOUDSAVER_AUTH_MODE` | `workspace` or `entra`. Verified human sessions require user sign-in rather than a shared workspace key. | `workspace` |

Billing evidence comes from the FOCUS ledger. See [Cost allocation and billing](cost-allocation-and-billing.md).

## Guardrails and limitations

- No case action or investigation executes infrastructure. Every verification result sets `automatic_execution` to false.
- All writes use optimistic versions. A stale version returns `409` with "Refresh before updating."
- Limits: 1,000 cases per workspace, 100 claim revisions per case, 200 events per case history, 10,000 ownership rows, 50,000 charge rows and 200 candidates per detection, and 500 investigations in metrics.
- Legacy (pre-v2) cases keep their history but cannot use the new lifecycle.
- Resolved and suppressed investigations are read-only until the source evidence changes.
- Currencies are never combined in totals.

## Tests

- [tests/test_outcomes.py](../../tests/test_outcomes.py): the full human lifecycle, self-attestation prevention, collector revocation, append-only reconciliation, negative outcomes, ownership and investigation deduplication, days that are not zero-filled, planned exceptions, version conflicts, receipt signatures, health failures, corrections, and one action per case.
- [tests/test_scoped_governance_outcomes.py](../../tests/test_scoped_governance_outcomes.py): scoped route classes for outcomes.
- [tests/test_route_inventory.py](../../tests/test_route_inventory.py): every route is classified.
- [web-dashboard/e2e/outcomes.spec.ts](../../web-dashboard/e2e/outcomes.spec.ts): the three financial measures, human approval, denial for workspace keys, investigation resolution, versioned ownership, and the viewer boundary.

## Related docs

- [Financial outcomes](../FINANCIAL_OUTCOMES.md)
- [Next-gen implementation](../NEXT_GEN_IMPLEMENTATION.md) (collector grants and signing)
- [Client-managed users and keys](../CLIENT_MANAGED_USERS_AND_KEYS.md)
- [Environment reference](../ENVIRONMENT.md)
- [Cost allocation and billing](cost-allocation-and-billing.md)
- [Optimization evidence](optimization-evidence.md)
