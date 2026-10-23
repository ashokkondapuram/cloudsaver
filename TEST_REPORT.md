# CloudSaver v0.7.3 verification report

October 22, 2026. This report describes local verification, not production certification.

## Scope and sources

- Drive [UI/UX design guide](https://docs.google.com/document/d/1ewfeSv9580SHLb1vN4OGqwX2NZ5fUmBFvsOmPNxMQeU/edit): persistent six-view workspace, observation charts, virtualized inventory, filters, review drawers, automation and settings.
- Drive [backend hardening guide](https://docs.google.com/document/d/1SHfRfpM9nh_cWeQ6-K1FrCqxG2y2IpJSaL-oEdwykMg/edit): durable Azure scan submission/polling, existing outbox/lease reuse, PostgreSQL pools, dependency readiness, correlation/problem errors, CORS and shared sliding-window rate limiting.
- Existing v0.7.1 features, production-only provenance, forced tenant RLS and import-only GitOps are retained. Earlier release evidence is archived in docs/TEST_REPORT_v0.7.1.md.

## Backend evidence

Backend behavior is unchanged from v0.7.2. Its 324-test suite also passed on GitHub in run 39864318033. The v0.7.3 change updates frontend selection timing and release metadata.

`python scripts/test_postgres.py --tb=short`: **324 passed**, using fresh disposable PostgreSQL 16 and Redis 7 containers, separate owner/runtime roles and migration upgrades. Containers are removed by the runner; existing data volumes are not changed.

Added checks cover concurrent idempotent submissions, conflicting key reuse, atomic job/outbox rollback, authorized/connected scopes, tenant isolation, a five-job backlog bound, HTTP 202 without scanning, poll persistence after API restart, disabled-job behavior, Starter manual worker completion, scope fingerprints, connection reuse after commit/rollback with no tenant-context leakage, row-factory restoration, atomic 120-request Redis sliding windows with tenant separation/expiry, safe problem responses, correlation propagation and explicit CORS. Existing broker-loss/retry/fencing, RLS, pricing, billing, provider, GitOps, plan validation and delivery tests remain included.

`python -m pip check`: no broken requirements. The suite emits the upstream Starlette/httpx TestClient deprecation warning; tests still pass. No backend dependency was added for pooling: SQLAlchemy and psycopg were already present.

## Frontend evidence

`npm run test:e2e`: **13 passed** on Chromium against the final production build.

Production typechecking/build: Next.js 16.4.2 and React 19, all eight routes generated (six workspace views, proxy and not-found). Host webpack production build passes. Node 22 Alpine Docker build also passes using the normal Turbopack build and verified TLS dependency installation. `npm audit --json` reports **0 vulnerabilities** across installed dependencies.

Coverage includes actual provider drill-down; combined provider/priority/tag filtering; 28px compact density; column controls; current-page selection; 10,000-row virtualization; evidence/cost/server-code drawers and focus restoration after virtual rows are replaced; viewer gates; command/scoped navigation; memory-only credentials; exact duplicate-key plan upload; GitOps preview/acknowledgment; explicit provider scan action; mobile layout; delivery audit/replay/XSS handling. Automated axe checks find no serious/critical violations in the tested overview, inventory, settings and drawer views. This does not replace manual assistive-technology or broad browser/device acceptance.

All browser APIs are intercepted using explicitly labeled QA workspaces. No real cloud scan, checkout, webhook message, product PR or infrastructure mutation runs in these tests. Screenshots show interface QA fixtures, not customer observations.

## Container and smoke evidence

Both release images build successfully: `cloudsaver-python:0.7.2` and the Node 22 standalone dashboard. All eight long-running Compose services are running; configured PostgreSQL, Redis, gateway, tenant and scanner health checks pass. The existing data volumes are preserved. `scripts/smoke_stack.py` passes through the gateway and dashboard proxy, including readiness, authentication, retained scan lookup, GitOps, reliability/delivery, the new scan-job list, UUID correlation and bounded validation. No cloud scan or outbound integration is triggered.

Builds preserve the session proxy configuration and CA verification. No credentials, .env files, customer snapshots, node_modules or compiled artifacts are included in the source package.

## Remaining acceptance and limits

- New durable interactive jobs support Azure only and remain disabled by default. Operator provisioning, connected subscriptions, a worker and delivery dispatcher are required. The browser and existing multi-cloud API continue synchronous scanning. Cancellation, detailed stage progress and multi-cloud job scheduling remain open.
- Pool limits apply per process/DSN; a deployment connection budget and load test are required. Readiness checks database/Redis availability where required, not cloud credentials, workers, end-to-end SLOs or HA failover.
- Authorized Azure/AWS/GCP/Kubernetes, Entra, Stripe test-mode, GitHub App and Slack/Teams acceptance is still required. Local fixtures cannot certify these integrations.
- Billing series, non-Azure verified dollar estimates, realized savings, OpenCost allocation, browser PKCE onboarding and ITSM assignment remain unavailable. Unknown values remain unknown.
- Production TLS, Kubernetes/HPA, backup/restore, chaos/load acceptance, secret rotation/expiry and production cutover/rollback have not been executed. Delivery remains at least once; Redis leases are not a quorum Redlock guarantee. Preserve job/outbox/audit state during incident recovery.

## CI follow-up

The first GitHub run passed backend tests, dependency audit, typechecking and production build, but its faster Chromium runner exposed a Shift-R selection synchronization race. Selection now updates table and workspace state in the same event, keyboard listeners update before paint, and snapshot changes clear selection. Follow-up production build and browser checks are recorded with the correcting commit. The v0.7.2 container/smoke results above describe the preceding release; v0.7.3 has not been redeployed to the local Compose stack.

The v0.7.3 webpack production build and TypeScript check pass. All 13 Playwright workflows pass against that production build, including the corrected shortcut and automated accessibility checks.
The combined filter/selection/Shift-R workflow also passes five consecutive fresh-browser runs.
