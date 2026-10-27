# UI/UX implementation and local verification

Date: 2026-10-27. Source baseline: `19856e4`. Specification: [UI/UX improvements README](../UI_UX_IMPROVEMENTS_README.md).

This increment improves existing customer and operator workflows. It does not implement every future capability in the specification. The root README, APIs, identity policy, provider adapters, approval authorities, database schemas, and dependency versions are preserved.

## Delivered behavior

| Area | Implementation |
| --- | --- |
| Workspace context | Persistent workspace name, exact selected resource observation time in UTC, selected resource scope, and a link explaining the independent billing period. No billing completeness is inferred from an inventory scan. |
| Navigation | Existing customer destinations grouped into Understand, Improve, Finance, Act & Govern, Operate, and Administer. Search is labeled as pages and current-snapshot findings rather than an unrestricted global search. |
| Evidence health | Complete authorized resource counts, observed/total assessment checks, resource evidence-gap counts, finance access guidance, and links through workloads, evidence review, governance, and outcomes. No new background provider calls. |
| Explicit billing sync | Restored the existing durable-job submission control removed by the latest upstream changes. Submission is explicit and idempotent; polling is restricted to billing job routes, unknown states remain errors, and a failed status read can resume the same job without another submission. Billing no longer claims to run as part of resource scans. |
| Review queue | Priority ordering before selecting the first five resources. Loading, failure, historical synthetic data, and incomplete scans cannot appear as a successful empty queue. Historical synthetic snapshots use the existing historical resource experience. |
| Customer rules | Provider, service, pillar, saved effective state, and text filters; catalog/policy/override information; explicit unavailable/retired/disabled states; bounded whole-number parameters; no-op draft removal; exact before/after review; and visible save confirmation. |
| Policy conflicts | A conflict or uncertain write blocks another submission. Current-policy reload retains the permitted draft in memory, and a new preview uses the current version. No automatic mutation replay. |
| Operator rules | Per-workspace staged enable/disable changes, up to the existing 100-rule request limit, followed by exact customer/workspace/version review and one versioned write. Filtering never hides changed entries from the final review. This is configuration review, not a simulated impact preview. |
| Read-only use | Viewers, scope-limited customer credentials, auditors, unavailable rules, unpublished rules, and deleted operator workspaces do not receive applicable write authority from the new UI. Backend enforcement remains authoritative. |
| Portal context | Visible customer and loaded directory record context, direct customer billing/activity navigation, deep-linked workspace tabs, and keyboard tab navigation. The rule panel separately reports its current loaded policy version. |
| Draft protection | In-memory policy drafts have confirmation on ordinary link navigation, mouse/keyboard tab changes, marked workspace-switch/refresh controls, and browser unload. Drafts are not saved to browser storage. This does not claim a universal Next.js history-navigation blocker. |
| Accessibility | Responsive context panels and catalogs, keyboard-scrollable rule tables, named mobile search, explicit filter labels, and one success announcement in the portal. Existing dialog focus restoration and reduced-motion support remain. |

## Using the improvements

### Customer workflow

1. Connect an authorized workspace and select the resource snapshot/scope.
2. Read the context strip and Evidence health before using review estimates.
3. Open Settings → Analysis rules. Inspect a rule's catalog details and saved effective state.
4. Make delegated changes. Bounds are validated before requesting a saved-observation preview.
5. Review the exact change list, workspace, policy version, and estimated evaluation impact. Apply explicitly.
6. On conflict or uncertain completion, inspect/reload current policy before requesting another preview. Historical snapshots retain their original rules.
7. Use Cost allocation for billing source windows and Savings & investigations for financial outcome evidence. Resource retail estimates remain separate.

### Operator workflow

1. Open the authorized workspace and its Rules tab; the URL can retain `?tab=rules`.
2. Filter the catalog and inspect rule provenance and availability.
3. Toggle permitted rules into a draft. Toggles alone make no API write.
4. Review every draft entry, including entries hidden by catalog filters.
5. Confirm the exact customer, workspace, and expected policy version, then apply.
6. If another administrator changed policy, reload current policy and review the retained intended changes before another write.

## Local verification

Functional-increment local results, before the subsequent CSS follow-up below:

| Check | Result |
| --- | --- |
| Customer production build (`npm run build`) | Passed |
| Portal production build (`npm run build`) | Passed |
| Customer and portal TypeScript (`npm run typecheck`) | Both passed |
| Complete customer browser suite (`npm run test:e2e -- --workers=2`) | 119 passed |
| Complete portal browser suite (`npm run test:e2e`) | 12 passed |
| Portal unit suite (`npm test`) | 11 passed |
| Changed-source Gitleaks scan, with redacted output | Passed |
| Git whitespace checks | Passed |

The customer browser harness starts the production build on a loopback port and sets `CLOUDSAVER_DASHBOARD_URL`. Portal Playwright starts its own loopback production server. Both use `CLOUDSAVER_BROWSER_EXECUTABLE=/usr/bin/chromium` in this environment. The existing runtime-error fixture rejects uncaught page errors.

Local logs are under `/workspace/artifacts/cloudsaver-ui-improvements`; the final customer browser log is `customer-browser-complete.log`. Earlier failed runs were corrected and are not counted as additional passing tests. The final customer run includes the full existing suite and eight new scenarios; the portal run includes four rule/context scenarios and one draft-protection scenario in addition to its original seven.

Runtime: Node.js `24.22.1`; installed customer Next.js `16.4.2`; installed portal Next.js `16.4.3`; system Chromium. Package manifests and lockfiles were not changed.

Verification uses existing synthetic browser fixtures and local production builds. Portal fixtures use a synthetic shell cookie and intercepted identity responses; they do not establish a real operator login. No connected cloud sandbox, external model, payment provider, or production deployment is involved.

New regression scenarios cover evidence counts under scope changes, unavailable inventory, rule provenance/read-only access, empty/out-of-bounds/reverted parameter edits, stale policy recovery, exact operator writes, mobile layout, theme accessibility, unsaved-draft navigation, and read-only recovery of an uncertain billing job status.

Initial runs exposed a duplicated portal status announcement, inconsistent exact filter labeling, and an unnamed mobile search control. These were corrected. The historical fixture was updated to stop expecting a live inventory read for a historical synthetic snapshot. Theme accessibility checks use the existing reduced-motion mode to avoid measuring an intermediate animated color during theme changes.

## Remaining specification work

- Full coordinated plans, API/UI/orchestration wiring, and independent outcome evidence remain governed by the [feature acceptance matrix](FEATURE_ACCEPTANCE_MATRIX.md).
- The evidence-health panel summarizes the selected resource snapshot; it does not query every connector, job queue, approval, incident, or billing source to create an enterprise attention queue.
- Rule detail displays existing catalog metadata. A richer contract for declared telemetry/sample requirements, units, treatment options, and verification is separate backend/catalog work. Missing metadata is not invented.
- Customer rule preview estimates changes against saved observations. Operator rule review uses the existing configuration contract and does not claim live/simulated resource impact.
- The existing maximum of 10,000 loaded resources per scan and 50 displayed rows per resource page is unchanged. Larger estates need the separately designed server-side query/export contract.
- Comprehensive browser history blocking, manual screen-reader review, Firefox/WebKit coverage, representative customer usability studies, and deployed integration acceptance remain outstanding.
- No Site has been registered or published. No Git push or deployment is part of this build request.

## CSS refinement follow-up

The subsequent CSS request adds dedicated, readable `app/experience.css` files to the customer dashboard and platform portal. Each independently deployed application imports its stylesheet from its root layout. The earlier compressed evidence-context/rule styles were moved out of `globals.css`; no interaction handlers, API contracts, permissions, or dependencies changed in this follow-up.

Visual refinements include consistent panel radii and shadows, a deliberate rule-filter grid, clearer expanded rule details, separated evidence/KPI panels, compact mobile metadata, touch-sized filter/action controls, and visible focus states. Sidebar navigation scrolls independently on short screens while its footer remains reachable. Wide catalogs retain local horizontal scrolling rather than widening the whole page.

CSS-specific verification:

- Both customer and portal production builds passed, including their build-time TypeScript checks.
- The existing customer console-experience and improvement-workflows suites passed: **15 checks**, covering themes, automated accessibility, mobile drawers, rules, drafts, and billing recovery.
- The existing portal browser suite passed: **12 checks**.
- Two temporary visual-review scenarios passed outside the repository test tree. Synthetic screenshots cover customer dark/light overview, desktop/mobile rule catalogs, and operator desktop/mobile catalogs. A 1280×620 viewport check confirmed that the final sidebar navigation item remains reachable.
- Whitespace checks passed. The release manifest was regenerated and checked after the final stylesheet and documentation changes.

Local screenshots and build/verification logs are under `/workspace/artifacts/cloudsaver-css`. The preceding 119-case customer run belongs to the functional increment; it was not repeated in full for this CSS-only follow-up. No permanent tests, provider calls, Git push, or deployment were added by the CSS request.

## Complete page and tab audit

The subsequent [page-by-page CSS audit](CSS_PAGE_TAB_AUDIT.md) expands coverage to all explicit customer/portal route families and native tab groups: 90 states, 900 layout samples, and 180 contrast samples. It records the additional fixes, final results, and local-fixture boundaries separately from the earlier functional and styling passes.
