# Durable delivery and recovery

v0.7.1 implements a PostgreSQL transactional outbox for Azure scheduled jobs and
aggregate Slack/Teams notifications. Interactive multi-cloud scans remain
synchronous. GitOps requests retain their separate reconciliation protocol.

## Contracts

| Boundary | Durable behavior |
| --- | --- |
| Scheduler → broker | Job reservation and scan delivery intent commit together. The scheduler does no broker I/O. |
| Worker → notification | Snapshot, normalized findings, job completion and notification intent commit together. |
| Dispatcher claim | Tenant-scoped `FOR UPDATE SKIP LOCKED`, 60-second lease, fresh ownership token, commit before network I/O. |
| Scan handoff | Broker acceptance records `published`; only durable job completion records `delivered`. |
| Lost broker message | After 15 minutes, reconcile job state and republish the same job ID if it never started. Stale running jobs are fenced before requeue. |
| Notification | A 2xx response records `delivered`. Timeout/lost response may cause duplicate messages. |
| Retry | Eight automatic attempts; exponential backoff plus jitter. Retry 408/429/5xx/transport failures. Respect Retry-After, clamped to 1–3600 seconds. Other HTTP responses, including redirects, dead-letter immediately. |
| Manual replay | Admin only, dead-letter notifications only, explicit duplicate-risk acknowledgment, at most three replay cycles. Scan execution is never replayed through this endpoint. |

Every claim consumes an attempt, including a crash before send. Completion
requires a current unexpired token. A crash after provider acceptance but before
DB acknowledgment is deliberately ambiguous: webhook providers do not implement
exactly-once delivery. `X-CloudSaver-Event-ID` stays stable across retries; recipients
may use it for deduplication if their integration supports that.

Scan transport attempts and the worker's four durable execution attempts are
different budgets. Live workers are protected by a renewable Redis lease, durable
ownership token and 600-second hard task limit. Reconciliation treats a running
job older than 15 minutes as lost; it never restarts a recently running job.
The broker task ID and subscription arguments must match the committed delivery
intent. Current operator scope, persisted subscription activation, paid plan and
cloud authorization are checked again before scanning and before result commit.

## Deploy and configure

Back up PostgreSQL with your normal encrypted, access-controlled backup process
and verify recovery before production upgrades. Apply Alembic revision
`0007_delivery_outbox` with the schema owner, then recreate scanner/gateway/tenant,
notification and worker images. The runtime role must remain NOSUPERUSER /
NOBYPASSRLS and must not own or inherit ownership of storage tables.

Delivery is disabled by default. A minimal private configuration is:

```dotenv
CLOUDSAVER_DELIVERY_ENABLED=true
CLOUDSAVER_NOTIFICATION_TARGETS=[{"target_id":"finops","tenant_id":"<authorized-tenant-UUID>","channel":"slack","url_env":"CLOUDSAVER_WEBHOOK_PRIMARY"}]
CLOUDSAVER_WEBHOOK_PRIMARY=<operator-issued-HTTPS-webhook>
```

`channel` accepts `slack` or `teams`. Destination names must reference
`CLOUDSAVER_WEBHOOK_*` environment variables. Only HTTPS Slack / Teams hostnames
are accepted; redirects are not followed and TLS verification stays enabled.
Targets have an explicit tenant UUID. Operators must provision the referenced
workspace first. Users cannot supply a URL, secret, destination or arbitrary
message. The database stores target identity/fingerprint and aggregate counts;
API/audit responses omit payloads, webhook URLs and fingerprints.

The supplied Compose file forwards `CLOUDSAVER_WEBHOOK_PRIMARY` to scanner and
worker/dispatcher containers. For other secret variable names, add them through a
private operator-owned environment/secret override to all three services. JSON
target configuration contains variable names only. Do not commit secrets.

For manual notifications, run the dispatcher profile:

```bash
docker compose --profile delivery up -d --build
```

For scheduled scans, explicitly activate intended subscriptions with
`scripts/provision_tenants.py`, verify the persisted paid plan, set
`CLOUDSAVER_SCHEDULED_SCANS=true`, and run the `scheduled` profile. It includes
worker, Beat and dispatcher. Keep one Beat scheduler; DB reservations also limit
Growth to daily and Enterprise to hourly scheduling. The dispatcher can be
replicated: claims are coordinated by PostgreSQL, not process-local memory.

Automatic notifications require `CLOUDSAVER_AUTOMATED_ALERTS=true` in addition to
approved targets. This flag controls creation of new automatic intents. It does
not revoke previously queued manual or automatic intents. A manually authenticated
admin enqueue does not require the automatic-alert switch.

Use the dashboard or authenticated operational API to confirm that an enabled
dispatcher actually polls. An enabled environment flag alone is not proof of
liveness. Last successful cycle means queue access/reconciliation completed;
individual provider failures are represented separately in event history.

## Upgrade differences

The legacy global `CLOUDSAVER_NOTIFICATION_WEBHOOK` no longer sends messages.
Migrate it to an explicit tenant target; no global-to-tenant mapping is guessed.
`POST /api/v1/notifications/{scan_id}` now returns HTTP 202 with `status=queued`
and delivery IDs. Repeating it for the same scan/target/endpoint revision returns
the same intent. It does not resend an acknowledged message.

Old pre-v0.7.1 queued jobs lack a durable subscription envelope. They are not
silently backfilled or executed by the new worker. Pause schedules, let valid
in-flight work drain before upgrading, then inspect old queued jobs and create
new scheduled work from currently authorized configuration. Existing scan and
GitOps history is retained.

Notifications from historical synthetic snapshots or incomplete scans are
rejected. Changing a target URL/channel changes its fingerprint. Pending intents
for the previous endpoint dead-letter as `target_changed`; they never silently
follow the new endpoint. After reviewing the change, enqueue a new notification
for the owned scan. Restart/recreate relevant services after config rotation.

## Operational API

All routes use existing bearer authentication and tenant isolation. Viewer may
inspect the workspace; enqueue/replay require TenantAdmin.

| Request | Result |
| --- | --- |
| GET `/api/v1/operations/reliability` | State counts, overdue age, tenant target names/channels and dispatcher timestamps. |
| GET `/api/v1/operations/deliveries?limit=50&status=dead_letter&before=UUID` | Keyset-paginated history; optional state filter, limit 1–100. |
| GET `/api/v1/operations/deliveries/{id}/audit?limit=50&before=UUID` | Keyset-paginated lifecycle transitions, sanitized errors and pseudonymous actors. |
| POST `/api/v1/operations/deliveries/{id}/retry` | Body `{"acknowledge_duplicate_risk":true}`; 202 queues a bounded replay. |
| POST `/api/v1/notifications/{scan_id}` | 202 commits/reuses aggregate intents for that tenant's approved targets. |

Audit is append-only **for the runtime role**: it has SELECT/INSERT and no
UPDATE/DELETE grants. Database owners can change schema/data; this is not WORM,
an externally immutable security ledger, or an audit of every product action.
Audit cursors cannot reference another tenant/delivery. Replay bodies are limited
to 1 KB and validation never echoes caller-supplied values.

## Incident procedure

1. Inspect backlog, state, oldest due age, dispatcher last poll and the event's
   audit. Preserve PostgreSQL data. A `published` scan is waiting for execution;
   it is not proof of scan completion.
2. For missing polls, inspect dispatcher process health, PostgreSQL connectivity
   and migrations. Logs use bounded error codes and avoid provider/DSN details.
   Monitor poll age and overdue backlog externally according to your SLO; no
   alerting backend or default availability SLO is deployed by this source.
3. For Redis outage/message loss, restore the broker and worker. Dispatch intent
   survives in PostgreSQL. Reconciliation runs without rerunning completed jobs.
   Do not manually change a job's status or ownership token.
4. For 429/5xx/timeout, allow bounded retries. For a dead letter, fix the provider
   configuration or outage first, inspect possible prior receipt, then explicitly
   request notification replay. Acknowledged deliveries cannot be replayed.
5. Pause outbound work with `docker compose stop delivery-dispatcher`. An in-flight
   HTTP request may still have been accepted. Disable the operator delivery flag
   and recreate API services to reject new enqueues/replays as well. Stopping Beat
   prevents new schedule reservations; queued intents remain durable.
6. Resume the dispatcher after validating scope and destination configuration.
   Never delete PostgreSQL/Redis volumes as a queue-recovery technique.

Shutdown stops between delivery attempts; an interrupted attempt is reclaimed
after lease expiry. Backlog/throughput, target ordering and provider acceptance
need staging load/fault verification. No FIFO/exactly-once guarantee is made.
Runtime roles cannot purge delivery/audit rows. Define retention/archival and
dependent-FK handling with a separate privileged maintenance process before
production; none is automatically run.

Rollback requires stopping dispatchers/workers first and reviewing newly queued
intents. A schema downgrade drops delivery/audit evidence and maps queued job
notification states to failed; it is not a safe incident recovery tool. Prefer
forward fixes with preserved history.
