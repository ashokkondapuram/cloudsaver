# Detailed UI and request reliability verification

Review date: 2026-10-26. Local branch: `fix/aetherguard-p0-completion`. The latest remote main, `53201d68c8559e53bfad35e2b4d9003ef728d364`, was fetched and merged into the local fix branch. It contains the AetherGuard feature merge but not the earlier local hardening commit `6f41b49`. This work preserves that hardening. The enclosing commit and generated release manifest identify the delivered source.

The acceptance environment remains **local tests only**. No cloud account, external model, customer credential or live payment provider was used. This report describes reproduced fixes and bounded verification, not a promise that every possible runtime condition will succeed. The [feature acceptance matrix](FEATURE_ACCEPTANCE_MATRIX.md) still identifies incomplete product capabilities and environment-dependent gates. The root README is preserved.

## Corrected behavior

| Area | Failure or inconsistency | Result |
| --- | --- | --- |
| Resource inventory | Only the first 1,000 resources were read. Later resources could not be found through the grid. | Reads successive pages of at most 1,000, with a documented maximum of 10,000 resources per scan. Validates scan, observation, total, required row shape, finite prices, evidence coverage and unique keys. Rejects changing, incomplete, duplicate, malformed or oversized inventories instead of presenting a complete-looking partial rollup. |
| Large resource grids | Rendering and discovery filtering could grow with every resource/finding pair. | Renders 50 matching rows at a time and indexes related findings by identity. Searching and CSV filtering operate on the loaded complete supported inventory, including records beyond the first source page. |
| Inventory-only resources | Provider/category counts and quick views depended on findings. Resources with zero findings could disappear from discovery filters. | Facets use resource rows. Category and missing-price filters retain inventory-only resources; an absent price remains unknown. Protection filtering also considers saved resource assessment signals. |
| Scope changes | Locally selected resources could survive a global scope change. | Scope, scan and credential changes clear selection; action selection immediately excludes resources outside the selected scope. |
| Resource details | A closed and reopened drawer could show cached details before its new response arrived. | The detail lifecycle is bound to credential, scan and resource. Closing unmounts it; reopening waits for fresh details. History, questions and decisions cannot inherit a previous drawer's local state. |
| Session expiry | A 401 could leave the cached workspace and action controls visible. | The active credential is invalidated, cached workspace/selection and persisted session token are cleared, and login explains that reconnection is required. A credential-specific subscription prevents a response for an old credential from invalidating a different current credential. A 403 remains an access error and does not sign out a valid session. |
| Workspace bootstrap | Malformed profile/history/plan bodies could reach rendering code or mix a foreign plan with a workspace. | Validates profile structure, role arrays, plan-to-tenant binding, scan identity, finding fields and finite monetary observations before accepting a connection or refreshed evidence. Malformed initial connections do not persist credentials. Backend authorization remains authoritative. |
| AI batch visibility | Missing progress counters could cause invalid progress rendering or leave the UI ready to submit additional work while status was unknown. | Validates owned scan, status, bounded total and every progress counter. Queue controls remain disabled during initial status checking and on status errors. The error is announced as a status message, with an explicit read-only check-status recovery action. Status checking does not invoke inference. |
| API transport | Successful empty responses caused JSON errors; malformed success bodies could crash consumers; ambiguous writes were presented like ordinary retryable reads. | Handles 204 explicitly, rejects malformed/null/primitive success data, bounds requests, preserves caller cancellation, and distinguishes read failure from uncertain mutation. Neither client automatically replays mutations. On uncertainty, the user is directed to inspect status/activity before resubmission. Customer errors preserve an available request reference. |
| Portal paged reads | Missing list wrappers could crash customer lists. | Known paged GETs require an items array and a valid optional cursor. Incomplete payloads show a recoverable error instead of fabricated empty results. |
| Portal asynchronous state | A late load-more response could overwrite newer filter/customer/refresh data. Failed filtered reads could keep old rows visible. | The shared loader binds reads and state setters to their request context and generation, ignores late writes after context/refresh/unmount, and removes old rows while loading or after failure. |
| Portal keyboard flow | Native modal opening defeated the customer input's requested autofocus. | Explicit autofocus is applied after opening the modal. Keyboard dismissal and return focus to the invoking control are verified. |

## Verification gates

Every current customer and portal browser journey imports its package's shared `e2e/test.ts` fixture. That fixture fails the journey on an uncaught page error even when visible assertions succeed. A separate synthetic negative control deliberately raised `SYNTHETIC_RUNTIME_GATE`; the runtime gate rejected the run. That expected rejection is a detector check, not an application test failure or a production incident.

Both browser configurations restrict fixture targets to loopback HTTP. Portal fixtures intercept browser API calls and use an opaque synthetic UI cookie solely to render the protected HTML shell; they do not authenticate against a real identity service or establish a production server session. Server-side authorization acceptance is separate. No production runtime flag or authentication bypass was added.

The portal now declares a pinned Playwright development dependency, a `test:e2e` command and a required browser step in its existing CI job. Existing Python, worker, customer dashboard, portal, security and real-stack jobs remain in place. The browser checks are required by the workflow; repository protection/ruleset enforcement and hosted results for the new SHA still require separate verification.

## Results

Final checks completed with zero application-test failures:

| Check | Result |
| --- | --- |
| Customer dashboard browser and request-contract suite | **111 passed**, no failures or skips, in the complete final run. Includes the existing 82 scenarios, added pagination/session/response/race cases, and cancellation without `AbortSignal.any`. |
| Platform portal browser journeys | **7 passed**, no failures or skips. Includes the modal-focus fix and the shared uncaught-error gate. |
| Portal unit tests | **11 passed**, no failures or skips. |
| Gateway, route inventory and Compose contracts | **58 passed**, one existing Starlette/httpx deprecation warning. |
| Default production builds and TypeScript checks | Customer dashboard and portal passed under Node 24.22.1. |
| Real local HTTP transport | Both financial/GitOps and governance stack scripts passed. No cloud mutation or model call occurred. |
| Dependency audits | Customer and portal npm audits reported **zero known vulnerabilities** at check time. |
| Source and inventory checks | Undefined-name lint, tracked-source secret scan including its synthetic-secret negative control, whitespace checks, workflow YAML, package/lock agreement and the regenerated release manifest passed. |
| Browser error detector self-check | Deliberately uncaught synthetic page error caused the expected rejected run; the harness verified that the runtime gate, rather than the visible body assertion, rejected it. |

Preliminary runs exposed a stale tab/notice locator and the portal autofocus defect, and the first customer harness attempt started before its build completed. Those runs are not represented as green evidence. After corrections, the complete suites listed above were run against the final application behavior. The earlier 24-case focused customer run and 110-case run overlap the final 111 cases and are not added to its total.

The final customer HTTP client uses an explicit AbortController, cancellation forwarding and timer cleanup instead of requiring `AbortSignal.any`. This compatibility path has a regression; Firefox/WebKit browser engines themselves were not run in this environment. Chromium was the browser engine used for the UI suites.

## Reproduction

Use the declared Node 24.22.1 runtime and the committed lockfiles. The local Node archive checksum was verified. Customer Next.js is locked to 16.4.2 and portal Next.js to 16.4.3; their installed versions matched those locks. The portal dependency addition was installed through npm; existing customer dependencies were reused from the matching checkout.

Customer commands are `npm ci`, `npm run typecheck`, `npm run build` and `npm run test:e2e` from `web-dashboard`. Serve the completed production build on loopback and set `CLOUDSAVER_DASHBOARD_URL`; install Playwright Chromium or set `CLOUDSAVER_BROWSER_EXECUTABLE` to an approved local Chromium. Do not start tests while a build is replacing `.next`.

Portal commands are the same from `platform/portal`, with `npm test` for its unit suite. Its browser configuration starts and cleans up its own loopback production server. `CLOUDSAVER_PORTAL_URL` can select an unused loopback port. CI installs Playwright Chromium and runs the committed commands after the production build.

`python scripts/test_real_stack.py` and `python scripts/test_governance_stack.py` separately exercise actual local dashboard-proxy/gateway/core HTTP transport and synthetic governance evidence workflows. They are not intercepted browser tests and are not live cloud acceptance. Docker must be available through the managed local daemon.

## Remaining acceptance boundaries

- Resource exploration in this increment supports at most 10,000 resources in a selected scan; larger estates need smaller scan scopes or a separately implemented large-estate query/streaming design. Oversized input is explained and refused, not zero-filled or described as complete.
- Snapshot summary and lifecycle counts refer to the selected scan; table scope, discovery filters and table pages are separate display selections. CSV includes all loaded rows matching the filters, not just the current 50-row table page.
- The new portal browser tests cover customer listing, role controls, keyboard focus, read failure, pagination race, malformed payload, ambiguous creation and mobile layout. They do not establish complete browser coverage of every platform administration journey, real Entra login, cookie revocation across deployments or live finance/provider behavior.
- HTTP time bounds and safe uncertainty messages do not cancel or roll back a server/provider write. Operators must reconcile uncertain outcomes before resubmitting. Backend idempotency, approval, lease and permission controls remain required.
- No Python application, identity, migration or worker implementation changed in this increment. The previous 1,091-test backend/platform result and 24-worker-test result are historical evidence for the unchanged source, not rerun counts for this increment.
- Full AetherGuard API/UI/orchestration wiring, actual provider/model acceptance, HA/load testing, recovery drills and independent security/finance/data-governance sign-off remain open as described in the feature matrix. Local success does not close those gates.
