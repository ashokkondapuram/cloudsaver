# Activity and delivery

Activity and delivery is where you review what CloudSaver did in your workspace: saved scans, saved AI assessment attempts and token usage, and the durable delivery outbox that hands scheduled scans to workers and sends Slack or Teams notifications. Every delivery intent is committed to PostgreSQL before any external call, claimed under a short lease, retried with bounded backoff and recorded in an append-only audit trail. Failed notifications can be replayed manually up to three times after you acknowledge the duplicate risk.

Last reviewed against the code on Oct 25, 2026.

## Where to find it

- **Route:** `/activity` ([web-dashboard/app/activity/page.tsx](../../web-dashboard/app/activity/page.tsx) renders `ConsolePage view="activity"`, which shows `ActivityView` from [WorkspaceViews.tsx](../../web-dashboard/components/WorkspaceViews.tsx)).
- **Navigation label:** **Activity & delivery** ([AppShell.tsx](../../web-dashboard/components/AppShell.tsx)).
- **Tabs:**
  - **Delivery & audit** — `ReliabilityPanel` in [ReliabilityPanel.tsx](../../web-dashboard/components/ReliabilityPanel.tsx).
  - **Scan history** — `ScanHistory` in [WorkspaceViews.tsx](../../web-dashboard/components/WorkspaceViews.tsx).
  - **AI assessments** — `AIAssessmentHistory` in [EnterpriseEvidence.tsx](../../web-dashboard/components/EnterpriseEvidence.tsx).
- **Other entry points:**
  - The notifications bell in the app shell polls delivery status every 30 seconds and shows how many deliveries need attention.
  - The **Activity & ITSM** tab in the finding drawer ([drawer/FindingDrawer.tsx](../../web-dashboard/components/drawer/FindingDrawer.tsx)) shows deliveries for the current scan, taken from the 100 most recent deliveries.
- **Who can see it:** Every signed-in user can open all three tabs. Only a `TenantAdmin` sees the retry control for failed notifications. Workspaces with restricted data scope see only deliveries for scans they can view.

## What you can do

### Delivery and audit

- **See the delivery status.** The panel shows counts for **Waiting** (`pending`), **In flight** (`leased`), **Broker accepted** (`published`) and **Needs intervention** (`dead_letter`). It also shows the operator switch, last dispatcher poll, last successful cycle, oldest due item and approved integrations. It refreshes every 30 seconds while the page is visible, or when you select **Refresh status**.
- **Filter and page.** Use **Delivery state** to filter by status, including **Acknowledged** (`delivered`), and **Load earlier deliveries** for older items. Each row shows the target (or **Scheduled scan**), last update and attempts out of 8.
- **Inspect the audit trail.** Select a delivery to open **Delivery audit**. It lists each action, status, attempt, error code and pseudonymous actor. Use **Load earlier events** to page back.
- **Retry a failed notification.** For a `dead_letter` notification, a `TenantAdmin` can open **Retry this notification**, fix the cause, check **I understand this may send a duplicate notification**, and select **Queue retry (n/3 used)**. Retry is unavailable when the operator switch is off or three replays are used.

### Scan history

The **Scan history** tab lists saved scans with time, short scan ID, finding count, providers and status, and marks historical synthetic snapshots. Select **Refresh history** to reload. Selecting a scan makes it the active scan and opens `/resources`.

### AI assessments

The **AI assessments** tab shows attempts, completed outcomes and pending or uncertain outcomes over the last 30 days, and provider-reported token usage by provider, model, cost center and application. It lists the 10 most recent attempts; select **Load older AI assessments** for more, or **Inspect assessment** to see the saved advice, guardrails, token counts and lifecycle events. Opening this page never runs inference, and pending or uncertain attempts are not retried automatically.

### Send a notification for a scan

`POST /api/v1/notifications/{scan_id}` queues a notification to every approved integration for a completed live scan. There is no dashboard button for this; call it through the API.

## How it works

### Enqueue

- **Scheduled scans.** When scheduled scans are enabled, `reserve_scheduled_job` in [workers/storage.py](../../workers/storage.py) inserts the scan job and its `scan` delivery event in one transaction. Interactive job submissions also enqueue a `scan` event, and a workspace can have at most five unfinished scan jobs.
- **Automated alerts.** When a scan completes and alerts are enabled ([app/operations.py](../../app/operations.py) `alerts_enabled`: the platform switch, the workspace switch and the plan's automated-alert entitlement), `complete_job` enqueues one `notification` event per approved target in the same transaction ([workers/tasks.py](../../workers/tasks.py)).
- **Manual notifications.** [app/delivery_api.py](../../app/delivery_api.py) enqueues notifications through `DeliveryRepository.enqueue_notification` in [database/delivery.py](../../database/delivery.py).

### Dispatch

[workers/dispatcher.py](../../workers/dispatcher.py) runs as the `delivery-dispatcher` Compose service (`python -m workers.dispatcher`, profiles `scheduled` and `delivery`). It exits immediately if delivery is disabled. Each cycle, for every configured workspace, it:

1. Reconciles published scan events against `scan_jobs`, recovering messages lost by the broker or a crashed worker.
2. Claims one due event at a time with `FOR UPDATE SKIP LOCKED` and a 60-second lease. Events that already used eight attempts move to `dead_letter` with `attempt_limit`.
3. For a `scan` event, rechecks that the subscriptions are still authorized and the origin is still allowed, then publishes the Celery task `execute_subscription_scan`. The event becomes `published` and is rechecked after 15 minutes.
4. For a `notification` event, checks that the target still exists with the same fingerprint, then posts "CloudSaver scan completed: N review findings across M scopes." as Slack blocks or a Teams Adaptive Card 1.4, with an `X-CloudSaver-Event-ID` header, redirects disabled and a 15-second timeout. The response body is never read.
5. Records the outcome with the lease token and updates the dispatcher heartbeat.

`scan` events are processed only when scheduled scans are enabled or `CLOUDSAVER_INTERACTIVE_JOBS=true`. The dispatcher polls again after 1 second when it processed work and after 5 seconds otherwise.

### Retry rules

| Outcome | Result |
| --- | --- |
| 2xx response | `delivered` |
| Network or transport error | Retry after `min(30 × 2^(attempt − 1), 1800)` seconds plus up to 10 seconds of jitter (`transport_unavailable`) |
| 429 | Retry after the provider's `Retry-After`, clamped to 1–3,600 seconds (`rate_limited`) |
| 5xx or 408 | Retry with backoff (`provider_unavailable`) |
| Other 4xx | `dead_letter` (`provider_rejected`) |
| Target removed or changed | `dead_letter` (`target_changed`) |
| Scan scope no longer authorized | `dead_letter` (`scope_revoked`) |
| Eighth attempt fails | `dead_letter` (`attempt_limit`) |

A manual replay ([database/delivery.py](../../database/delivery.py) `replay`) applies only to `dead_letter` notifications with fewer than three replays. It resets the event to `pending` with zero attempts and audits `replay_requested`.

### Notification targets

[app/delivery_config.py](../../app/delivery_config.py) (`load_targets`) combines operator targets from `CLOUDSAVER_NOTIFICATION_TARGETS` with webhooks that workspace administrators saved in the registry (target ID `workspace-slack` or `workspace-teams`). Only HTTPS `hooks.slack.com/services/` URLs for Slack and `*.webhook.office.com` or `*.environment.api.powerplatform.com` URLs for Teams are accepted. Destinations are never taken from API callers.

## API reference

All paths are forwarded by the API gateway ([services/gateway.py](../../services/gateway.py)) to the scanner service. Every route requires an authenticated workspace credential.

| Method | Path | Purpose | Required role/scope |
| --- | --- | --- | --- |
| GET | `/api/v1/operations/reliability` | Delivery summary: availability, operator switch, targets, counts, oldest due item and dispatcher heartbeat | Any authenticated caller |
| GET | `/api/v1/operations/deliveries` | Page of deliveries (`limit` 1–100, default 50; `status`; `before` cursor) | Any authenticated caller; PostgreSQL |
| GET | `/api/v1/operations/deliveries/{event_id}/audit` | Audit events for one delivery (`limit` 1–100; `before` cursor) | Any authenticated caller; PostgreSQL |
| POST | `/api/v1/operations/deliveries/{event_id}/retry` | Replay a dead-letter notification (`{"acknowledge_duplicate_risk": true}`, at most 1 KB) | `TenantAdmin`; dispatcher enabled |
| POST | `/api/v1/notifications/{scan_id}` | Queue notifications for a completed live scan to all approved targets | `TenantAdmin`; delivery enabled and targets configured |
| GET | `/api/v1/scans` | Saved scan history (`limit` 1–100) | Any authenticated caller |
| GET | `/api/v1/scans/{scan_id}` | One saved scan | Any authenticated caller |
| GET | `/api/v1/ai/assessments` | Saved AI assessment attempts (`limit` 1–50, default 25; `before`; `scan_id`; `resource_reference` as a 64-character hex digest) | Any authenticated caller |
| GET | `/api/v1/ai/assessments/{assessment_id}` | One saved assessment with its events | Any authenticated caller |
| GET | `/api/v1/ai/usage` | Provider-reported token usage (`days` 1–90, default 30) | Any authenticated caller |

Status codes to expect: `503` when PostgreSQL, the dispatcher or delivery is unavailable; `409` when a replay is not allowed or the scan is not a completed live scan; `404` for unknown or hidden deliveries; `422` for invalid cursors or acknowledgments; `413` for oversized replay bodies.

## Data and evidence

- **`delivery_events`, `delivery_audit` and `delivery_dispatchers`** ([migrations/versions/0007_delivery_outbox.py](../../migrations/versions/0007_delivery_outbox.py)). Events store the kind (`scan` or `notification`), job and scan IDs, target ID and fingerprint, status, attempts, replay count, error code and timing. API responses never include the destination URL, payload or lease token.
- **Audit actors** are `principal:<sha256>` pseudonyms for replays. No email address, access key or raw claim is recorded.
- **Delivery meaning.** **Broker accepted** means the scan was handed to the queue. **Acknowledged** means the webhook provider returned success; it does not prove a person read the message. A delivery can repeat after a lost response.
- **AI history** comes from `ai_inference_attempts` and `ai_inference_events` ([migrations/versions/0009_enterprise_evidence.py](../../migrations/versions/0009_enterprise_evidence.py)). Token counts are provider-reported, and billed AI cost is not shown.

## Permissions

| Action | Required |
| --- | --- |
| View delivery status, deliveries, audit, scan history and AI history | Any authenticated workspace caller |
| Retry a dead-letter notification | `TenantAdmin` |
| Queue notifications for a scan | `TenantAdmin` |
| Configure notification targets, scheduled scans and alerts | Platform operator (environment or registry); workspace administrators can save a Slack or Teams webhook in workspace settings |

## Configuration

| Variable | Purpose | Default |
| --- | --- | --- |
| `CLOUDSAVER_DELIVERY_ENABLED` | Operator switch for the dispatcher, manual notifications and replays | `false` |
| `CLOUDSAVER_NOTIFICATION_TARGETS` | JSON array (at most 100, at most 32,000 characters) of targets with exactly `target_id`, `tenant_id`, `channel` (`slack` or `teams`) and `url_env` | `[]` |
| `CLOUDSAVER_WEBHOOK_*` | Environment variable named by a target's `url_env` that holds the webhook URL. Store it in a secrets manager. | Unset |
| `CLOUDSAVER_SCHEDULED_SCANS` | Platform switch for scheduled scans when no registry is configured (hourly or daily, capped by the plan) | `false` |
| `CLOUDSAVER_AUTOMATED_ALERTS` | Platform switch for automated scan-completion alerts when no registry is configured | `false` |
| `CLOUDSAVER_INTERACTIVE_JOBS` | Lets the dispatcher publish interactive scan jobs | `false` |
| `CLOUDSAVER_DISTRIBUTED_SCAN_LOCK` | Requires Redis for distributed scan locking (Redis is also required when delivery or interactive jobs are enabled) | Unset in code; `true` for `scanner-service` in Compose |
| `REDIS_URL` | Broker and gateway rate-limit store | Set in Compose |

PostgreSQL is required for durable delivery. Without it, the reliability endpoint reports `available: false` and the panel asks you to configure PostgreSQL.

## Guardrails and limitations

- **Off by default.** Nothing is dispatched until the operator enables delivery and starts the dispatcher.
- **Approved destinations only.** Webhook hosts are restricted to Slack and Teams, and a changed target dead-letters existing events instead of redirecting them.
- **Bounded attempts.** Each event gets at most eight attempts, and each notification at most three manual replays. Changing the destination requires a new notification intent.
- **Possible duplicates.** A previous attempt may have reached the provider before the response was lost. Replays require you to acknowledge this.
- **No secrets in logs.** The dispatcher logs no DSN, broker URL, webhook URL, payload or provider exception text, and never reads provider response bodies.
- **Tenant isolation.** One workspace's failure does not stop other workspaces' delivery cycles.
- **Finding drawer view is partial.** The **Activity & ITSM** tab filters the 100 most recent deliveries for the current scan.

## Tests

- [tests/test_delivery.py](../../tests/test_delivery.py) — delivery API, targets, retries and replay rules.
- [tests/test_outbox_lease.py](../../tests/test_outbox_lease.py) — lease fencing and concurrent claims.
- [tests/test_worker.py](../../tests/test_worker.py) — scheduled job reservation and completion enqueueing.
- [tests/test_services.py](../../tests/test_services.py) — gateway and notification service forwarding.
- [tests/test_v041_api.py](../../tests/test_v041_api.py) — role checks, including that Viewer and BillingAdmin cannot enqueue or replay deliveries.
- [tests/test_compose.py](../../tests/test_compose.py) — Compose services and profiles, including the dispatcher.
- [tests/test_postgres.py](../../tests/test_postgres.py) — PostgreSQL behavior, including the outbox.
- [web-dashboard/e2e/reliability.spec.ts](../../web-dashboard/e2e/reliability.spec.ts) — browser coverage of the delivery panel.

## Related docs

- [Durable delivery](../DELIVERY.md)
- [Database operations](../OPERATIONS.md)
- [AI assessment](../ASSESSMENT_AI.md)
- [Environment variables](../ENVIRONMENT.md)
- [Production hardening](../PRODUCTION_HARDENING.md)
