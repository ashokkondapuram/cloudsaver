# CloudSaver v0.7.1 verification report

Verified 2026-10-22. Baseline: published v0.7.0 commit 9e2020d.

## Delivered scope

Production reliability, security and integration foundations: PostgreSQL
transactional scan dispatch/notification intent; tenant-bound Slack/Teams targets;
leased concurrent delivery, retry budgets, broker-loss reconciliation and
admin replay; append-only runtime delivery audit and operator backlog/history.
Interactive multi-cloud scans remain synchronous. This is not a blanket claim
that the platform is production-ready.

## Executed checks

- **314 backend tests passed**, no skips, with Python 3.12 and disposable real
  PostgreSQL 16 / Redis 7: `python scripts/test_postgres.py`.
- Upgrade to 0007_delivery_outbox retains earlier branch/merge/cloud/GitOps scan
  history. Runtime roles cannot own/bypass forced RLS, read foreign tenant rows,
  update/delete delivery audit, or reference a foreign scan/job owner.
- Scheduler reservation rolls back both job and delivery intent if enqueue fails.
  Scan completion rolls back snapshot/findings/job when notification enqueue fails.
  Duplicate intent survives repository restart without duplicate audit insertion.
- Concurrent real PostgreSQL claims acquire distinct rows. Expired leases reject
  stale completion. Eight attempts exhaust to dead letter, replay is capped at
  three cycles and audit/list keyset pagination preserves row identities.
- A real Celery producer publishes to disposable Redis. Deleting the accepted
  broker message simulates message loss; reconciliation republishes the same
  durable task ID. No cloud scanner worker is launched by this test.
- Reconciliation defers recently running jobs, skips a concurrently locked job,
  fences stale workers and terminalizes exhausted dispatch. A broker task without
  a matching stored subscription envelope cannot create or fail a legitimate job.
- Testing the actual Celery entry point found and fixed an inherited nonexistent
  CredentialProviderError import; the actual CredentialError is now handled.
- Multi-target notification status stays queued until all targets acknowledge,
  becomes failed for a dead letter, returns to queued on replay and becomes sent
  after the final acknowledgment. Individual delivery history remains authoritative.
- HTTP mocks verify Slack plain-text blocks, Teams Adaptive Cards, 2xx/408/429/5xx
  handling, bounded Retry-After, redirect rejection, target fingerprint mismatch,
  redacted timeout errors and no outbound workspace bearer header. Provider bodies
  are not read or persisted. No live webhook was contacted.
- API tests verify Viewer/BillingAdmin denial for enqueue/replay, owned-scan lookup,
  explicit strict acknowledgment, generic invalid-body errors and the 1 KB replay
  limit. Target secret variables are not resolved by identity metadata services.
- **Two Chromium browser tests passed** against the built Next.js dashboard:
  admin audit/replay requires acknowledgment and makes one replay request; Viewer
  has no replay controls; hostile audit text is escaped; 390px mobile layout has
  no horizontal overflow. Browser API calls are intercepted with test-only fixtures.
- TypeScript and production build pass on Next.js 16.4.2 / React 19.3.1 / Tailwind
  CSS 4.3.3. Node 22 Docker build passes. The old Tailwind/PostCSS chain was
  replaced, not hidden with audit suppression.
- **npm audit: zero known vulnerabilities** (all dependency classes) at verification.
  This is a registry advisory snapshot, not a security certification.
- Python container build, pip check, compileall, Compose config validation and
  git diff --check pass. One inherited Starlette/httpx TestClient deprecation
  warning remains.

- Running Compose stack: all eight long-running services healthy; schema migration
  completed without replacing PostgreSQL/Redis volumes. Saved historical scan
  97b7f025-9e24-4be1-8d13-d595913507ea remained readable. Gateway/dashboard smoke
  verifies auth, entitlements, history, GitOps routes, invalid-plan redaction and
  new operational routes. The smoke passed again after scanner/gateway/dashboard
  restart. Delivery remains disabled with no targets/backlog or
  observed dispatcher poll; no outbound work was initiated.
- Disposable database downgrade/upgrade round-trip preserved scan history, mapped
  queued notification state for the older schema and restored forced RLS under
  a non-superuser migration owner. This test is not a production restore drill.

## Continuous checks added

.github/workflows/verify.yml runs the disposable DB/broker suite, frontend audit,
typecheck/build and intercepted Chromium workflows on main pushes and pull
requests. Actions are pinned to observed v6 commit SHAs, token permissions are
read-only and checkout credentials are not persisted. No customer credentials are
used. Dependabot is configured for weekly Python/npm/Action review PRs.
Local equivalents ran; a hosted Actions result is separate evidence and is not
claimed by this report.

## Limits and rollout requirements

Delivery is at least once. Timeout/crash after provider acceptance can duplicate a
notification; 2xx is provider acknowledgment, not human receipt. Eight automatic
attempts and three manual replay cycles are intentional limits, not indefinite
retry or exactly-once guarantees. Scan transport attempts and worker execution
attempts are separate budgets. Runtime roles cannot edit/delete audit, but a DB
owner can: external immutable storage and retention/archival remain unimplemented.

Delivery/automatic alerts/schedules remain disabled in the verification workspace.
Live Slack/Teams acceptance, process-kill/broker-restart staging drills, sustained
load, queue latency SLOs, external backlog alerting, HA/failover and production
restore acceptance remain required. No live cloud scan, payment, customer
infrastructure PR, ticket or remediation was executed. Source publication to the
user's GitHub repository is separate from product integration acceptance.

The legacy global webhook variable no longer enables sending. Targets must be
explicitly bound to tenants; destination rotation creates a new fingerprint.
Old queued jobs without a stored scope envelope are not silently guessed or
backfilled. Read docs/DELIVERY.md before activating or upgrading scheduled workers.
The runbook covers pause, ambiguity, replay and rollback restrictions.

Browser coverage is limited to the new delivery workflow and existing stack
smoke; it does not establish a complete visual/accessibility audit. Browser
PKCE/consent, live Entra/Stripe/cloud/GitHub App acceptance, wider Terraform/OPA
corpora, ITSM adapters, durable multi-cloud jobs/cancellation, billing
reconciliation and OpenCost remain pending. No production-readiness or compliance
certification is claimed. Earlier evidence is retained in docs/TEST_REPORT_v0.7.0.md.
