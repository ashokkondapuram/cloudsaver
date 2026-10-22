# CloudSaver v0.2.0 verification — 2026-10-22

This report records executed checks for the database ingestion and isolation
milestone. No live Azure resources were read or changed, no external alerts were
sent and no payment or public deployment was performed. Previous release evidence
is retained in `docs/TEST_REPORT_v0.1.0.md`.

## Passed

- Reproduced the original suite before edits: **43 passed**.
- `python test_platform.py --postgres --frontend`: **57 Python tests passed**, followed by successful TypeScript checking and an ordinary frontend production build. The 14 PostgreSQL cases run against a fresh disposable PostgreSQL 16.15 container, using a separate non-superuser schema owner and restricted `cloudsaver_app` role. The runner removes that container afterward.
- PostgreSQL cases cover forced RLS and runtime role privileges, absent/unknown context, cross-tenant reads and inserts on all domain tables, forbidden tenant updates, commit/rollback context reuse, rejected foreign scan links, atomic ingestion rollback, duplicate scan rejection, repeated observations, empty scans, current subscription scope, privileged runtime rejection, runtime migration rejection, HTTP tenant-header spoofing, and application restart/history reads.
- Online Alembic upgrade: baseline 0001, insert a legacy snapshot, upgrade to 0002 and confirm the old payload remains readable. Migration runs as the non-superuser owner. No historical snapshot is rewritten or silently backfilled.
- `python -m compileall -q app services database migrations scripts tests test_platform.py`: passed.
- `CLOUDSAVER_MIGRATION_URL=postgresql://postgres@localhost/cloudsaver python -m alembic upgrade head --sql`: passed offline SQL generation through 0002.
- Dashboard `npm ci`, `npm run typecheck` and `npm run build`: passed on host Node 24.19.0 without a memory helper or compiler workaround. The old release's host limitation did not recur.
- Docker image builds for all services and the migration job: passed. The dashboard production build also passed inside the supplied Node 22 Alpine Dockerfile, without a memory workaround.

## Compose stack smoke — passed

- Fresh PostgreSQL initialization completed; the owner migration job exited 0.
- `docker compose ps --all` showed PostgreSQL, Redis, tenant, scanner and gateway healthy, with analytics, notifications and the dashboard running.
- `python scripts/smoke_stack.py`: passed. Verified unauthenticated rejection, authenticated workspace lookup, an eight-finding demo scan, saved history, latest-snapshot analytics, dashboard HTML, dashboard proxy authorization/detail lookup and rejection of an unlisted proxy route.
- `docker compose restart scanner-service api-gateway web-dashboard`, then `python scripts/smoke_stack.py --scan-id d3a239c2-0353-440c-a004-8b3bd81ba936`: passed. The same complete scan was returned after restart without creating another scan.
- No remediation or notification endpoint was invoked. This is HTTP integration evidence, not browser visual QA or a live-cloud acceptance test.

## Compose verification environment

The managed environment injects an HTTPS proxy. The executed build command was:

```bash
BUILDX_CONFIG=/workspace/scratch/buildx docker --host=unix:///var/run/docker.sock compose -f compose.yaml -f /workspace/scratch/compose-cloud.yaml up --build -d
```

The local override supplied a BuildKit secret named `proxy_ca` from the system
combined CA bundle to each Python/Node build. `BUILDX_CONFIG` relocated buildx's
writable state; Docker registry configuration and credentials were preserved.
These absolute scratch paths are environment-specific and are not shipped as
required setup paths. On an ordinary Docker host, use the README commands.

Testing caught and fixed two integration failures: host private extraction modes
prevented PostgreSQL's user from reading bind-mounted init files; initialization
files now live in a dedicated PostgreSQL image with explicit modes. Injected
lowercase HTTP proxy settings also overrode uppercase NO_PROXY; Compose now sets
both variants for internal service hosts.

## Dependency audit and remaining verification

`npm audit --json` reports **9 advisories (6 high, 3 moderate)** in the inherited
frontend dependency graph: braces/chokidar/micromatch/fast-glob, Next's nested
PostCSS, and Tailwind's selector-parser/postcss-nested dependencies. The direct
PostCSS is 8.5.31, while Next 15.5.28 pins 8.4.31 internally. The audit reports no
straightforward available fix for the complete supported Next 15/Tailwind 3
combination. This milestone preserves those architecture versions; dependency
remediation and compatibility testing remain necessary before shared hosting.

Live Azure permissions, scan latency at scale and throttling guarantees are not
verified. Entra consent, memberships, Key Vault/certificate support, Stripe,
durable jobs, real billing evidence, automatic alerting, Terraform and snapshot
retention automation remain open in `IMPLEMENTATION_STATUS.md` and `ROADMAP.md`.
Browser visual/accessibility/performance QA and a complete backup/restore drill
remain outstanding. A procedure is provided in `docs/OPERATIONS.md`.

One warning remains: Starlette deprecates its HTTPX TestClient integration; it
does not fail the suite. No Gemini review is claimed.

## Edited and added files

- `app/main.py`, `app/store.py`, `services/common.py`: normalized transactional writes, runtime role/schema checks and release version.
- `database/models.py`, `migrations/versions/0002_scan_findings.py`: scan model and tenant-owned finding links, unique constraints and backward-compatible upgrade.
- `database/Dockerfile`, `database/.dockerignore`, `Dockerfile`, `Dockerfile.services`, `web-dashboard/Dockerfile`, `compose.yaml`: reliable PostgreSQL initialization, migration job, optional build CA secrets and internal proxy exclusions.
- `tests/test_postgres.py`, `pytest.ini`, `scripts/test_postgres.py`, `scripts/smoke_stack.py`, `scripts/scan.py`, `test_platform.py`, `Makefile`: repeatable integration and operator commands.
- `web-dashboard/package.json`, `web-dashboard/package-lock.json`: version metadata only; dependency versions are unchanged.
- `README.md`, `ROADMAP.md`, `IMPLEMENTATION_STATUS.md`, `docs/OPERATIONS.md`, this report and the prior report archive: implementation status, migration/restore instructions and exact evidence.
- `scripts/release.py`, `RELEASE_MANIFEST.json`: source-only package and matching checksums; local credentials, data, dependency directories and build output are excluded.
