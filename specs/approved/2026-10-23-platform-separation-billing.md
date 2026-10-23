# Platform separation and billing ownership

**Status:** Approved
**Date:** Oct 23, 2026
**Approved:** Oct 23, 2026
**Author:** CloudSaver team
**Versions:** Platform 1.0.0 (new), CloudSaver 1.3.0
**Builds on:** `specs/approved/2026-10-23-platform-token-portal.md` (identity-service, `token-db`, platform
portal, directory projection, provider-scoped keys)

## Approval decisions

All 15 open questions are resolved with their recommended defaults (approved Oct 23, 2026). See
[Open questions](#open-questions) for each default and [Implementation notes](#implementation-notes) for how
they were applied.

## Request and assumptions

The user's request, verbatim: "I need the platform pprtal separate from the cloudsaver - I use platform portal to
provide keys and configure based on payment from clients - cloudsaver is for clients and fix the payment
integration in cloudsaver to lkink to olatform portal so for tracking stripe can be added later that just a
key".

This spec assumes:

1. **Separate means independently deployable, not a separate repository yet.** The platform (portal,
   identity-service, its database) gets its own directory, compose project, network, images, version and
   environment file. It stays in this repository for now (Open question 1).
2. **Platform operators record payments by hand today.** There is no customer-facing checkout. The portal is the
   system of record for plans, subscriptions and payments, and the plan decides what each workspace and key can
   do.
3. **CloudSaver stops owning billing.** It reads the plan and entitlements from the platform, enforces them,
   and links customers to a billing contact. It no longer talks to Stripe.
4. **"Stripe can be added later, just a key."** Turning Stripe on must only require configuring secrets
   (Stripe secret key and webhook secret) and setting a provider switch. No code change, migration or
   redeploy of CloudSaver.
5. **Platform operators are internal staff.** Customer self-service stays out of scope, as in the approved
   portal spec.

## Problem statement

- **The platform isn't separate.** `token-db`, `identity-migrate`, `identity-service`, `identity-import` and
  `platform-portal` live in CloudSaver's `compose.yaml` (project `cloudsaver`):
  - They share the `cloudsaver-python:1.2.0` image, the `x-environment` anchor, CloudSaver's Redis (logical DB 2
    for throttling and key-eviction pub/sub) and the default network.
  - The Python code is cross-imported. CloudSaver imports `identity.client` and `identity.keys.redact`.
    `identity/domain.py` imports `app.entitlements`, `app.cloud_scope` and `app.tenant_config`.
    `identity/app.py` imports `app.runtime`, and `identity/store_postgres.py` imports `database.connection`.
  - As a result, the platform can't be released, scaled, versioned or secured on its own. A CloudSaver
    rebuild also rebuilds the operator stack.
- **Billing lives in the customer product, and it's half-built.**
  - `app/entitlements.py` hard-codes the plan catalog (`TIER_LIMITS`: Starter, Growth, Enterprise). It also
    creates Stripe Checkout sessions (`create_checkout_session`, Growth only), gated by `checkout_configured()`
    (commit `1057732` hid the Growth checkout until Stripe is configured).
  - `services/billing.py` and `database/billing_store.py` take Stripe webhooks
    (`POST /api/v1/billing/webhook`, gateway to tenant-service). They write `stripe_*` columns on
    `public.organizations` and dedupe into `public.stripe_events` (migration `0002_billing`, forced RLS).
  - Stripe customer and price mapping comes from env JSON (`CLOUDSAVER_STRIPE_CUSTOMERS`,
    `STRIPE_PRICE_TIERS`) on tenant-service and scanner-service.
- **The plan has two owners, and payments aren't tracked anywhere.**
  - Operators set `plan_tier` per workspace in the portal (`directory.workspaces.plan_tier`), and Stripe
    webhooks overwrite `organizations.plan_tier` in CloudSaver. Nothing reconciles the two.
  - Most customers today pay by invoice, and there's nowhere to record that a customer paid, for which
    period, or what happens when payment lapses.
- **The dashboard implies self-service purchase.**
  - Settings > Billing & plan shows "Start Growth checkout" when checkout is configured, or "Online checkout
    isn't set up" otherwise.
  - Quota errors say "Upgrade to a higher tier", but customers can't upgrade themselves.

Note: `app/plan_policy.py` (Terraform plan guardrails), `app/pricing.py` (retail price estimates) and
`app/finops_api.py` with `app/focus.py` (FOCUS cloud-bill imports, "Billing evidence") aren't subscription
billing. They stay in CloudSaver unchanged.

## Proposed solution

1. **Platform product (1.0.0).**
   - Move `identity/`, `identity_migrations/`, `identity_db/`, `identity_alembic.ini` and `platform-portal/` into
     a top-level `platform/` directory with its own compose project, images, Redis, `.env`, tests and version.
   - Remove all Python imports between the two products. The platform gets its own copies of scope validation
     and the plan catalog. CloudSaver gets its own identity client.
2. **CloudSaver connects only through a contract.** CloudSaver reaches identity-service at a configured URL with
   a per-service caller token, over one shared external Docker network locally (private networking in Azure).
   It has no platform database credentials and no access to the platform's Redis.
3. **The platform owns billing.** A new `billing` schema in the platform database (today's `token-db`) holds:
   - **Plans:** the catalog and its entitlements.
   - **Subscriptions:** one current subscription per customer.
   - **Payments:** recorded manually now.
   - **Provider events:** webhook deduplication.

   A billing evaluator derives each customer's **billing state** (Active, Grace, Lapsed) and **effective
   entitlements**. It pushes them to every workspace of the customer through the directory change feed and the
   verify response, and constrains key issuance.
4. **CloudSaver enforces entitlements, doesn't sell plans.**
   - Quota and feature checks read the projected entitlements instead of `TIER_LIMITS`.
   - Checkout and the Stripe webhook are removed.
   - The dashboard shows the current plan, state and renewal date, plus a Manage billing link (a configurable
     URL) or "Contact your account manager".
5. **Stripe is a configuration switch.**
   - Billing providers sit behind a `BillingProvider` interface. `manual` is the default.
   - `stripe` ports the existing, tested `transition()` logic from `database/billing_store.py` into the
     platform. It turns on only when `PLATFORM_BILLING_PROVIDER=stripe` and both Stripe secrets resolve from
     Key Vault (or the untracked `.env` locally).
   - Webhooks arrive at the platform (portal route forwarded to identity-service) and update the same
     subscription and payment records.

### Decisions

| Topic | Decision |
| --- | --- |
| Repository | Same repository, `platform/` directory, separate compose project `platform`, images `zafin-platform-*`, own CI path filter. Separate repository later if teams split (Open question 1). |
| Code coupling | Zero imports across `platform/` and CloudSaver code, enforced by a test. Shared behavior is a versioned HTTP contract (`platform/contracts/identity-v1.md` plus JSON fixtures that both test suites load). |
| Cross-project network (local) | One external Docker network `platform-link` (internal, no egress) created by the platform project. Only `identity-service` and CloudSaver's key-verifying services join it. **Not** `host.docker.internal`, which would need a host port for identity-service and behaves differently on Linux (a loopback-bound host port isn't reachable from containers there). |
| Platform Redis | Its own `platform-redis` for throttling. CloudSaver gets cache evictions from an identity-service long-poll endpoint instead of subscribing to Redis. |
| Billing grain | One current subscription per **customer**. Every workspace of the customer inherits its plan (Open question 2). |
| Plan source of truth | `billing.subscriptions` → effective plan → `directory.workspaces.plan_tier` (now derived, not edited directly once billing is enabled) → projection → CloudSaver. |
| Lapse behavior | After `current_period_end` the subscription is in Grace for `grace_days` (default 14). After that it's Lapsed and the workspaces get the fallback plan (Starter by default), or are suspended if the operator chooses that setting (Open question 3). |
| Key issuance | Requires a customer billing state of Active or Grace (a $0.00 Starter subscription counts). Existing keys aren't revoked by billing changes, because entitlements and suspension already take effect at verify time (Open question 4). |
| Money | Integer minor units plus an ISO 4217 currency on every record. Displayed as `$1,200.00`, or `USD 1,200.00` in multi-currency lists. No FX conversion. |
| Stripe | Ported now and off by default. No Checkout or customer-portal sessions in this release. Stripe customer and price mapping moves from env JSON to database fields set in the portal. |
| Versioning | Platform 1.0.0. CloudSaver 1.3.0 (checkout and webhook were never enabled in production; removal is announced in the changelog). |

### Architecture

```text
 Customer browser ── :3000 web-dashboard ── api-gateway :8000 ─┬─ tenant / scanner / analytics / notification
                           (project: cloudsaver)                │  verify, change feed, events (long-poll)
                                                                ▼          network: platform-link (external)
 Operator browser ── :3100 platform-portal ── identity-service :8005 ── platform-db (internal network)
 Stripe (later) ──── /api/webhooks/stripe ──┘ (project: platform)   └── platform-redis (throttle)
```

## Detailed design

### Repository layout

```text
platform/
  compose.yaml            # project "platform"
  .env.example            # placeholders only
  Dockerfile              # zafin-platform-identity
  requirements.txt        # no CloudSaver dependencies
  identity/               # moved from /identity, plus identity/billing/
  identity_migrations/    # moved; adds i0002_billing
  identity_alembic.ini
  platform-db/            # moved from /identity_db (Dockerfile, init.sh)
  portal/                 # moved from /platform-portal
  contracts/              # identity-v1.md, fixtures/*.json
  scripts/setup_platform.py
  tests/
```

- `platform/` never gets an `__init__.py`, so it can't shadow the standard-library `platform` module. Platform
  code runs with `platform/` as its working directory (`import identity`). CloudSaver's `pytest.ini`
  `testpaths` excludes `platform/`.
- These move into `platform/identity/` as owned copies: `identity/domain.py`'s use of `app.cloud_scope`,
  `app.tenant_config` and `app.entitlements` (as `identity/validation.py` and `identity/billing/catalog.py`),
  `app.runtime.install_log_redaction` and `database.connection`.
- CloudSaver gets `app/identity_client.py` (moved from `identity/client.py`) and its own key-redaction regex in
  `app/runtime.py`.
- A test in each suite fails if any module imports across the boundary.

### Data model: platform database

The database stays the existing `token-db` (renamed to `platform-db` in compose, same volume). Migration
`i0002_billing` adds schema `billing`. All timestamps are `timestamptz` UTC. Every table has `version int` for
optimistic concurrency, plus `created_at`, `created_by`, `updated_at` and `updated_by`.

- **`billing.plans`**
  - Columns: `code varchar(16) PK` (`STARTER`, `GROWTH`, `ENTERPRISE`; new codes allowed, uppercase), `name
    varchar(60)`, `description varchar(300)`, `status ('active'|'retired')`, `list_price_minor bigint NULL`,
    `currency char(3) NULL`, `interval ('month'|'year'|'custom') NULL`, `entitlements jsonb`,
    `external_price_refs jsonb` (for example `{"stripe": ["price_…"]}`; each ref is unique across plans).
  - **Entitlements schema** (validated server-side; unknown keys rejected):
    - Carried over from `TIER_LIMITS`: `max_subscriptions` (cloud scopes; name kept for compatibility),
      `max_resources_per_scan`, `allowed_scan_frequencies`, `can_export_terraform`, `can_use_keyvault`,
      `can_dispatch_automated_alerts` and `retention_days`.
    - New: `allowed_providers` (subset of `azure`, `aws`, `gcp`, `kubernetes`), `max_workspaces`,
      `max_active_keys_per_workspace` (≤ 20, the existing hard cap) and `max_key_lifetime_days` (≤ 365).
  - Seeded from today's `TIER_LIMITS`, with every provider allowed. Plans are never deleted, only retired. A
    retired plan can't be assigned to new subscriptions.
- **`billing.subscriptions`**
  - Columns:
    - `id uuid PK`, `customer_id uuid FK directory.customers`, `plan_code FK plans`
    - `status ('trialing'|'active'|'past_due'|'canceled'|'expired')`, `provider ('manual'|'stripe')`
    - `external_subscription_ref varchar(255) NULL`, `current_period_start`, `current_period_end`,
      `cancel_at_period_end bool`, `canceled_at NULL`
    - `amount_minor bigint`, `currency char(3)`, `interval`, `grace_days smallint` (0–60, default from
      settings), `entitlement_overrides jsonb NULL` (same schema as plan entitlements, partial),
      `notes varchar(500)`
    - Stripe watermark columns ported from `organizations`: `provider_event_created`,
      `provider_invoice_event_created`, `provider_subscription_created`
  - A partial unique index allows at most one subscription per customer whose status isn't `canceled` or
    `expired`.
- **`billing.payments`**
  - Columns:
    - `id uuid PK`, `customer_id FK`, `subscription_id FK NULL`
    - `amount_minor bigint > 0`, `currency char(3)`, `status ('pending'|'paid'|'failed'|'refunded'|'void')`
    - `method ('bank_transfer'|'card'|'check'|'other')`, `reference varchar(80)` (invoice number or
      remittance reference; unique per customer when not void), `invoice_date date NULL`, `due_date date NULL`,
      `paid_at timestamptz NULL` (required when `paid`)
    - `period_start date`, `period_end date` (`period_end` ≥ `period_start`), `provider`,
      `external_payment_ref varchar(255) NULL` (unique), `notes varchar(500)`
    - `void_reason NULL`, `voided_by NULL`, `voided_at NULL`
  - Rows are never deleted. They're voided instead.
  - Free text is rejected if it contains a 13–19-digit sequence that passes the Luhn check, so card numbers
    can't be stored.
- **`billing.provider_events`**: `(provider, event_id) PK`, `event_type`, `event_created bigint`,
  `customer_id NULL`, `outcome varchar(64)`, `received_at`. It replaces `public.stripe_events`, is append-only
  and is kept for 400 days.
- **`billing.settings`** (single row):
  - `default_plan_code` (used when a customer has no subscription; default `STARTER`), `default_grace_days`
    (14) and `lapsed_action ('downgrade'|'suspend')` (default `downgrade`)
  - `lapsed_plan_code` (`STARTER`), `default_manage_billing_url NULL` (https only) and
    `require_subscription_for_keys bool` (default true)
- **`directory.customers` gains**:
  - `billing_contact_email NULL` and `manage_billing_url NULL` (https only, no credentials, query or fragment;
    the same rules as today's `checkout_configured`)
  - `external_customer_refs jsonb` (for example `{"stripe": "cus_…"}`; unique per provider)
  - `billing_state ('active'|'grace'|'lapsed'|'none')` and `billing_state_changed_at`, both derived and stored
    for listing and filtering
- **`directory.workspaces.plan_tier`** stays (verify and projection keep working) but is written only by the
  billing evaluator when `PLATFORM_BILLING_ENABLED=true`. A new `entitlements jsonb` column holds the
  effective entitlements, and `entitlements_version int` increments on change.
- **`directory_changes.change_type` gains `entitlements_changed`.** The snapshot already contains the full
  workspace, now including `plan`.
- **`identity.key_events` actions gain**: `plan_created`, `plan_updated`, `plan_retired`,
  `subscription_created`, `subscription_changed`, `subscription_canceled`, `payment_recorded`,
  `payment_updated`, `payment_voided`, `billing_state_changed`, `entitlements_changed`,
  `billing_settings_updated` and `provider_event_applied`. `actor_type` gains `provider`. The table stays
  append-only.
- **`identity.cache_events(seq bigserial PK, tenant_id NULL, key_id NULL, event, occurred_at)`** feeds the
  long-poll eviction endpoint. It's written in the same transaction as the change and kept for 24 hours.
- **Roles.** `identity_app` gets `SELECT`, `INSERT` and `UPDATE` on `billing.*` except `provider_events`, which
  gets `INSERT` and `SELECT` only. There's no `DELETE` on any billing table, and `identity_retention` may
  delete only expired `provider_events` and `cache_events` rows.

**Billing evaluator** (in identity-service; runs every 5 minutes and on every billing write; idempotent):

| Subscription | Billing state | Effective plan |
| --- | --- | --- |
| None | `none` | `default_plan_code`. Key issuance is blocked if `require_subscription_for_keys`. |
| `trialing` or `active`, before `current_period_end` | `active` | Subscription plan plus overrides |
| `active` or `past_due`, after period end, within `grace_days` | `grace` | Subscription plan plus overrides |
| After grace, or `canceled` or `expired` after period end | `lapsed` | `lapsed_plan_code` (downgrade) or workspaces suspended (suspend) |

- A manual payment recorded as `paid` with **Extend subscription to the end of this period** checked sets
  `current_period_end = max(current, payment.period_end)`. It also sets `status='active'`.
- Voiding or refunding that payment re-runs the evaluator but never shortens a period automatically. The
  operator edits the period explicitly.
- When a workspace's effective entitlements or plan change, the evaluator:
  - updates `directory.workspaces`
  - writes `directory_changes` (`entitlements_changed`) and `cache_events` (tenant eviction)
  - records `billing_state_changed` or `entitlements_changed`
- Effective key providers become key ∩ workspace configured ∩ plan `allowed_providers`.
- Suspension through `lapsed_action=suspend` uses the existing workspace suspend path, with actor `system`.
  Reactivation is automatic when the state returns to `active`, but only for workspaces the evaluator
  suspended (`suspended_by='billing'`).

### Data model: CloudSaver database

- **Migration `0013_billing_projection`** (after the planned `0012_drop_registry_keys`):
  - Adds `tenant_registry.entitlements jsonb NULL`, `entitlements_version int`, `billing_state varchar(8)`,
    `plan_name`, `current_period_end NULL`, `grace_ends_at NULL` and `manage_billing_url NULL`. These are
    written only by the projector.
  - Revokes `INSERT` on `public.stripe_events` from `cloudsaver_app`, which makes the table read-only.
  - The `stripe_*` columns on `organizations` stay readable for export. `organizations.plan_tier` keeps being
    maintained by `_sync_domain` for workers.
- **Migration `0014_drop_local_billing`** (removal phase, at least 30 days after the billing import is
  verified):
  - Drops `public.stripe_events`, the nine-column set from `0002_billing` except `organizations.plan_tier` and
    its check constraint, and `uq_organizations_stripe_customer`.
  - Its `downgrade()` re-creates the empty structures only. The data lives in the platform.
- **Unaffected:**
  - **Outbox and delivery:** no outbox event types are billing-related (`database/outbox.py`,
    `workers/dispatcher.py`).
  - **FOCUS billing evidence:** `public.focus_*` and the `/api/v1/finops/*` routes stay as they are. To avoid
    confusing the two kinds of billing, dashboard copy calls them "Cloud billing data". "Plan" means the
    CloudSaver subscription.
- **RLS** is unchanged. Every tenant table keeps forced RLS. `tenant_registry` stays a non-RLS projection, and
  entitlements aren't secret.

### APIs

#### Platform admin API (identity-service, called by the portal server)

Authentication and authorization match the approved spec: an Entra token, with `PlatformOperator` for writes
and `PlatformAuditor` for `GET`. Every write requires `version` where one applies (`409` on a stale version),
records `key_events` and returns `Cache-Control: no-store`. Amounts are `{amount_minor, currency}`.

| Method | Path | Purpose |
| --- | --- | --- |
| GET / POST | `/admin/v1/plans` | List or create a plan |
| GET / PATCH | `/admin/v1/plans/{code}` | View, or edit name, description, price, entitlements or external price refs. The response includes affected customer and workspace counts. |
| POST | `/admin/v1/plans/{code}/retire` | Retire a plan, which blocks new subscriptions to it |
| GET | `/admin/v1/billing/customers?billing_state=&plan=&renews_before=&cursor=` | Billing overview across customers |
| GET / POST | `/admin/v1/customers/{id}/subscriptions` | History, or create the current subscription `{plan_code, status, current_period_start, current_period_end, amount_minor, currency, interval, grace_days?, entitlement_overrides?, notes?}` |
| GET / PATCH | `/admin/v1/subscriptions/{id}` | View, or change plan, period, amount, grace, overrides or notes (`provider='stripe'` subscriptions allow only notes and overrides) |
| POST | `/admin/v1/subscriptions/{id}/cancel` | `{at_period_end: bool, reason}` |
| GET / POST | `/admin/v1/customers/{id}/payments` | List, or record a payment `{subscription_id?, amount_minor, currency, status, method, reference, invoice_date?, due_date?, paid_at?, period_start, period_end, notes?, extend_period: bool}` |
| PATCH | `/admin/v1/payments/{id}` | Change status (`pending` → `paid`/`failed`, `paid` → `refunded`), dates or notes |
| POST | `/admin/v1/payments/{id}/void` | `{reason}` |
| GET | `/admin/v1/customers/{id}/entitlements` | Effective plan, billing state and entitlements per workspace, with the source (plan, override, fallback) of each value |
| PATCH | `/admin/v1/customers/{id}` | Gains `billing_contact_email`, `manage_billing_url` and `external_customer_refs` |
| GET / PUT | `/admin/v1/billing/settings` | Billing settings. `GET` also returns `provider: {name: "manual"\|"stripe", configured: bool, webhook_url}` with no secret values. |

**Changed behavior:**

- **`PATCH /admin/v1/workspaces/{tenant_id}` with `plan_tier`:** returns `409` "This workspace's plan comes
  from the customer's subscription. Change it on the customer's Billing tab." when billing is enabled.
- **`POST /admin/v1/workspaces/{tenant_id}/keys` and rotate:**
  - Return `402` "This customer doesn't have an active subscription. Create a subscription or record a
    payment before you issue keys." when issuance is blocked.
  - Enforce `max_active_keys_per_workspace` and `max_key_lifetime_days`.
- **`POST /admin/v1/workspaces`:** enforces `max_workspaces`.

#### Webhook

- `POST /billing/v1/webhooks/{provider}` on identity-service. It's reached only through the portal route
  `POST /api/webhooks/stripe`, which needs no session or CSRF check, passes the raw bytes and the
  `Stripe-Signature` header, limits the body to 1 MiB and is rate-limited per IP.
- Signature verification happens only in identity-service, which is the only component holding the webhook
  secret.
- Responses:
  - `503` "Stripe isn't configured" when the provider is off
  - `400` for an invalid signature or payload
  - `200 {"outcome": "duplicate"}` for a known event ID
  - `503` on a persistence failure, so Stripe retries
- Handled events (same set as today): `customer.subscription.created`, `customer.subscription.updated`,
  `customer.subscription.deleted` and `invoice.payment_succeeded`.
  - Subscription events upsert `billing.subscriptions` (`provider='stripe'`).
  - Paid invoices insert `billing.payments` (`status='paid'`, `external_payment_ref=in_…`).
  - Customer and price mapping come from `external_customer_refs` and `external_price_refs`. Unknown
    customers return `400`. Unknown or ambiguous prices map to the default plan, recorded as
    `unknown_price_default`.

**Provider interface** (`platform/identity/billing/providers/`):

```python
class BillingProvider(Protocol):
    name: str
    def configured(self) -> bool: ...
    def parse_webhook(self, body: bytes, headers: Mapping[str, str]) -> ProviderEvent: ...  # verifies signature
    def apply(self, event: ProviderEvent, state: CustomerBillingState) -> list[BillingChange]: ...
```

- `ManualProvider` has no webhook. `configured()` is always true.
- `StripeProvider` is a port of `transition()`, `validate_event()` and `invoice_subscription()`, with their
  existing tests. `configured()` requires `PLATFORM_STRIPE_SECRET_KEY` and `PLATFORM_STRIPE_WEBHOOK_SECRET`
  from Key Vault (`platform-stripe-secret-key`, `platform-stripe-webhook-secret`) or the untracked local
  `.env`.
- Identity-service refuses to start when `PLATFORM_BILLING_PROVIDER=stripe` but the secrets are missing.
- Neither secret is ever logged, returned or stored in the database. The `stripe` Python package moves from
  CloudSaver's `requirements.txt` to the platform's.

#### Internal API (CloudSaver → identity-service)

- **`POST /internal/v1/keys/verify`** gains a `plan` block. The addition is backward compatible, and the
  contract version stays `v1`.

  ```json
  "plan": {
    "code": "GROWTH",
    "name": "Growth",
    "billing_state": "active",
    "current_period_end": "2026-11-30T00:00:00Z",
    "grace_ends_at": null,
    "entitlements_version": 7,
    "entitlements": {
      "max_subscriptions": 10, "max_resources_per_scan": 2500,
      "allowed_scan_frequencies": ["manual", "daily"], "can_export_terraform": true,
      "can_use_keyvault": false, "can_dispatch_automated_alerts": true, "retention_days": 90,
      "allowed_providers": ["azure", "aws", "gcp", "kubernetes"]
    },
    "manage_billing_url": null
  }
  ```

  Payment amounts, references and contact emails are never sent to CloudSaver.
- **`GET /internal/v1/directory/changes` and `/snapshot`:** each workspace snapshot includes the same `plan`
  block. The projector writes it to the new `tenant_registry` columns, and `_sync_domain` keeps
  `organizations.plan_tier` in step.
- **New `GET /internal/v1/events?after=<seq>&wait=25`** (callers: every verifying service):
  - Long-polls `cache_events`. It returns up to 500 events, or an empty list after `wait` seconds.
  - It replaces the Redis subscription in the client. The 30-second cache cap still bounds staleness if the
    poll fails.
  - If `after` is older than retention, the response is `410` and the client flushes its cache.

#### CloudSaver API changes (1.3.0)

| Endpoint | Change |
| --- | --- |
| `POST /api/v1/billing/checkout` (gateway, scanner) | Removed. Returns `410` "Plan changes are handled by your account manager." in 1.3.x, then `404` in 1.4.0. |
| `POST /api/v1/billing/webhook` (gateway, tenant) | Removed. Returns `410` "Billing webhooks are handled by the platform." in 1.3.x, then `404`. `services/billing.py`, `database/billing_store.py` and `BillingCheckoutRequest` are deleted. |
| `GET /api/v1/billing/entitlements` | Keeps the path. Removes `checkout_available` and adds `plan_name`, `billing_state`, `current_period_end`, `grace_ends_at`, `manage_billing_url`, `max_resources_per_scan`, `allowed_scan_frequencies` and `allowed_providers`. Values come from the verify `plan` block, or the projection in Entra mode and for workers. |
| `GET /api/v1/me` | Adds `plan_name` and `billing_state` (`plan_tier` is unchanged). |
| Quota and feature errors | `402` "Your {plan} plan allows up to {n} cloud scopes. Contact your account manager to change your plan." and `403` "Terraform review is available on plans that include it. Contact your account manager." |

- `app/entitlements.py` keeps `TierEntitlements` as the type. `get_tier_entitlements(name)` is replaced by
  `entitlements_for(tenant)`, which reads the projected or verified entitlements.
- The static `TIER_LIMITS` table is used only when a workspace has no projected entitlements (before platform
  1.0.0 is deployed). In that case the service logs `entitlements_fallback` once per workspace.
- `workers/tasks.py`, `workers/storage.py`, `workers/dispatcher.py` (which hard-codes `GROWTH`/`ENTERPRISE`),
  `app/jobs_api.py`, `app/main.py` and `app/settings_api.py` switch to entitlement fields.
- `create_checkout_session`, `checkout_configured` and `_verify_customer` are deleted.
- Env vars removed from CloudSaver compose and `.env.example`: `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`,
  `CLOUDSAVER_STRIPE_CUSTOMERS`, `STRIPE_PRICE_TIERS` and `CLOUDSAVER_BILLING_RETURN_URL`.

### UI changes

All text follows the Zafin UX writing rules: sentence case, American English, `Oct 23, 2026`, `9:00 AM`,
`$1,200.00`. Billing states are shown as Active, Trial, Grace period, Lapsed, Canceled and No subscription.

#### Platform portal

- **Navigation:** Customers, Workspaces, Billing (new), Plans (new), Activity, Security, Settings.
- **Billing:**
  - Table columns: Customer, Plan, Status, Renews, Last payment, Amount.
  - Filters: Status, Plan, Renews before.
  - Row example: "Acme Corp · Growth · Active · Nov 30, 2026 · Oct 28, 2026 · $1,200.00 per month".
- **Customer details** gets a **Billing** tab:
  - **Subscription card:** plan, status, period ("Oct 1 – Nov 30, 2026"), amount, grace period and provider
    (Manual or Stripe).
    - Actions: Create subscription, Change plan, Edit, Cancel subscription.
    - Cancel offers "At the end of the current period" (the default) or "Now", and a reason is required.
  - **Payments** table:
    - Columns: Reference, Period, Amount, Status, Paid on, Method, Recorded by. A row's "Recorded by" reads,
      for example, "Oct 28, 2026, by Priya Patel".
    - Actions: Record payment, Edit, Void.
  - **Entitlements:** per-feature table with Value and Source (Plan, Override, Fallback), and Edit overrides.
  - **Billing contact:** Billing email, Manage billing link, Stripe customer ID (shown only when Stripe is
    configured).
- **Record payment dialog:**
  - Fields: Amount, Currency (USD default), Billing period (start and end), Invoice or reference, Invoice date,
    Due date, Status (Paid, Pending, Failed), Paid on (required for Paid), Method (Bank transfer, Card, Check,
    Other), Notes.
  - Checkbox: "Extend subscription to the end of this period" (on by default for Paid).
  - Helper text: "Don't enter card numbers. Use the invoice or remittance reference."
  - Button: Record payment.
- **Void payment dialog:**
  - Title "Void this payment?" with "Voided payments stay in the history and no longer extend the
    subscription."
  - A reason is required. Destructive button: Void payment.
- **Change plan dialog:**
  - Shows a preview: "3 workspaces move from Starter to Growth. Changes apply within 30 seconds."
  - Button: Change plan.
- **Plans:**
  - Table columns: Plan, Price, Customers, Status.
  - The Edit plan dialog lists each entitlement with a plain label ("Cloud scopes per workspace", "Resources
    per scan", "Scan frequencies", "Terraform review", "Automatic alerts", "Retention (days)", "Cloud
    providers", "Workspaces per customer", "Active keys per workspace", "Maximum key lifetime (days)").
  - Saving shows "This change applies to 12 customers within 30 seconds."
  - Button: Save changes. Actions: Create plan, Retire plan.
- **Settings > Billing:**
  - **Payment provider:** "Manual" or "Stripe". Status reads "Stripe isn't configured. To enable it, add the
    Stripe secret key and webhook secret to Key Vault and restart the identity service." When Stripe is
    configured, the webhook URL is shown for copying.
  - **Grace period (days)** and **After the grace period** (Downgrade to Starter, Suspend workspaces).
  - **Default manage billing link** and **Require a subscription to issue keys**.
- **Workspaces:**
  - Plan is shown read-only, with "Set by the customer's subscription".
  - Issue key is disabled with "This customer doesn't have an active subscription." when issuance is blocked.
- **Activity** lists billing actions, for example "Recorded payment INV-1042 for $1,200.00 · Oct 28, 2026 at
  9:00 AM, by Priya Patel".

#### CloudSaver dashboard

- **Settings tab:** "Billing & plan" becomes **Plan**.
  - **Content:** "Your current plan" with the plan name and status badge, plus "Renews on Nov 30, 2026" (or
    "Ended on Nov 30, 2026"). It also shows usage (cloud scopes used of allowed), included features (Included
    or Not included) and the retention allowance.
  - **Action:** **Manage billing** opens `manage_billing_url` in a new tab (`rel="noopener noreferrer"`, https
    only) when one is set. Otherwise the tab shows "To change your plan, contact your account manager."
  - **Removed:** "Start Growth checkout", the checkout popup logic in `WorkspaceProvider.checkout`, the
    `checkout.stripe.com` check, `checkout_available` and the `billing/checkout` path in the proxy route
    allowlist (`web-dashboard/app/api/[...path]/route.ts`).
- **Banners** (all roles; dismissible per session):
  - Grace: "Your payment is past due. Growth features stay available until Dec 14, 2026. Contact your account
    manager."
  - Lapsed with downgrade: "Your Growth plan ended on Dec 14, 2026. Starter limits now apply."
  - Lapsed with suspend: this uses the existing 403 "This workspace is suspended. Contact your CloudSaver
    administrator."
- **Feature gates:**
  - Controls for features the plan doesn't include (Terraform review publish, daily or hourly schedule, Key
    Vault) stay visible but disabled, with "Not included in your plan."
  - Providers outside `allowed_providers` stay hidden, the same as provider-scoped keys.
- **Terminology:** "Billing evidence" becomes "Cloud billing data" where it refers to FOCUS imports.

### Deployment and compose

**`platform/compose.yaml`** (project `platform`):

```yaml
name: platform
services:
  platform-db:          # was token-db; image zafin-platform-db:1.0.0; networks [platform-db]
  identity-migrate:     # zafin-platform-identity:1.0.0; networks [platform-db]
  identity-service:     # zafin-platform-identity:1.0.0; networks [platform-db, platform-internal, platform-link]; no host port
  platform-redis:       # redis:7-alpine; networks [platform-internal]; no host port
  platform-portal:      # zafin-platform-portal:1.0.0; networks [platform-internal, portal-edge]; ports ['127.0.0.1:3100:3100']
networks:
  platform-db: {internal: true}
  platform-internal: {internal: true}
  portal-edge: {}       # egress for Entra sign-in only
  platform-link: {name: platform-link, internal: true}
volumes:
  platform-db-data: {name: cloudsaver_token-db-data}   # reuse the existing volume; no dump/restore
```

**CloudSaver `compose.yaml`:**

- Removes `token-db`, `identity-migrate`, `identity-service`, `identity-import`, `platform-portal`, the
  `identity-db`, `portal` and `portal-edge` networks, and the `token-db-data` volume declaration. Removing the
  declaration doesn't delete the volume.
- Declares `platform-link: {external: true}`. Only `api-gateway`, `tenant-service`, `scanner-service`,
  `analytics-service` and `notification-service` join it, as well as `default`.
- `depends_on: identity-service` is removed. Startup ordering is handled by `make up`, which starts the
  platform first, and services keep failing closed (`503`) until verify answers.
- `CLOUDSAVER_IDENTITY_URL` becomes configurable, with `http://identity-service:8005` as the default.
  `CLOUDSAVER_IDENTITY_REDIS_URL` is removed.
- **Caller tokens.** CloudSaver's `scripts/setup_compose.py` generates the per-service caller tokens into
  CloudSaver's untracked `.env` and prints only their SHA-256 digests. `platform/scripts/setup_platform.py
  --add-callers` writes those digests to `PLATFORM_IDENTITY_CALLERS` in the platform's untracked `.env`. The
  portal's own caller token is generated by the platform script.
- **Ports and binding.** Everything stays loopback-only: dashboard `127.0.0.1:3000`, gateway `127.0.0.1:8000`,
  portal `127.0.0.1:3100`. The platform database, Redis and identity-service publish no host ports.
- **Environment.** Platform variables use a `PLATFORM_*` prefix. Identity-service also accepts the current
  `CLOUDSAVER_*` names for one release (1.0.x) and logs a deprecation notice. The `cs_live_`/`cs_test_` key
  format and the Entra audience `api://cloudsaver-identity` don't change.
- **`identity-import`** is retired from both projects (cutover is done). The billing import below is a
  file-based job, so neither product needs the other's database.
- **Make targets:** `make platform-up` and `make platform-down` (project `platform`), `make up` (platform first,
  then CloudSaver) and `make link-platform` (callers and network check).
- **Azure.**
  - The platform is its own Container Apps environment (or AKS namespace) with its own managed identities.
  - CloudSaver reaches identity-service over private networking (VNet peering or private endpoint), never the
    public internet.
  - Only the portal's `/api/webhooks/*` path is publicly routable when Stripe is enabled. The rest of the
    portal stays behind Entra and the operator network policy.

### Security

- **Secrets.**
  - Stripe secret key, webhook secret, pepper and database passwords come from Key Vault in Azure, and from
    the untracked `.env` locally.
  - `.env.example` files contain empty placeholders only. No values that look like real keys appear anywhere.
  - CloudSaver holds no billing secrets after 1.3.0.
- **Isolation.**
  - The platform database is reachable only by identity-service and its migration job.
  - `platform-link` is internal and carries only identity-service and the CloudSaver callers. A compose test
    asserts that CloudSaver services have no platform database URL, platform Redis URL, Stripe variable or
    `platform-db` network.
- **Least privilege.**
  - There's no `DELETE` on billing tables.
  - Payments are voided, not deleted.
  - `provider_events` are append-only.
- **Audit.** Every billing change records `key_events`, with the operator from Entra, or `provider:stripe`
  and the event ID for webhook changes. Amounts are included in details; references are included; card data
  is never present and is rejected on input.
- **Data minimization.** CloudSaver receives only plan, state, dates, entitlements and the manage-billing URL,
  never payment amounts, references or contact emails.
- **Webhook hardening.**
  - Verification uses raw bytes with a 300-second signature tolerance.
  - Bodies are limited to 1 MiB, and events are deduplicated by ID.
  - Tenant ownership never comes from Stripe metadata, only from database mapping, as today.
  - A persistence failure returns `503` so Stripe retries.
- **Fail closed.** If identity-service is unreachable, CloudSaver keeps returning `503` (unchanged). Workers
  (scheduler and dispatcher) use the last projected entitlements, which is safe because the projection only
  changes through the feed.
- **RLS.** CloudSaver tenant tables keep forced RLS. `0013` and `0014` don't touch any RLS policy except the
  `stripe_events` policy, which is dropped together with the table.

### Migration of existing billing data

1. **Export (CloudSaver).**
   - `scripts/export_billing.py` (new, read-only, run in the `migrate` container) writes
     `billing-export.json`. For each organization it includes `tenant_id`, `plan_tier`,
     `stripe_customer_id`, `stripe_subscription_id`, status and watermarks. It also includes the
     `stripe_events` IDs and outcomes.
   - The file contains identifiers only, no secrets. It's written to a temporary path and never committed.
2. **Import (platform).** `python -m identity.billing.importer billing-export.json`, idempotent:
   - **Customer resolution:** `tenant_id` → `directory.workspaces.customer_id`.
   - **Stripe subscription present:** creates a `provider='stripe'` subscription with the mapped status and
     watermarks, and sets `external_customer_refs.stripe`. It's read-only in the portal until Stripe is
     configured.
   - **Otherwise:** creates a `manual` subscription. The plan comes from `directory.workspaces.plan_tier`, the
     current operator-set value, which wins over `organizations.plan_tier` on conflict and is reported. The
     amount is `0`, the status `active`, and `current_period_end` is 30 days out, so operators review and
     record real terms within the grace window.
   - **Stripe events:** event IDs are inserted into `billing.provider_events`, so replays can't double-apply.
   - **Report:** the job prints counts and conflicts by `tenant_id` only.
3. **Verify.**
   - Every workspace's effective plan after import equals its pre-import `plan_tier` (the import report shows
     zero differences, or each one is listed and explained).
   - Operators complete subscription terms.
4. **Remove.** Apply `0014_drop_local_billing` at least 30 days after step 3.

**Backward compatibility:**

- **Platform 1.0.0 additions are additive.** CloudSaver 1.2.0 ignores the `plan` block, so the platform can
  ship first.
- **CloudSaver 1.3.0 works with or without the block.** Without it, the service falls back to projected
  `plan_tier` and `TIER_LIMITS`.
- **Event transport.** The long-poll events endpoint and Redis pub/sub both run during 1.0.x, so either
  CloudSaver version gets evictions.

### Rollout

1. **Phase 0, prerequisites.**
   - Key Vault secrets for the platform.
   - The `platform-link` network.
   - The Azure platform environment and private connectivity.
   - The Stripe Dashboard webhook endpoint stays disabled until Phase 5.
2. **Phase 1, repository split (no behavior change).**
   - Move the code to `platform/` and remove the cross-imports.
   - Add `platform/compose.yaml`, which reuses the existing volume, and the `platform-redis` service.
   - Remove the platform services from CloudSaver compose and join `platform-link`.
   - Add the long-poll events endpoint with dual publishing (Redis and `cache_events`).
   - **Exit criteria:** both suites are green, the boundary import test passes, and a sign-in, revoke and
     rotate run works across the two projects.
3. **Phase 2, platform billing (platform 1.0.0, `PLATFORM_BILLING_ENABLED=false`).**
   - Migration `i0002_billing`, plan seed, admin API and portal screens, the evaluator in dry-run mode
     (computes and logs, writes nothing), and the verify and snapshot `plan` block (with values from today's
     `plan_tier`).
4. **Phase 3, data import and enablement.**
   - Export and import as described above.
   - Set `PLATFORM_BILLING_ENABLED=true`. Workspace `plan_tier` is now derived from subscriptions.
   - **Exit criterion:** zero unexplained plan differences.
5. **Phase 4, CloudSaver 1.3.0.**
   - Ships entitlement-driven enforcement, `0013_billing_projection`, `410` on checkout and webhook, the
     dashboard Plan tab, banners and feature gates, and Stripe variable removal.
   - Remove the Stripe webhook endpoint from the Stripe Dashboard before deploying.
   - **Rollback:** redeploy 1.2.0. Its checkout stays hidden because `STRIPE_SECRET_KEY` is no longer set.
6. **Phase 5, optional: Stripe.**
   - Add the Key Vault secrets and set `PLATFORM_BILLING_PROVIDER=stripe`.
   - Point the Stripe webhook to `https://<portal>/api/webhooks/stripe` and set Stripe IDs per customer and
     plan in the portal.
   - No code change or CloudSaver deploy is needed.
7. **Phase 6, removal (30 days or more after Phase 3).**
   - Apply `0014_drop_local_billing`.
   - Remove the `410` stubs (CloudSaver 1.4.0), the `CLOUDSAVER_*` platform env fallbacks (platform 1.1.0)
     and Redis pub/sub publishing.

## Acceptance criteria

- [ ] `platform/` builds and runs with `docker compose -p platform` alone. CloudSaver builds and runs with its own
      compose file, and neither file defines the other's services.
- [ ] No Python module under `platform/` imports `app`, `services`, `workers` or `database`, and no CloudSaver
      module imports `identity`. Both suites enforce this with a test.
- [ ] Platform images are versioned `1.0.0` and CloudSaver images `1.3.0`. Each has its own changelog entry and
      `.env.example` with placeholders only.
- [ ] Locally, CloudSaver services reach identity-service only over `platform-link`. Identity-service, the
      platform database and the platform Redis publish no host ports. Every published port binds `127.0.0.1`.
- [ ] CloudSaver containers have no platform database URL, platform Redis URL or Stripe variables (compose test).
- [ ] Existing workspace keys, revocation (within 30 seconds, and within 2 seconds when the events endpoint is
      healthy), suspension and provider-scoped keys behave exactly as before the split.
- [ ] Existing `token-db` data is preserved across the split without a dump and restore.
- [ ] Operators can create and retire plans, edit entitlements, create, change and cancel a customer
      subscription, and record, edit and void payments with amount, currency, period, status,
      reference, paid date and method. Every change is audited.
- [ ] A plan or subscription change updates every workspace of the customer in CloudSaver (`/api/v1/me`,
      `/api/v1/billing/entitlements`, enforcement) within 30 seconds.
- [ ] A paid payment with "Extend subscription to the end of this period" moves the renewal date. After the
      period plus grace, the customer becomes Lapsed and its workspaces get the fallback plan, or are suspended
      when `lapsed_action=suspend`, and recover automatically when a new payment is recorded.
- [ ] Key issuance and rotation return `402` without an Active or Grace subscription when
      `require_subscription_for_keys` is on, and respect the plan's key count and lifetime limits.
- [ ] A plan whose `allowed_providers` excludes AWS removes AWS from every key's effective grant at verify time.
- [ ] CloudSaver has no Stripe code, dependency or env variables. `POST /api/v1/billing/checkout` and
      `/api/v1/billing/webhook` return `410` in 1.3.x.
- [ ] CloudSaver quota and feature checks (scans, scan jobs, schedules, alerts, Terraform export, Key Vault) read
      projected or verified entitlements, and none reference `TIER_LIMITS` except the documented fallback.
- [ ] The dashboard Plan tab shows plan, state, renewal date, usage and features, plus Manage billing (when a
      URL is set) or "To change your plan, contact your account manager." No checkout UI remains.
- [ ] Grace and lapsed banners and the "Not included in your plan" gates appear with the specified text.
- [ ] With `PLATFORM_BILLING_PROVIDER=manual`, the webhook returns `503`. With Stripe secrets configured and the
      switch set, the ported Stripe tests pass against the platform tables (signature, dedupe, out-of-order
      events, unknown price, untracked deletion), and identity-service refuses to start if the switch is set
      without secrets.
- [ ] The billing import reproduces every workspace's current plan with zero unexplained differences, and
      imported Stripe event IDs aren't re-applied.
- [ ] Payment notes and references that contain a Luhn-valid card number are rejected.
- [ ] No secret appears in logs, audit details, API responses or committed files (log-scan test extended to Stripe
      key and webhook-secret formats).
- [ ] Portal and dashboard text follows the UX writing, date, time and currency formatting rules.

## Out of scope

- A separate git repository for the platform. The layout is designed so that a later move is a `git subtree
  split`.
- Stripe Checkout, Stripe customer-portal sessions, payment links and any customer self-service purchase.
- Invoice generation or PDFs, tax, dunning emails, proration, refunds through a provider, usage-based or
  metered billing, and FX conversion.
- Billing for products other than CloudSaver (a multi-product catalog).
- Customer-facing workspace or key management (unchanged from the approved portal spec).
- Changes to FOCUS cloud billing data (`/api/v1/finops/*`), other than the label.
- Production infrastructure-as-code beyond the networking requirements stated here.

## Open questions

All open questions are resolved: the recommended default of each question below was approved on Oct 23, 2026.

1. **Same repository or separate repository?** **Default:** same repository, `platform/` directory, separate
   compose, images, version and CI path filters. Revisit when a separate team owns the platform.
2. **Subscription per customer or per workspace?** **Default:** per customer, and all its workspaces inherit
   the plan. Per-workspace differences use `entitlement_overrides` only.
3. **What happens after the grace period?** **Default:** a 14-day grace period, then downgrade to Starter
   (keys keep working with Starter limits). Suspension is an opt-in setting.
4. **Should payment gate key issuance, and should key expiry follow the billing period?** **Default:** gate
   issuance and rotation on an Active or Grace subscription. Don't tie key expiry to the billing period,
   because downgrade and suspension take effect at verify time and are reversible.
5. **Can customers without a subscription use Starter for free?** **Default:** yes, through
   `default_plan_code=STARTER`. Key issuance still needs a subscription (a $0.00 Starter subscription is fine)
   while `require_subscription_for_keys` is on.
6. **Where does Manage billing point?** **Default:** a per-customer `manage_billing_url`, falling back to the
   platform default, or no button and the contact text. Https only.
7. **Port the Stripe provider now or later?** **Default:** port it now, disabled. It's existing, tested code,
   and it makes "Stripe is just a key" true. Don't build Checkout.
8. **Webhook ingress.** **Default:** through the portal route `/api/webhooks/stripe`, with only that path
   public in production. The alternative is a dedicated public `billing-webhook` service, if the portal must
   never be internet-routable.
9. **Cross-project networking locally.** **Default:** the external `platform-link` network. The alternative,
   `host.docker.internal` with identity-service published on `127.0.0.1:8005`, works on Docker Desktop but
   not on Linux, and adds a host port.
10. **Cache eviction transport.** **Default:** the identity-service long-poll endpoint. CloudSaver never
    connects to the platform Redis.
11. **Environment variable prefix.** **Default:** `PLATFORM_*` for platform services, with `CLOUDSAVER_*`
    accepted during 1.0.x. Keep the `cs_` key prefix and the Entra audience.
12. **Versions.** **Default:** platform 1.0.0 and CloudSaver 1.3.0, as a minor version because checkout and
    the webhook were never enabled in production. Use 2.0.0 instead if any external integrator calls the
    billing endpoints.
13. **Separation of duties for billing.** **Default:** no new role. `PlatformOperator` manages billing and
    `PlatformAuditor` reads it. Add a `PlatformBillingAdmin` app role if finance staff shouldn't issue keys.
14. **Retention of billing records.** **Default:** plans, subscriptions, payments and audit are kept
    indefinitely (finance records). Provider events are kept for 400 days and cache events for 24 hours.
15. **Rename `token-db`.** **Default:** rename the service to `platform-db` in compose, and keep the volume
    name `cloudsaver_token-db-data` until a planned maintenance window.

## Dependencies

- `specs/approved/2026-10-23-platform-token-portal.md` (implemented in 1.2.0). This spec supersedes its
  compose layout, its use of the shared Redis and its operator-editable `plan_tier`.
- Planned CloudSaver migration `0012_drop_registry_keys` lands before `0013`.
- Key Vault secrets: `platform-stripe-secret-key` and `platform-stripe-webhook-secret` (Phase 5 only), plus the
  existing pepper, renamed or aliased for the platform managed identity.
- Azure: a platform environment, managed identities, private connectivity from CloudSaver, and a public route
  for the webhook path only (Phase 5).
- Code touched in CloudSaver: `app/entitlements.py`, `app/main.py`, `app/jobs_api.py`, `app/settings_api.py`,
  `app/auth.py`, `app/runtime.py`, `app/tenant_registry.py` (projection columns), `services/gateway.py`,
  `services/tenant.py`, `services/scanner.py`, `services/billing.py` (deleted), `database/billing_store.py`
  (deleted), `workers/tasks.py`, `workers/storage.py`, `workers/dispatcher.py`, `requirements.txt`,
  `compose.yaml`, `.env.example`, `scripts/setup_compose.py`, `Makefile`, `tests/test_billing.py` (moves to the
  platform), `tests/test_entitlements.py`, plus `web-dashboard/components/WorkspaceViews.tsx`,
  `WorkspaceProvider.tsx`, `AppShell.tsx`, `lib/types.ts` and `app/api/[...path]/route.ts`.
- A concurrent CloudSaver change (demo-data purge and provider-neutral UI wording) should merge first. This
  spec's dashboard text assumes provider-neutral wording ("cloud scopes", not "Azure subscriptions").
