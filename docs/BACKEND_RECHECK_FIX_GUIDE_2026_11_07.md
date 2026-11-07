# CloudSaver backend recheck and repair guide

Review date: 2026-11-07. Source baseline: `f021af0` (`fix: harden backend evidence boundaries and restore CI contracts`).

This is a source-based repair guide, not a certification that the backend is error-free. The checkout was clean at the start of this review. No new remote fetch, cloud operation, deployment, application-code change, or push was performed in this documentation pass. References below are relative to this repository and describe this commit. Existing API compatibility should be preserved through additive contracts and explicit migration plans.

## 1. Executive assessment and evidence

The earlier CI runtime exceptions have been repaired, but passing local tests does not close the remaining data-quality, isolation, and durability gaps. The most consequential remaining paths are:

1. Code Mode treats a forbidden-token regex as a JavaScript execution boundary.
2. Resource GET requests can collect and persist cloud evidence; refresh state can conceal missing evidence and get stuck after errors.
3. Financial profile code can substitute estimated waste for retail cost and accept reconciled benefits without an explicit matching period/currency contract.
4. Grafana handlers do not consistently constrain shared records to their own integration kind before reads or writes.
5. Financial queries and latest-record lookups apply important filtering after global limits or aggregation.
6. Assessment helpers still interpret some missing telemetry as evidence of idleness; absence of findings can produce a perfect score.

### Verification provenance

The retained prior local run against the pushed changes reports **1,510 passed, 101 skipped, one warning**, in 164.44 seconds; measured coverage **85.31%**, above the 85% gate. Evidence: `/tmp/cloudsaver-recheck-full.log` in this execution workspace. This temporary path is not a durable CI artifact. The report's measured coverage applies to the configured coverage selection, not automatically every service.

That suite was **not rerun in this documentation pass**. PostgreSQL/Redis-dependent acceptance is not established by this local result. A final disposable real-stack rerun was blocked by Docker storage exhaustion. Earlier real-stack results preceded the final fixes and must not be presented as current acceptance. Publish fresh CI reports with commit SHA, test selection, dependency versions, skips, and service logs before release.

Evidence labels used below:

- **Confirmed source behavior:** inspected control flow or query establishes the described behavior; deployed exploitability or incident frequency is not implied.
- **Acceptance gate:** a required runtime or integration check not established here.
- **Proposed contract:** intended implementation guidance, not an existing supported endpoint or feature.

### Previously repaired: do not reopen without a regression

| Earlier issue | Current disposition |
|---|---|
| Undefined telemetry `contract`, scanner `observed_at`, duplicate resource `analysis_readiness` | Repaired in the baseline commit; retain regression coverage. |
| Internal analysis route registration and rule-catalog authorization inventory | Reconciled; continue route-inventory tests when adding handlers. |
| Grafana deadline fixture / async execution expectations | Updated; do not remove production deadline or lease controls. |
| Optional vector-extension creation by a restricted owner | Migration now accommodates absent/preinstalled extension; real upgrade acceptance remains required. |
| Missing component/day billing coverage permitting a booked delta | Guard added; semantic period/currency/source completeness still needs the work below. |
| Scoped pillar-analysis leakage and provider-ID collisions | Filtering/regressions added; this does not prove all aggregate queries are scoped correctly. |
| Metric envelopes, valid zero values, nonfinite numeric inputs | Specific loader paths hardened; inspect other numeric boundaries independently. |

See [existing backend improvements](BACKEND_IMPROVEMENTS.md), [boundary regressions](../tests/test_backend_boundary_regressions.py), and [scoped-store regressions](../tests/test_scoped_store_resource_reads.py).

## 2. Prioritized repair backlog

Priority P0 means a release blocker for enabling the affected capability; P1 means correctness/reliability work before customer acceptance; P2 means scale and operational hardening. It does not imply every affected feature is deployed or reachable anonymously.

| ID | Priority | Workstream | Completion evidence |
|---|---|---|---|
| BE-01 | P0 if enabled | Code Mode execution isolation | Isolated runtime and adversarial resource/capability tests |
| BE-02 | P1 | Durable Code Mode dispatch and response validation | Crash/replay/mismatched response tests |
| BE-03 | P1 | Asynchronous resource refresh | Concurrent requests, lease expiry, cancellation and stale evidence tests |
| BE-04 | P1 | Financial meaning and comparability | Currency, period, revision and counterfactual tests |
| BE-05 | P1 | Grafana integration-kind boundaries | Foreign-kind read/update tests with unchanged durable state |
| BE-06 | P1 | Scoped financial SQL | Hidden rows cannot affect visible totals, currency, or limits |
| BE-07 | P1 | Evidence-aware recommendations and scores | Missing-input cases return unknown/unassessed |
| BE-08 | P2 | Latest-record and resource lookup completeness | Large-dataset tests and query plans |
| BE-09 | P1 gate | Azure transport, scope and freshness | Authorized sandbox evidence plus failure simulation |
| BE-10 | P1 gate | Database/runtime/migration acceptance | Fresh and upgrade runs under restricted roles |
| BE-11 | P1 gate | AI policy and workflow routing | Every inference/dispatch entry point passes negative authorization tests |

## 3. BE-01 — Replace Code Mode's regex execution boundary

**Confirmed source behavior.** [Python validator](../app/code_mode_validate.py) and [worker bridge](../workers/code-mode-bridge/src/index.js) reject selected lexical tokens. The bridge then constructs code using `new Function` and calls the submitted transform. Blocking literal `Function(` does not establish isolation: JavaScript can obtain constructors indirectly. A harmless candidate regression input is `function transform(input) { return (() => {})["constructor"]("return 7")(); }`. Its indirect constructor expression is not covered by the current forbidden-token pattern. This review did not execute hostile code or test a deployed worker.

The bridge also reads the full request body before verifying its shared-secret/HMAC headers. There is no application-level bounded stream read or output-size check in this handler. A signed request has no timestamp/nonce replay window. Platform limits may exist, but they do not establish the application's intended per-run contract.

**Repair:** keep this capability disabled for untrusted snippets until an actual isolated execution mechanism is selected and tested. Use a runtime with no ambient secrets, filesystem, provider identity, or outbound network. Expose only explicitly registered typed capabilities when needed. Enforce CPU/wall-time, memory, input/output byte limits and concurrency quotas. Syntax validation is useful for usability, but must not be the security boundary. Verify the chosen Cloudflare execution mechanism actually supports the required dynamic-code workflow; source presence is not deployed-runtime compatibility.

**Acceptance:** indirect constructors, escaped identifiers, prototype access, infinite loops, recursion, huge output and malformed bodies must terminate or reject within the configured budget. Test zero provider-secret/network access. Bind signed requests to run, tenant, snippet digest, timestamp and replay identity. Ensure duplicate delivery follows a documented idempotent result contract. Run these checks only in an isolated test harness.

## 4. BE-02 — Commit execution intent before external dispatch

**Confirmed source behavior.** [CodeModeRepository.create_and_execute](../app/code_mode_store.py) invokes the bridge inside the write transaction that inserts the run and audit intent. A process failure after external execution but before commit can lose the durable record of execution. A slow bridge holds the transaction open. [Executor](../app/code_mode_executor.py) checks only that the returned JSON is a dictionary; it does not bind the returned tenant/run/digest to the request. It reads response bodies without an application byte cap, and provider error body text can become persisted error detail.

**Repair:** transactionally create a queued run and outbox intent, then commit. A worker claims with a database-time lease and fence, dispatches a stable run ID, and commits the result only under the current fence. Treat dispatch ambiguity explicitly; do not silently re-execute an action with uncertain external effects. Validate a strict response schema including identity and digest. Use bounded reads and safe error categories; keep sensitive diagnostic data in restricted logs with redaction.

**Acceptance:** kill the worker before dispatch, after dispatch, and before result commit. Verify replacement claims cannot overwrite newer results. Reject a valid-shaped response for another tenant/run, unknown status, oversized JSON and invalid digest. Test retries with same/different idempotency bodies and reauthorization after principal revocation.

## 5. BE-03 — Separate resource reads, refresh jobs and evidence quality

**Confirmed source behavior.** [Resource API](../app/resource_api.py) invokes `refresh_observation_if_stale` on detail paths. [Refresh implementation](../app/resource_refresh.py) defaults automatic refresh to enabled, performs live Azure collection and analysis, and persists results. Its cached `refresh_in_progress` read and subsequent write are separate operations, so this check does not provide an atomic claim across replicas.

After marking analysis running, a failure can reach the outer exception handler, which returns the previous observation without recording a terminal refresh state. [Timestamp projection](../app/resource_timestamps.py) computes `stale = evidence_needs_refresh(ev) and not refresh_in_progress`; starting refresh therefore suppresses the stale/incomplete indication even though usable new evidence has not arrived. The refresh also carries the saved scan timestamp into new analysis. The implementation is Azure-specific: enforce provider applicability before invoking it.

**Repair:** make GET return a bounded stored projection. Introduce an explicit, authorized idempotent refresh command and scheduled refresh jobs; preserve existing clients through an additive migration. Maintain independent fields for evidence freshness, refresh job state, last attempt and last successful collection. Use source observation time and actual collection time separately. A running job must not make old evidence fresh. Terminal errors, cancellation and expired leases must remain recoverable. Scope checks occur at enqueue and dispatch.

**Acceptance:** 20 concurrent reads must not create 20 cloud collections. A provider timeout leaves the last good snapshot visible as stale, with a safe error and next retry. Simulate process termination after marking running and ensure lease recovery. Test scope removal, duplicate queue delivery, Azure refresh requested for a non-Azure resource, future timestamps, and mixed-age metric/configuration sources.

## 6. BE-04 — Repair financial labels, units and comparison selection

**Confirmed source behavior.** In [Azure JSON profile](../app/azure_json_profile.py):

- `retail_monthly_from_scan` falls back from `retail_estimate_usd` to `estimated_monthly_waste_usd`, then labels the result as a retail-meter basis. Avoidable opportunity is not total retail cost.
- `finance_reconciled_benefit` selects the latest reconciled case before checking the requested period. A newer nonmatching case can hide an older matching case.
- Period mismatch is rejected only when stored period fields are present; absent period metadata can be accepted for a requested window.
- The helper has no requested-currency argument or currency comparison before returning an amount.

**Repair:** use distinct typed amounts for retail cost, billed/effective cost, estimated opportunity and reconciled benefit. Each carries currency, unit, exact interval, scope, source revision, calculation version and completeness. Never substitute one financial measure for another. Filter comparable cases before selecting the newest eligible revision. Require explicit matching interval and currency; missing metadata yields unavailable, not a reusable number. Convert currencies only through a versioned approved FX input.

Coverage guards already added for missing components/days must remain. Received-day counts are not proof of source financial finality. Require exact expected partitions and a source-specific replacement/incremental contract; only a complete comparable replacement snapshot can imply absence. Late credits create new calculations rather than overwriting reports.

**Acceptance:** waste=$30 and retail unknown must not display $30 retail. Test EUR billing with USD estimates, absent dates/currency, adjacent windows, a newer wrong-period case plus an older matching case, partial snapshots, negative credits, late adjustments, zero amounts and decimal rounding residuals. Assert both result and explanation/source references.

## 7. BE-05 — Enforce Grafana record kind before access or mutation

**Confirmed source behavior.** [GrafanaK8sStore.job](../app/grafana_k8s_store.py) reads the shared `observability_jobs` table by tenant and ID without filtering `grafana_rightsizing` kind. The worker already has a kind-filter helper, but this read does not use it. A same-tenant unrelated job can therefore be returned through the Grafana job route if its ID is known. This is a cross-feature boundary issue, not proof of cross-tenant access.

[Grafana update handler](../app/kubernetes_grafana_api.py) invokes the generic connector update and only afterward checks the returned connector kind. This does not enforce that the original record belonged to the Grafana integration before mutation.

**Repair:** constrain the SELECT and UPDATE predicates to tenant, ID and expected kind. Check optimistic version in the same write predicate. Return a non-enumerating 404 for another kind and leave the record unchanged. Reuse repository methods that enforce the integration-specific boundary rather than post-validating a generic write.

**Acceptance:** request a non-Grafana job through the Grafana route; expect 404 and no unrelated payload. Submit a valid Grafana envelope against a non-Grafana connector; assert unchanged kind, configuration, version and mutation history. Test tenant mismatch, stale version and concurrent updates. Preserve the existing asynchronous 202, lease/fence, deadline and safe-error controls.

## 8. BE-06 — Scope financial SQL before aggregation and limits

**Confirmed source behavior.** [FOCUS summary](../app/focus.py) chooses automatic currency from tenant-wide charge counts. `_summary` reads up to 50,001 charge/import rows for the tenant/currency before applying provider/account authorization in Python. Unauthorized rows are excluded from the final totals, but can still select the visible currency or trigger a limit error for a narrowly scoped caller.

**Repair:** compile the authorized provider/account predicate into currency selection, charge selection and coverage selection. Apply it before grouping, sorting and limits. Keep parameterized SQL and RLS; RLS tenant isolation alone does not implement provider/account grants. Ensure empty or revoked grants deny access rather than dropping the predicate. Centralize scope compilation and use equivalent semantics on PostgreSQL and test backends.

**Acceptance:** a caller with one authorized USD account must get the same result when 60,000 hidden EUR or USD rows are added elsewhere in the tenant. Test hidden imports, empty grants, provider collisions, scope revocation and explicit currency selection. Validate query plans with representative indexes. Do not solve this by raising limits indefinitely.

## 9. BE-07 — Make recommendation eligibility and scoring evidence-aware

**Confirmed source behavior.** [Evaluation helpers](../app/analysis_service/evaluators/_helpers.py) treat missing network input/output as zero in `is_idle_compute`. `is_idle_load_balancer` accepts missing request history when target count is zero. [Cost evaluator](../app/analysis_service/evaluators/cost.py) includes a 35% estimate formula; this is not an observed candidate SKU price. [Pillar scoring](../app/analysis_service/scoring.py) returns 100 when there are no relevant findings, without receiving assessment coverage.

**Repair:** return structured eligibility with `pass/fail/unknown/not_applicable`, required evidence, observed coverage and blockers. Unknown network history must not become idle traffic. Missing findings must be distinguishable from completed checks with no findings. Separate a numerical score from coverage and assessed status; display no trusted score when prerequisites are absent. Label heuristic estimates explicitly or suppress them until a compatible priced candidate exists. Keep ownership, workload SLO, representative peak, retention and IaC checks as independent proposal/execution gates.

**Acceptance:** low CPU plus missing network produces unknown idleness; zero targets plus absent request history remains a review signal. Empty inventory and unavailable collectors must not become healthy coverage. Test incompatible SKU, missing memory, seasonal demand, legal retention and complete negative findings. Pin evaluator/rule/policy versions and evidence digests so repeated evaluation is reproducible.

## 10. BE-08 — Remove silent latest-record and lookup truncation

**Confirmed source behavior:**

- [ResourceStore.latest_decisions](../app/resource_store.py) fetches the latest 20,000 tenant decisions before filtering requested resource keys. Older applicable decisions can disappear behind other resources' activity.
- [ObservabilityStore.latest_snapshots](../app/observability_store.py) limits to 500 tenant snapshots before choosing one per connector. A quiet connector can disappear behind a busy connector.
- [Resource API](../app/resource_api.py) includes identity/filter loops bounded at 10,000 inventory rows. This needs an explicit incomplete result or a direct indexed lookup, not an implicit not-found for an existing later resource.

**Repair:** put requested keys and scope predicates into SQL. Select latest per entity using deterministic window functions or PostgreSQL `DISTINCT ON` with a tie-breaker. Use direct normalized identity lookup for resource details. Keep limits for safety, but report bounded/incomplete queries explicitly. Profile batched reads to avoid replacing truncation with unbounded N+1 queries.

**Acceptance:** seed more than each former cap with a requested record beyond it. Test equal timestamps, empty key sets, provider/native-ID collisions and authorization. Compare results against a complete reference calculation and capture query plans and latency distributions.

## 11. BE-09 — Azure collection and freshness engineering

The current [JSONReader](../app/cloud_http.py) already includes pacing (default 0.25 seconds) and delegates transport handling; do not replace existing controls without measuring their behavior. [Batch metrics](../app/collectors/azure_monitor_batch.py) is used by the bulk path in [azure_live](../app/collectors/azure_live.py), while [resource_pipeline](../app/collectors/resource_pipeline.py) invokes `enrich_live_row` without prefetched batch metrics. This means batch support existing in the tree does not establish that every active collection path uses it.

### Proposed collection contract

1. Maintain a verified capability record per endpoint profile, operation, scope and API version. Separate inventory, metrics, activity, pricing and billing permissions.
2. Schedule by source freshness target and workload importance. Deduplicate overlapping requests for the same source/window/resource set.
3. Use bounded shared concurrency and quota budgets keyed to the provider's actual throttling dimensions. A process-local pace does not establish a fleet-wide limit.
4. Honor valid `Retry-After`, use bounded exponential jitter when appropriate, and enforce a total deadline/attempt budget. Do not retry forbidden access or invalid requests indefinitely. Record safe error categories.
5. Batch only compatible requests with verified region, namespace, API version and token audience. Preserve per-resource success/partial/error results. Validate actual Azure endpoint permissions and batch limits in an authorized sandbox.
6. Persist pages and checkpoints with a fence. Empty pages with continuation are not completion. Validate continuation destinations before forwarding credentials. No deletion from partial inventory.
7. Store observed, collected, last-attempt and last-success timestamps independently. Failed refresh never advances successful freshness. Record sample windows, coverage and source lag.
8. Read APIs serve stored evidence and expose stale/partial state. Querying the dashboard should not multiply provider calls.

**Acceptance matrix:** 429 with/without Retry-After; 503 bursts; connection/read timeout; token expiry; denied scope; empty continuation page; malformed response; partial batch; worker death after a page; two workers claiming the same partition; scope removed mid-sync; permanently unavailable memory; stale CPU with fresh configuration. Assert persisted checkpoints, quality markers, bounded retry behavior and no zero filling.

No system can guarantee providers never return 429 or that upstream data is always fresh. Define measured freshness objectives and alert before the agreed budget expires. Track queue age, source observation age, last successful collection, throttle rate, retry delay, expired leases and per-tenant quota exhaustion. Source unavailability must remain visible rather than being relabeled success.

## 12. BE-10 — Database, migrations and service acceptance

**Acceptance gate, not a newly proven isolation defect.** [Enterprise transaction context](../app/enterprise_store.py) uses `app.current_tenant_id`; [0038](../migrations/versions/0038_code_mode_runs.py) uses the same setting in RLS. Do not copy a different setting name from a proposed architecture into only one side of the implementation.

Required validation on disposable infrastructure:

- Fresh database upgrade and every supported existing upgrade path; capture sanitized migration stderr on failure.
- Verify all tenant-owned tables, junctions and newly introduced tables have intended RLS policies and composite references. Test actual runtime roles, not an owner connection.
- Assert runtime role is neither table owner, superuser nor BYPASSRLS; distinguish migration credentials from service/worker credentials.
- Reuse the same physical pooled connection for tenant A, no context, tenant B, rollback and exception paths. Verify missing context denies data and writes.
- Directly test cross-tenant foreign keys, scope restrictions, stale optimistic versions, concurrent claims and rejected stale fences.
- Verify financial columns and calculations preserve decimal precision and negative credits; test serialization boundaries independently.
- Exercise PostgreSQL/Redis restart, outbox recovery and restore while external work is uncertain. Reconcile before re-enabling mutations.
- Verify startup against retained volumes and existing credentials, not just fresh bootstrap. Avoid regenerating credentials incompatible with persistent PostgreSQL roles.

### Health and operational readiness

Inventory every API, worker, identity component and bridge with its actual startup command, dependencies, probe and expected failure state. This review does not claim that every service currently lacks probes.

Liveness should detect a wedged process without depending on Azure availability. API readiness should use bounded checks for dependencies needed to serve safely. Worker readiness/health should include heartbeat, dispatch capability and lease progress; a running process alone does not prove work is progressing. Provider degradation belongs in connection health and evidence quality, not necessarily application-wide readiness. Include disk, database pool, queue-age and object-store mismatch alerts. The storage exhaustion that blocked verification must be resolved before treating full-stack acceptance as complete.

## 13. BE-11 — AI routing and fetching acceptance

[Workflow routing](../app/agent_workflow_routing.py) is declarative and explicitly performs no cloud I/O. A rule's suggested channel or agent-operation name is not authorization. [Platform AI policy](../app/ai_platform_policy.py) blocks inference when current policy is unavailable. Preserve that behavior.

[Processor guard](../app/ai_processor_guard.py) has a different local contract: it rejects `ai_enabled is False`, but missing `ai_enabled` is not itself denied, and absent/empty purposes fall back to two defaults. It uses a small secret-pattern set. This is a **guard-composition review item**, not proof that a reachable inference path bypasses the stronger platform policy.

**Repair/verification:** enumerate every model call site and its complete guard chain. Require explicit processor/model/region/purpose authorization where the deployment policy requires opt-in. Use one effective policy contract; do not let fallback routing silently change processing region, provider or data classification. Scope evidence retrieval before prompt construction. Minimize fields instead of relying on secret regexes to recognize every credential. Bind cited evidence to tenant/resource/version and reject unsupported citations.

Model failure should return a deterministic unavailable state or an explicitly approved fallback. It must not prevent ordinary resource reads, invent telemetry, change an unknown assessment into a pass, or grant execution authority. Durable inference jobs need cancellation, budget reservations, bounded retries, usage reconciliation and safe errors.

**Acceptance:** missing policy, disabled tenant, empty permitted purposes, forbidden model/region, unavailable policy service, revoked scope, foreign evidence ID, poisoned retrieved text, fabricated citations, oversized context, exhausted token budget and failed provider. For workflow dispatch, separately test unknown action, changed manifest, expired approval and unavailable authorization. No model output can expand the action registry or execute arbitrary commands.

## 14. Implementation sequence and closure rules

1. Disable or isolate unsafe dynamic execution before extending Code Mode. Enforce Grafana kind boundaries and scoped financial SQL.
2. Move refresh and bridge execution onto durable job lifecycles; fix evidence freshness semantics in the same change.
3. Repair financial comparison contracts and unknown-evidence recommendations. Add compatibility adapters for existing response shapes where necessary.
4. Fix lookup completeness, then benchmark real query plans and collection fan-out.
5. Complete Azure, AI, migration, runtime-role and recovery acceptance on authorized infrastructure.
6. Run the full backend suite with PostgreSQL/Redis, then relevant platform/worker contracts. Publish artifacts and review every skip. Keep the 85% threshold; improve meaningful branch coverage rather than lowering it.

Each repair PR should include the concrete trigger, current failure, intended contract, migration/compatibility impact, focused negative tests, concurrency tests where applicable, and observable failure/recovery behavior. Mark a ticket closed only when its acceptance evidence exists for the changed commit. A source fix, a passing mock test and a dated authorized sandbox result are three different levels of evidence.

This guide adds documentation only. Production capability, provider-wide coverage, zero throttling, permanent freshness and error-free operation are not established by this review.


## Implementation follow-up (working tree, 2026-11-07)

The subsequent repair pass changed application code; the original review above remains a baseline, not a statement that every issue is still present.

- Remote Code Mode now fails closed in both Python and the worker. Stub mode remains available and status describes execution availability. A verified isolated runtime and durable dispatch integration are still open; disabling execution is containment, not completion of those features.
- Automatic refresh defaults off. Refresh timestamps use collection time, future analysis timestamps are stale, and running refresh no longer suppresses incomplete evidence. Failed refresh clears cached running state where cache writes succeed. Explicit durable refresh jobs, fencing and complete GET-purity migration remain open.
- Grafana job reads filter kind; connector updates constrain the original kind in the versioned write. Financial SQL applies grants before currency resolution and limits.
- Missing traffic no longer establishes idleness. Unpriced 35% rightsizing savings were removed. Broader unknown-result and assessment-coverage scoring remains open.
- Waste is no longer retail cost. Reconciled benefits require explicit USD and matching dates and search eligible historical rows. Non-USD billing does not enter USD-only balance calculations. Source replacement semantics and full typed-money evolution remain open.
- Latest decisions filter requested keys and rank per resource before applying a cap. Latest snapshots rank per connector before selection. Large inventory identity lookup migration remains open.

Database/Redis, sandbox Azure permissions, complete AI call-chain acceptance, restore exercises and provider freshness objectives remain release gates. No live-cloud acceptance was performed by this repair pass.

Repair verification: the backend suite completed with **1,517 passed, 101 skipped, one warning in 94.44 seconds** (`/tmp/backend-repair-full-unrestricted.log`). This invocation did not report a coverage measurement. Focused repair/financial/telemetry checks also passed (28 tests). The worker bridge was subsequently reduced to a static 503 response, and refresh failure return handling was adjusted; these final edits passed syntax/diff checks but were not included in that completed full-suite snapshot. No skipped real-service test is claimed as acceptance.

Final pre-push verification: **1,517 passed, 101 skipped, one warning in 95.15 seconds** against the final Python changes. Worker route/body rejection checks also passed. See [whole-codebase guide](CODEBASE_REVIEW_AND_ACCEPTANCE_GUIDE.md) for the expanded cross-service backlog and acceptance criteria.
