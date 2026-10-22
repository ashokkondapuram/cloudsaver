# CloudSaver v0.1.0 verification

This report distinguishes executed checks from source-only foundations. No live Azure resources were read or changed, no external notifications were sent, and nothing was deployed.

## Passed

- `python -m pytest -q`: **43 passed**. Tests cover workspace authorization and cross-tenant reads, persistence across app restart, concurrent scan rejection, failed audits saving no partial data, unknown live cost estimates, Azure pagination/truncation and scope checks, fixed gateway routing, latest-snapshot analytics, notification ownership and redaction, and remediation selection/confirmation safeguards.
- The generated disk script passes `bash -n`. A piped/noninteractive invocation aborts before calling a stubbed Azure CLI.
- `python -m compileall -q app services database migrations scripts`: passed.
- `CLOUDSAVER_MIGRATION_URL=postgresql://postgres@localhost/cloudsaver python -m alembic upgrade head --sql`: passed **offline SQL generation**. The output creates four domain tables, compound ownership constraints, forced RLS, read/write tenant policies and restricted runtime grants. It does not apply a migration to PostgreSQL.
- A real Uvicorn HTTP smoke test passed: factory startup, health response, missing-key rejection, an eight-finding demo scan and saved-history lookup. It used temporary SQLite storage and an ephemeral loopback port.
- Dashboard `npm run typecheck`: passed without workarounds.
- Dashboard production build: compilation, type validation, page generation and build traces passed with the environment workaround described below.
- Built dashboard HTTP smoke: page renders its workspace form; the runtime proxy forwards a bearer header and remediation JSON to a mocked gateway; an unlisted API route returns 404.

## Build environment limitation

The provided host runs Node 24.19 in a restricted environment. Ordinary `npm run build` fails before application compilation because Node's `process.memoryUsage()` RSS inspection returns `ENOENT: uv_resident_set_memory`.

The successful build command was:

```bash
NODE_OPTIONS='--require /workspace/scratch/c042050a0bde/next-build-memory.cjs' NEXT_TELEMETRY_DISABLED=1 npm run build
```

That **scratch-only helper is not included in the source release**. It catches only the unavailable memory telemetry operation, substitutes RSS=0 and obtains actual heap/external statistics from `node:v8`. It changes no application, dependencies, compiler or TypeScript settings. This establishes successful application compilation with an environment accommodation; an ordinary unmodified build on the prescribed Node 22/Docker runtime remains to be reproduced. Do not copy the temporary absolute helper path into your setup. Use `npm ci && npm run build` on Node 22.

## Not executed or incomplete

- Docker is not installed in the development environment. Full Compose startup, Redis behavior under live load, PostgreSQL initialization, online Alembic execution and database-enforced RLS integration remain unverified. HTTP ownership tests do not prove database RLS enforcement.
- No live Azure tenant/subscription credentials were available. Real ARG queries, RBAC, service-principal onboarding, real savings and API throttling behavior require acceptance testing.
- No browser visual or interactive end-to-end QA was performed. Build and HTTP checks do not establish rendered layout or large-estate performance.
- Notification-provider behavior is mocked; no Slack or Teams message was sent.
- SQLAlchemy domain tables are migration foundations; current scan persistence uses complete scan snapshots. Entra OAuth onboarding, real billing ingestion, durable jobs, commercial billing and Azure deployment are outstanding in ROADMAP.md.
- One dependency deprecation warning reports Starlette's transition away from the HTTPX TestClient integration. It does not fail the tests.
- Gemini has not reviewed this release. README.md contains a development handoff, with no runtime Gemini integration.
