# v1.0.0 master-guide implementation

Source: [CloudSaver Enterprise Platform: Comprehensive Feature Upgrade & Architecture Master Guide (v1.0.0)](https://docs.google.com/document/d/1FmtfohZPlnlwZ1lbcCuu-XX0G1uc6UI3Z87svw4P0zc/edit), read October 23, 2026; modified 11:37:03 UTC.

Also inspected the [Drive CloudSaver-v1.0.0.zip](https://drive.google.com/file/d/1sR1FVDmi61-B3pWyel5V5JGvwbobkPFc/view). SHA-256: `d77c4cb4bd717669a360a60625d850549a7608a8a01be35ec7763e43723cfa4d`. Its README identifies v0.4.1; its AWS scanner contains error-to-demo fallback, pricing uses regional reference constants, and the ITSM component formats payloads without dispatch or webhook synchronization. These findings come from source inspection, not an executed acceptance test of that package. Packaged databases, bytecode, demo state, keys and old frontend dependencies were not imported into the application.

The implementation extends verified GitHub v0.11.0 (`053db837e3d184c4e8847a93a93c58842bb7efea`), whose CI completed successfully. The new artifact is named **CloudSaver-v1.0.0-integrated.zip**, preserving the original Drive package.

## Mapping to the eight feature areas

| Guide area | Working implementation | Remaining boundary |
| --- | --- | --- |
| 1. Multi-cloud discovery | Existing keyless scoped Azure/AWS/GCP/Kubernetes readers, complete pagination and fail-closed collection; new pool of at most four independent account/region readers, stable output order and all-or-nothing results | EC2 CloudWatch idle inference, more resource types, production throughput/load acceptance |
| 2. FinOps attribution | New normalized FOCUS field-subset imports; decimal-preserving billed/effective/list costs, charge deduplication, credits, isolated currencies, conditional ESR, declared daily coverage, provisional month-end budget projection and nonseasonal Z-score signals | Native CUR/Azure export/BigQuery connectors, billing reconciliation, certified full FOCUS conformance, inferred amortization and validated net snapshot savings |
| 3. Tenancy/security | Existing verified Entra access tokens, server-owned workspace scopes, three application roles and PostgreSQL forced RLS; finance-only billing endpoints and RLS on all four new evidence tables | Four-level organization hierarchy, five new role mappings, browser PKCE/consent/membership workflows |
| 4. Backend/concurrency | Existing durable Azure HTTP-202 jobs/outbox, owner-fenced leases, readiness, correlation and bounded DB pools; new bounded concurrent multi-source reading | Durable interactive multi-cloud jobs, cooperative cancellation and deployment fault/throughput acceptance. Multi-cloud HTTP remains synchronous |
| 5. Enterprise AI assessments | Existing evidence-led five-pillar rules and keyless target adapters; new committed attempt intent, permanent per-key fences, saved outcomes, append-only runtime lifecycle events and provider usage grouped by model/target/structured cost-center and application IDs | Semantic truth validation, reconciled dollar budgets, PTU/model-selection evaluation, vector retrieval, SageMaker, provider Guardrails and full topology evidence |
| 6. Remediation/GitOps | Existing protected-intent suppression, human approval, live tag/state checks, successful pre-deletion disk snapshot in generated Bash and import-only Terraform/GitHub App draft-review workflow | No execution engine or score-based action approval. Snapshot retention remains the existing 90-day operator instruction; no lifecycle enforcement or restore certification |
| 7. ITSM/governance | Existing durable tenant-bound Slack/Teams deliveries, operational replay/audit; new inference lifecycle and append-only billing evidence | Native Jira/ServiceNow ticket dispatch and authenticated status synchronization remain unimplemented. A ticket or model score cannot unlock infrastructure execution |
| 8. Console/UX | Existing dark/light six-view console, command search, virtual inventory, comparison and evidence drawers; new billing upload/review, currency/date/budget controls, coverage inspection and AI assessment/usage/history tab | Raw telemetry/dependency feeds and broader usability/load testing. No invented flatlines, safety percentages or measured savings |

The guide's performance, retention, ZDR, safety-score and compliance statements are requirements or aspirations, not observed guarantees. No AI-generated action approval, blind deletion, downgraded dependency chain, copied credential examples or demo-as-live behavior was introduced.

## Schema and activation

Review and apply Alembic **0009_enterprise_evidence** as the schema owner before starting upgraded PostgreSQL services. It adds `ai_inference_attempts`, `ai_inference_events`, `focus_imports` and `focus_charges`, each with enabled and forced RLS. Cross-owner references are composite where applicable. The runtime role cannot update/delete lifecycle or billing records; completed/uncertain inference outcomes cannot be rewritten. An owner/superuser can administer storage, so this is not tamper-proof WORM or compliance certification.

The local SQLite development path persists the same feature data with explicit tenant predicates; it does not provide PostgreSQL database-level RLS. Shared deployments require PostgreSQL with the existing restricted application role. No shared Compose stack or existing customer database was modified during verification.

The API factory now uses the SQL inference ledger for its default gateway. AI remains off unless the operator enables it and binds approved targets. No provider call occurs during import, history or usage reads. Database reservation failures stop inference before a provider call. An accepted provider request with a lost result remains pending/uncertain, with no automatic replay. Cached reads do not count as new attempts. The hourly limit uses database time and tenant-scoped transaction serialization; no DB transaction spans model inference.

SQL fences and stored advice have no automatic TTL. Define backup, retention and owner-controlled purge procedures before deployment. This release does **not** migrate old Redis inference records into SQL: pause inference during cutover, retain outstanding old keys/outcomes and do not resubmit old uncertain requests. The legacy directly constructed SDK Redis coordinator still has its documented 24-hour limits; it is not the API's new coordinator. A restored/lost database can still lose inference history; exactly-once external inference is not guaranteed.

Structured `CostCenter` and `ApplicationId` tag values may label usage if unambiguous and bounded to identifier characters. Missing, conflicting or malformed values become `unassigned`. These identifiers stay in SQL metadata and are never added to the model context. Attribution remains observed/unverified, not a finance ownership assertion. Actor references are tenant-scoped hashes; workspace keys do not identify individual people.

## API

Existing bearer authentication, workspace ownership and preview-digest acknowledgement remain required.

| Method / path | Contract |
| --- | --- |
| GET `/api/v1/ai/assessments` | Tenant-owned metadata pages; `limit` 1–50, `before` owned UUID cursor, optional `scan_id` and `resource_reference` filters |
| GET `/api/v1/ai/assessments/{id}` | Saved outcome, escaped-text advisory and recorded lifecycle; foreign IDs return 404 |
| GET `/api/v1/ai/usage?days=30` | 1–90-day provider-reported known token portions, completed/unmetered/incomplete outcome counts; up to 10,000 attempts per window |
| POST `/api/v1/finops/imports` | BillingAdmin or TenantAdmin only; normalized JSON below; 201 with inserted count and replay flag |
| GET `/api/v1/finops/imports` | Recent import receipts, filtered to current authorized cloud scopes |
| GET `/api/v1/finops/summary` | Finance-only `start`, exclusive `end`, `currency` and optional nonnegative decimal-string `budget`; at most 366 UTC days |

Summary and history reads never dispatch inference or tickets. New routes are explicitly allowed through the gateway and Next proxy; caller-provided upstream URLs are not accepted.

## Normalized billing import contract

This is a documented **FOCUS 1.0 field subset**, not a universal native billing-export parser. `x_ChargeId` is CloudSaver's stable-row-identity extension. Convert native exports into this contract before uploading; do not invent missing effective/list costs. Commitment amortization must already be represented by supplied effective costs; this importer does not derive term-hour amortization or expose an independent AmortizedCost column.

```json
{
  "source_id": "example-export-2026-10-01",
  "provider": "azure",
  "sub_account_id": "00000000-0000-0000-0000-000000000000",
  "billing_currency": "USD",
  "period_start": "2026-10-01",
  "period_end": "2026-10-02",
  "complete": false,
  "records": [{
    "x_ChargeId": "example-stable-charge-id",
    "ProviderName": "Azure",
    "BillingAccountId": "example-billing-account",
    "SubAccountId": "00000000-0000-0000-0000-000000000000",
    "BillingCurrency": "USD",
    "ChargePeriodStart": "2026-10-01T00:00:00Z",
    "ChargePeriodEnd": "2026-10-02T00:00:00Z",
    "ResourceId": null,
    "ChargeCategory": "Usage",
    "BilledCost": "10.00000000",
    "EffectiveCost": "8.00000000",
    "ListCost": "12.00000000"
  }]
}
```

This example is illustrative schema data, never loaded into production. Replace account identifiers with current authorized scopes. ProviderName values are `Azure`, `AWS`, `Google Cloud`; outer provider values are `azure`, `aws`, `gcp`. Each file covers one provider/sub-account/currency and an exclusive interval of 1–366 UTC days. Charges must lie fully inside it. Null resource IDs support account-level charges; supplied IDs must match the declared cloud account. Unsupported identifiers require normalization or account-level records, not a scope bypass.

Requests are capped at 2 MB / 5,000 records. Calculations use a request-local 60-digit decimal context so permitted extreme totals/ratios do not exceed the default arithmetic precision. Monetary values are decimal strings with at most 15 integer and eight fractional digits; floats, booleans, NaN, exponent notation and missing required amounts are rejected. Credits/adjustments may be negative. Zero is retained. ListCost may be null; missing values do not become zero. Records and currency are never mixed through an implicit exchange rate.

A source ID identifies one immutable canonical import; order-independent replay returns the original receipt. Reusing it for changed data returns 409. Stable charge IDs are unique per tenant/provider/billing-account: identical charges in overlapping imports are ignored, conflicts reject the whole batch without partial writes. Corrections require explicit new adjustment/credit identities, not silent invoice overwrites. Database transactions serialize competing imports for a tenant.

`complete` is an operator declaration that the file covers all charges in that provider/sub-account/currency interval, including days with zero spend. It is not independent reconciliation. The latest overlapping declaration determines coverage for each scope/day. A partial update removes completeness until a later complete declaration. A day is complete only if all relevant current scopes are covered, the day is closed in UTC, and no multi-day charge would require invented daily allocation. Missing days remain null. A complete empty export may establish observed zero.

Totals include only fully contained charge periods. Overlapping, partially contained charges are counted separately and never prorated. ESR is `(1 - effective/list) * 100` only when every included record has list-cost evidence and the total list cost is positive. It is an imported-cost ratio, not measured optimization savings.

The provisional month-end projection needs a month-to-date window ending after the last selected closed day, complete daily coverage throughout, seven covered closing days and nonnegative recent velocity. It uses the last seven days' mean billed cost and actual calendar days remaining. A supplied budget produces an overrun review signal. The 30-day population Z-score needs 31 complete days and nonzero baseline variance; it is nonseasonal and not a root-cause diagnosis. None of these calculations certifies provider reconciliation, future spend, snapshot overhead or realized savings.

## Console workflows

Cost allocation now includes finance-restricted billing evidence: explicit JSON selection, file-size check, source/record preview, scope/completeness acknowledgement, import receipts, date/currency/budget filters, provider amounts, daily coverage and provisional projections. File contents and credentials remain in memory; disconnect clears the session. Reads and file selection do not import automatically.

Activity & delivery adds **AI assessments**: provider-reported usage and unmetered portions, recorded attempt status, paginated history, saved advice/provenance and lifecycle events. Pending/uncertain outcomes have no retry/approve/execute control. Switching tabs or sessions aborts reads and prevents late responses from appearing in another context. Scrollable evidence tables are labeled and keyboard-focusable.
