# CloudSaver development roadmap

The current release implements an engineering MVP from the Drive architecture. Completion below means source is present, not that a production deployment or live-cloud acceptance test has passed. Read `TEST_REPORT.md` for verified results.

## Current implementation

- Next.js 15 / React 19 dashboard with TypeScript and Tailwind; a separate standalone API supports lightweight local demo development.
- Five FastAPI services: gateway, tenant, scanner, analytics and notification.
- Operator-managed workspace keys and tenant/subscription configuration; tenant authorization on reads and scan execution.
- Four read-only Azure Resource Graph checks with pagination and complete-scan persistence.
- Demo mode with illustrative fixtures and no cloud calls.
- SQLite standalone storage and PostgreSQL scan storage with forced RLS, a restricted application role and transaction-local tenant context.
- Redis gateway request limiting, latest-scan analytics and an explicit optional aggregate webhook send.
- Dockerfiles, Compose topology and Makefile commands for local development.
- SQLAlchemy domain models, a scan-link migration and atomic normalized PostgreSQL ingestion; existing snapshot history remains readable. A disposable PostgreSQL suite verifies runtime-role isolation, rollback and migration boundaries.
- Reviewable deletion-script generation for selected live unattached disks and unassociated public IPs, with tenant/subscription checks, interactive exact-ID approval and immediate state rechecks. The application never executes generated scripts.

No runtime Gemini integration is included. Gemini is an optional development collaborator using the handoff brief in README.md.

## 1. Assembled stack — local demo verified in v0.2.0

Run the documented test suite and frontend production build. Start Compose in a Docker-capable environment, verify health and service routing, run a demo scan, restart services and confirm history persists. Test scanner timeout/failure behavior through the gateway. Record exact evidence and resolve any mismatch between dashboard contracts and service responses.

Acceptance evidence: local Docker image builds (including Node 22), fresh initialization, owner migration, authenticated demo scan, analytics/dashboard proxy routing and persistence across service restart passed. See TEST_REPORT.md. Live-cloud timeout/load behavior and browser QA remain open.

## 2. Database tenant isolation — implemented in v0.2.0

Use a disposable PostgreSQL instance with the production migration owner and `cloudsaver_app` runtime role. Test two tenants, unknown tenant context, connection reuse, failed transactions and attempted cross-tenant inserts/reads. Confirm role flags and forced RLS. Execute and verify the included Alembic baseline, establish ongoing migration discipline, and add a documented backup/restore procedure. Wire the normalized domain model into an explicitly tested write path before treating it as active application storage.

Acceptance evidence: the PostgreSQL integration suite demonstrates denied cross-tenant reads/writes independently of HTTP-layer checks, context cleanup after commit/rollback, rejection of privileged runtime roles, linked finding constraints, atomic rollback and retained legacy history. Backup/restore has a documented procedure in `docs/OPERATIONS.md`; an actual restore drill remains outstanding.

## 3. Implement enterprise identity and onboarding

Replace shared bootstrap workspace keys with Entra sign-in and server-validated tokens, authorization roles and a membership model. Build admin-consent state/nonce handling and explicit subscription authorization. Add credential rotation and certificate or managed secret handling suitable for customer tenants. Preserve server-derived tenant scopes.

Acceptance: a tenant administrator can onboard an authorized subscription, ordinary users cannot add unauthorized subscriptions, and cross-tenant token and role tests pass.

## 4. Move scans into durable jobs

Introduce a persistent queue and worker. Record queued/running/completed/failed states, cancellation semantics, bounded retries and idempotency. Replace process-local scan locks with a distributed mechanism. Add progress reporting, scheduler ownership, retention limits and operational telemetry.

Acceptance: worker restart recovers unfinished work without duplicate completed scans, failed jobs remain auditable, and request handlers do not wait for a full cloud audit.

## 5. Attribute costs with evidence

Integrate authorized Cost Management data and appropriate resource/SKU/region pricing. Store currency, billing period, calculation basis, confidence and exclusions. Avoid treating resource-count or GB-based guesses as verified savings. Distinguish potential waste, realizable savings and realized savings.

Acceptance: representative resource classes reconcile against an agreed billing dataset; unsupported cases display unknown rather than invented costs.

## 6. Prepare commercial operation

Add deployment infrastructure, HTTPS ingress, secret management, network controls, audit logs, service-level monitoring, backups and load tests. Implement subscription entitlements and billing only after identity and tenancy acceptance. Add notification scheduling and delivery auditing before promising automatic alerts. The current script generator is limited to human-reviewed disk/IP deletion scripts. Expand remediation only with a separate permission model, dry-run evidence, audit trails and recovery plans; account for the non-atomic gap between state checks and deletion.

Acceptance: a reviewed deployment and incident runbook, tested tenant boundaries, restore evidence and explicit product limits. Public deployment, Stripe billing, SAML, automatic alerts and application-executed remediation are not part of the present verified release. Script-generation tests do not verify that a live deletion is appropriate or safe.

## Collaboration rules

Assign a bounded file set to each developer or assistant before parallel work. Preserve starter code documents in Drive and keep the project README updated with release status and development handoff. Review code and tests together, record remaining verification limits and deliver source packages to the same Drive folder. Do not represent generated code as Gemini-reviewed unless Gemini has actually reviewed it and the review evidence is retained.
