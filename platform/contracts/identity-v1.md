# Identity service internal contract, v1

This is the only interface between CloudSaver and the platform. Neither product imports the other's code.
The JSON files in `fixtures/` are canonical examples. The platform suite asserts that identity-service
responses have the same shape, and the CloudSaver suite replays them as stubbed responses.

- **Base URL:** `CLOUDSAVER_IDENTITY_URL` on CloudSaver (default `http://identity-service:8005`). Locally the
  services meet on the external, internal-only Docker network `platform-link`. In Azure, private networking.
- **Caller authentication:** header `X-Service-Token: <caller token>`. Identity-service stores only SHA-256
  digests (`PLATFORM_IDENTITY_CALLERS`, JSON `{caller: hex digest}`). Callers: `gateway`, `tenant`, `scanner`,
  `analytics`, `notification` (CloudSaver) and `portal` (platform). Unknown token: `401`. Known caller on an
  endpoint it may not use: `403`.
- **Compatibility:** additions are backward compatible. Clients ignore unknown fields. Removing or renaming a
  field, or changing a meaning, needs `v2`.
- **Responses** use `Cache-Control: no-store`. Errors are `application/problem+json` with `detail`.

## `POST /internal/v1/keys/verify`

Callers: `gateway`, `tenant`, `scanner`, `analytics`, `notification`.

Request (`extra` fields are rejected with `422`; the body is never logged or echoed):

```json
{"key": "<presented key>", "client_ip": "203.0.113.10", "request_id": "<uuid or null>"}
```

Responses:

- `200` valid grant: `fixtures/verify_valid.json`.
- `200` rejection: `fixtures/verify_invalid.json`. `reason` is one of `malformed`, `unknown`, `secret_mismatch`,
  `revoked`, `expired`, `rotated_out`, `workspace_suspended`.
- `429` throttled, with `Retry-After`.
- `5xx` service failure. Callers fail closed (`503`).

`allowed_providers` is the effective grant: key providers ∩ workspace configured providers ∩ plan
`allowed_providers`. `all_providers` is true only when the key follows the workspace's providers **and** the plan
allows every configured provider, so a `true` value never widens access.

### `plan` block (added in platform 1.0.0)

Present on valid grants and on every workspace snapshot. CloudSaver 1.2.0 ignores it.

| Field | Type | Notes |
| --- | --- | --- |
| `code` | string | Plan code, uppercase (`STARTER`, `GROWTH`, `ENTERPRISE` or operator-defined) |
| `name` | string | Display name |
| `billing_state` | string | `active`, `grace`, `lapsed` or `none` |
| `current_period_end` | string or null | ISO 8601 UTC |
| `grace_ends_at` | string or null | ISO 8601 UTC, set in `grace` and `lapsed` |
| `subscription_plan_name` | string or null | The customer's subscribed plan when it differs from the effective plan (after a lapse), else null || `entitlements_version` | integer | Increments whenever entitlements change |
| `entitlements` | object | See below. Clients ignore unknown keys. |
| `manage_billing_url` | string or null | HTTPS only; customer URL, else the platform default |

Entitlements sent to CloudSaver: `max_subscriptions` (cloud scopes per workspace), `max_resources_per_scan`,
`allowed_scan_frequencies` (subset of `manual`, `daily`, `hourly`), `can_export_terraform`, `can_use_keyvault`,
`can_dispatch_automated_alerts`, `retention_days` and `allowed_providers` (subset of `azure`, `aws`, `gcp`,
`kubernetes`). Key-management limits (`max_workspaces`, `max_active_keys_per_workspace`,
`max_key_lifetime_days`) stay in the platform. Payment amounts, references and contact emails are never sent.

## `GET /internal/v1/directory/changes?after=<seq>&limit=<1..500>`

Caller: `tenant`. Response `fixtures/directory_changes.json`. `change_type` is `workspace_upserted`,
`workspace_deleted`, `platform_updated` or `entitlements_changed` (platform 1.0.0). Workspace snapshots are complete,
so applying one twice is harmless, and they include the `plan` block. `410` means the cursor is older than
retention: resync from the snapshot.

## `GET /internal/v1/directory/snapshot`

Caller: `tenant`. Response `fixtures/directory_snapshot.json`.

## `GET /internal/v1/events?after=<seq>&wait=<0..25>` (platform 1.0.0)

Callers: every verify or directory caller. Long-poll cache evictions; replaces the Redis subscription.

- Without `after`: returns immediately with `{"items": [], "seq": <current head>}`.
- With `after`: returns up to 500 events with `seq > after` as soon as any exist, or an empty list after `wait`
  seconds (`fixtures/events.json`). `seq` in the response is the cursor for the next call.
- `410` (`fixtures/events_gone.json`) when `after` is older than retention (24 hours) or ahead of the head. The
  client clears its cache and restarts from the head.
- Event fields: `seq`, `tenant_id` (or null), `key_id` (or null), `event` and `directory` (true when the
  directory changed and the projector should poll now). A client evicts cached grants that match `key_id` or
  `tenant_id`.
- While the poll is failing, clients disable their positive cache; the 30-second cache cap bounds staleness.

## `POST /billing/v1/webhooks/{provider}` (platform-internal)

Caller: `portal` only (the portal route `POST /api/webhooks/stripe` forwards the raw body and the
`Stripe-Signature` header). Not part of the CloudSaver contract.
