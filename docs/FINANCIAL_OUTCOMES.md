# CloudSaver 1.6.0 — financial outcomes pilot

This increment implements **verified savings cases, explicit application ownership and accountable cost investigations**. Open **Savings & investigations** in the customer dashboard. The platform portal continues to provision workspaces, principals and roles; it does not gain access to customer financial records through this release.

Read [the upgrade runbook](releases/1.6.0-UPGRADE.md) and [enterprise launch gates](ENTERPRISE_READINESS_GAPS.md). Synthetic regression results are engineering evidence, not customer invoice validation, independent audit or production acceptance. General enterprise launch remains NO-GO until those gates close.

## What each number means

| Dashboard measure | Evidence and meaning | Exclusions |
| --- | --- | --- |
| Estimated opportunity | Saved recommendation retail estimate, when available in USD, per 30 days. Multiple finding estimates on one resource are not added together. | No price means **Unknown**. This is not actual billed savings. |
| Validated run-rate reduction | Human-approved implementation, successful signed provider action, fresh complete post-change observation, accepted health/utilization and comparable signed recurring-cost/business-volume evidence. Normalized to a 30-day recurring basis. | Not an invoice credit or a forecast. Missing evidence and excessive demand changes prevent validation. |
| Reconciled financial benefit | A separate verified human finance reviewer accepts signed reconciliation against exact imported resource charges for a closed 30-day observation window. | No annualization, unverified charge imports, aggregate-to-resource guesses or overlapping financial claims. |

Negative outcomes stay negative. Currencies are reported separately and never added. Estimates/run rates use the latest saved case per resource and currency; reconciled benefit sums supported, nonoverlapping historical windows across cases. These are different denominators. The outcome metric is validated cases / implemented cases, not recommendation value. Reopening a case preserves prior append-only financial claim history; it withholds the current run rate until revalidated.

An authorized collector supplies:

```
demand_ratio = post_business_units / baseline_business_units
run_rate = baseline_recurring_cost * demand_ratio
           - post_recurring_cost - added_recurring_cost - retained_commitment_cost
financial_benefit = baseline_billed_cost * demand_ratio
                    - post_billed_cost - added_recurring_cost - retained_commitment_cost
                    - transition_cost + counterfactual_adjustment
```

Demand must be positive with a ratio between 0.25 and 4. The collector and finance reviewer must approve the linear demand normalization for this workload. The model does not establish causality or automatically adjust seasonality. `added_recurring_cost`, retained commitments and transition cost describe incremental/displaced costs **outside the already included post-resource amount**; the reviewer must exclude double counting. `counterfactual_adjustment` is signed: positive increases the demand-adjusted avoided-cost baseline, negative decreases it. It must have documented finance rationale in the review/change record. The drawer exposes these inputs and the business unit for review.

## Lifecycle and roles

`Detected → Assigned → Reviewed → Approved → Implemented → Validated → Financially reconciled`

1. A TenantAdmin selects a resource in an owned completed scan, chooses rightsizing or retirement, and saves a proposal. Baseline scan, whitelisted partial configuration, available utilization, retail opportunity and original imported billing digest are frozen.
2. The administrator assigns an accountable alias and records review notes. Approval requires a verified human TenantAdmin, a change reference and UI acknowledgment. A shared API key cannot approve.
3. Implement the separately approved change through your normal change process or a separately approved CloudSaver agent task. **No action in this outcome workflow executes cloud infrastructure.**
4. A configured collector submits a signed successful resize/delete action after approval. One provider event cannot implement two cases. Recording implementation requires the audit event to match the frozen configuration, resource and action.
5. Select the post-change scan in the dashboard snapshot toolbar. Finance can validate after signed health/utilization and comparable billing/business-volume evidence arrive. A failed evaluation remains implemented with explicit evidence-gap codes.
6. A different verified human with BillingAdmin (or TenantAdmin) reviews reconciliation. The approver cannot reconcile their own change. Missing provider reconciliation, credits, exact local charges or financial approval cannot be replaced by a checkbox in an import.
7. Record new signed evidence, including a new signed billing receipt, for a correction, then reconcile again. A new immutable revision supersedes the prior revision for that same resource/currency/window. It is not added to the previous amount. Changed source grants, newer receipts or imported charges withhold affected reported conclusions; read requests never modify the saved case.

All endpoints require an authenticated active workspace. All outcome routes are deliberately classified `full_scope` for this initial increment: provider/scope-restricted principals cannot use a workspace-wide financial report. Viewer receives 403. Finance may read, detect and investigate; TenantAdmin maintains cases, ownership and planned exceptions. Service/API principals may deliver authorized signed evidence but cannot approve/reconcile/suppress as a human. Existing agent execution approvals and per-step permits are unchanged.

Legacy savings-case records remain visible with a legacy label and retained history. They do not acquire verified status or enter the new totals automatically.

## Collector configuration and receipt delivery

Receipt ingestion is disabled by an empty source list. There is no default collector key. Operators must deploy a reviewed collector in the approved data environment and obtain financial/health evidence from authoritative systems. Current automatic billing readers continue to report **coverage unverified**; enabling an automatic reader does not make it a reconciled collector.

Example non-secret grant structure (replace UUIDs with the provisioned workspace and authorized subscription):

```json
[{"tenant_id":"WORKSPACE_UUID","source_id":"finance-export","providers":["azure"],"kinds":["audit","billing","slo"],"scope_ids":["SUBSCRIPTION_UUID"],"key_env":"CLOUDSAVER_EVIDENCE_KEY_OUTCOMES"}]
```

Set this JSON in `CLOUDSAVER_EVIDENCE_SOURCES`. Store at least 32 random characters in `CLOUDSAVER_EVIDENCE_KEY_OUTCOMES` through the approved secret mechanism. Compose maps this one secret **only to scanner-service**, the core verifier. A custom `CLOUDSAVER_EVIDENCE_KEY_*` reference requires an explicit core-only secret/environment mapping in the deployment. Never put it into browser code, a workspace access key, the agent runtime, Git, logs or an AI prompt. Use different source grants/secrets per tenant/collector responsibility. Revoke a source grant to withhold its supported conclusions; rotate the secret for future ingestion. Previously accepted records are retained for audit rather than erased on key rotation.

`POST /api/v1/outcomes/evidence/receipts` requires a finance-authorized bearer credential as well as `X-Evidence-Signature`. The collector signs **the exact raw envelope** with HMAC-SHA256: UTF-8 Python-compatible `json.dumps(envelope, sort_keys=True, separators=(',', ':'), allow_nan=False)` canonical bytes, including default ASCII escapes. Header is lowercase hexadecimal. Use JSON strings for decimal amounts and explicit UTC offsets for timestamps. This is a local attestation protocol, not a third-party invoice signature. Transport must use the supported authenticated TLS deployment; a stolen collector secret defeats that collector's attestation trust.

Envelope fields (unknown fields and duplicate JSON properties are rejected):

| Field | Contract |
| --- | --- |
| `receipt_id`, `tenant_id`, `case_id` | UUIDs. Retrying the same signed receipt is idempotent; changed content with the same receipt key returns 409. |
| `source_id`, `provider`, `scope_id`, `resource_id`, `kind` | Exact operator grant and owned case/resource binding. Azure resource IDs normalize to lowercase. No wildcard scope. |
| `issued_at` | Offset-aware timestamp, no more than 5 minutes old or 60 seconds ahead of core time. Clock synchronization is required. Old observations may be attested by a freshly issued receipt. |
| `payload` | One of the strict proof shapes below. Envelope limit 16 KB, within the existing bounded gateway/BFF request limits. |

Proof shapes are published in the API OpenAPI contract and [outcome contracts](../app/outcome_contracts.py):

- **audit:** `event_id`, operation `resize` or `delete`, status `Succeeded`, `occurred_at`, `before_configuration_digest`, optional `after_configuration_digest` (required for rightsizing verification). Digests use the canonical sorted JSON whitelisted configuration shown by the case and observed resource, SHA-256. Names/tags/secrets/full resource payloads are excluded. Whitelist includes VM size, instance/machine type, SKU/tier, disk/capacity/storage SKU and desired replicas; this is explicitly a partial configuration snapshot.
- **slo:** `window_start`, `window_end`, `policy_reference`, strict boolean `health_accepted` and `utilization_accepted`, bounded `utilization_summary`, optional `configuration_digest` (required for rightsizing). The accepted policy must be application-specific and cover the full post-billing window after implementation. Rightsizing also requires nonempty frozen baseline configuration; a newly observed size cannot prove a change from an unknown original size. The fresh post-change scan must be less than 24 hours old and explicitly report complete supported resource-type inventory for the scope, including region for AWS/GCP. Absence from an incomplete scan cannot prove retirement.
- **billing:** ISO dates `baseline_start`, `baseline_end`, `post_start`, `post_end`; `currency`; decimal strings `baseline_recurring_cost`, `post_recurring_cost`, `added_recurring_cost`, `retained_commitment_cost`, `baseline_billed_cost`, `post_billed_cost`, `transition_cost`, `counterfactual_adjustment`, `baseline_business_units`, `post_business_units`; `business_unit`; normalization method `business_volume_ratio`; strict boolean `coverage_complete`, `commitments_accounted_for`, `credits_accounted_for`, `provider_reconciled`; `invoice_reference` and `ledger_digest` for reconciliation. Both windows are exactly 30 closed days, baseline ends before approval, post starts after the provider event and ends by the post observation.

Obtain the local ledger digest using finance-authorized `GET /api/v1/outcomes/cases/{id}/billing-evidence?baseline_start=YYYY-MM-DD&baseline_end=YYYY-MM-DD&post_start=YYYY-MM-DD&post_end=YYYY-MM-DD&currency=USD`. It reports charge totals, observed daily records, categories, partial overlaps and digests. This read does not assert completeness. The collector must reconcile totals and missing periods to the trusted provider export/invoice, then sign that conclusion. Exact local resource totals must match the signed values. Partial overlapping charges or absent charge evidence prevent financial reconciliation. Account/project aggregates cannot prove a resource benefit; Kubernetes requires compatible exact resource billing evidence before financial reconciliation is supported.

No background collector or finance approval is invented when these integrations are unconfigured. The UI shows awaiting evidence/Unknown.

## Ownership and cost investigations

Application ownership is a direct resource mapping: application, environment, team, accountable owner alias and cost center. Saving requires a resource in an owned completed scan and the current revision (initial version 0). Writes append an immutable revision. History is retained; a stale write returns 409. Aliases avoid entering personal customer data. Ownership is for accountability/routing at investigation detection time; it is not retroactive financial allocation.

Detection is an explicit finance-authorized POST on imported **daily** FOCUS charges:

- Choose a closed UTC day within the last 90 days and currency, or use the latest closed imported billing day. No provider API is invoked by this action.
- Group by provider, authorized scope, resource ID (or an explicit account/project aggregate). Compare with at least 3 of the previous 4 matching weekdays. Missing days are unknown, not zero; monthly records are excluded rather than spread into daily costs.
- Flag increases strictly greater than the maximum of 5 currency units, 20% of the median baseline, and 3 median absolute deviations. This first deterministic rule targets positive spend increases, not all anomaly classes. It has no trained forecasting model or real-time telemetry claim.
- Record charge-category median changes (Usage, Credit, Adjustment, Tax, Purchase), source lag, baseline counts and evidence digest. Medians are not additive: category changes need not sum to the overall change. Usage/price decomposition is unavailable without quantity/rate evidence.
- Attach current ownership for in-app routing. Nearby agent assignments are possible correlations, explicitly not proven deployments or causes. No Slack/email/ticket is sent.
- The same entity/day/rule is deduplicated. Corrected evidence revises the same investigation, retains prior events and reopens resolved signals. If the corrected amount no longer crosses the threshold, it enters `review_required`; a person records the resolution instead of retaining a stale positive alert.
- Acknowledge, assign, investigate, add notes and resolve with classification actionable/not_actionable/planned/duplicate. Resolving requires an accountable owner and acknowledgment. Optimistic versions prevent stale decisions from overwriting concurrent changes.
- Verified human TenantAdmin can pre-approve an exact resource/window exception, at most 30 days, beginning no earlier than the current UTC day. Exceptions do not hide charges or rewrite prior investigations. The window is start-inclusive/end-exclusive; a new detection outside it is not suppressed. There are no wildcard/global exceptions in this release.

Metrics describe at most the latest 500 saved investigations: mean acknowledgment/resolution times and actionable percentage among resolved cases. They are not external alert delivery SLAs or calibrated detection precision. Detector bounds: 50,000 rows over a 29-day window and at most 200 candidate investigations per run; excess data is rejected explicitly. Case limit is 1,000 per workspace; a case report rejects more than 100 financial revisions instead of silently summing a truncated history; billing proof windows at most 5,000 local rows each; ownership history at most 10,000 revisions per workspace in the initial mapping view. Validate these bounds against a design partner's data before supporting larger tenants. Detection is bounded synchronous local work with DB statement timeouts, not an unbounded cloud job.

## Persistence, governance and operating boundary

Core migration `0022_financial_outcomes` adds forced tenant RLS on ownership, anomaly state/events, exceptions and financial claims. Runtime access cannot update/delete ownership revisions, anomaly events, approved exceptions or financial claims. Case/anomaly writes are versioned and share the existing tenant database transaction lock; action binding, claims, case state and audit event commit together. Different cases cannot claim overlapping resource/currency periods. Correction revisions supersede matching windows without deleting history.

This workflow does not call AI, train a knowledge base, export customer evidence or execute connectors. Data stays in the configured core database and authenticated application responses within the operator's approved environment. Applying existing approved connectors elsewhere remains subject to their separate governance controls. Include these new records in tenant recovery, retention, legal-hold and erasure policy review; append-only finance history is not a claim of a legally approved retention period.

Database/source operators remain trusted: HMAC validates collector identity and scope, not the truth of the underlying data. Independently reconcile representative invoices, prove SLO policies, review linear demand assumptions and perform adversarial tenant/approval tests before selling verified financial outcomes.

## Next increments and acceptance

This increment deliberately preserves the supplied roadmap sequence. It does **not** ship customer/transaction metric ingestion and general unit-economics reporting, proportional shared-cost allocation, monthly showback/chargeback, probabilistic forecasts/backtesting, GPU/model quality-cost comparisons, commitment procurement or new PR preventive enforcement. Their foundations remain existing platform capabilities; they need separate reviewed evidence contracts, workflows and acceptance fixtures. Application/team/service aggregate anomaly models also follow the direct resource/account pilot rather than pretending ownership labels are a complete allocation model.

Design-partner acceptance: reconcile known corrected invoices and retained commitments; verify independent finance approval and signed health windows; route an actual cost change to its owner; measure implemented-to-validated percentage, actionability, acknowledgment/resolution time and direct ownership coverage. Keep estimated opportunity, run-rate reduction and reconciled benefit separate in every report.
