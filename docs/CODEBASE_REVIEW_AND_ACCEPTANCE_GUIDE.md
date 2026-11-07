# CloudSaver codebase review and acceptance guide

Review date: 2026-11-07. Baseline: `f021af0` plus the working-tree backend repairs described in [backend review](BACKEND_RECHECK_FIX_GUIDE_2026_11_07.md).

## Scope and confidence

This review inventories the repository's major execution surfaces and inspects representative implementation and contract boundaries across backend, collectors, workers, dashboard, platform identity, portal, licensing, infrastructure and CI. It is not a line-by-line audit of every file, a penetration test, or proof of all provider operations. The application directory alone contains 292 files; uninspected paths require their own implementation review. A TODO, empty exception class or intentionally unsupported adapter is not automatically a defect.

**Confirmed** below means the cited source establishes the behavior. **Gate** means runtime acceptance is required; it does not allege a demonstrated bug. **Contained** means a capability has been disabled safely rather than fully implemented.

The final local backend run after the code repairs completed with **1,517 passed, 101 skipped, one warning in 95.15 seconds**. Log: `/tmp/backend-prepush-final.log` (temporary workspace evidence). This invocation did not measure coverage. The final JavaScript worker check verified `/run` returns 503 before body parsing and unrelated paths return 404. Platform, dashboard, portal, Node agent, full Docker, browser, security and cloud sandbox suites were not independently executed in this review. Do not transfer the backend result to those components.

## Repository coverage map

| Surface | Relevant entry points | Review outcome |
|---|---|---|
| API and authorization | `app/main.py`, `app/auth.py`, `app/provider_access.py`, `app/resource_api.py` | Existing scoped contracts reused; large-inventory and replay acceptance remain. |
| PostgreSQL and projections | `app/enterprise_store.py`, migrations, `app/resource_store.py`, `app/focus.py` | Several query repairs made; runtime role, upgrade and pool tests still required. |
| Collectors | `app/collectors/`, `app/cloud_http.py`, `app/provider_retry.py` | Shared read transport exists; verify all active paths and source completeness individually. |
| Durable work | `workers/tasks.py`, `workers/dispatcher.py`, `workers/lease.py` | Redis renewal and outbox dispatch exist; crash/recovery acceptance required. |
| Analysis and AI | `app/analysis_service/`, `app/agent_workflow_routing.py`, `app/ai_platform_policy.py` | Missing-traffic estimates improved; assessment coverage and guard composition open. |
| Execution | `app/code_mode_*`, `workers/code-mode-bridge/`, `agent-worker/` | Unsafe Code Mode contained; typed agent mutation controls need independent acceptance. |
| Identity and licensing | `platform/identity/`, `app/offline_license.py` | Signed offline claims exist; expiry/revocation/deployment mode acceptance required. |
| Portal | `platform/portal/lib/server/`, `platform/portal/lib/useLoad.ts` | Confirmed process-local sessions; late-response guards already present. |
| Dashboard | `web-dashboard/lib/api.ts`, `lib/session-contract.ts`, API proxy | Existing timeout/401/uncertain-write handling; route response validation incomplete in generic helper. |
| Deployment and CI | Compose files, Keycloak deployment, `.github/workflows/verify.yml` | Health checks and multiple verification jobs exist; no deployment success inferred. |

## Priority and implementation ownership

Use one accountable owner per item; roles below are proposed team responsibilities, not assigned individuals.

| ID | Priority | Owner | State / closure requirement |
|---|---|---|---|
| CR-01 | P1 | Identity / portal | Confirmed local session storage; test two replicas and restart. |
| CR-02 | P1 | Frontend / API | Confirmed generic payload assertion; add route decoders and contract tests. |
| CR-03 | P1 | API / frontend | Proxy catalog drift risk; generate method/path inventory and parity tests. |
| CR-04 | P1 | Licensing / security | Gate: offline grants, rotation, local denial and worker expiry. |
| CR-05 | P1 | Data / cloud | Open Azure/freshness/financial items in backend guide. |
| CR-06 | P1 | Workers | Gate: outbox, lease loss, uncertain writes and restore recovery. |
| CR-07 | P1 | Analysis / AI | Open unknown-evidence scoring and policy-chain checks. |
| CR-08 | P0 before re-enable | Execution | Code Mode contained; isolated execution remains unavailable. |
| CR-09 | P1 | Platform / database | Gate: migrations, retained volumes, role separation and RLS. |
| CR-10 | P1 | Operations | Gate: service-specific health and measured recovery. |
| CR-11 | P2 | Release engineering | Gate: image provenance, dependency gates and release manifest. |
| CR-12 | P1 | QA / product | Gate: real browser workflows and evidence/error presentation. |

P0 applies to enabling the affected execution feature. A gate is closed only by repeatable evidence against the release commit, not an unchecked checklist.

## CR-01: Portal sessions must survive the supported deployment topology

**Confirmed:** [portal session store](../platform/portal/lib/server/session.ts) stores sessions and provider credentials in a process-global `Map`. The implementation already has random session IDs, idle/absolute expiry, step-up timing and secure/HttpOnly/SameSite cookies. Preserve those controls. The map is not shared between replicas and disappears on process restart. Sticky routing can reduce replica misses but does not solve restart persistence or coordinated revocation.

**Fix:** either explicitly constrain the supported portal to a single ephemeral-session replica, or move sessions to a shared store with TTLs, revocation, access controls and protected credential storage. Prefer opaque browser session IDs. Coordinate refresh-token rotation with compare-and-swap or a per-session lock; concurrent requests must not rotate the same token twice. Bound session count and sweep expired data. Keep business authorization in identity APIs, independent of the portal's cached profile.

**Acceptance:** log in through replica A and use the session through B; restart A and verify the documented survival/reauthentication behavior. Concurrent refresh requests must produce one valid token lineage. Test logout across replicas, expired idle and absolute windows, stale profile after role revocation, unavailable session store and step-up expiry. Cookies and tokens must not appear in client logs, errors, telemetry or exports.

## CR-02: Validate route payloads before data reaches components

**Confirmed:** [dashboard API helper](../web-dashboard/lib/api.ts) parses JSON and rejects non-object success payloads, but returns `raw as T`; it cannot establish a requested route's fields. [session contract](../web-dashboard/lib/session-contract.ts) adds validation for workspace and scan evidence, so do not characterize the entire dashboard as unvalidated. The generic helper already handles timeouts, aborts, 401 invalidation bound to the exact token and uncertain mutation failures.

**Fix:** give critical routes generated or explicitly maintained runtime decoders. Validate list envelopes, IDs, enums, nullable metrics, finite money values and pagination cursors. Model missing/partial/stale as first-class states. Distinguish a bounded empty collection from collection failure. Treat an aborted mutation as uncertain until its idempotency/job status can be checked; preserve the current helper's protections.

**Acceptance:** inject a 200 response containing HTML, `{}`, missing array, null telemetry, unknown enum, nonfinite/invalid amount and wrong resource/tenant ID. Components must render a recoverable state without crashing, fabricating zero or showing success. Switch workspaces while a request is in flight; the previous result must not update the new workspace. A late 401 for the old token must not end the new session. Retry an uncertain write through the same idempotency identity.

## CR-03: Keep proxy, backend and authorization route contracts synchronized

**Confirmed design:** [dashboard proxy](../web-dashboard/app/api/[...path]/route.ts) uses multiple handwritten regular expressions to allow routes. The backend separately registers and classifies handlers. This is a drift-prone duplication, not proof that every route is currently broken. A backend route's presence does not prove browser reachability or correct method restrictions.

**Fix:** define a reviewable method/path inventory for externally supported operations and generate/test proxy admission from that contract. Match methods as well as paths, limit request bytes and preserve required concurrency, idempotency, correlation and content headers. Keep internal endpoints inaccessible through the browser proxy. Maintain bounded upstream timeouts and streaming/download contracts; do not buffer arbitrary exports without a size bound.

**Acceptance:** every supported frontend operation reaches its authorized backend handler; unsupported methods and internal analysis/worker endpoints are rejected. Test encoded path segments, unexpected query strings, large bodies, upstream disconnect, error correlation, content type and download limits. Verify both direct API and proxied requests enforce the same scope. A proxy allowlist is not a replacement for backend authorization.

## CR-04: Make identity and offline licensing behavior explicit

**Observed controls:** [issuer](../platform/identity/license_tokens.py) signs RS256 grants using a configured RSA key of at least 3072 bits, binds issuer/audience and expiry, and clips validity to billing entitlement boundaries. [validator](../app/offline_license.py) implements local validation, local denial IDs and matching provisioned workspaces. Offline validation intentionally cannot discover arbitrary later platform-database changes without a synchronization mechanism. Keycloak authenticates identities; commercial entitlement issuance remains a separate reviewed policy.

**Fix/gate:** publish supported verification modes and the authority for users, licenses, provider grants and background collection. Define maximum offline lifetime, emergency denial distribution, trusted key rotation and how reduced entitlements propagate. Avoid claiming immediate platform revocation for disconnected instances. Do not silently widen offline scopes to configured workspace scopes. A license is a signed grant, not a provider credential.

**Acceptance:** reject wrong issuer/audience/algorithm, unknown key, modified claims, expired/not-yet-valid grants, malformed scopes, suspended local workspace and mismatched customer. Rotate signing keys while honoring only the documented overlap. Test paid-period boundary, local denylist updates, background-license expiry and unavailable identity mode. Verify secrets remain outside Git and that `.env` generation preserves existing persistent credentials. Do not print real credentials in test reports.

## CR-05: Data fetching, quality and money must remain independently verifiable

Use [BE-03 through BE-09](BACKEND_RECHECK_FIX_GUIDE_2026_11_07.md) for source-specific triggers and repair steps. In particular, batching existing in one legacy path is not proof the active scanner batches requests. Neither a received page nor a successful HTTP status proves complete inventory, sufficient telemetry or final billing.

**Acceptance:** each provider/service operation has a dated capability record: API version, endpoint profile, exact scope/permissions, pagination termination, quotas, source lag, fields and cost assumptions. Test partial pages, empty continuation, revoked scope, regional failure, Retry-After, timeout and duplicate delivery. Changes to native IDs create the documented incarnation behavior. Billing corrections preserve source revisions and calculations. Unknown memory/network/workload demand cannot yield a safe rightsizing conclusion. Measure freshness objectives per source; never promise permanent freshness or absence of provider throttling.

## CR-06: Prove worker fencing and uncertain-write recovery

**Existing controls:** [lease heartbeat](../workers/lease.py) renews production ownership and raises on loss; its separate in-memory manager is explicitly a legacy test double. [delivery dispatcher](../workers/dispatcher.py) claims events, checks authorization callbacks, fingerprints destinations and bounds retry behavior. [Node worker](../agent-worker/src/main.ts) heartbeats assignments and checks failures before start. These are useful controls, not evidence of exactly-once external effects.

**Fix/gate:** inventory each worker's claim, renew, commit and external-call boundaries. Confirm callbacks are actually supplied by production entry points. Every commit checks the current fence. Distinguish queued retry from a write that may have happened. For dispatch/notification, define delivery dedupe and retention. Cancellation must not claim to undo completed provider calls.

**Acceptance:** two workers claim concurrently; old worker pauses past lease expiry; replacement completes; old worker resumes and cannot commit. Kill between outbox commit/publish and dispatch/result. Simulate lost heartbeat, revoked authority, duplicate webhook, changed destination, 429 and persistent denial. Restore database to an earlier point with a later external execution; writes remain disabled until reconciliation identifies the actual state.

## CR-07: Assessments and AI need separate evidence and authorization contracts

[Workflow channels](../app/agent_workflow_routing.py) are declarations, not permissions. [platform policy](../app/ai_platform_policy.py) already fails closed when unavailable; [processor guard](../app/ai_processor_guard.py) has defaults that require call-chain review. Missing traffic estimates were repaired, but a perfect pillar score derived from no findings still needs coverage semantics.

**Fix/gate:** enumerate model invocation entry points and prove each uses the effective policy before retrieving data or exporting context. Record approved model, region, purpose, data classification, policy version and usage. No fallback may silently broaden them. Add evaluated-check coverage alongside scores; do not infer a pass from a collector that never ran. AI advice must cite authorized evidence and cannot create observations, approve risk or expand typed actions.

**Acceptance:** disabled/missing policy, exhausted budget, forbidden region/model, revoked evidence scope, injected text and invented citation all produce deterministic refusal or unavailable results. Empty inventory, unsupported rule, missing metric window and stale telemetry remain unassessed/unknown. Pin input/evaluator versions and reproduce outcomes.

## CR-08: Keep Code Mode unavailable until isolation is proven

The current Python executor and [bridge](../workers/code-mode-bridge/src/index.js) reject remote execution. This is an intentional compatibility change: live Code Mode is unavailable, while the explicit test stub remains. The earlier forbidden-token regex is not a sandbox.

**Fix:** select a runtime that enforces capability, network, CPU, memory and output limits independently of snippet syntax. Commit queued intent before dispatch, validate tenant/run/digest on responses, and implement replay and reconciliation semantics. Re-enabling `new Function` in the authenticated bridge is not an acceptable completion.

**Acceptance:** indirect constructor/prototype access, infinite loops, enormous output, malformed/oversized requests and replay cannot escape quotas or access ambient secrets/network. Crash after execution but before commit must retain durable run identity and reconciliation. Only then enable behind an explicit release capability.

## CR-09: Validate migrations and retained-volume startup

Follow [database acceptance](BACKEND_RECHECK_FIX_GUIDE_2026_11_07.md). The implementation's tenant context is `app.current_tenant_id`; use the exact setting consistently. Forced RLS in a migration is not proof the deployed role is restricted. The initial stack's credential files and a retained database can drift even if a fresh stack starts.

**Acceptance:** clean install and each supported upgrade; restricted role ownership/BYPASSRLS checks; same physical pooled connection across A/no-context/B including rollback; composite FK violations; migrations with optional extension absent/present; retained-volume startup after rebuilding without credential regeneration. Capture sanitized failing revision/SQL diagnostics. Document forward recovery for incompatible changes and coordinated database/object/key restore.

## CR-10: Define health by service and work progress

**Observed controls:** [Python worker health](../workers/health.py) tracks completed polling progress; [Node health](../agent-worker/src/health.ts) uses a 120-second progress window. Compose already registers numerous readiness checks, including Keycloak. Do not replace existing probes with a superficial process-only check or claim they are absent.

**Gate:** long-running legitimate assignments must renew progress within their intended health window; otherwise a functioning worker can be restarted. Python readiness dependency callbacks run in a single HTTP server handler and need bounded behavior. Map every service's actual dependencies and expected degradation, and confirm the deployment invokes its probe.

**Acceptance:** healthy idle polling, healthy long job, wedged poll, failed dependency, slow dependency, shutdown and recovered connection. Liveness and readiness return within a declared deadline and expose no credentials. Azure outage should degrade connection/evidence health without unnecessarily restarting every API. Test resource exhaustion, queue age, pool saturation and disk alerts. Measure restore/recovery targets rather than inventing them.

## CR-11: Release the exact verified artifacts

**Observed controls:** [CI](../.github/workflows/verify.yml) includes backend, dashboard, platform, Node agent, portal, security, real-stack and manifest jobs; backend coverage selects particular modules. These checks must be evaluated individually. Compose uses some mutable upstream tags such as Redis Alpine; a source lockfile does not pin container contents.

**Fix/gate:** publish a release manifest with commit, image digests, dependency lock checks, SBOMs and provenance. Pin production base/service images according to the operating policy and review updates. Distinguish built local tags from remote immutable release digests. Resolve storage exhaustion before rerunning Docker acceptance; retain bounded logs and artifacts.

**Acceptance:** each required job succeeds on the release SHA, all skipped tests are explained, fresh migrations and real-stack contracts run, browser fixtures are clearly distinguished from real backend evidence, and the deployed image digests equal the tested manifest. Verify vulnerability policy against current advisories; this review did not execute a fresh dependency audit. Test rollback/forward correction with persistent data.

## CR-12: Exercise actual user journeys across the full stack

The portal's [useLoad](../platform/portal/lib/useLoad.ts) already rejects stale generations. Preserve this while adding cancellation and data contracts where needed. Browser unit/mocked API tests do not prove identity, gateway, database and cloud integration work together.

**Acceptance journeys:**

1. Start a fresh stack, authenticate through Keycloak, issue an authorized license and connect CloudSaver.
2. Restart with retained volumes; access remains consistent and no generated credential is overwritten.
3. Connect a limited scope; dashboard, exports, AI context and worker queries expose only that scope.
4. Show missing/partial metrics, collection throttling and stale evidence with a safe next action; no invented zero or green verification.
5. Create a plan, independent approval, changed manifest, rejected stale apply, uncertain execution and reconciliation.
6. Import complete and partial billing, corrected credit and another currency; totals and benefit stages remain distinct.
7. Expire/revoke a session/license and exercise the documented online/offline behavior.
8. Run keyboard, mobile, screen-reader and reduced-motion tests on the critical paths. Respect the requested plain UI without extra animation.

Record expected API status, persistent state, audit event and visible result for each journey. Test both success and recovery. Assign a human owner for errors that cannot recover automatically.

## Delivery plan and release evidence

First close authorization and execution boundaries, then durable job/freshness behavior, then financial/assessment meaning, then scalability. Keep fixes small enough to review with compatibility and migration details. Avoid building a parallel identity, job queue or API hierarchy when the existing foundations can be extended.

A repair is complete only with: failing trigger/reproduction; reviewed source change; negative and concurrency tests when applicable; required real-service/sandbox evidence; safe error and recovery behavior; updated contract/documentation; and the exact release SHA/artifact references. Track unknowns explicitly. This guide recommends checks across the whole repository; it does not claim every file or deployed integration has been exhaustively verified.
