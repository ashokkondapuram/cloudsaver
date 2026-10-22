# CloudSaver v0.4.1 verification — 2026-10-22

This release continues the **actual Drive v0.4.0 ZIP**. The original full suite
reproduced as **142 passed, 2 failed**; the guide's 29-test report was a subset.
Failures were live empty-scan savings reported as zero and an API lease import
referencing a nonexistent class. Both are fixed. Passing original tests also
accepted unsigned JWTs and synthetic checkout URLs; those tests were replaced
with behavior checks for verified identity and real/fail-closed provider paths.

## Passed

- `python scripts/test_postgres.py`: **209 passed**, no skips, in 8.78 seconds on
  the final run. The harness creates/removes isolated PostgreSQL 16.15 and Redis
  7 containers, private ephemeral credentials and separate schema-owner/runtime
  roles. The only warning is Starlette's HTTPX TestClient deprecation.
- Identity tests use generated RSA keys to verify real signatures and reject
  unsigned, tampered, wrong-key, expired, future, wrong-issuer/audience/tenant,
  missing-claim, missing-scope and privilege-inference attempts. API tests cover
  Viewer/BillingAdmin/TenantAdmin actions and shared gateway verification.
- Pricing tests use bounded mocked HTTP responses, assert the correct `$filter`
  parameter, exact USD meter/unit/type/region matching and explicit resource
  quantity, and reject ambiguous data, unsafe pagination, invalid prices and
  provider failure. Unsupported evidence and net savings remain unknown.
- Export tests cover authorization, matching rule/resource types, duplicate
  selections, stable unique Terraform import labels and absence of fabricated
  resource settings, deletion plans or automatic snapshot promises.
- Checkout tests assert trusted customer/organization/price routing, fixed return
  URLs and stable retry idempotency through a mocked Stripe SDK boundary.
  Existing raw-body signature, deduplication and out-of-order webhook tests remain.
- Real PostgreSQL tests cover forced RLS, cross-tenant reads/inserts/updates,
  absent context, commit/rollback connection reuse, atomic normalized ingestion,
  failed-write rollback, owned scan links, privileged runtime rejection, Stripe
  event persistence and authoritative entitlement changes, stale worker tokens,
  transactional schedule reservations and hidden foreign jobs.
- Upgrade tests start separately from **0002_scan_findings** and
  **0003_scan_jobs**, apply the merge head and verify legacy snapshots remain
  readable. The migration graph has one head, 0004_merge_hardening. Applied prior
  migration histories are not rewritten.
- Real Redis tests use independent clients to verify mutual exclusion, owner-only
  renewal/release, takeover after simulated expiry and heartbeat detection of
  lease loss. The legacy in-memory outbox tests prove only their test foundation.
- `python test_platform.py --postgres --frontend`: passed the then-current 206
  tests, TypeScript checking and ordinary host Node 24 production build; the
  final 209-test run adds migration-lineage and explicit pricing-quantity cases.
- Final Docker image builds passed for the shared Python runtime, PostgreSQL
  initialization image and dashboard on **Node 22 Alpine**. No Node memory helper,
  disabled TLS verification or compiler workaround was used.
- `python -m compileall -q app services database migrations workers scripts tests test_platform.py`: passed.
- `CLOUDSAVER_MIGRATION_URL=postgresql://postgres@localhost/cloudsaver python -m alembic upgrade head --sql`: passed offline generation through the merge revision. Online upgrade evidence comes from the integration tests above.

## Final Compose smoke — passed

All final images started with `compose up --no-build --wait`. PostgreSQL, Redis,
Python services and dashboard were ready; the owner migration exited 0. The
HTTP smoke verified authentication, fixture scan creation, saved history,
latest-snapshot analytics, dashboard HTML/proxy routing and rejection of an
unlisted proxy route. A pre-upgrade scan,
`c0bd4dc1-cb65-4bb8-bb39-639a33f9e7ac`, remained readable after the final service
images were recreated. No remediation, notification or payment endpoint was
invoked.

## Build environment

The managed runtime uses an HTTPS proxy and a private default umask. Dockerfiles
accept an optional BuildKit `proxy_ca` secret; initialization files are copied
into the PostgreSQL image with explicit read/execute modes. Compose sets both
NO_PROXY variants for internal service hostnames. Registry credentials and TLS
verification were preserved.

The executed build used a local override supplying the combined system CA bundle:

```bash
BUILDX_CONFIG=/workspace/scratch/buildx docker --host=unix:///var/run/docker.sock compose -f compose.yaml -f /workspace/scratch/compose-cloud.yaml build scanner-service web-dashboard postgres
docker --host=unix:///var/run/docker.sock compose up -d --no-build --wait --wait-timeout 120
```

These scratch paths are environment-specific and are not shipped as required
setup paths. `make build` builds each distinct image once; Python services share
one image. Unused Docker build cache was cleared after the container's VFS layers
filled the workspace disk. The interrupted build/checks were rerun successfully.

## Remaining acceptance limits

- No live Entra tenant, Stripe session/payment, Azure subscription scan, automatic
  alert, Terraform apply or resource deletion was performed. SDK/crypto/mock tests
  do not establish external RBAC, tenant onboarding, payment or cloud behavior.
- No browser visual/accessibility/performance QA or target Terraform/provider
  plan validation was performed. Text generation and a successful web build are
  narrower evidence than those acceptance checks.
- Browser PKCE sign-in, consent callbacks, memberships, interactive durable job
  progress/cancellation, a transactional outbox, reliable notification delivery,
  existing-subscription billing portal, deployment and restore drills remain open.
- Redis heartbeat and per-job ownership tokens do not establish exactly-once
  execution across Redis failover and PostgreSQL. Celery broker publication and
  crash recovery still need fault testing; automatic alerts stay disabled.
- `npm audit --json` on the inherited Next 15/Tailwind 3 graph reports **9
  advisories: 6 high and 3 moderate**. The dependency graph is unchanged except
  release-version metadata. Dependency remediation/compatibility work is required
  before shared hosting; no production security certification is claimed.
- Retail rates are list-price estimates, not actual customer bills or realized
  savings. Missing data remains unknown. Disk-tier/VM-storage and actual net
  remediation-cost models require further evidence.

## Source and review record

Imported modules include explicit Key Vault providers, Stripe webhooks, billing
storage, Celery workers and the v0.4 dashboard. The v0.2 normalized scan storage,
forced RLS, database initialization image and operator scripts remain. New/edited
code primarily lives in app/auth.py, app/main.py, app/entitlements.py,
app/pricing.py, app/remediation_terraform.py, shared service authentication,
workers/tasks.py, workers/lease.py, workers/storage.py, database/models.py, the
merge migration, Compose and dashboard contracts. Behavior tests cover these
changes. README, ROADMAP, IMPLEMENTATION_STATUS and SOURCE_CONTEXT distinguish
working paths from unfinished source foundations. Historical evidence is archived
under docs. No external Gemini review is claimed.
