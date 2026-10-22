# v0.7.2 backend hardening

Source: [Production Go-Live & Backend Hardening Guide](https://docs.google.com/document/d/1SHfRfpM9nh_cWeQ6-K1FrCqxG2y2IpJSaL-oEdwykMg/edit), read October 22, 2026.

## Durable interactive Azure scans

`POST /api/v1/scan-jobs` accepts a JSON object with `subscription_ids` (1–100 unique authorized Azure subscription UUIDs) and a UUID `idempotency_key`. Only TenantAdmin can submit. The tenant comes from verified authentication, never a request body/header. The response is HTTP 202 with `job_id`, `status`, `poll_url`, `result_url`, attempts and timestamps, plus `Location` and `Retry-After: 3`. Follow `GET /api/v1/scan-jobs/{job_id}`; a completed job links to its owned `/api/v1/scans/{scan_id}` result. `GET /api/v1/scan-jobs?limit=50` returns recent workspace jobs; foreign job IDs return 404.

The job and PostgreSQL delivery intent commit together under a tenant advisory transaction lock. Repeating a key with the same selection returns the same job. Reusing it with another selection returns 409. At most five unfinished jobs may be queued per workspace. No provider call runs in the submission request. No job state depends on an API process's memory or Celery result backend.

The existing worker revalidates the operator allowlist, active database subscriptions, current plan/resource quota and durable broker envelope. A Redis lease with owner-checked renew/release and durable job-attempt fencing protects concurrent scans. Completed redeliveries reuse their result; partial scans never commit. Interactive Azure jobs are permitted on Starter within its quota; scheduled jobs retain paid cadence requirements. Worker results now include the Azure scope fingerprint for trend comparability.

Activation (operator configuration, off by default):

1. Apply `alembic upgrade head` using the migration role. No new schema migration is required beyond the existing `0007_delivery_outbox` head.
2. Provision trusted tenant subscriptions with `scripts/provision_tenants.py --activate`, using the restricted runtime database role and the intended organization binding.
3. Set `CLOUDSAVER_INTERACTIVE_JOBS=true` and `CLOUDSAVER_DELIVERY_ENABLED=true` in private configuration. Leave `CLOUDSAVER_SCHEDULED_SCANS=false` to enable only manual submissions.
4. Run the `scan-worker` and `delivery-dispatcher` alongside the API. With Compose: `docker compose --profile scheduled --profile delivery up -d scan-worker delivery-dispatcher`. The scheduler is not needed for manual jobs.
5. Verify `/readyz`, worker health and authenticated `/api/v1/operations/reliability` in staging before accepting submissions.

Existing `/api/v1/scans` and `/api/v1/scans/multi-cloud` remain synchronous for compatibility. Durable interactive jobs currently support Azure only; cancellation, detailed stage progress, multi-cloud queued execution and browser submission/polling controls remain future work. Inspect delivery history if a queued job cannot be dispatched; scan dead letters require operator investigation rather than an unsafe automatic replay.

## Runtime and database safeguards

- `/healthz` checks process liveness. `/readyz` returns HTTP 200/503 with dependency names and up/down states, without DSNs or exception text. PostgreSQL is checked where configured; the gateway checks Redis, and the scanner checks Redis when distributed locking, delivery or interactive jobs require it. These are dependency probes, not a worker/cloud-provider health guarantee.
- PostgreSQL runtime access uses process-local SQLAlchemy pools around the existing psycopg driver. API database/scan handlers run in FastAPI's thread pool, rather than blocking the async event loop. Pre-ping, recycle and bounded overflow handle dropped/idle connections. Commit/rollback, RESET ALL and transaction-local tenant context prevent context carrying into the next request. The existing restricted-role/forced-RLS startup checks remain mandatory.
- Pool controls: `CLOUDSAVER_DB_POOL_SIZE=2`, `CLOUDSAVER_DB_MAX_OVERFLOW=3`, `CLOUDSAVER_DB_POOL_TIMEOUT=5`, `CLOUDSAVER_DB_POOL_RECYCLE=1800`. These limits apply **per process and database URL**. Budget every service, worker, replica and migration connection below the server limit before increasing them. Dispose application pools before maintenance that requires all sessions closed.
- Authenticated gateway throttling uses Redis TIME and an atomic sliding-window Lua script: 120 accepted requests per tenant in 60 seconds, expiring bounded state, HTTP 429 with a computed Retry-After, and 503 when coordination is unavailable. A forged X-Tenant-ID cannot create an independent rate bucket. Public Stripe webhook handling continues to authenticate by signature.
- Correlation accepts canonical UUID request IDs or generates new ones; request IDs propagate across gateway upstream calls and the dashboard proxy. API failures use `application/problem+json` with status/title/detail/instance/request_id. Validation and unexpected failures do not echo submitted credentials, plans or provider exception text. Existing authentication and Retry-After headers are retained.
- `CLOUDSAVER_ALLOWED_ORIGINS` is an exact comma-separated HTTPS allowlist; local HTTP is permitted only for localhost/127.0.0.1. Empty disables cross-origin access. No wildcard origin or browser credential cookie is enabled.

## Guide adaptations and go-live limits

The guide's illustrative in-memory jobs, simulated savings, source-embedded passwords, unverified tenant headers, unlimited lock retries and invalid 539 readiness status were not copied. The existing Redis primary lease is described accurately; it is not a quorum Redlock or an HA guarantee. Cloud credentials continue through the existing scope-checked provider adapters and Key Vault lifecycle; verification does not return access keys or token payloads.

The guide's load/latency targets, TLS termination, Kubernetes replicas/HPA, AWS/Azure credential acceptance, secret expiry checks, backup/restore drills and production cutover require a real authorized staging/production environment. They are not certified by local tests. During rollback preserve PostgreSQL history, stop ingress/new submissions, drain or stop the affected workers, and investigate delivery state. Do not delete wildcard Redis locks, flush broker queues or blindly downgrade a shared database while workers are active. See DELIVERY.md and OPERATIONS.md.
