# Next-generation CloudSaver implementation

Source: [next-generation differentiation guide](https://docs.google.com/document/d/10scEX0pN62_XvvjJiQMDvxQ19xr9KpbEpx9tEcnRxTs).
Baseline: `de2bf3ed310158f98cec78b971068da0d3d3ef60` on GitHub `main`.

This increment implements the five new analysis engines, an Optimization Studio, a signed-evidence verification boundary and an auditable savings lifecycle. The source guide describes an older baseline and presents several proposed modules as already implemented. The repository now contains those new modules; this report distinguishes deterministic application behavior from live provider integration and financial proof. Competitor statistics and hypothetical discounts in the guide are not treated as measured product results.

## What changed

| Capability | Delivered behavior |
| --- | --- |
| Observed dependency map | `/optimization` can load the selected scan's authorized typed relationships, inspect source verification states and protected resources, and export the map. Unobserved endpoints are discarded. Components are limited to 200 nodes. Connectivity is not labelled cash savings or removal approval. |
| Causal counterfactuals | `simulate_cascading_topology_savings` validates an acyclic graph, requires all incoming prerequisites before unlocking a shared child, withholds inferred/stale links, reconciles repeated billed-component IDs and rejects competing opportunity alternatives. It calculates direct/downstream costs, recurring overhead, transition cost and payback. Missing costs remain unknown; negative net results are preserved. |
| SLO safety | `evaluate_slo_bounded_rightsizing` validates both 30-day, five-minute CPU and interval-P99 series and their paired coverage. Burn >1.0, interval P99 >=90% of the latency target, Pearson r >0.60, CFS >2%, OOM history, fixed heap and HPA coordination block reduction. Missing evidence blocks eligibility. |
| Kubernetes enforcement | The existing request-patch endpoint now requires a fresh signed SLO gate for every observed replica, in addition to its original utilization, controller, age, request-history, protection and replica-count checks. A user-uploaded planning file cannot satisfy that runtime gate. |
| Network analysis | NAT bypass and cross-zone alternatives use explicit, cloud-compatible destination types, observed-coverage/routing assumptions and user-supplied rates. They are not added because traffic may overlap. Unknown routing/coverage withholds the estimate. An optional AWS S3/DynamoDB Gateway Endpoint review file requires exact VPC/route identities and an independently supplied endpoint policy. Registry traffic cannot use the free Gateway model. |
| Ephemeral jobs | Completed job duration, active time and declared billed cost produce an idle allocation estimate. Startup work, minimum billing, critical-path work and commitments remain potential non-removable costs. No realized savings is claimed. |
| Commitment planning | `calculate_clean_commitment_baseline` applies `max(0, P10 hourly spend - open waste - existing commitments)` with exact decimals. The result is a planning ceiling, never a purchase authorization. `hourly_p10` provides nearest-rank math; the caller must establish timestamp continuity and comparable scope/period/basis. |
| Pre-merge firewall | The existing Terraform evaluator now rejects recognized commitment/capacity-reservation changes and provisioned/unknown Azure AI SKUs pending independent clean-baseline review. A request body cannot supply its own approval. Known PAYG deployments and Cost Explorer categories are not classified as commitment purchases. |
| Savings lifecycle | Tenant-isolated, versioned cases expose review, investigation, scheduling, rejection/deferral, system verification and automatic regression reopening. Creation is idempotent; stale writes return 409. Every successful mutation appends an event in the same transaction. |
| Financial verification | Completion requires explicit successful scope/type/region inventory, a trusted action event and equal, closed 30-day reconciled billing periods. Post-resource charges, complete snapshot/replacement overhead and one-time transition costs are deducted. Rightsizing additionally needs workload normalization and a complete safe post-action SLO window. |
| Regression reopening | A retired resource returning, recurrence of the original finding, post-action OOM evidence or CFS >5% reopens a verified case and sets its current savings claim to zero. Successful scans run this check; an optional periodic job retries saved-snapshot checks. Neither path calls a cloud mutation, billing API or model. |
| No duplicate credit | An append-only verified-action ledger binds canonical provider event identity to one case. New receipt UUIDs or case request keys cannot credit the same provider action twice. A failed follow-up scan leaves current savings unknown while preserving the prior verified period and its audit history. |
| Knowledge safeguards | Offline candidate screening strips common identifiers, rejects residual known tenant tokens and refuses client-derived origins even after redaction. It never publishes. Existing separate-database, dual-reviewer, citation, protected-action and deterministic-risk gates remain in force. No client-derived learning or training pipeline is enabled. |

## Model semantics

The studio contains two distinct forms of information:

1. **Observed topology** comes from an owned, filtered saved scan. It carries relationships and protection information. Its avoidable cost remains unknown unless independently established; an attachment is not proof that deleting its parent releases every cost.
2. **Planning scenarios** contain explicitly supplied assumptions. The mathematical result is marked `scenario_only`, `modeled`, `blocked` or `insufficient_evidence`; it never becomes a verified invoice result simply because a form was submitted.

Money inputs use nonnegative decimal strings with at most four fractional digits. Floats, booleans, exponents, NaN, whitespace and ambiguous leading-zero representations are rejected. Decimal arithmetic preserves intermediate precision. Negative calculated net outcomes are allowed. Existing FOCUS imports retain their separate eight-decimal contract; this change does not reduce historical billing precision.

The causal engine accepts at most 200 nodes, 500 edges and 50 roots. Cost components must be uniquely attributable; repeated component IDs with conflicting values are rejected. A 30-day month is an explicit payback convention. Unknown transition/retention cost is not substituted with zero.

The latency calculation uses the maximum observed five-minute interval P99 as a conservative proximity gate, not an invented global 30-day P99. Pearson correlation screens sensitivity and does not establish causation. Constant or mismatched series, insufficient paired coverage and unexplained gaps cannot authorize reduction. The same-core generation alternative is descriptive: no architecture compatibility, SLO improvement or 20–35% discount is fabricated.

## Savings states and authority

The guide groups rejection and deferral under a single lifecycle label. The implementation keeps **seven explicit states**:

```text
reviewed -> accepted_for_investigation -> scheduled
   |                  |                    |
   +------ rejected / deferred ------------+

scheduled -- trusted evidence --> verified_completed
verified_completed -- observed regression --> reopened_on_regression
reopened_on_regression -> investigation / rejected / deferred
```

Administrators can create cases and move between the review states. Finance-authorized users can request verification. Callers cannot submit `verified_completed` or `reopened_on_regression` as manual transitions. Viewer access is read-only; actual billing amounts are redacted from viewer case details, nested history and exports. Case actor identities are hashed.

Scheduling records the intended-action review time; it does not execute the action. The authoritative audit event must fall after scheduling and before the successful post-action inventory observation. Billing baseline must end before scheduling, and the observation period must start after the actual event, contain 30 complete UTC days and be closed before the inventory observation. Delayed or incomplete billing cannot be marked complete.

The current workspace cap is 1,000 saved cases. The scan resource picker shows up to 1,000 observations. These are explicit initial bounds; there is no unbounded implicit history crawl or automatic cloud discovery triggered by opening the studio.

## Migration

Apply the CloudSaver owner-role migration before starting updated API/worker images:

```bash
python -m alembic upgrade head
# New CloudSaver head: 0016_nextgen_savings
```

It adds `savings_cases`, `savings_case_events`, `savings_evidence_receipts` and `savings_verified_actions`. All four tables force tenant RLS. The runtime can insert/read events, receipts and action-credit records but cannot update/delete them. Case state/version updates use the existing tenant advisory transaction lock and optimistic version checks. PostgreSQL foreign keys bind cases to owned scans and action credits to owned evidence/cases. SQLite development storage has corresponding append-only triggers.

Platform Identity remains at `i0012_kubernetes_rules`; the separate knowledge migration remains unchanged. Existing snapshots are not rewritten into complete-scope proof. Run a new native scan to obtain explicit `scope_results`, including supported resource types and AWS/GCP regional coverage. Injected custom scanners do not automatically acquire completeness attestations.

Back up matching database/configuration versions before rollout. Disabling the new periodic worker does not remove audit history. Migration downgrade is an operator recovery procedure and drops the new evidence tables; it is not a routine rollback step.

## Configure trusted collector sources

By default `CLOUDSAVER_EVIDENCE_SOURCES=[]`. No workspace user can self-assert verified audit, reconciled billing or production SLO proof.

Register a bounded operator-owned source grant:

```json
[
  {
    "tenant_id": "11111111-1111-4111-8111-111111111111",
    "source_id": "approved-cloud-collector",
    "providers": ["azure"],
    "scope_ids": ["22222222-2222-4222-8222-222222222222"],
    "kinds": ["audit", "billing", "slo"],
    "key_env": "CLOUDSAVER_EVIDENCE_KEY_APPROVED_COLLECTOR"
  }
]
```

Use a separate source grant/key per collector trust boundary. The referenced secret must contain at least 32 characters and be injected into scanner-service through deployment secret storage. Only the non-secret grant JSON is forwarded by the common Compose environment; dynamically named secret values are not automatically passed. Collectors also need an authorized workspace service credential. The gateway preserves the dedicated `X-Evidence-Signature` header, and the application checks the workspace's provider/scope grants again. This is collector HMAC authentication plus workspace authorization, not human OIDC step-up.

Register the resource as an owned savings case before sending evidence. An envelope contains:

```json
{
  "receipt_id": "33333333-3333-4333-8333-333333333333",
  "source_id": "approved-cloud-collector",
  "tenant_id": "11111111-1111-4111-8111-111111111111",
  "provider": "azure",
  "scope_id": "22222222-2222-4222-8222-222222222222",
  "resource_id": "/subscriptions/22222222-2222-4222-8222-222222222222/resourceGroups/production/providers/Microsoft.Compute/disks/reviewed-disk",
  "kind": "audit",
  "issued_at": "<fresh UTC timestamp>",
  "payload": {
    "event_id": "<canonical provider event ID>",
    "occurred_at": "<authoritative event UTC timestamp>",
    "operation": "delete",
    "status": "Succeeded"
  }
}
```

`issued_at` must be freshly issued within five minutes, with up to 60 seconds of future clock tolerance. Old audit event times are allowed when they match the scheduled action. A repeated receipt identity with identical bytes is idempotent; changed evidence under the same receipt key returns 409. UUID provider event IDs are canonicalized before duplicate-credit detection. Revoking a source grant prevents its receipts from satisfying future gates; prior audit records remain preserved.

Sign the **original decoded JSON object**, before sending it, using UTF-8 JSON with sorted keys, compact separators and no NaN:

```python
import hashlib, hmac, json, os

canonical = json.dumps(receipt, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
secret = os.environ["CLOUDSAVER_EVIDENCE_KEY_APPROVED_COLLECTOR"]
signature = hmac.new(secret.encode(), canonical, hashlib.sha256).hexdigest()
# POST the receipt to /api/v1/optimization/receipts with the workspace credential
# and X-Evidence-Signature: <signature>. Do not log the secret or raw telemetry.
```

The receipt endpoint uses the existing 2 MB bounded/duplicate-key-rejecting JSON reader. Source/provider/scope/kind grants and the HMAC are validated before persistence.

### Payload contracts

| Kind | Required evidence |
| --- | --- |
| `audit` | Canonical event ID, timezone-aware occurrence time, `operation=delete` for retirement or `resize` for rightsizing, `status=Succeeded`. The trusted collector must obtain this from the authoritative provider activity/audit source. |
| `billing` | USD, equal closed 30-day baseline/observation date windows, `baseline_monthly_cost_usd`, `post_resource_cost_usd`, `new_backup_or_snapshot_overhead_usd`, `one_time_transition_cost_usd`, plus true `provider_reconciled`, `coverage_complete` and `overhead_inventory_complete`. Rightsizing also requires true `workload_normalized` and a documented `normalization_method`. |
| `slo` | `cpu_series`, `latency_p99_series`, `error_budget_burn_rate_30d`, `slo_latency_target_ms`, timezone-aware `observed_at`, `oom_kill_count_30d`, `p95_cfs_throttled_ratio`, `fixed_heap_configured` and `hpa_coordination_required`. Each range has `window_start`, `window_end` and `points=[{"at":"...","value":...}]`. |

For SLO receipts, the server computes the gate itself and stores the normalized result, observation time and raw-evidence digest; it does not persist raw CPU/latency samples. A submitted `gate` or `trusted` flag is not accepted. A fresh signed receipt with incomplete inputs is retained as an insufficient gate and cannot unlock a patch. A source must provide full-window OOM evidence; a sampled last-termination gauge alone cannot prove an exact zero event count.

Billing flags are **trusted-collector attestations**, not fields an ordinary workspace user can assert. The collector must reconcile actual provider invoice charges and discover replacement/backup overhead. OpenCost allocation, retail prices and operator-declared FOCUS imports do not themselves satisfy this contract. This service does not independently fetch or reconcile live invoices merely because a signed receipt exists. Deploy and validate the provider extractor/reconciliation system before enabling that collector grant.

## APIs and console

```text
GET   /api/v1/optimization/scans/{scan_id}
GET   /api/v1/optimization/scans/{scan_id}/topology/{resource_key}
POST  /api/v1/optimization/simulate/{topology|slo|network|commitments|batch}
GET   /api/v1/optimization/cases
POST  /api/v1/optimization/cases
GET   /api/v1/optimization/cases/{case_id}
PATCH /api/v1/optimization/cases/{case_id}
POST  /api/v1/optimization/cases/{case_id}/verify
POST  /api/v1/optimization/receipts
```

Case creation accepts `scan_id`, an exact resource ID present in that owned snapshot, `request_key` UUID, `action=retirement|rightsizing`, and an optional note. Review transitions accept `version`, target review state and note. Verification accepts the current case version and an owned post-action scan UUID. It cannot overwrite a stale version.

The existing Terraform evaluation API remains `/api/v1/policies/terraform/evaluate` and now applies the commitment firewall. Recognized changes remain blocked for independent review; an approved-scenario checkbox or request-supplied cost object cannot bypass it. Repository branch protection, CI check wiring, procurement approval and an authorized exception/release process remain operator responsibilities. No purchase or merge is performed by these APIs.

The studio provides separate observed-topology, causal-model, SLO-file, network/batch, commitment and saved-case workflows. It preserves decimal strings through form submission, supports mobile layouts, displays missing proof, and exports only authorized case/map evidence. Source-derived graph amounts remain unknown. Financial scenarios do not invoke an LLM, feed shared knowledge or mutate a cloud resource.

### Automatic regression retry

Successful synchronous scans and background scan completion run the saved-case regression checker. To retry missed checks periodically with Celery Beat, explicitly enable:

```text
CLOUDSAVER_SAVINGS_RECONCILIATION_ENABLED=true
```

The task is `workers.tasks.reconcile_savings_regressions`, scheduled at the existing scheduler tick. It reuses saved snapshots and records failed workspaces for retry; it performs no provider/model/billing network calls. Repeated checks do not duplicate a state-change event. Primary scan success is preserved if the post-save case check fails; that failure is logged and can be retried through this task or explicit verification.

## Supported boundaries and remaining work

- Live provider audit/flow-log/billing extractors and SLO exporters are not automatically installed. The new signed-receipt protocol is a server-enforced integration boundary, not proof that those external systems are ready. No live cloud acceptance or invoice reconciliation was performed during development.
- Observed topology is limited to currently collected, authorized typed endpoints. It is not an exhaustive causal model. Counterfactual cost components, traffic meters, avoidability, commitments and transition costs require independently established inputs.
- SLO screening does not choose or benchmark a target SKU, prove ISA/application compatibility or relax safety gates for a guessed generation upgrade. Human change approval and fresh current-state review remain required.
- AWS S3/DynamoDB Gateway Endpoint HCL is a review artifact with no default endpoint policy. Azure subnet changes, GCP private-access routes, automatic PreferClose patches, managed endpoint rollout and failover testing need provider-specific complete configuration adapters. No existing subnet/service configuration is guessed or overwritten.
- Hourly P10 collection/continuity, commitment utilization, future demand and plan-bound clean-baseline approvals require live finance/CI integration. The current firewall intentionally withholds recognized commitment changes; it does not purchase reservations, SPs, CUDs or AI PTUs.
- Kubernetes allocation estimates cannot establish node invoice reduction. A billing collector must account for reservation/commitment effects, node costs, replacement workloads and full overhead before attesting realized savings. Old or incomplete scope snapshots stay unverified, including missing AWS/GCP regional coverage.
- Human OIDC/PKCE sessions, fresh step-up, capability envelopes, time-bounded exceptions, historical HPA evaluation and complete cloud history collectors remain as documented in the prior implementation guides. Existing access/billing administration was retained; those unrelated pending features are not claimed complete here.
- Candidate scrubbing is an offline helper, not anonymization proof. Shared knowledge remains restricted to independently authored synthetic/approved public material and separate dual review. No client observation is activated as a training or contribution source. HIGH confidence or model-accuracy improvements are not invented from these scenarios.

## Verification

Validation completed for this increment:

- Full backend/platform suite: **766 passed** against disposable PostgreSQL 16 and Redis 7.
- After the final native-scan completeness and SLO-window freshness guards, the affected API, savings, worker, Kubernetes, route and platform-boundary suites were rerun: **112 passed**.
- Dashboard browser acceptance: **47 passed**, including the observed dependency map, planning engines, savings lifecycle, mobile layouts and automated accessibility checks. Browser APIs use controlled fixtures.
- Dashboard and platform portal production builds both passed compilation, TypeScript checks and page generation.
- `git diff --check` passed.

Backend runs emitted one upstream Starlette/httpx deprecation warning. Builds ran on Node 24.19.0; the repository declares Node >=24.22.1, which should be used for release validation. Tests use synthetic signed receipts. No live model inference, provider invoice reconciliation, cloud mutation, billing purchase, GitOps publication or production deployment was performed.
