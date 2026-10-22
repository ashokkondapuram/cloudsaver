# CloudSaver implementation status

This release continues the v0.1.0 source ZIP in the supplied Drive folder. The
expanded platform description is a target specification. The executable source
and executed tests determine the status below; prose and mock responses do not
establish a completed integration.

| Capability | Current implementation and evidence |
| --- | --- |
| Dashboard | Next.js 15 / React 19, TanStack sorting/filtering/virtualization, CSV/JSON exports and history. Typecheck and production build pass. Browser visual/performance QA remains open. |
| Gateway and services | Five FastAPI services, bearer authentication at each boundary, server-derived tenant scope, fixed routing and Redis rate limits. Caller-supplied X-Tenant-ID is ignored for authentication. |
| PostgreSQL isolation | Forced RLS on snapshots and all four domain tables, restricted runtime role, transaction-local context. Tested with a real PostgreSQL 16 server and two tenants. |
| Normalized ingestion | v0.2.0 atomically writes workspace configuration, snapshot and scan-linked findings. Invalid scope and failed writes save no partial data. Legacy snapshots remain readable without automatic backfill. |
| Azure checks | Four paginated read-only ARG rules. SDK logic is tested with mocks. Live credentials, RBAC, latency and throttling behavior remain unverified. |
| Enterprise identity | Entra OAuth, admin consent and membership authorization are still planned. Bootstrap workspace keys are implemented. |
| Billing | Stripe checkout, signed webhooks, customer mapping, entitlements and event idempotency are still planned. The separate Drive billing.py returns fabricated checkout URLs and is not used by this application. |
| Background jobs | Durable jobs, Celery, Beat, distributed locking and recovery remain planned. The separate tasks.py constructs sample findings and lacks persistent ingestion; it is not a verified live scanner. Current scans run synchronously with a process-local lock. |
| Credential storage | Live scanning requires explicit configured Azure client credentials. The separate Key Vault starter falls back to mock credentials; it is not integrated. A fail-closed vault/certificate implementation remains planned. |
| Cost attribution | Live values remain unknown. Demo dollars are labeled illustrative. No verified 6.2% savings, per-GB pricing, universal public-IP charge or run-rate reduction is claimed. Prices depend on SKU, region, agreement, billing period and actual meter evidence. |
| Remediation | Generates interactive review scripts for live unattached disks/IPs. The application never deletes resources. Snapshot automation, Terraform generation, retention enforcement and simulation remain planned. A retention tag alone does not implement a 90-day retention policy. |
| Notifications | Explicit operator-configured aggregate webhook delivery; provider calls are mocked in tests. No scheduled alerts or live sends were performed. |
| Hosting | Local Compose development deployment. Enterprise ingress, backup drills, monitoring, commercial operation and Azure Container Apps deployment remain open. |

The supplied `SET LOCAL app.current_tenant_id = :tenant_id` example is not used:
PostgreSQL SET does not accept that value as a regular bound SQL expression.
The implementation uses parameterized `set_config('app.current_tenant_id', value,
true)` inside the active transaction. The true flag makes the value local to
that transaction; tests verify it disappears after commit and failure rollback.

The current layout is `app/`, `services/*.py`, `database/`, `migrations/` and
`web-dashboard/`. It retains the existing source layout rather than introducing
duplicate service implementations. `compose.yaml` is the canonical Compose
file. `python test_platform.py`, `make scan`, `make test` and
`make test-postgres` provide the requested local entrypoints. Billing checkout
is not an implemented endpoint and the unauthenticated sample request will not
create a payment session.

Next development should implement and test Entra identity and memberships, then
durable scan jobs, before billing or automatic remediation. See ROADMAP.md.
