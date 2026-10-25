# AetherGuard P0 hardening and local verification

Review date: 2026-10-25. Source baseline: `ed9adc1d58faff19b76baa00faec7191df313be5` on `feature/aetherguard-control-plane-p0`. Fixes are prepared on `fix/aetherguard-p0-completion`. The enclosing commit and generated `RELEASE_MANIFEST.json` identify the delivered source; a passing test on the baseline does not imply these fixes already exist on the remote branch.

The approved acceptance environment is **local tests only**, with no connected cloud sandbox. This is an engineering regression report, not a complete audit, enterprise launch approval, provider acceptance or assertion that every roadmap feature is implemented. The root README is preserved. See the [feature acceptance matrix](FEATURE_ACCEPTANCE_MATRIX.md) for supported scope and remaining work.

## Defects corrected

| Boundary | Before | Corrected behavior and regression evidence |
| --- | --- | --- |
| Required safety evidence | Missing external-owner, action-applicability and headroom inputs could pass or become not applicable; invalid numeric values were accepted. | Strict typed evidence rejects coercion, extra fields and non-finite/out-of-range values. Mandatory missing evidence remains unknown and blocks eligibility. `tests/test_control_plane_boundaries.py`. |
| Financial scenario inputs | Truthy non-booleans and excessively large money values could misrepresent a result or lose precision. | Explicit booleans; bounded nonnegative decimal amounts; precision sufficient for every accepted amount; conflicting shared commitment snapshots require reconciliation. `tests/test_control_plane.py` and boundary tests. |
| Plan authority | Approval identity omitted proposed SKUs, exclusive targets and HA headroom claims. | These fields participate in the digest; changes invalidate approval. Unverified humans, expired approvals and changed identities fail closed. `tests/test_control_plane_workflow.py` and boundary tests. |
| Persistent plan lifecycle | Concurrent version requests could leak a database exception; state advancement did not establish current exact-version human authority. | Existing tenant transaction locking serializes creation and approval/state changes. Stale version requests return a domain conflict; approval/queue/run require an unexpired exact-version approval and latest version. PostgreSQL concurrency/lifecycle tests. |
| Idempotency | A reused key with different inputs could silently return the original result. | Scenario and assessment input identity is checked; changed inputs conflict instead of overwriting history. Store and PostgreSQL tests. |
| GitOps check integrity | Empty webhook secret, coercible plan-trust flags and contradictory persisted conclusions were accepted. | Empty/malformed signature inputs fail; trust must be a literal boolean; stored check conclusions must agree with trust and decision. Domain, store and database tests. |
| Database startup and rollback | New tables were outside the forced-RLS readiness check; populated-history downgrade was destructive. | Startup verifies all eight new tables. Downgrade locks them, checks owner-visible history, restores forced RLS and refuses populated rollback. Restricted-role, cross-tenant, immutable-column and rollback tests. |
| Resource-to-repository lookup | Operator-provided global index could reveal unowned resources or ungranted repository metadata. | Requires an authorized saved observation, current resource scope and a repository granted to that workspace; foreign/unavailable IDs return the same safe 404. `tests/test_gitops_mapping_authorization.py` plus real local HTTP transport. |
| Unit-cost advisory | Level ratios were reported as growth elasticity. | Elasticity compares percentage cost growth with percentage volume growth; unit-cost ratio is separate. Zero/unchanged baselines do not fabricate a result. `tests/test_unit_economics.py`. |
| Dashboard forwarding | Existing advisory GETs could not pass the browser proxy. | Exact GET-only allowlist entries forward unit-economics preview and authorized mapping; unsupported paths/methods remain denied. Local real-stack checks. |
| Incomplete API responses | Missing service or commitment summary fields could crash the page. | The view shows an explicit incomplete-evidence error and retains the surrounding workspace. New browser regressions. |
| Scope and export consistency | Global scope did not constrain resource rows; CSV omitted discovery/quick-view/scope filters. | The grid applies the scope selection, and CSV serializes exactly the displayed authorized rows in their displayed order. Unknowns stay empty and zero stays zero. Bounded partial inventory is labeled explicitly. Browser and CSV tests. |
| Spreadsheet content | The direct API CSV export did not neutralize whitespace-prefixed formulas. | Both resource CSV paths quote content and neutralize leading spreadsheet expressions, including whitespace prefixes. Python and TypeScript tests. |
| Repeated review preview | Repeated clicks regenerated an already returned artifact. | Reuses the current returned preview; session/workspace/scan/selection changes invalidate it and abort obsolete work. Browser review tests. |
| Mobile resource layout | Header actions widened the document beyond a 390px viewport. | Actions wrap within available width; tests wait for loaded resource rows before measuring width. |

## Test corrections

Several tests predated the current resource drawer. They now wait for the actual opened dialog, choose its Findings or Costs tab, and scope assertions to the relevant panel rather than Next.js's separate route-announcer alert. Fixture response shapes follow the current service contract. Initial overview requests settle before tests measure subsequent page authorization traffic.

Historical synthetic snapshots still cannot run live assessments or generate code. The historical comparison test now verifies this refusal while preserving navigation, selected-tab and focus assertions. Separate live tests continue to verify protection signals, deterministic assessment, stale-evidence disclosure, explicit AI consent, viewer denial and suppression of late responses after resource changes. No production authorization or evidence guard was removed to make a test pass.

## Verification record

Local runtime: Python 3.12.14, Node 24.22.1, PostgreSQL 16, Redis 7, Chromium through Playwright. The official Node archive checksum was verified before use. Existing lockfiles were retained. Dependency directories were reused from the checkout with identical package manifests and lockfiles; a fresh isolated dependency installation was not repeated for each build. Customer and portal builds use their default Next.js/Turbopack production command.

Overlapping targeted runs are not added together as a fabricated test count.

- Customer browser suite: **81 passed / 1 failed** in the final full 82-scenario run. The remaining failure was an outdated Rules/Dependencies tab selector; the current drawer places those sections under Evidence. After updating that selector, the same scenario passed in a **1-test focused rerun**, without further application changes. Thus all 82 distinct scenarios have passing evidence across these two runs, not a fabricated claim of one green full-suite command.
- Agent worker: typecheck and **24 tests passed** on Node 24.22.1.
- Platform portal: typecheck, **3 tests passed**, and default production build passed on Node 24.22.1.
- Customer dashboard: typecheck and default production build passed on Node 24.22.1.
- Both real local HTTP stack scripts passed with the final application code: legacy financial/GitOps transport, owned mapping and foreign-ID denial, unit-economics preview, and the signed governance lifecycle through closure and drift reopening.
- Python and all three Node dependency audits reported **no known vulnerabilities** at check time. `pip check`, undefined-name lint, configured high-severity/high-confidence Bandit checks, tracked-source secret scan and the scanner's synthetic-secret negative control passed.
- Backend targeted follow-up: **74 passed** for mapping, GitOps, unit economics, control-plane boundaries/store/workflow/migration and Compose; **13 passed** for resource-assessment/API/CSV regressions. These overlap the full suite and are not added to its count.
- The earlier full backend/platform run passed **1,082 tests** with **89.27% control-plane coverage** before the subsequent GitOps, unit-cost and CSV changes. A final full-suite run covers the completed application changes; its result is recorded separately below.

### Final backend/platform result

**1,091 passed, one deprecation warning, no failures or skips**, in 227.24 seconds against disposable PostgreSQL/Redis. The selected critical-module aggregate reached **87.41%**, exceeding the configured 85% threshold. AetherGuard covered **341 of 382 statements (89.27%)**. These are line-coverage measurements, not proof that every behavior is covered.

The command used `PYTHONPATH=platform python scripts/test_postgres.py tests platform/tests` with the backend CI coverage selection (including `app.control_plane`), `--cov-fail-under=85`, JUnit output and coverage JSON. The warning concerns Starlette/httpx TestClient deprecation; tests completed successfully. No cloud credential, provider mutation or model inference was used.

The generated release manifest was rechecked after recording these results. Remote feature head was revalidated as the original `ed9adc1d58faff19b76baa00faec7191df313be5`; these local fixes have not been pushed or merged. Hosted CI has not been run on the fix commit.

## Reproduction and limits

The portable job recipes are in [verify.yml](../.github/workflows/verify.yml). Install the declared Python development dependencies and Node lockfiles using the declared runtime. Backend integration runs use `python scripts/test_postgres.py tests platform/tests` with `PYTHONPATH=platform`; the script creates disposable PostgreSQL/Redis containers with random credentials and cleans up its own containers. Production databases are not test fixtures.

The full local backend run measures `app.control_plane` coverage; CI retains its existing security-critical aggregate threshold and now includes that package. Dashboard browser tests use a production build served on loopback and intercepted synthetic API fixtures. The two `scripts/test_real_stack.py` and `scripts/test_governance_stack.py` journeys separately exercise actual local browser-proxy/gateway/core transport and durable synthetic evidence workflows. They do not invoke a real cloud provider or model.

The native portal currently has three declared financial unit tests plus type/build verification; this does not establish a complete portal browser journey. Security results are bounded to the configured lint rules, Bandit severity/confidence selection, current advisory databases and tracked-source secret scanner. They are not penetration-test evidence. No container vulnerability scan, production restoration drill, cloud IAM acceptance or live integration test is claimed by this report.

AetherGuard's domain/storage modules remain unregistered as a complete control-plane API, UI or orchestration service. Complete capability-specific implementation and the environment acceptance gates in the feature matrix before describing those capabilities as shipped or fully working.
