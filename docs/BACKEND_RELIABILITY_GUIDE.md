# CloudSaver backend reliability analysis and fixing guide

## Scope and evidence

Baseline: `590828686de127be5d5cb01da428aa445ef7af9c` on `main`, plus follow-up fixes on `main` after README refresh. This guide covers backend APIs, data ingestion, authorization, storage, background execution, integrations and operations. UI/UX is excluded.

Evidence is source inspection and targeted regression tests, not a production certification. Existing tests listed below are verification assets. No live cloud operations, deployment, migration or destructive recovery exercise was performed for the original analysis.

Use the [route register](API_ROUTE_REGISTER.md) alongside this guide. It records the source authorization catalog from `app/route_inventory.py`, not an independently verified deployment inventory. Generate OpenAPI from each running service and compare it before claiming exhaustive API coverage.

## Executive assessment

The backend has useful foundations: transaction-local tenant context, pooled PostgreSQL connections, forced RLS in evidence migrations, scope-filtered scans, bounded provider reads, Redis cooldown coordination, decimal billing imports and progress-based worker health. Preserve these implementations and extend their tests.

The clearest weaknesses found are in metadata filtering, provider numeric parsing and the newer drift event/outbox path. Address these before increasing automated execution or collection concurrency. Other sections describe release gates requiring further inspection and runtime evidence; they are not blanket declarations that those controls are broken.

## Prioritized findings

| Priority | Source | Observed behavior | Required correction and acceptance |
|---|---|---|---|
| High | `app/provider_access.py`, `filter_scan` | `failed_scopes` was filtered by scope predicate without also requiring its provider to be in `allowed`. A provider-only restricted request could retain another provider's failure metadata when rebuilding coverage. | **Fixed:** require provider AND scope visibility for every failure record. Regression: `test_provider_restricted_scan_drops_foreign_failed_scopes` in `tests/test_resource_evidence_contracts.py`. |
| High | `app/drift/event_ingress_api.py`, `process` | Iterates `events[:100]`, returning 202 for a larger batch while silently ignoring the remainder. | Reject oversized batches before enqueueing, or persist all items through a documented bounded ingestion protocol. A 101-event request must never acknowledge all input while dropping event 101. |
| High | `app/drift/outbox_store.py`, `claim_pending/complete/fail` | Claim changes status to `leased`; completion/failure checks status but has no owner/fence argument. The inspected claim path has no expiry-based reclaim. | Add database-time lease expiry, owner/fence, conditional heartbeat/checkpoint/completion, recovery and retry schedule. Kill a worker after claim and prove another worker recovers the item while the original worker cannot complete it. |
| High | `workers/event_drift_worker.py`, `workers/delivery_worker.py` | Redis lease contention returns `skipped` after the outbox has already been claimed. The return path does not release the database claim. | Return the claim to a scheduled pending state under its fence, or use a database claim protocol that does not strand work. Test concurrent intents for the same resource and repeated dispatch. |
| Medium | `app/provider_retry.py`, `read_json` | Default `json.loads` accepts non-standard NaN/Infinity constants; default float parsing can also overflow valid exponent syntax. | Reject non-finite constants and validate parsed numeric values before downstream use. Preserve Decimal parsing for finance. Test nested NaN/Infinity and `1e9999`, with safe errors and no raw payload disclosure. |
| Medium | `app/telemetry_contract.py`, `evaluate_series` | `math.isfinite` is called on unrestricted Python integers. An extremely large integer can raise OverflowError instead of returning insufficient evidence. | Bound numeric magnitude or handle conversion overflow in numeric validation. Test a very large integer sample and ensure an unknown result with null observed value. |
| Release gate | `app/collectors/azure_live.py` | ARM root and continuation host are hardcoded to public Azure. | Either explicitly support public Azure only or introduce a validated endpoint profile shared by identity audiences, requests and continuation checks. Never allow arbitrary token-bearing URLs. |

Priorities describe impact and remediation order. Confirm exploitability and operational reachability using authorized deployment-specific tests before assigning incident severity.

## 1. API contracts and gateway consistency

### Current structure

`app/main.py` assembles domain routers; `services/gateway.py` forwards selected operations. `app/route_inventory.py` classifies routes. Some writes are classified `scoped_read`; this classification permits scoped access and is not an HTTP read-only guarantee or a replacement for role checks.

### Review every registered operation

For every method/path, record: owning handler, service, gateway exposure, identity type, role, tenant selection, provider/scope checks, strict request schema, response schema, page bounds, request-size limit, timeout, idempotency behavior, concurrency precondition, audit event and failure codes.

1. Compare mounted OpenAPI routes with the source register; account for router prefixes and parameter aliases.
2. Verify direct service calls enforce the same security as gateway calls.
3. Reject unknown fields on mutation commands; bound strings, arrays, date ranges and nested JSON.
4. Define safe error responses without provider bodies, SQL text, credentials or stack traces.
5. Distinguish 401, authorized-safe 403, non-enumerating 404, conflict 409, validation 422, quota 429 and dependency 503.
6. For durable jobs, return an identifier and polling location. Document cancellation-requested separately from canceled.
7. Reauthorize idempotent replays. Bind the key to tenant, principal, canonical operation and request hash; changed input must conflict.
8. Use optimistic versions for mutable settings and decisions; concurrent writes must not silently overwrite each other.
9. Keep old response fields compatible while introducing explicit quality/freshness fields.

Acceptance: a route cannot be added without classification and negative authorization tests. Request validation and safe error behavior must be exercised through both gateway and owning service.

## 2. Tenant, provider and resource isolation

### Existing controls

`app/enterprise_store.py`, `app/store.py` and `workers/storage.py` establish `app.current_tenant_id` transaction-locally. `database/connection.py` commits or rolls back, resets session settings and invalidates connections on reset failure. Evidence migration `0009` enables and forces RLS and uses tenant-composite foreign keys. Compose selects `cloudsaver_app` for application connections.

Do not replace the setting with `app.current_workspace_id` in isolated files. A rename requires one coordinated compatibility plan for all policies, workers, application transactions and migrations.

### Database audit

```sql
SELECT current_user, rolsuper, rolbypassrls
FROM pg_roles WHERE rolname = current_user;

SELECT n.nspname, c.relname, c.relrowsecurity, c.relforcerowsecurity
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind IN ('r', 'p') AND n.nspname = 'public'
ORDER BY c.relname;
```

Compare RLS flags against the explicit tenant-owned table inventory, excluding justified global catalogs. Audit table ownership, inherited roles, direct partition grants, views and SECURITY DEFINER functions. Runtime connections must not own tables or assume migration privileges. A user-settable tenant context does not defend against arbitrary SQL execution; parameterization and database access restrictions remain essential.

### Scope audit

`ScopedStore` filters scan reads. It does not automatically secure arbitrary domain SQL. Inspect every repository query and export separately. Filter findings, inventory, rule evaluations, dependency edges, source ledgers, failed scopes and derived totals together. Authorization must precede aggregation and cache retrieval. Cache keys need tenant and effective authorization scope.

Acceptance: same physical pooled connection used for tenant A, missing context and tenant B; rollback paths; cross-tenant foreign keys; mixed-provider scans; same-provider restricted scopes; export and background job paths. Use real PostgreSQL, not SQLite, for RLS evidence.

## 3. Identity, Keycloak and licensing

`app/keycloak.py` binds configured HTTPS issuers and audiences, verifies RS256 signatures and performs online identity/licensing requests. `app/offline_license.py` uses configured issuer, audience and pinned RSA public keys. These are different availability and revocation models.

For an invalid Keycloak token, inspect safe metadata: expected issuer/realm, audience, key ID, algorithm, expiry and server clock. Check realm reachability, TLS trust, JWKS rotation and introspection credentials without logging tokens. Do not disable signature or audience checks to restore access.

Audit public routes individually: drift ingress is classified public relative to workspace authentication but implements a webhook-secret check. Public classification does not imply unauthenticated business access is intended.

Offline licenses require signature, issuer, audience, expiry, role and entitlement validation. Immediate centralized revocation is impossible without a communication mechanism; define short lifetime, local denylist/trust updates or another explicit revocation contract. The inspected baseline contains workspace-license behavior; client-wide license drafts elsewhere are not delivered by this guide.

Acceptance: wrong issuer/audience/key/algorithm, expired/not-yet-valid token, revoked online principal, key rotation, unavailable identity service, role escalation and nonhuman approval attempts.

## 4. Provider reads, retries and quotas

`app/provider_retry.py` has bounded read retries, HTTP-date/millisecond Retry-After parsing and Redis-backed cooldowns. Defaults are three attempts and a 30-second call budget. Production refuses process-local coordination when Redis is not configured. `app/cloud_http.py` disables redirects and bounds pagination.

A per-call deadline does not bound a complete multi-resource job. Define a total job deadline, per-partition budget and fair tenant concurrency. Audit SDK retry settings separately to prevent multiplying SDK and application retries.

| Outcome | Required handling |
|---|---|
| 429 | Honor provider minimum delay; durably defer long waits |
| 502/503/504 or transient network error | Retry only eligible reads with bounded jitter |
| 401/403 | Credential/permission recovery, not a retry storm |
| Invalid page/continuation | Partial or failed collection, never complete |
| Empty page with continuation | Continue according to provider semantics |
| Ambiguous mutation | Reconcile external state before retry |

Set quotas by appropriate provider/service/account boundary; shared host-only budgets can cause noisy neighbors, while per-token budgets can evade actual account limits. Do not automatically retry generic POST mutations. Avoid token-bearing redirects and validate continuation host, path and scheme.

Acceptance: simultaneous workers, long Retry-After, Redis outage, SDK timeout, repeated cursors, empty intermediate pages, malformed JSON and bounded response sizes. No architecture guarantees zero 429s; successful handling means predictable deferral and recovery.

## 5. Telemetry and observation correctness

`app/telemetry_contract.py` validates representative windows, coverage, sample alignment, duplicate timestamps and maximum gaps. `app/collectors/live_common.py` provides collection failure provenance and state-history handling. Preserve these controls.

Never equate absent samples with zero, absent events with continuous idleness, or an absent resource in a partial inventory with deletion. Store source time, collection time, units, resolution, provenance and completeness. Keep configuration assertions distinct from owner declarations and inferred relationships.

Proposed compatible metric envelope:

```json
{"metric":"cpu.utilization","value":null,"unit":"percent","status":"unavailable","reason_code":"provider_timeout","observed_at":null,"coverage_ratio":null,"points":[]}
```

This is a proposed API contract, not an existing universal response schema. Retain last-known evidence with its old timestamp after failure. Optional telemetry failure should not erase usable configuration; database corruption and authorization failure must not be disguised as empty success.

Validate input magnitude and scaled output before serialization. Percentiles cannot be merged by averaging percentiles. Audit aggregate algorithms, demand windows, resource age and independent guest-memory availability before enabling rightsizing.

Acceptance: true zero, absent value, stale data, insufficient coverage, duplicate/out-of-order samples, huge integers, invalid units and missing workload SLOs.

## 6. Freshness, inventory and reconciliation

Define freshness objectives per data source, not one global interval. Track last attempt, last success, last complete reconciliation, source observation time, expected cadence and failure reason. Billing delivery lag differs from inventory or application metrics.

Use events as readback hints and periodic complete reconciliation as repair. Persist page/checkpoint progress atomically. Do not infer deletion when a scope loses permission. Resource identifier reuse after confirmed deletion requires an incarnation boundary so historical evidence and approvals cannot target a replacement accidentally.

Acceptance: failed region, removed authorization, partial page set, late event, reused identifier and stale cached response. A refresh failure must not advance last-success time or silently replace prior values with empty results.

## 7. Jobs, outbox and execution reliability

The newer drift outbox needs particular attention; do not assume guarantees from other job implementations apply to it. `GitOpsRemediationStore.queue_with_outbox` places request and intent in one transaction, which is useful. Claim recovery and stale-worker rejection need additional controls described in the findings.

Recommended state model: queued -> leased/running -> completed; recoverable failure -> retry_wait -> queued; permanent failure -> failed; ambiguous external write -> reconciliation_required. Cancellation is cooperative and may require reconciliation.

Add lease owner, monotonically increasing fence, database-time expiry, next-attempt time and bounded attempts. Every heartbeat, checkpoint, completion and failure update must match the current fence. Use conditional updates and verify affected rows. Redis token-checked release prevents deleting another owner's lock but does not fence later database or cloud writes.

For webhook batches, validate the full batch before committing any item or define an explicit per-item acknowledgement protocol. Stable delivery IDs and canonical payload hashes prevent duplicate side effects and changed-body replay.

Acceptance: crash after claim, crash after external success, lost Redis lease, contention, duplicate delivery, stale worker resumption, cancellation during mutation and restore with outstanding runs. Reconcile external PR/pipeline/provider state before replaying uncertain work.

## 8. Finance and billing integrity

`app/focus.py` accepts bounded decimal strings; core charge columns in migration `0009` use NUMERIC(24,8). `_import_snapshot` appends correction deltas and preserves missing groups unless explicitly authoritative. Native sync results expose unverified coverage.

Audit every downstream sum, rate, allocation, export and response conversion. Decimal input alone does not prove end-to-end financial precision. Separate currencies and windows; preserve negative credits, taxes where supplied, residuals and unattributed costs. Document rounding precision and rounding mode.

Only a verified complete replacement snapshot can establish disappearance. Pagination completion alone does not prove provider finality or invoice settlement. Persist source revision and calculation version. Late adjustments supersede reports rather than rewriting evidence silently.

Acceptance: duplicate source delivery, corrected amounts, missing group in partial versus replacement snapshot, negative charge, zero denominator, mixed currency and allocated amount plus residual equaling source amount.

## 9. GitOps, agents and AI boundaries

Audit `app/gitops_api.py`, `app/gitops_vcs.py`, `app/agent_store.py` and worker adapters for exact target, registered repository/path, immutable artifact digest, approval expiry and current authorization. A successful apply must remain unverified until technical criteria pass. Financial benefit requires separate billing evidence.

Bind plan source commit, provider/toolchain lock, state identity and target incarnation. Reject changed inputs. Ensure repository branch/environment protections are verified in the customer setup. Database and cloud writes cannot be made one atomic transaction; uncertain outcomes require reconciliation.

AI must remain scoped to authorized evidence, approved processing boundaries and budgets. Treat retrieved content as untrusted. Citation validation and output schemas supplement access controls; prompt filtering does not replace them.

Acceptance: self-approval, expired approval, drift between plan/apply, duplicate dispatch, partial apply, unregistered action, unsupported citation and cross-tenant retrieval.

## 10. Database capacity, migrations and recovery

`database/connection.py` uses bounded process-local pools, pre-ping, connect timeout and reset-on-return. Calculate the total connection budget across API replicas and Celery child processes; per-process limits multiply. Measure transaction latency and pool wait under load.

Apply expand/backfill/contract migrations using a separate migration identity. Test clean installation and every supported upgrade path. Start services only after successful migration; schema compatibility belongs in readiness. Never delete a persistent volume to repair a credential mismatch. Environment password changes do not change an existing database role automatically.

Back up PostgreSQL, evidence objects, manifests and encryption-key recovery configuration together. After restore, suspend mutations, identify missing objects and reconcile database jobs with remote pipeline and Terraform/provider state before resuming.

Acceptance: migration failure, runtime role forbidden from migration, old schema, wrong credentials, rollback, pool exhaustion, interrupted backfill and measured restore rehearsal. RPO/RTO must be measured and agreed rather than inferred from backup configuration.

## 11. Health, observability and incident operations

Compose uses service paths including `/readyz` and `/health/ready`; document the actual mapping before standardizing aliases. `workers/health.py` tracks polling progress and readiness dependencies.

Liveness should detect a stalled process/loop. Readiness should verify the dependencies needed to serve assigned work. Provider health should expose integration-specific failure and staleness without unnecessarily making persisted-read APIs unavailable.

Monitor API latency/error rate, pool wait, queue age, attempts, lease loss, outbox age, provider 429s, next retry, last complete collection, billing lag, partial scope count and authorization failures. Use bounded-cardinality metrics; keep raw resource IDs out of metric labels. Correlate request/job/attempt IDs in sanitized logs.

Runbooks must cover credential expiry, provider outage, Redis outage, database failover, stuck claims, duplicate external writes, billing revisions and restored state. Assign an operator and escalation path for each.

## 12. Verification plan

Suggested focused command, from a configured development environment with repository dependencies installed:

```bash
python -m pytest -q \
  tests/test_provider_retry.py \
  tests/test_inventory_scope_security.py \
  tests/test_resource_evidence_contracts.py \
  tests/test_route_inventory.py \
  tests/test_billing_jobs.py \
  tests/test_outbox_lease.py \
  tests/test_worker_health.py \
  tests/test_keycloak.py \
  tests/test_offline_license_security.py
```

Inspect fixture/environment requirements before running integration tests. `tests/test_postgres.py` contains real-role/RLS, pooled-context, migration and worker-fencing cases; `tests/test_control_plane_postgres.py` covers control-plane persistence. `tests/test_provider_retry.py` includes a disposable-Redis case requiring `CLOUDSAVER_TEST_REDIS_URL`. Existing older outbox tests do not automatically validate the newer platform drift outbox.

Add regression cases for every confirmed finding. Then execute real PostgreSQL/Redis tests, service-level API tests and bounded load/fault tests. Finally run authorized provider sandbox acceptance for each enabled operation and endpoint profile. Record skipped tests and unavailable dependencies explicitly.

## 13. Delivery sequence and definition of done

1. Snapshot baseline contracts and reproduce confirmed findings.
2. Fix metadata isolation and ingress acknowledgement loss.
3. Add drift outbox lease recovery, fencing and contention recovery.
4. Harden numeric/provider parsing and telemetry failure contracts.
5. Audit every domain query, API and export for tenant/provider scope.
6. Validate billing precision, revisions and completeness semantics.
7. Exercise migrations, health, load and restore procedures.
8. Publish actual supported provider operations and measured reliability results.

Each change needs a source reference, reproduction, implementation diff, compatibility notes, regression result and operational recovery path. A release is ready when its declared capabilities pass these gates; neither a provider logo nor a passing unit suite proves all APIs are operational.
