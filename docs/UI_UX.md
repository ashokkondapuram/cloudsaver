# CloudSaver v0.10.0 console experience

Source: [Advanced UI/UX Architecture & Component Engineering Guide](https://docs.google.com/document/d/1hETTGMG5X9zo3AuuthHQgR8cgFPrG97V694sGxve2Os/edit), the newest matching Drive guide, modified October 23, 2026 at 04:07 UTC. Its internal v0.7.2 label describes the source design; implementation extends the latest v0.9.0 product as v0.10.0. The duplicate document `14ZrmNNhiZtkhnBf5tUMc2gjUMAIQ7JsTHHwqwrQZSLQ` contained the same text when reviewed.

## Implemented guide mapping

| Guide requirement | Current experience |
| --- | --- |
| Deep slate design system | Default dark canvas, elevated surfaces, semantic indigo/amber/rose/emerald colors, provider badges, self-hosted Inter/JetBrains Mono and matching chart colors |
| Comfortable reading preferences | Explicit dark/light toggle in the console and sign-in screen; theme preference survives navigation/reload independently of credentials |
| 240px/64px navigation | Existing six workspace routes and mobile navigation retained; collapsed desktop rail now measures 64px |
| Executive inventory banner | Observed finding count, configured scopes represented in findings, known retail subtotal, protected-intent count and unknown pricing coverage; actual observations drive all values |
| Provider and category pills | Counted AWS/Azure/GCP/Kubernetes facets plus storage/compute/database/network/application categories, composable with priority/type/scope/tag/search filters |
| Fast focused views | Protected-intent and missing-price presets; command palette opens real category/intent/pricing routes; search matches query tokens across names, groups, rules and scopes |
| Category and sizing columns | Technical category and observed disk capacity or Kubernetes request size; missing sizing stays explicit |
| 360° grid posture | Saved protection signals or “Needs assessment”; the grid does not invent a risk percentage or live safety certification |
| Density and virtualization | 28/38/48px rows, existing pagination, sortable/reorderable/hideable/pinnable columns and virtual rendering retained |
| Floating bulk actions | Exact selected count, known retail portion and pricing-coverage denominator; existing selected CSV/JSON and reviewed-code workflow |
| Context-preserving drawer | 640px drawer with previous/next across the filtered, sorted results; active tab stays selected during comparison |
| Five-pillar radar | Evidence coverage per pillar, explicit observed/risk/unknown legend, accessible textual descriptions and buttons that open the corresponding check group |
| Telemetry | Returned Kubernetes P95/request/window/sample facts; missing time-series data has an explicit empty state rather than a fabricated utilization chart |
| Keyboard and accessibility | Existing Cmd/Ctrl-K, g d/g f, table Cmd/Ctrl-A, Shift-R and Escape retained; drawer arrows/Home/End, visible focus, named facets and readable semantic states |

## Interaction boundaries

Provider/category counts and the banner describe the current scan and scope selection; table filters then narrow those observations. Quick views modify the protection/pricing lens and combine with other active facets. Clear all removes all table and scope filters. `has:Owner` tests exact tag-key presence, `Owner=platform` tests exact values, and a bare expression matches part of a key. Arbitrary regular expressions are not evaluated.

Command quick views use bounded `category`, `intent` and `pricing` query parameters. They do not write resource names, account identifiers or credentials into shareable links. Finding navigation uses the current sorted filtered rows, including rows on later pages, and retains that comparison context until the drawer closes or a scan/workspace changes. A command/overview-opened finding has no invented comparison list.

The radar's axis value is the number of checks with evidence divided by the total checks in that pillar. **Observed risks count as evidence.** Full coverage can still include serious risk. Unknown points do not establish zero risk. The server's deterministic assessment, protection rules, current scope and artifact permissions remain authoritative. A saved protection signal disables Bash export in the client too; import-only Terraform still requires independent review.

Telemetry summaries retain native units and sample provenance. No idle-duration, dollar savings, raw metric series or dependency graph is inferred from a stopped/unattached signal. FOCUS billing, Jira/ServiceNow assignment, actual remediation execution and model-granted approval are not added by this UI release.

Only theme, row density and sidebar appearance are saved in browser local storage. Workspace credentials and finding data stay in memory; scan/workspace changes clear comparison context. Theme changes do not request cloud operations. Radar and tab navigation scroll their own containers rather than the document behind the modal.

## Verification

Playwright uses explicitly labeled interface QA fixtures and intercepted APIs. New workflows exercise dark/light persistence, zero-versus-unknown prices, composable facets, protection export gates, sorted drawer comparison, command deep links, telemetry gaps, mobile sizing and tab endpoints. Automated axe checks inspect all six operational views in both themes; existing assessment-dialog and navigation checks remain in the suite. Screenshots show interface test data, not customer cloud evidence. See [the release verification report](../TEST_REPORT.md) for actual executed checks. Manual assistive-technology and broad device acceptance remain necessary.

## Earlier source

The v0.7.2 light console was developed from [Detailed UI/UX Improvement Specification & Design System Guide](https://docs.google.com/document/d/1ewfeSv9580SHLb1vN4OGqwX2NZ5fUmBFvsOmPNxMQeU/edit), read October 22, 2026. Its normalized reference is retained in `drive-ui-ux-v0.7.1.txt`. Existing GitOps, delivery audit/replay, settings and billing permissions continue to use their established backend controls.


## v0.11.0 assessment workflow

The existing resource drawer now shows policy version, saved-observation age/status, evidence fingerprint, review priority and missing-evidence count. Stale/unknown/future observations prompt a refresh. Checks disclose their expected evidence fields. Cost allocation shows the first six entries from the server's bounded review queue and opens the actual saved finding. AI requests carry the preview digest; the server rejects stale previews before budget reservation. Operator token ceilings and source-provider restrictions are disclosed, and completed advisories show provider-reported input/output tokens with unknown billed cost. None of these labels is an action approval or verified prose claim.
