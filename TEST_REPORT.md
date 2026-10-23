# CloudSaver v1.0.0 integrated verification report

Executed October 23, 2026. Baseline: verified GitHub v0.11.0, commit `053db837e3d184c4e8847a93a93c58842bb7efea` (CI success). Requirements: the exact user-named [v1.0.0 master guide](https://docs.google.com/document/d/1FmtfohZPlnlwZ1lbcCuu-XX0G1uc6UI3Z87svw4P0zc/edit) and inspected Drive CloudSaver-v1.0.0.zip. See docs/V1_MASTER_GUIDE.md for the eight-area mapping and original-package provenance.

| Check | Executed result |
| --- | --- |
| Complete backend suite, `python scripts/test_postgres.py --tb=short` | **433 passed**, disposable PostgreSQL 16 and Redis 7; containers cleaned up |
| Python dependency consistency, `python -m pip check` | Passed |
| Production compilation and TypeScript, `npx next build --webpack` | Passed; all nine routes generated |
| Complete browser suite against a fresh production server | **30 passed**, intercepted test-only APIs |
| New enterprise workflows against the standalone production artifact | **5 passed**, including finance/history accessibility, viewer restrictions, uncertain outcomes and late-response cancellation |
| Whitespace validation, `git diff --check` | Passed |

## Verified implementation

- **Durable inference:** a committed, tenant-owned attempt exists before provider invocation; no transaction spans inference. Restarted instances reuse completed results. Concurrent and uncertain attempts cannot replay, cached reads do not consume another slot, and the hourly budget counts accepted attempts. A failed result commit preserves a fence and never exposes uncommitted advice. Reservation failure prevents invocation. Provider errors remain sanitized.
- **History/usage:** saved advice, evidence policy/digest, lifecycle and known provider token portions remain tenant-scoped. Missing counters stay unknown. Structured cost-center/application attribution is recorded separately and never enters model input. Unmetered and incomplete outcomes remain visible. No billed-dollar estimate is invented.
- **PostgreSQL:** migration 0009 applies on the disposable database. All four new tables enable and force RLS. No-context/foreign-context reads cannot reveal records. Cross-owner inserts, runtime billing deletion, lifecycle editing and terminal-outcome updates are rejected. Existing migration lineage, normalized ingestion, forced RLS and lease/outbox tests continue to pass.
- **Billing evidence:** finance-authorized imports validate schema, scopes, resource ownership, currency, periods and exact decimal strings. Duplicate source replay and overlapping charge deduplication are stable; conflicting charges reject atomically. Credits and real zero are retained. Foreign/removed cloud scopes are not exposed. Float/boolean/NaN/exponent/overprecision inputs are rejected. Extreme permitted monetary ratios and projections retain exact decimal results in an isolated high-precision context.
- **Analytics:** currency groups remain separate; missing list costs prevent ESR. Declared complete empty exports establish zero; partial declarations remove coverage. Long or partially overlapping charges never become fabricated daily series or complete forecast coverage. Month-end projections require proper same-year month-to-date windows and sufficient covered closed days. Z-scores require a complete, nonconstant 30-day baseline; signals remain provisional and nonseasonal.
- **Discovery:** four independent read-only sources can progress concurrently with correct tenant identity bindings. Any failed reader discards the overall result; normalized authorization, duplicate detection and finding limits remain enforced. No error-to-demo fallback is added.
- **Routing/roles:** new gateway paths forward only to the fixed scanner service and retain bearer authentication. Visitor-supplied upstream parameters are ignored; malformed dynamic IDs fail before forwarding. Viewer billing reads/imports are denied; saved AI history remains tenant-bound.
- **Console:** explicit billing-file preview/acknowledgement/import, preserved monetary strings, currency/budget filtering, receipts, saved AI advice, lifecycle and usage inspection pass browser workflows. Pending/uncertain outcomes have no retry/approve/execute control. Late detail responses cannot appear after tab changes. All new evidence scroll regions are labeled and keyboard-focusable. Existing dark/light, mobile, virtual inventory, comparison/focus, plan review, delivery replay and role workflows still pass.

Browser screenshots contain labeled test fixtures, not customer invoices or actual AI responses. Production modules never import these fixtures. All external provider clients used in backend verification are injected/mocked; no real cloud scan, model invocation, remediation, payment, alert, ticket or product GitOps PR was executed.

## Deployment and acceptance boundary

Apply schema-owner migration **0009_enterprise_evidence** before starting upgraded PostgreSQL services. The integration keeps existing keyless identity and RLS architecture; no new secret storage is required. The shared Compose stack and existing databases were not upgraded or restarted during testing. SQLite remains a local development path without database-enforced RLS.

The API now uses SQL attempt coordination, with durable fences and no automatic advice/history TTL. Define retention, backup/restore and owner-controlled purge procedures. Old Redis inference records are not automatically migrated: use a controlled inference cutover and do not resubmit old uncertain requests. Runtime append-only grants/terminal-outcome protection are not WORM or compliance certification. Database loss/restore can still lose history; external exactly-once inference is not guaranteed.

The billing contract is a normalized FOCUS field subset with x_ChargeId identity, not native export ingestion or full FOCUS certification. Completeness is operator-declared and not provider-reconciled. Resource-level bill matching, native connectors, verified amortization, seasonality, net snapshot economics, realized savings and monetary AI budgets remain open. Jira/ServiceNow synchronization, full organization hierarchy, extra role mappings, durable interactive multi-cloud jobs, full topology and autonomous execution are not claimed.

The Drive ZIP was inspected, not accepted as a production baseline or executed wholesale. Its old database/demo/dependency artifacts were not imported. Current secrets, data volumes, caches and test outputs are excluded from the integrated source package. The original Drive ZIP is preserved and the new artifact uses CloudSaver-v1.0.0-integrated.zip.

No cloud identities are configured here, so live IAM/model compatibility, billing-source reconciliation, deployment/load acceptance, provider retention policies, semantic AI quality and compliance remain unverified. GitHub CI runs on publication; its final result is reported separately without changing the packaged report after release.
