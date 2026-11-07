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

## Subsequent implementation pass

The follow-up working tree implements these additional controls:

- **CR-01:** encrypted persistent portal sessions and atomic OAuth-state consumption, shared between processes on a local volume; refresh-token rotation is leased and fenced. Compose mounts the volume with runtime-user ownership. Multi-host distributed sessions remain outside this adapter's supported topology; see the portal README.
- **CR-02:** dashboard critical route/list validation, bounded response bytes and JSON structure, rejection of nonfinite numbers, and optional typed route decoders. This does not claim a complete generated schema for every legacy endpoint.
- **CR-03:** explicit method/path admission for Grafana and rule-catalog routes missing from the browser proxy; internal paths remain denied. Complete generated method/path parity for legacy routes remains open.
- **CR-05:** resource GET paths now always serve persisted evidence; authorized scan jobs are the existing collection/refresh mechanism. Azure detail failures no longer advance the successful status-fetch timestamp. Inventory bounds fail visibly rather than return fabricated not-found/partial rollups.
- **CR-06/10:** successful agent heartbeats maintain health during long assignments; failed heartbeats mark it unready. Python worker dependency probes have a bounded wait and at most one outstanding probe, preserving liveness under a blocked dependency.
- **CR-07:** processor access requires explicit boolean opt-in and an explicit nonempty purpose allowlist. Empty account analysis is unassessed with no perfect scores; finding-severity scores are explicitly labeled as partial and cannot override unknown legacy evidence with a pass.

The broad checks also found and repaired two stale fixtures: a pagination URL assertion that ignored a following query parameter, and a Node-agent plan fixture whose operation type widened to a generic string. Production safety contracts were preserved.

External acceptance remains necessary for provider credentials/API behavior, real migrations/RLS/Redis, actual IdP and protected CI, restore exercises, vulnerability policy and image provenance. Code Mode remains disabled until isolated execution acceptance; a stub is not that acceptance. No cloud mutation or deployment was performed.

### Verification for the subsequent pass

- Backend suite: **1,519 passed, 101 skipped**, one warning, 134.55 seconds (`/tmp/backend-completion-final.log`). The subsequent explicit-consent guard also passed its focused regression/master-plan suite (29 tests). Azure freshness/read tests passed (29 tests).
- Independent identity/platform suite: **113 passed, 9 skipped** (`/tmp/platform-completion-tests.log`).
- Supported Node 24.22.1: portal typecheck and **15 unit tests**, agent typecheck and **26 tests**, dashboard typecheck and **34 unit tests** passed. Both Next.js production builds completed successfully on that runtime.
- No coverage percentage is inferred from these invocations. Temporary log paths are local evidence and must be replaced by retained CI artifacts for release approval.
- No real-service skip, browser unit test, or successful build is represented as live-provider, full-browser, RLS, disaster recovery, or deployment acceptance. Full generated route/response schema parity, distributed multi-host session storage, and re-enabling isolated Code Mode remain separate implementation items.


## Shared-session and durable-execution follow-up

The portal now supports shared Redis sessions across hosts using an official,
locked Redis client. Compose provisions a dedicated persistent session service
with `noeviction`, independent of identity throttling. Local SQLite remains an
optional local adapter. Session/OAuth operations are asynchronous and atomic;
refresh ownership is fenced and expired state cannot be renewed by a client
clock. Readiness checks the configured shared store, and an outage never causes
fallback to local sessions. Switching adapters requires reauthentication.

Real-Redis acceptance passed with **19 portal tests and no skips**, covering
shared reads, concurrent claims, stale fences, one-use state, cross-client
revocation, encrypted payloads and server-time idle expiry. Portal typechecking
and the Node 24.22.1 production build passed. CI now provides its own Redis to
run these cases. Tests used isolated UUID keys in an existing Redis; the newly
configured persistent Compose service was not deployed or restore-tested here.

Code Mode now commits intent before adapter invocation, handles concurrent
idempotency-key insertion, validates returned run/tenant/snippet bindings, and
records interrupted/ambiguous outcomes as reconciliation-required without
re-executing them on retry. Known pre-dispatch refusal remains failed. Remote
execution remains disabled until an isolated runtime is independently accepted.

The broader backend snapshot passed **1,522 tests, 101 skipped**, one warning,
in 95.07 seconds; the final outcome-classification changes passed the focused
suite (**16 tests**). Temporary logs: `/tmp/shared-session-backend-final.log`,
`/tmp/shared-final-focused.log`, `/tmp/shared-redis-acceptance-final.log`. These runs
supersede earlier counts for their respective checks, but not missing cloud,
RLS, full-browser, restore, schema-generation or artifact-provenance acceptance.

The final Compose/setup/identity contract selection passed **54 tests**; the portal dependency audit reported **0 vulnerabilities** at this check. Redis does not replace the remaining isolated execution, generated-schema parity or authorized cloud/restore acceptance.


## Generated browser admission follow-up

The handwritten browser route expressions have been replaced by a generated
method/path table. A committed manifest explicitly reviews **211 browser
operations and 7 exclusions**. New backend operations need an explicit decision;
they are not auto-published. Internal/service operations and provider callbacks
cannot be published by ordinary manifest entries. Parameter formats are bounded
and reviewed, and malformed/doubly encoded paths are refused.

CI now checks the manifest against the backend inventory, verifies the generated
file is current, runs the dashboard unit contracts, and tests the actual built
Next proxy against a synthetic local gateway. The transport test verifies header
preservation and that rejected operations never reach the gateway. It makes no
cloud, database or identity calls and is not provider/authorization acceptance.

Verification: **8 route/parity tests**, **36 dashboard unit tests**, dashboard
typecheck and production build passed; the built proxy transport acceptance also
passed. Source and generated files are checked with
`python scripts/generate_browser_routes.py --check`.

CR-03's admission drift is addressed by this contract. Full typed response-schema
coverage remains separate work; a route admission pattern does not establish
that every legacy response field is declared or validated. Cloud/runtime,
restore and isolated execution gates remain open as previously documented.
