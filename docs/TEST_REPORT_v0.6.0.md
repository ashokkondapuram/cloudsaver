# CloudSaver v0.6.0 verification report

Date: 2026-10-22 (UTC). Source repository: ashokkondapuram/project.

## Scope and source review

Read the v0.5.0 source package/guide and the advanced v0.6.0–v1.0.0 roadmap
from Drive root. The source ZIP SHA256 is recorded in SOURCE_CONTEXT.md.
Kept the verified PostgreSQL/authentication paths, ported AWS/network feature
intent, and implemented GCP/Kubernetes ingestion, provider UX, scoped import
review exports and observation trends. Did not inherit PostgreSQL stubs,
permissive schemas, live-to-demo fallbacks or unverified scheduling/ITSM claims.

## Executed checks

- Python 3.12.14: `python scripts/test_postgres.py` — **242 passed**, no skips.
  The runner created and removed disposable PostgreSQL 16 and Redis 7 containers.
  One inherited Starlette/httpx TestClient deprecation warning remains.
- PostgreSQL runtime role denies cross-tenant access independently of HTTP.
  New cloud_findings rows use forced RLS and tenant-owned scan foreign keys.
  Mixed snapshot/finding failures roll back; old scan history survives upgrades
  from each prior branch and the v0.4.1 merge revision.
- Existing identity, Stripe signature/ownership, entitlements, Key Vault, Azure
  pagination, worker retries/leases/fencing, gateway and remediation checks pass.
- GCP tests cover zonal/regional disks, reserved external IPv4, pagination,
  malformed/foreign identities, partial scopes, repeated tokens and late failures.
  SQL tests require all 336 hourly maxima for every series; gaps, nonzero values,
  wrong project identities and absent telemetry never become idle findings.
- Kubernetes tests cover complete 337-point windows, P95/headroom calculations,
  missing samples, high usage, NaN, wrong cluster labels, duplicate series and
  provider warnings. Unknown live costs remain null.
- Real boto3/botocore Stubber contract tests cover STS account binding, EC2/RDS
  pagination, association filtering, foreign RDS ARNs and provider failures.
  No AWS request or demo fallback occurs in those tests.
- API tests cover provider selection, rejection of caller-supplied scopes,
  role boundaries, full-scan failure without persistence, restart history,
  scope/mode-separated trends, same-count resource replacement and Terraform
  ownership/live-mode constraints. Gateway forwards only fixed routes.
- Frontend TypeScript and Next.js production build passed on the host. The
  Node 22 Docker build also performs TypeScript checking and production build.
- `python -m compileall -q app services database workers tests`, `pip check` and
  `git diff --check` passed.

## Container stack and upgrade acceptance

- Built the final Python image and dashboard image through the managed proxy,
  with TLS verification and a temporary BuildKit CA mount. Python 3.12 and Node
  22 builds passed. The five Python services share one image.
- `docker compose up -d --no-build --wait --wait-timeout 120` passed against
  the existing local v0.4.1 data volume; migration 0005 completed successfully.
  Eight services ran, required health checks passed, migration exited zero.
- Legacy Azure demo smoke passed through gateway, history and analytics.
  Saved scan: d818a9ef-9bae-4deb-a9bc-a72d88ced6f0.
- Multi-cloud demo smoke passed through dashboard POST proxy, gateway, scanner,
  PostgreSQL, analytics, provider discovery and trend proxy. All 21 synthetic
  findings persisted, including 10 normalized non-Azure findings.
  Saved scan: 97b7f025-9e24-4be1-8d13-d595913507ea.
- Restarted scanner, gateway and dashboard. Read both saved scans again without
  generating new ones, and read the previously saved v0.4.1 scan
  966ad538-0f24-4dba-8c3b-0792168a3053. Persistence and compatibility passed.
- No database/Redis volume was removed. Build cache was pruned to accommodate
  the environment's vfs disk usage. No live cloud, alert or payment was invoked.

These are HTTP/service checks, not browser visual/accessibility acceptance.

## Cost and operational limits

GCP and AWS test responses and Kubernetes metrics are controlled offline fixtures;
these checks do not establish live provider/IAM/engine/metric acceptance.
Kubernetes P95 is over hourly samples of five-minute CPU rates / working-set
memory, not continuous peak utilization or node/billing savings. Missing data is
unknown. GCP SQL requires explicit dev/staging labels and engine-supported
connection metrics. Global GCP addresses and other AWS partitions are excluded.

Live AWS/GCP/Kubernetes prices, net and realized savings remain unknown. GCP
Billing Catalog and customer billing reconciliation remain roadmap work. No
Azure/GCP/AWS mutation, Terraform plan/import/apply, real Stripe Checkout, alert
send, ITSM ticket creation or external Gemini review was executed.

Interactive scans remain synchronous, with current proxy time limits. Existing
Azure-only Celery scheduling remains opt-in and alerts disabled; transactional
publish/delivery outbox, multi-cloud jobs/cancellation and ITSM operational
acceptance are pending. Browser PKCE/onboarding, browser visual/accessibility QA,
backup/restore drill, load/fault tests and production deployment remain pending.

The frontend audit still reports **9 inherited advisories (6 high, 3 moderate)**
in the Next/PostCSS and Tailwind dependency graph. The recorded remediation
requires a planned compatible upgrade; no unsafe major-version audit fix or
TLS bypass was applied. This development release is not production acceptance.

Historical v0.4.1 evidence is retained in docs/TEST_REPORT_v0.4.1.md.
