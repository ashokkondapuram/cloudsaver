# Billing admin API, v1 (portal server → identity-service)

Platform-internal. Same authentication as the rest of `/admin/v1/*`: the portal caller token plus the operator's
bearer token. `PlatformOperator` for writes, `PlatformAuditor` for `GET`. Every write takes the `version` it
loaded (`409` "This item changed since you loaded it. Refresh and try again." when stale) and records a
`key_events` row. Money is always `amount_minor` (integer, minor units) plus `currency` (ISO 4217, uppercase).
Dates are ISO 8601 (`YYYY-MM-DD` for `date` fields, UTC timestamps ending in `Z` otherwise).

## Shapes

**Entitlements** (all keys required on plans; partial on overrides; unknown keys rejected with `422`):
`max_subscriptions` (int ≥ 0), `max_resources_per_scan` (int ≥ 1), `allowed_scan_frequencies` (non-empty
subset of `manual`, `daily`, `hourly`, must include `manual`), `can_export_terraform`, `can_use_keyvault`,
`can_dispatch_automated_alerts` (bool), `retention_days` (1–3650), `allowed_providers` (non-empty subset of
`azure`, `aws`, `gcp`, `kubernetes`), `max_workspaces` (int ≥ 1), `max_active_keys_per_workspace` (1–20),
`max_key_lifetime_days` (1–365).

**Plan:** `{code, name, description, status ('active'|'retired'), list_price_minor|null, currency|null,
interval ('month'|'year'|'custom')|null, entitlements, external_price_refs ({"stripe": ["price_…"]}),
customer_count, workspace_count, version, created_at, created_by, updated_at, updated_by}`

**Subscription:** `{id, customer_id, plan_code, plan_name, status ('trialing'|'active'|'past_due'|'canceled'|
'expired'), provider ('manual'|'stripe'), external_subscription_ref|null, current_period_start,
current_period_end, cancel_at_period_end, canceled_at|null, amount_minor, currency, interval, grace_days,
entitlement_overrides|null, notes|null, version, created_at, created_by, updated_at, updated_by}`

**Payment:** `{id, customer_id, subscription_id|null, amount_minor, currency, status ('pending'|'paid'|'failed'|
'refunded'|'void'), method ('bank_transfer'|'card'|'check'|'other'), reference, invoice_date|null,
due_date|null, paid_at|null, period_start, period_end, provider, external_payment_ref|null, notes|null,
void_reason|null, voided_by|null, voided_at|null, version, created_at, created_by, updated_at, updated_by}`

**Billing settings:** `{default_plan_code, default_grace_days, lapsed_action ('downgrade'|'suspend'),
lapsed_plan_code, default_manage_billing_url|null, require_subscription_for_keys, version, updated_at,
updated_by, billing_enabled (read-only, from PLATFORM_BILLING_ENABLED), provider: {name ('manual'|'stripe'),
configured (bool), webhook_url|null}}`. No secret values are ever returned.

## Endpoints

| Method | Path | Request | Response |
| --- | --- | --- | --- |
| GET | `/admin/v1/plans` | | `{items: [Plan]}` |
| POST | `/admin/v1/plans` | `{code, name, description?, list_price_minor?, currency?, interval?, entitlements, external_price_refs?}` | `201` Plan |
| GET | `/admin/v1/plans/{code}` | | Plan |
| PATCH | `/admin/v1/plans/{code}` | `{version, name?, description?, list_price_minor?, currency?, interval?, entitlements?, external_price_refs?}` | Plan (counts are the customers and workspaces the change applies to) |
| POST | `/admin/v1/plans/{code}/retire` | `{version}` | Plan |
| GET | `/admin/v1/billing/customers?billing_state=&plan=&renews_before=&cursor=&limit=` | | `{items: [BillingRow], next_cursor}` |
| GET | `/admin/v1/customers/{id}/subscriptions` | | `{current: Subscription\|null, items: [Subscription]}` (newest first) |
| POST | `/admin/v1/customers/{id}/subscriptions` | `{plan_code, status, current_period_start, current_period_end, amount_minor, currency, interval, grace_days?, entitlement_overrides?, notes?}` | `201` Subscription. `409` if a current one exists. |
| GET | `/admin/v1/subscriptions/{id}` | | Subscription |
| PATCH | `/admin/v1/subscriptions/{id}` | `{version, plan_code?, status?, current_period_start?, current_period_end?, amount_minor?, currency?, interval?, grace_days?, entitlement_overrides?, notes?}` | Subscription. `provider='stripe'` allows only `notes` and `entitlement_overrides`. |
| POST | `/admin/v1/subscriptions/{id}/cancel` | `{version, at_period_end, reason}` | Subscription |
| GET | `/admin/v1/customers/{id}/payments` | | `{items: [Payment]}` (newest first) |
| POST | `/admin/v1/customers/{id}/payments` | `{subscription_id?, amount_minor, currency, status, method, reference, invoice_date?, due_date?, paid_at?, period_start, period_end, notes?, extend_period}` | `201` Payment |
| PATCH | `/admin/v1/payments/{id}` | `{version, status?, paid_at?, invoice_date?, due_date?, notes?, extend_period?}` | Payment |
| POST | `/admin/v1/payments/{id}/void` | `{version, reason}` | Payment |
| GET | `/admin/v1/customers/{id}/entitlements` | | `{customer_id, billing_state, plan: {code, name}, subscription: Subscription\|null, issuance_blocked, effective: {<key>: {value, source ('plan'\|'override'\|'fallback')}}, workspaces: [{tenant_id, name, plan_tier, entitlements_version}]}` |
| PATCH | `/admin/v1/customers/{id}` | adds `billing_contact_email?, manage_billing_url?, external_customer_refs?` | Customer |
| GET / PUT | `/admin/v1/billing/settings` | PUT: `{version, default_plan_code?, default_grace_days?, lapsed_action?, lapsed_plan_code?, default_manage_billing_url?, require_subscription_for_keys?}` | Billing settings |

`BillingRow`: `{customer_id, customer_name, billing_state, plan_code, plan_name, subscription_id|null,
subscription_status|null, current_period_end|null, amount_minor|null, currency|null, interval|null,
last_payment: {paid_at, amount_minor, currency, reference}|null}`

**Additions to existing views:**

- Customer: `billing_contact_email`, `manage_billing_url`, `external_customer_refs`, `billing_state`,
  `billing_state_changed_at`.
- Workspace: `plan_name`, `plan_locked` (true when billing is enabled), `issuance_blocked` (true when key issue
  and rotate would return `402`), `entitlements_version`.
- Session: `billing_enabled`, `billing_provider`.
- Audit actions: `plan_created`, `plan_updated`, `plan_retired`, `subscription_created`, `subscription_changed`,
  `subscription_canceled`, `payment_recorded`, `payment_updated`, `payment_voided`, `billing_state_changed`,
  `entitlements_changed`, `billing_settings_updated`, `provider_event_applied`. `actor_type` gains `provider`.
  Billing details include `customer_id`, and for payments `reference`, `amount_minor` and `currency`.

**Errors with fixed text:**

- Workspace `PATCH` with `plan_tier` while billing is enabled: `409` "This workspace's plan comes from the
  customer's subscription. Change it on the customer's Billing tab."
- Key issue or rotate when blocked: `402` "This customer doesn't have an active subscription. Create a
  subscription or record a payment before you issue keys."
- Free text with a Luhn-valid 13–19 digit number: `422` "Remove the card number. Use the invoice or
  remittance reference instead."

## Webhook

`POST /billing/v1/webhooks/{provider}` (caller `portal`). The portal route `POST /api/webhooks/stripe` forwards the
raw body (at most 1 MiB) and `Stripe-Signature`; it needs no session or CSRF check and is rate-limited per IP.
Responses: `503` "Stripe isn't configured" when the provider is off, `400` invalid signature or payload,
`200 {"received": true, "outcome": "duplicate"}` for a known event, `503` on a persistence failure.
