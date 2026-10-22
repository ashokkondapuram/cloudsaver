> Imported historical Sprint A–C handoff. Current behavior and verification are governed by README.md and TEST_REPORT.md.

# Sprints A–C: billing events, scheduled scans and customer credentials

This release implements the next development steps from the updated Drive README. These are executable integration paths, not proof of a deployed payment system, a running cloud schedule or successful Key Vault access. Consult `TEST_REPORT.md` for the exact test evidence and external checks still required. There is no runtime Gemini integration; Gemini may use this document as a development handoff.

## Sprint A — Stripe webhook processing

`services/billing.py` handles raw Stripe webhook events at `/api/v1/billing/webhook`. The route is intentionally public for Stripe delivery and authenticates the event using the configured endpoint signing secret and Stripe signature verification. It does not trust browser bearer keys or event metadata to establish customer ownership.

Trusted operator configuration maps Stripe customer IDs to existing organization and tenant records:

```json
{
  "cus_example": {
    "tenant_id": "11111111-1111-4111-8111-111111111111",
    "organization_id": "33333333-3333-4333-8333-333333333333"
  }
}
```

Set this mapping in `CLOUDSAVER_STRIPE_CUSTOMERS`. The referenced organization row must already exist and contain the same Stripe customer ID. `STRIPE_PRICE_TIERS` maps approved `price_...` IDs to `STARTER`, `GROWTH` or `ENTERPRISE`. Unrecognized or ambiguous prices cannot grant a higher tier.

`database/billing_store.py` applies the event and updates plan state atomically under tenant RLS. The store retains event IDs for deduplication and uses separate subscription and invoice watermarks to handle out-of-order delivery conservatively. A payment-success notification does not independently promote an unrelated subscription. Migration `0002_billing` adds organization billing state and the tenant-scoped event ledger.

No Stripe Checkout endpoint, fake checkout URL or payment collection flow is included. Plan-state processing is a foundation; it does not mean all application endpoints enforce commercial entitlements. Before production use, verify the actual public HTTPS route, signing-secret configuration, retry behavior and representative subscription lifecycle events with Stripe test mode. Never send a live charge merely to verify this code.

## Sprint B — opt-in scheduled scan workers

Celery workers use Redis and JSON task messages. Scheduled scanning is disabled unless an operator explicitly enables `CLOUDSAVER_SCHEDULED_SCANS`. The worker selects only the intersection of server-configured tenant/subscription allowlists and provisioned PostgreSQL records whose tenant connection and subscription activation states permit scanning. A task cannot introduce an arbitrary tenant or subscription.

Azure mode runs the real `scan_live` path; demo mode uses clearly identified demo fixtures. The PostgreSQL worker storage path commits the scan snapshot, normalized findings and completed job together. Migration `0003` supplies the job foundation. A failure must not create a successful partial audit.

Compose's worker profile is opt-in and includes worker/beat services. Redis persistence is enabled for the queue. Starting containers is not sufficient to authorize scanning: apply migrations, provision the intended domain records, explicitly activate subscriptions and enable the schedule deliberately. Use the provisioning CLI's current `--help` and the root README for the exact supported options; do not guess provisioning flags.

`CLOUDSAVER_AUTOMATED_ALERTS` is separately disabled by default. When enabled, the worker sends an aggregate completion summary to the configured allowlisted webhook only after database commit. This outbound action requires operator configuration and should be verified against a controlled test destination. A post-commit webhook is not a durable notification outbox; delivery guarantees and retry semantics need review before promising reliable alerts.

Celery and Redis improve background execution but do not, by themselves, prove exactly-once work, operational recovery or scheduler ownership. Validate crash recovery, duplicate delivery, lease/lock behavior and backlog handling against real services before increasing concurrency.

## Sprint C — fail-closed Key Vault credential provider

`app/keyvault.py` selects exactly one provider using `CLOUDSAVER_CREDENTIAL_PROVIDER=env|keyvault`. Environment mode retains the explicitly configured Azure client-secret path. Key Vault mode requires `AZURE_KEYVAULT_URL` to be an approved public Azure vault HTTPS endpoint; a missing, malformed or inaccessible vault does not fall back to environment credentials or mock secrets.

The default vault authentication is managed identity. `AZURE_KEYVAULT_AUTH=default` explicitly opts into the Azure default credential chain for local development. The provider derives a secret name from the authorized tenant UUID:

```text
tenant-<tenant UUID with hyphens removed>-cred
```

The secret contains a JSON credential document. For client-secret authentication, its schema is:

```json
{
  "azure_tenant_id": "11111111-1111-4111-8111-111111111111",
  "client_id": "44444444-4444-4444-8444-444444444444",
  "auth_type": "client_secret",
  "client_secret": "set-the-real-secret-in-Key-Vault-only"
}
```

Certificate authentication uses `auth_type: "certificate"`, `certificate_pem` and `private_key_pem` instead of `client_secret`. Both PEM values remain in memory; the Azure credential constructor receives combined certificate material without a temporary private-key file. The credential's tenant ID must match the server-owned tenant identity. Duplicate JSON fields, mixed authentication material and unexpected fields are rejected.

Secrets use redacted `SecretStr` fields and a bounded process-local cache: default TTL 300 seconds, configurable from 0 to 900 through `AZURE_KEYVAULT_CACHE_TTL_SECONDS`, with at most 128 tenants retained. A refresh reads the latest secret version. Rotation may take up to the configured TTL to become visible in each process; use a controlled cache clear or process restart when immediate revocation is required. A failed refresh does not return expired material.

Grant the runtime managed identity only the vault secret-read access it needs and configure the customer application's Azure permissions independently. The provider does not create applications, grant RBAC, write vault secrets or perform tenant onboarding. Azure Key Vault permissions, managed identity resolution, certificate validity and rotation need a live acceptance test.

## Migrations, provisioning and release acceptance

Apply Alembic migrations using the separate schema-owner `CLOUDSAVER_MIGRATION_URL`. Runtime services use `CLOUDSAVER_DATABASE_URL` with the restricted application role. Do not run migrations as `cloudsaver_app` or weaken RLS to bypass a provisioning error.

The operator provisioning CLI seeds configured tenant, organization and subscription records. Subscription activation is an explicit step rather than an inference from possession of an ID. Billing routes must match the actual provisioned customer/organization relationship. Verify provisioning options with the shipped CLI and preserve its output as release evidence without secrets.

Before treating A–C as operationally accepted:

1. Apply all migrations against a disposable PostgreSQL instance and prove tenant isolation with the runtime role.
2. Provision two test tenants, confirm inactive subscriptions cannot be scanned, and verify a worker restart/duplicate-delivery scenario.
3. Verify valid and invalid Stripe signatures, duplicate events and reversed event ordering against test-mode fixtures or a controlled Stripe endpoint.
4. Verify Key Vault access, tenant mismatch rejection and secret rotation using a restricted test identity and vault.
5. Leave automated scanning and alerts disabled until the operator has approved the intended tenants, subscriptions and destination.

Unit tests and mocked integration tests support these checks but cannot replace external-service acceptance. Do not claim Stripe, Celery schedules or Key Vault have been exercised live unless the test report records that run.
