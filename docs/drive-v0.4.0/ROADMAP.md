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
- SQLAlchemy domain models and Alembic migrations. The scheduled-worker path writes normalized findings and a scan snapshot atomically; the synchronous API retains its snapshot storage path.
- Stripe signature-verified webhook processing with trusted customer routing, durable event deduplication and conservative plan-state updates; no Checkout flow.
- Opt-in Celery scheduled scanning with PostgreSQL activation checks and separately opt-in aggregate alerts.
- Explicit environment or Key Vault credential providers, bounded secret caching and in-memory client-secret/certificate construction without mock fallback.
- Reviewable deletion-script generation for selected live unattached disks and unassociated public IPs, with tenant/subscription checks, interactive exact-ID approval and immediate state rechecks. The application never executes generated scripts.

No runtime Gemini integration is included. Gemini is an optional development collaborator using the handoff brief in README.md. `SPRINTS_ABC.md` describes the new billing, worker and Key Vault paths and their remaining live acceptance checks.

## 1. Reproduce and verify the assembled stack

Run the documented test suite and frontend production build. Start Compose in a Docker-capable environment, verify health and service routing, run a demo scan, restart services and confirm history persists. Test scanner timeout/failure behavior through the gateway. Record exact evidence and resolve any mismatch between dashboard contracts and service responses.

Acceptance: one documented, reproducible clean-start run with no external cloud credentials required, plus persistence across restart. Do not claim this acceptance until it has been executed.

## 2. Prove database tenant isolation

Use a disposable PostgreSQL instance with the production migration owner and `cloudsaver_app` runtime role. Test two tenants, unknown tenant context, connection reuse, failed transactions and attempted cross-tenant inserts/reads. Confirm role flags and forced RLS. Execute and verify the included Alembic baseline, establish ongoing migration discipline, and add a documented backup/restore procedure. Verify the normalized scheduled-worker write path and the synchronous snapshot path together, including rollback of failed snapshot/finding/job transactions. Validate the operator provisioning CLI and explicit subscription activation with two independent tenants.

Acceptance: database integration tests demonstrate denied cross-tenant access independently of HTTP-layer checks and confirm that application connections cannot bypass RLS.

## 3. Implement enterprise identity and onboarding

Replace shared bootstrap workspace keys with Entra sign-in and server-validated tokens, authorization roles and a membership model. Build admin-consent state/nonce handling and explicit subscription authorization. Validate the included Key Vault credential provider with a restricted managed identity, customer certificate material, secret rotation and expired-cache failure cases. Add an operational rotation and emergency-revocation procedure. Preserve server-derived tenant scopes.

Acceptance: a tenant administrator can onboard an authorized subscription, ordinary users cannot add unauthorized subscriptions, and cross-tenant token and role tests pass.

## 4. Accept and harden scheduled scan jobs

The opt-in Celery/Redis worker and PostgreSQL job/write path are included. Exercise them against real Redis and PostgreSQL before treating the schedule as operational. Verify job states, bounded retries, duplicate delivery and crash recovery. Evaluate cancellation semantics, distributed coordination and the interaction with synchronous scan requests. Add progress reporting, scheduler ownership, retention limits and operational telemetry. Keep scheduled scans disabled until the intended tenant/subscription records have been explicitly activated.

Acceptance: worker restart recovers unfinished work without duplicate completed scans, failed jobs remain auditable, and request handlers do not wait for a full cloud audit.

## 5. Attribute costs with evidence

Integrate authorized Cost Management data and appropriate resource/SKU/region pricing. Store currency, billing period, calculation basis, confidence and exclusions. Avoid treating resource-count or GB-based guesses as verified savings. Distinguish potential waste, realizable savings and realized savings.

Acceptance: representative resource classes reconcile against an agreed billing dataset; unsupported cases display unknown rather than invented costs.

## 6. Prepare commercial operation

Add deployment infrastructure, HTTPS ingress, secret management, network controls, audit logs, service-level monitoring, backups and load tests. Verify the included Stripe webhook path against test-mode lifecycle events, invalid signatures, duplicate delivery and out-of-order updates. Add Checkout and endpoint-level entitlement enforcement only after identity and tenancy acceptance. Scheduled aggregate alerts are included behind a separate disabled-by-default flag; add delivery auditing and a durable notification outbox before promising reliable automatic alerts. The current script generator is limited to human-reviewed disk/IP deletion scripts. Expand remediation only with a separate permission model, dry-run evidence, audit trails and recovery plans; account for the non-atomic gap between state checks and deletion.

Acceptance: a reviewed deployment and incident runbook, tested tenant boundaries, restore evidence and explicit product limits. Public deployment, operational Stripe acceptance, Checkout, SAML, reliable alert-delivery guarantees and application-executed remediation are not part of the present verified release. Existing webhook, scheduled-worker and Key Vault source paths need their external acceptance evidence recorded before being described as live. Script-generation tests do not verify that a live deletion is appropriate or safe.

## Collaboration rules

Assign a bounded file set to each developer or assistant before parallel work. Preserve starter code documents in Drive and keep the project README updated with release status and development handoff. Review code and tests together, record remaining verification limits and deliver source packages to the same Drive folder. Do not represent generated code as Gemini-reviewed unless Gemini has actually reviewed it and the review evidence is retained.
