# CloudSaver v0.10.0 verification report

Date: October 23, 2026 (UTC). Baseline: latest GitHub `main`, v0.9.0 commit `b61f1b7cdca47e68568f3434dca8a5918ae2bd30`. The newest Drive UI guide and its adaptation are recorded in [SOURCE_CONTEXT.md](SOURCE_CONTEXT.md) and [docs/UI_UX.md](docs/UI_UX.md).

## Executed local checks

| Check | Result |
| --- | --- |
| Dashboard TypeScript check | Passed |
| Final production `next build --webpack` | Passed, including its TypeScript validation and generated route output |
| Production browser suite, system Chromium | 24 passed against the final production build |
| Standalone output with copied static assets | Started successfully; the dark/light accessibility workflow passed against this output |
| Accessibility coverage | All six operational views in both themes; the assessment dialog; existing navigation and mobile checks |
| Inventory scale and density | 10,000-finding virtualization workflow passed; compact rows remain 28px, medium is 38px, relaxed is 48px |
| `git diff --check` | Passed |

The browser suite uses explicitly labeled interface QA observations and intercepted API calls. Screenshots are UI previews, not live customer evidence. The standalone run additionally refreshed the desktop previews using the same API fixtures. The production app never imports these test fixtures.

## Verified interactions

- Dark is the default. Explicit light preference survives navigation and reload. Browser local storage contains appearance preferences, not the test credential or finding data.
- Counted provider/category facets, priority/type/scope/tag filters, protected-intent and missing-price lenses combine correctly. A real zero price remains priced. Unknown prices stay outside the known retail subtotal.
- Command palette quick views open real category/intent/pricing filters. Search matches tokens across resource and scope context. Tag existence and exact-value matching retain their explicit semantics.
- New category/sizing and review-posture cells retain native observed units and explicit missing values. The floating toolbar labels the priced portion of the selected findings.
- Comparison follows filtered, sorted finding order. Previous/next preserve the active tab. Closing the drawer restores focus through a stable resource key captured before virtual-row rerenders, including a click without native button focus.
- Radar axes represent observed evidence coverage, including risks. Pillar buttons open the corresponding checks and scroll within the drawer. No safety percentage, live dependency graph or approval is manufactured.
- Telemetry renders returned P95, request, unit, window and sample facts. Missing raw series does not produce a flatline or idle-duration claim.
- Protected intent disables destructive Bash export in the UI while import-only Terraform remains reviewable when permitted. Existing server-side ownership, role and protection checks remain authoritative.
- Scrollable evidence JSON is keyboard-focusable. Drawer tabs support arrows and Home/End, remain visible while navigating, and fit the mobile viewport.
- Existing explicit scan submission, selected CSV/JSON, reviewed code, plan upload, GitOps acknowledgement, delivery audit/replay, viewer restrictions and late-AI-response cancellation workflows still pass.

## Scope and acceptance limits

Backend business logic, dependencies, schema, identity federation and cloud integrations are unchanged; backend edits only advance release metadata. The preceding v0.9.0 CI passed its backend and dashboard gates. GitHub Actions will independently rerun the full backend, dependency and dashboard gates after publication; consult the repository workflow for that subsequent result.

Automated axe checks found no serious/critical issues in the tested operational views in either theme, and the assessment-dialog check passed its full tagged rule set. This does not replace manual assistive-technology, usability, broad-device or full WCAG acceptance. No 100,000-row latency target is claimed.

No shared Compose stack restart or deployment was attempted for this UI release. No live cloud scan, inference, notification, payment, product change request or remediation was triggered. Real billing normalization, raw telemetry charts, full dependency analysis, ITSM assignment and autonomous execution remain outside this milestone. AI remains opt-in under its existing controls.
