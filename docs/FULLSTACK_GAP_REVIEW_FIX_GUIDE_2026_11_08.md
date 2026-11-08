# CloudSaver full-stack gap review and fix guide (2026-11-08)

Read-only review of `main` at `0574cfe`. **No code was changed.** This document is the fix backlog.

## 1. Scope, method and confidence

| Area | Paths | Finding prefix |
| --- | --- | --- |
| Dashboard frontend | `web-dashboard/` | `FE-DASH-nn` |
| Platform portal frontend | `platform/portal/` | `FE-PORTAL-nn` |
| Identity / billing service | `platform/identity/`, `platform/identity_migrations/`, `platform/egress/` | `BE-PLAT-nn` |
| Core API, auth, tenancy | `app/main.py`, `app/auth.py`, `app/*_api.py`, `services/` | `BE-API-nn` |
| Collection, analysis, money | `app/collectors/`, `app/analysis_service/`, `app/focus.py`, `app/scan_*`, pricing/finops | `BE-DATA-nn` |
| Workers, DB, migrations, agent-worker, infra, CI | `workers/`, `database/`, `migrations/`, `agent-worker/`, `compose*.yaml`, `k8s/`, `.github/` | `BE-OPS-nn` |

**Method.** The code was read statically, area by area. Every Critical and High item below was re-opened and confirmed against source before it went into this guide, except where it is labelled **Plausible**. Plausible means the code path exists but the runtime trigger was not confirmed.

**Checks executed during the review**

| Check | Result |
| --- | --- |
| `web-dashboard`: `node --test unit/*.test.mjs` | 36 / 36 pass |
| `agent-worker`: `npm test` | 26 / 26 pass |
| `agent-worker`: `tsc --noEmit` | clean |
| `web-dashboard`: `npm run typecheck` | fails **locally only**: `@phosphor-icons/react` and `framer-motion` are in the lockfile but missing from `node_modules`. Run `npm ci` first. This is not a code gap. |
| `scripts/generate_browser_routes.py --check` | clean |
| Python suites (`tests/`, `platform/tests/`) | **not run**. The local interpreter is 3.15 without deps, and the suites need Docker Postgres/Redis. CI runs them on 3.12. |

**Status of prior review items (verified in code, not taken from the docs)**

| Prior item | Status | Where it continues |
| --- | --- | --- |
| CR-01 portal sessions | Largely closed (encrypted store, rotation, one-time state) | Residual: FE-PORTAL-09, 10, 11 |
| CR-02 route payload validation | **Open**. `lib/api.ts` still ends in `raw as T` for most routes. | FE-DASH-04, 25 |
| CR-03 proxy parity | Mostly closed. The test compares only against generated regexes, not against the backend route inventory. | §9 test gaps |
| CR-08 / BE-01 Code Mode | Contained: the bridge returns a static 503 and the executor is unavailable. The regex validator must never become the boundary. | BE-API-14, BE-OPS-23 |
| BE-02 commit intent before dispatch | **Fixed** (`app/code_mode_store.py:93-156`) | none |
| BE-03 refresh separation | **Open** | BE-DATA-14 |
| BE-04 financial meaning | **Open** | BE-DATA-02, 03, 04, 32 |
| BE-06 scoped financial SQL | Fixed in `focus.py`; **open** in `outcome_anomalies.py` | BE-DATA-22 |
| BE-07 evidence-aware scoring | **Open** | BE-DATA-07 |
| BE-08 silent truncation | Mostly fixed | Residual: BE-DATA-22, BE-PLAT-24 |
| CR-12 real-stack journeys | **Open**. The e2e suite runs on fixtures only. | §9 |

**Areas reviewed and found sound.** None of the following needs action:

- **Database isolation:**
  - Transaction-local `set_config` tenant context with `RESET ALL` on release.
  - FORCE RLS on all tenant tables.
  - The store refuses superuser and BYPASSRLS roles.
- **Tokens and routes:**
  - JWT validation pins alg, aud, iss, exp, nbf and iat.
  - CORS is an exact-origin allow-list.
- **Dashboard rendering and routing:**
  - The proxy allow-list rejects encoded and dot path segments.
  - The dashboard has no `dangerouslySetInnerHTML`.
  - The docs route is not open to path traversal.
- **Background work and the pipeline:**
  - The delivery-repository leases are fenced and dead-lettered.
  - The migration chain has a single head.
  - `.env*` files are git-ignored.
- **Provider calls:** retry and pagination bounds in `provider_retry.py` and `_pagination.py`.
- **Egress:** the egress proxy pins resolved IPs.

---

## 2. Severity summary and fix order

| Severity | Count | IDs |
| --- | --- | --- |
| **Critical** | 3 | BE-PLAT-01, BE-PLAT-02, BE-DATA-01 |
| **High** | 24 | see §3 |
| Medium | ~75 | per-area sections |
| Low | ~55 | per-area sections |

### 2.1 Recommended waves

**Wave 0: money and tenancy breaks (ship first, each fix is small and independent)**

1. BE-PLAT-01: Stripe webhook can never commit (DB CHECK violation).
2. BE-PLAT-02, 05, 06: checkout completion dropped, manual subscriptions overwritten, paid-but-not-applied recorded as success.
3. BE-DATA-01: billing import fails above about 166 resources per subscription.
4. BE-API-02: cross-tenant secret exfiltration via `secret_ref`.
5. BE-API-01: Grafana SSRF (no private-address check).
6. BE-API-03: AWS `ExternalId` missing on most assume-role paths.
7. BE-PLAT-04: CustomerAdmin escalates to CustomerOwner.

**Wave 1: authorization, safety and data correctness**

- **Auth:** BE-API-04 drift webhook auth, FE-PORTAL-01 and 02 step-up, BE-PLAT-03 entitlements, BE-PLAT-07 plan_tier CHECK.
- **Change-safety integrity:** FE-DASH-01 fabricated safety evidence, BE-OPS-07 drift guard, BE-OPS-02 drift abort.
- **Numbers shown to customers:** BE-DATA-02 to 07.
- **Worker reliability:** BE-OPS-03, 04, 05, 06 (poison messages, migration 0034, retention).

**Wave 2: robustness and UX.** All remaining Medium items. Do FE-DASH-02 to 04 early because they block the workspace for large tenants.

**Wave 3: Low items, infra hardening, CI gates (§9).**

### 2.2 Coupled fixes: ship together

| If you change… | …you must also fix | Why |
| --- | --- | --- |
| BE-API-21 (remove per-tenant advisory lock in `enterprise_store.transaction`) | **BE-OPS-01** and the concurrency half of **BE-OPS-02** | The global lock is what currently prevents the agent heartbeat from causing a lost update. Removing it makes BE-OPS-01 a real High bug. |
| BE-API-02 (per-tenant secret refs) | BE-API-17, BE-PLAT-24 (Prometheus token env) | The same pattern applies to Grafana, Prometheus, Keycloak `secret_env` and evidence `key_env`. |
| FE-DASH-11 (bind GitOps preview to publish) | Backend `PublishRequest` needs a `fingerprint` field | Frontend and backend contract change. |
| FE-DASH-13 (GET with `persist=true`) | `browser-operations.json` and the backend route | Method change on a reviewed route. |
| BE-DATA-03 / 04 (currency) | FE-DASH-12 (`FinancialFiveStrip` currency labels) | The UI currently labels USD fields with `costs.currency`. |

---

## 3. Critical and High findings (detail)

### BE-PLAT-01: Critical. The Stripe webhook can never commit a subscription update.
- **Where:** `platform/identity/billing/stripe_webhook.py:84`; `platform/identity_migrations/versions/i0007_client_access.py:70-72`.
- **Evidence:** `actor = {'actor': 'stripe', 'actor_type': 'provider'}`, but `identity.key_events` has `CHECK (actor_type IN ('operator','service','system','customer'))`.
- **Failure:**
  - Every handled event writes a `provider_event_applied` key event. That write raises CheckViolation, and the whole transaction rolls back, including the dedupe row.
  - The handler returns 500, and Stripe retries until it gives up.
  - Stripe-driven plan, status and cancel changes never apply.
  - The memory store has no CHECK, so the unit tests pass.
- **Fix:** use `actor_type='system'` (preferred, no migration). Otherwise add migration `i0017` that extends the CHECK with `'provider'`.
- **Verify:**
  - Add a Postgres test in `platform/tests/test_identity_postgres.py` that posts a signed `customer.subscription.updated` and asserts a 200 response and a changed subscription row.
  - Add a static test asserting that every `actor_type` literal in `platform/identity/**` is in the migration CHECK.

### BE-PLAT-02: Critical. `checkout.session.completed` is never processed, so customers are charged but the plan is not applied.
- **Where:** `platform/identity/billing/providers.py:17` (`HANDLED`) and `:215-216`; `billing/stripe_webhook.py:85-95`.
- **Evidence:** `HANDLED` omits `checkout.session.completed`. Unhandled kinds return `ProviderEvent(..., {}, handled=False)` with an empty object, so `session.get('metadata',{}).get('plan_change_request_id')` never matches.
- **Failure:**
  - The approved plan change stays in `pending_payment` forever after the customer pays.
- **Fix:**
  - Add `checkout.session.completed` and `checkout.session.async_payment_succeeded` to `HANDLED`, and pass the real object.
  - Require `payment_status=='paid'`.
  - Match `session.id` to the stored `stripe_checkout_session_id`.
  - Verify the amount and currency against the plan.
- **Verify:**
  - A signed completed-session event moves the request to `approved` and changes `workspaces.plan_tier`.
  - Negative case: `payment_status='unpaid'` changes nothing.

### BE-DATA-01: Critical. The billing import fails silently once a subscription has more than about 166 billed resources.
- **Where:** `app/focus.py:78` (`records: list[Charge] = Field(max_length=5000)`); `app/collectors/billing_sync.py:508` builds one `ImportRequest` with no chunking. Callers: `app/scan_billing.py:61-70`, `app/billing_jobs.py:128-134`.
- **Failure:**
  - 30 days × 200 resources is about 6,000 charges, which fails validation.
  - `scan_billing` logs a warning and continues.
  - The scan completes with no or stale cost evidence, and no finding gets a real cost.
- **Fix:**
  - Chunk `charges` into batches of 5,000 or fewer, with `source_id = digest + chunk index`, inside one transaction (all-or-nothing).
  - Propagate a failed import to the scan as `billing_refresh.status='failed'` (see BE-DATA-08).
- **Verify:**
  - 6,001 synthetic rows through `_import_snapshot` are all inserted, and a re-run is idempotent.
  - A failing import marks the scan as billing-degraded.

### BE-PLAT-03: High. Plan entitlements (`max_workspaces`, `max_active_keys_per_workspace`, `max_key_lifetime_days`) are not enforced.
- **Where:** `platform/identity/billing/catalog.py:13`; enforcement uses the constants `MAX_ACTIVE_KEYS=20` and `MAX_EXPIRY_DAYS=365` (`domain.py:13-14`, `service.py:670,712`). `create_workspace` has no count check.
- **Fix:** read the merged entitlements (plan plus overrides) in `create_workspace`, `issue_key`, `rotate_key` and the delegated customer issue path, and reject over-limit requests with 409 or 422.
- **Verify:** a per-limit test with a plan whose limit is 1.

### BE-PLAT-04: High. A CustomerAdmin can escalate to CustomerOwner by issuing or rotating a key for another user.
- **Where:** `platform/identity/customer/admin.py:449-503` (`issue_customer_workspace_key`, where `subject_user_id` comes from the payload) and `:504-510` (`rotate_customer_key`).
- **Failure:**
  - An admin issues a key with `subject_user_id` set to the owner and receives the secret.
  - `customer_context_from_key` then grants that admin `CustomerOwner`.
  - With that role the admin can perform ownership transfer and suspend users.
- **Fix:** allow the action only when the subject's customer role is equal to or lower than the caller's, or when the subject is the caller. Only an Owner may act for admins or for the owner.
- **Verify:** an Admin attempting `subject_user_id=<owner>` and `rotate(<owner key>)` receives 403.

### BE-PLAT-05: High. Stripe events overwrite manual subscriptions, and failed updates are marked processed.
- **Where:** `billing/stripe_webhook.py:115` and `:132-135`.
- **Failures:**
  - (a) `latest_provider_subscription(...) or current_subscription(...)` rewrites a `provider='manual'` row.
  - (b) A `None` result from `update_subscription` (version mismatch) is ignored after the event id was already inserted, so the update is lost and the retry is deduplicated.
  - (c) When there is no local subscription, nothing is created, yet the event is recorded as applied.
- **Fix:**
  - Apply events only to `provider='stripe'` rows, or create one.
  - Raise on a `None` update so the event insert rolls back.
- **Verify:** three tests, one per case.

### BE-PLAT-06: High. A paid plan change is recorded as success even when it was not applied.
- **Where:** `billing/stripe_webhook.py:48-49` and `:91-95`.
- **Failure:**
  - The operator rejects the request while the customer is paying.
  - `complete_plan_change_from_checkout` returns `None`, but the event is recorded as `plan_change_paid` with a 200.
  - The customer is charged and nothing alerts anyone.
- **Fix:**
  - On a `None` result, record `paid_but_not_applied` and alert.
  - Expire the Checkout session on reject, or forbid rejecting from `pending_payment`.
- **Verify:** a reject-then-webhook test.

### BE-PLAT-07: High. The `workspaces.plan_tier` CHECK rejects custom plans.
- **Where:** `platform/identity_migrations/versions/i0001_directory_identity.py:57` (`CHECK (plan_tier IN ('STARTER','GROWTH','ENTERPRISE'))`) versus `domain.py:10` `PLAN_CODE` (any `^[A-Z][A-Z0-9_]{1,15}$`). `_apply_subscription_plan` and `_sync_customer_entitlements` write `plan['code']`.
- **Failure:** an operator creates plan `PRO`, and subscribing a customer to it returns 500.
- **Fix:** replace the CHECK with an FK to `billing.plans(code)` in a new migration, and stop validating against `TIERS`.
- **Verify:** a Postgres test that creates a custom plan, subscribes a customer and syncs.

### BE-PLAT-08: High. Billing-list pagination is wrong whenever a filter is used.
- **Where:** `platform/identity/billing/admin.py:271-310`. It fetches `limit+50` rows, filters in Python, and returns `next_cursor` only if more than `limit` rows survive the filter.
- **Failure:** lapsed customers beyond the first page are never shown.
- **Fix:** filter in SQL, or loop until `limit+1` matches and use a keyset cursor on the last id.
- **Verify:** 300 customers with 3 lapsed ones scattered through the list. All 3 are reachable.

### BE-API-01: High. The Grafana connector allows SSRF because the private-address check is never applied.
- **Where:** `app/collectors/grafana_rightsizing.py:56` (`check_url(base, resolve=False)`) and `:211-217` (`httpx.Client(base_url=self.base…)` with no re-check). `check_url` returns before the IP checks when `resolve=False` (`app/collectors/observability.py:55`).
- **Failure:** a tenant admin registers `https://10.x.x.x/` or `https://kubernetes.default.svc/`. The service calls it from inside the cluster with the connector secret attached, which gives an internal port and host oracle.
- **Fix:**
  - Call `check_url(self.base, resolve=True)` before every request.
  - Pin the resolved IP (BE-API-07).
  - Share one request helper with `ObservabilityClient`.
- **Verify:** a `grafana_mimir` connector pointing at `https://127.0.0.1/` sends no request and returns `OBSERVABILITY_DESTINATION_BLOCKED`.

### BE-API-02: High. Any tenant admin can exfiltrate another tenant's (or the platform's) secret env var.
- **Where:** `app/collectors/observability.py:21,99` (`SECRET_REF` regex) and `:207-211` (`os.getenv(self.connector['secret_ref'])`); `app/collectors/grafana_rightsizing.py:99-117`.
- **Failure:**
  - Tenant A sets `base_url` to a host it controls and `secret_ref=CLOUDSAVER_OBSERVABILITY_SECRET_<B's name>`.
  - The next `/test` call sends B's secret to A's host.
- **Fix:**
  - Bind secret refs to the authenticated tenant. Either use an operator-managed map `CLOUDSAVER_OBSERVABILITY_SECRETS={"<tenant_id>":["REF"]}`, or require the name `…_SECRET_<TENANT_UUID_HEX>_<NAME>` built server-side.
  - Apply the same rule to Grafana, Prometheus (`bearer_token_env`), Keycloak `secret_env` and evidence `key_env`.
- **Verify:** tenant A referencing B's variable gets 422 at create time and no outbound request is made.

### BE-API-03: High. AWS `ExternalId` is missing on most assume-role paths (confused deputy).
- **Where:** `app/cloud_identity.py:117-121` adds `ExternalId` only if `source['external_id']` is set.
  - Paths that set it: `app/multi_cloud.py:34`, `app/access_probe.py:107`, `app/collectors/prometheus_auth.py:27`.
  - Paths that do not: `app/collectors/billing_sync.py:366`, `app/collectors/commitments.py:112`, `app/collectors/observability.py:243`, `app/drift/operational_fetch.py:82`.
- **Failure:** if a target role's trust policy lacks `sts:ExternalId`, tenant A can read tenant B's Cost Explorer, CUR or commitments by entering B's role ARN. Otherwise these paths simply fail.
- **Fix:** inside `aws_session` and `_assume`, always set `ExternalId = tenant['tenant_id']` (never read it from `source`). Remove the per-caller plumbing.
- **Verify:** patch `sts.assume_role` and assert `ExternalId==tenant_id` for every `aws_session` caller.

### BE-API-04: High. The drift webhook uses one global secret, takes the tenant from the payload, and copies the secret into customer clouds.
- **Where:** `app/drift/event_ingress_api.py:21-33,87-110`; `app/drift/workspace_resolver.py`; `app/drift/cloud_event_subscriptions.py:55-110,189-200`.
- **Failure:**
  - One `CLOUDSAVER_DRIFT_WEBHOOK_SECRET` is shared by everyone. It is pushed into every customer's EventBridge connection and Pub/Sub `pushConfig.attributes`, where it is readable by principals in that project.
  - Any holder can forge events that name another tenant's subscription or account and queue outbox intents for that tenant.
  - The secret is also accepted from the JSON body (`message.attributes.webhook_secret`).
  - The Azure Event Grid validation handshake is answered only after the secret check, so the Azure handshake cannot succeed.
- **Fix:**
  - Use a per-tenant, per-provider ingest credential (an opaque path id plus HMAC-SHA256 over `timestamp.body` with a 5-minute window).
  - Resolve the tenant from the credential and reject events whose account is outside that tenant's scopes.
  - Use Event Grid's `aeg-sas-key` / validation handshake and Pub/Sub OIDC push auth.
  - Never accept the secret from the body.
- **Verify:**
  - Tenant A's credential with a tenant-B subscription event returns 403 and enqueues nothing.
  - A stale timestamp is rejected.

### BE-DATA-02: High. The existing-commitment run-rate is divided by 730 regardless of grain, so the recommended new commitment is overstated.
- **Where:** `app/scan_commitment_evidence.py:198` (`hourly += … / Decimal(730)`).
- **Failure:**
  - A $10/hr Azure savings plan (grain Hourly) counts as $0.0137/hr, and `recommended_new_commitment_hr` is inflated by about 730×.
  - Non-USD items are summed as USD.
  - Shared reservations are counted once per subscription.
- **Fix:**
  - Normalise by `commitment_grain`: Hourly as-is, Monthly ÷ 730, period total ÷ period hours.
  - Skip non-USD items, or convert them with an explicit rate.
  - Dedupe by `commitment_id`.
  - Unknown grain means coverage is unverified.
- **Verify:** Hourly 10 gives 10/hr, an EUR item is excluded, and a duplicate id is counted once.

### BE-DATA-03: High. Any billing currency is labelled `*_usd` and fed into USD thresholds.
- **Where:** `app/focus.py:243-244,268,301`; `app/analysis_service/billing_enrich.py:226-228`; `loader.py:78-79`; `scoring.py:22`.
- **Failure:**
  - EUR amounts are compared against USD retail prices.
  - A resource with rows in two currencies gets a nondeterministic one of them (the first seen, ordered by random id).
- **Fix:**
  - Carry `currency` through `CostSnapshot`.
  - Convert only with an explicit rate, otherwise the cost is unknown.
  - Return a `mixed_currency` flag rather than skipping rows.
- **Verify:** USD and EUR rows for one resource produce a flagged or unknown result.

### BE-DATA-04: High. Rows in non-preferred currencies are silently discarded on import.
- **Where:** `app/scan_billing.py:56`; `app/collectors/billing_sync.py:529`; `app/billing_jobs.py:122`.
- **Failure:** a subscription billed in USD and CAD loses its CAD spend, and the run still reports `completed`.
- **Fix:** import every observed currency (the workspace currency only selects the display), or mark the run `partial` with `unimported_currencies`.
- **Verify:** with two currencies, either both are stored or the run is partial.

### BE-DATA-05: High. OPS_UNTAGGED reports 100% of a resource's monthly cost as savings, and fires when tags were never collected.
- **Where:** `app/analysis_service/evaluators/operational.py:62` (`financial(monthly, savings=monthly)`).
- **Failure:** a $5,000/month resource that is missing a `service` tag reports $5,000/month of savings. AWS RDS, DynamoDB and S3 rows (which have no tag collection, `aws_live.py:113-143`) always fire.
- **Fix:** set `savings=None`, and fire only when the evidence carries a `tags_collected` marker.
- **Verify:**
  - `tags={}` without the marker produces no finding.
  - Collected tags that are missing `owner` produce a finding with `estimated_monthly_savings_usd is None`.

### BE-DATA-06: High. COST_ORPHAN_PUBLIC_IP fires on EBS volumes and GCP disks, so savings are counted twice.
- **Where:** `app/scanner_aws.py:46`, `app/scanner_gcp.py:128` (`association_verified=bool(Attachments/users)` on every row); `loader.py:88-91` maps it to `ip_associated`; `evaluators/_helpers.py:42` returns True before checking the resource type.
- **Fix:** check the resource type before the `ip_associated` branch, or stop mapping `association_verified` to `ip_associated` for non-IP types.
- **Verify:** an `aws:ec2:volume` with `association_verified=False` does not produce COST_ORPHAN_PUBLIC_IP.

### BE-DATA-07: High. Scores report "healthy 100" when nothing was assessed (BE-07 is still open).
- **Where:** `app/analysis_service/scoring.py:17-18`; `pipeline.py:15-22`; `service.py:58-62` (unassessed resources count as 100 in the mean).
- **Fix:** return `None` with `assessment_status='unassessed'` when there is no coverage, weight the account score by assessed resources only, and expose `assessed_resource_count`.
- **Verify:** an empty inventory, and an inventory with no metrics, both return unassessed and no numeric 100.

### FE-DASH-01: High. The browser fabricates the evidence used by the deterministic action-safety firewall.
- **Where:** `web-dashboard/lib/control-plane.ts:140-165` (`actionEvidenceFromResource`); consumed by `app/control_plane_api.py:139-158` and `app/control_plane/action_safety.py`.
- **Evidence:**
  - Unobserved fields are hard-coded: `removes_quorum_member:false`, `violates_capacity_floor:false`, `ip_dependency_confirmed:false`.
  - `is_standby_or_replica` is set to `false` whenever a substring search of the protected reasons finds no match.
  - `memory_history_days:14` and `valid_sample_ratio:0.95` are invented whenever any metric key contains "memory".
- **Failure:** the backend treats `false` as an affirmative PASS for AG-HA-01 and AG-DR-01 and persists the evidence with a digest. The audit record therefore claims facts that were never observed.
- **Fix:**
  - **Frontend:** send `null` for anything not directly observed, and take the windows and ratios from `observation.evidence.metric_summaries`.
  - **Backend (preferred):** derive the evidence server-side from the resource key, and treat client-supplied evidence as advisory only.
  - **Backend:** when a field is `null`, the rule result must be `UNKNOWN`, not PASS.
- **Verify:**
  - A unit test that an empty observation gives `null` for every non-derived field.
  - A backend test that an all-`false` payload without server evidence is not PASS.

### FE-DASH-02: High. Connecting another workspace does not stop the old scan poll.
- **Where:** `web-dashboard/components/WorkspaceProvider.tsx:192-226` (`connect()` never calls `stopScanPoll()`). By contrast `disconnect()` does call it (`:226`).
- **Failure:**
  - `scanPoll.current`, `scanPhase` and `scanActivity` keep the old workspace's values.
  - The poll effect is guarded by `scanPoll.current`, so a running scan in the new workspace is never polled.
  - The stale "Scan in progress" label blocks `AutoScanOrchestrator`.
- **Fix:** call `stopScanPoll()` on a successful connect (or in a `[token]` cleanup effect).
- **Verify:** an e2e test that polls in workspace A, switches to B (which has a running scan), and asserts that polling continues with the correct label.

### FE-DASH-03: High. `/docs/*` returns 404 in the production image.
- **Where:** `web-dashboard/Dockerfile:9` copies docs into the **build** stage only, while the runner stage copies only `.next/standalone` and `.next/static`. `lib/repo-docs.ts:21-35` reads `process.cwd()/docs` at request time (the layout is `force-dynamic`).
- **Failure:** the Settings "View setup guide" link (MANAGED_IDENTITY_ROLES.md) is broken in containers.
- **Fix:** add `COPY --from=build --chown=node:node /app/docs ./docs` to the runner stage, or import the markdown at build time.
- **Verify:** a container smoke test where `curl -f /docs/MANAGED_IDENTITY_ROLES.md` returns 200.

### FE-DASH-04: High. Response validation budget rejects larger tenants and blocks connect.
- **Where:** `web-dashboard/lib/api.ts:20-26` (`if(++nodes>250_000) throw`, plus a 20 MB byte budget) applied to `/scans`, which embeds every finding.
- **Failure:** about 25k findings across the scan history make connect and refresh fail with "incomplete evidence", and the workspace cannot load.
- **Fix:**
  - Make the budget proportional to bytes, or validate only the shape the consumer reads (`validateScan` already checks findings per field).
  - Longer term, paginate `/scans` and stop embedding the findings.
- **Verify:** `unit/api-response-validation.test.mjs` with 30k findings resolves.

### BE-OPS-02: High. The drift abort edits the agent task row without bumping the version, writing an event or checking reconciliation.
- **Where:** `app/drift/drift_manager.py:85-88` (`UPDATE agent_tasks SET state='cancelled',payload=%s …`).
- **Failure:**
  - A `running` task with a `started` step becomes plain `cancelled`, so an in-flight cloud mutation can never reach `needs_reconciliation`.
  - No `agent_task_events` row is written.
  - `version` is not bumped, so a later `_save` that compares the old version still succeeds and can undo the abort (once BE-API-21 is changed).
  - `drafting` and `cancel_requested` tasks are not covered.
- **Fix:** route the abort through `AgentRepository._save`. Set `needs_reconciliation if unreconciled(p) else cancelled`, record an event, and bump `version`.
- **Verify:** a running task with a started step, followed by a drift event, must end in `needs_reconciliation` and leave an event row.

### BE-OPS-03: High. Platform-outbox poison messages that crash the worker are retried forever.
- **Where:** `app/drift/outbox_store.py:75-81` (`_reclaim_expired` does not increment `attempts`) and `:100-105` (`claim_pending` does not increment either).
- **Failure:** an intent that OOM-kills the task, or hits `task_time_limit`, never reaches `fail()`. It is reclaimed every tick and starves the head of the queue (`ORDER BY created_at`).
- **Fix:**
  - Increment `attempts` in the claim UPDATE.
  - In reclaim, dead-letter rows with `attempts >= MAX`.
  - Add a `next_attempt_at` backoff.
- **Verify:** a claim that is allowed to expire without `fail()` 8 times ends `failed`.

### BE-OPS-04: High. The GitOps `except` order makes the `OutboxConflict` handler dead and leaves requests stuck in QUEUED.
- **Where:** `workers/delivery_worker.py:66-97`; `OutboxConflict(ValueError)` at `app/drift/outbox_store.py:16`.
- **Failure:**
  - `except ValueError` runs first, so a `JSONDecodeError` or `ValidationError` from a transient VCS 502 HTML body is treated as a terminal `package_invalid`.
  - That path never updates `gitops_remediation_requests`.
  - `complete()` and `update_status()` run in separate transactions.
- **Fix:**
  - Put `except OutboxConflict` first, and classify errors explicitly.
  - Set the request to `FAILED` on `package_invalid`.
  - Run both updates in one transaction.
- **Verify:** an executor raising `JSONDecodeError` is retried and the request status follows the intent.

### BE-OPS-05: High. Migration 0034 silently updates zero rows under a non-superuser owner, and loads all scans into memory.
- **Where:** `migrations/versions/0034_canonical_rule_ids.py:43-62,71-85`.
- **Failure:**
  - The tables use FORCE RLS and no tenant is set, so the policy matches nothing.
  - Compose hides this because it migrates as `postgres`, but managed databases do not run migrations as a superuser.
  - `fetchall()` reads every tenant's scans inside a single transaction.
- **Fix:**
  - Wrap the data update in `ALTER TABLE … NO FORCE ROW LEVEL SECURITY` … `FORCE`, as `0007` does, or loop per tenant with `set_config`.
  - Stream the work in batches.
  - Ship a corrective migration `0039` that re-runs the canonicalisation idempotently.
- **Verify:** `alembic upgrade head` as a non-superuser owner on a seeded DB leaves no legacy rule ids.

### BE-OPS-06: High. One poison row blocks a tenant's data retention forever, and the failure is never logged.
- **Where:** `app/data_retention.py:55-68` (200 erases in one transaction with no savepoint); `workers/data_retention.py:14-16` (`except Exception: failed+=1` with no log).
- **Failure:** retention deadlines are missed with no operator signal. This is a compliance issue.
- **Fix:** use a savepoint per row (`begin_nested()`), quarantine rows that fail, and log the tenant id and exception class.
- **Verify:** a corrupt row plus a valid expired row: the valid one is erased and the failure is reported.

### BE-OPS-07: High. The agent-worker's "pre-mutation drift guard" never compares live state with the stored baseline.
- **Where:** `agent-worker/src/runtime/pre_mutation_drift_guard.ts:10-17`; `agent-worker/src/contracts.ts:149-152` (`stateMatches` is true when `expected_state` is empty); `agent-worker/src/runtime.ts:20` (checks `plan.steps[0]` only).
- **Failure:**
  - The resource drifts between task creation and approval.
  - The inspect step has an empty `expected_state`, so the write proceeds against the changed state.
  - `task.payload.expected_state`, which the server captured, is never compared with the live state.
- **Fix:**
  - For each write step, compare the live inspect result with `task.payload.expected_state` and fail with `LIVE_RESOURCE_STATE_DRIFTED`.
  - Require a non-empty `expected_state` for inspect steps in `validateStepData`.
- **Verify:** a live state that differs from the payload baseline, with an empty step `expected_state`, results in no mutation.

---

## 4. Dashboard frontend (`web-dashboard/`): Medium and Low

| ID | Sev | Where | Problem | Fix | Verify |
| --- | --- | --- | --- | --- | --- |
| FE-DASH-05 | M | `lib/resources.ts:162,255`; `components/AutoScanOrchestrator.tsx:25` | `resourceCache` key includes `syncEpoch`, which changes every 8 s during a scan. Each change triggers a full reload and adds a new 10k-row entry, and entries are never evicted. Memory grows and the UI flickers. | Drop the epoch from the key and call `reload()` on epoch change. Evict on disconnect and keep at most N entries. | Unit: 5 epochs leave `cache.size<=2` |
| FE-DASH-06 | M | `components/WorkspaceProvider.tsx:98-102` | The `setTimeout` in `scheduleScanPoll` is untracked. A stop followed by a start with the same version leaves two poll chains running. | Store the timer id and clear it in `stopScanPoll`. | Fake-timer test counting `/scans` calls |
| FE-DASH-07 | M | `components/AutoScanOrchestrator.tsx:62-70`; `lib/auto-scan-coordination.ts` | The cooldown is check-then-write across tabs (per-tab sessionStorage plus async BroadcastChannel), so two tabs can both scan. Any admin page view auto-starts a cloud scan every 10 min with no cap. The cooldown is written even when `runScan` fails. There is dead code (`lastTenant`, `void reason`). | Use `navigator.locks` or a localStorage compare-and-set. Add an opt-in setting or daily cap. Write the cooldown only on success. Delete the dead code. | Two-tab simulation test |
| FE-DASH-08 | M | `components/ReliabilityPanel.tsx:17-39` | Raw `fetch` bypasses `lib/api.ts`. A 401 does not log out, there is no abort or timeout, and a 204 makes `.json()` throw. Filter responses race (no stale guard). `before=${cursor}` is not encoded. The retry POST has no idempotency key. | Use `api()` with a signal, encode the cursor, add a request counter and an idempotency key. | e2e: delayed filter response; 401 |
| FE-DASH-09 | M | `components/governance/ControlPlanePlansPanel.tsx:121-187` | The revision subscriber has no `.catch` or abort. `Promise.all(...).catch(()=>{})` means one failing plan hides every plan's versions. Old plans are requested under the new token. N+1 requests. | Use `allSettled` with a per-plan error. Reset state on `[token]`. Add a catch and a signal. | e2e: one versions call returns 500 |
| FE-DASH-10 | M | `ControlPlanePlansPanel.tsx:191-262` | `createPlan` (two POSTs) and `approveVersion` (approval plus transition) are not atomic and send no idempotency keys. Approval expiry uses the client clock. | Send idempotency keys on all four calls and reuse the plan id on retry. Prefer a combined server endpoint, with expiry computed server-side. | e2e: second call 500 then retry gives a single plan |
| FE-DASH-11 | M | `components/GitOpsPanel.tsx:74-78` | Publish does not send the previewed `fingerprint`, so the server may publish a different package. The preview is not cleared when `scan` changes. | Send the fingerprint, and have the backend reject a mismatch (add the field to `PublishRequest`). Clear the preview on scan change. | Changing the scan after preview disables publish |
| FE-DASH-12 | M | `components/resources/FinancialFiveStrip.tsx:23,39-46` | USD fields are labelled with `costs.currency`. `commitment_fee` is set to `effective_cost_usd` (not a fee). "Absorption proven" sends `'0.00'`, so the result is shown as net benefit computed from stand-in inputs. | Send `currency:'USD'` with USD fields. Require real fee data or disable the scenario. Label the result illustrative. | Request-body test with `currency='EUR'` |
| FE-DASH-13 | M | `components/resources/ResourceDrawer.tsx:190-205` | `GET /finops/azure-resource-costs?…&persist=true` writes data and calls Azure, and can be prefetched or retried freely. | Make it a POST with an idempotency key, or drop `persist` from the GET (also update the backend and `browser-operations.json`). | Contract test: no allow-listed GET accepts a persisting parameter |
| FE-DASH-14 | M | `proxy.ts:9`; `app/api/[...path]/route.ts:15-16` | HSTS is sent only if `nextUrl.protocol==='https:'`, which is never true behind TLS termination. The client IP is the last XFF entry, which a client can spoof if the app is exposed directly (Plausible). | Key HSTS on `x-forwarded-proto` or an env flag. Use a configured trusted-proxy depth. | Extend `unit/proxy-contract.test.mjs` |
| FE-DASH-15 | M | `lib/api.ts:56`; `WorkspaceProvider.tsx:223` | Any 401 from any endpoint ends the session, including a 401 from a provider or integration that the gateway passes through. | Revoke only on an explicit `invalid_token` code. The backend must emit a distinct code. | 401 with an integration code keeps the session |
| FE-DASH-16 | M | `lib/resource-csv.ts:12`; `lib/finops.ts` | The formula-injection guard prefixes negative **numbers** with `'`, so credits are exported as text and Excel sums break. | Skip the prefix when `typeof value==='number'`. | `e2e/resource-csv.spec.ts`: `-12.5` stays numeric and `=1+1` is escaped |
| FE-DASH-17 | M | `components/resources/ResourcesView.tsx:251-253` | Export CSV is enabled while loading or partial, so users download a partial estate as if it were complete. | Disable until `progress.complete`, or add a "partial X of Y" trailer row. | Playwright with slow pagination |
| FE-DASH-18 | M | `components/code-mode/CodeModePanel.tsx:48-95` | On token change `selected` is not reset and `submit` has no stale guard. `JSON.parse` accepts arrays and null. The raw SyntaxError is shown. `maxLength` counts characters, not bytes. "completed" is shown for any state. | Reset on `[token]`, validate a plain object, measure with `TextEncoder`, and phrase the notice from the state. | Array input; switch workspace mid-run |
| FE-DASH-19 | M | `components/settings/ObservabilitySettings.tsx:128-146` | The 30×2 s poll has no abort or unmount guard, locks the UI for 60 s, and times out silently. | Use an AbortController and show a "still running, check back" notice. | e2e: job never completes |
| FE-DASH-20 | L | `ResourcesView.tsx:60-70`, `ResourceDrawer.tsx:507-510`, `kubernetes/GrafanaRightsizingPanel.tsx:30-40` | Load failures are shown as "No approved AI target" or "no connectors", so an outage looks like configuration. | Separate error state with a retry button. | n/a |
| FE-DASH-21 | L | `ResourcesView.tsx:73`, `ResourceDrawer.tsx:516` | The idempotency key is reused after the user changes target or scope, which causes a 409 or a replay. | Reset the key on any input change. | n/a |
| FE-DASH-22 | L | `lib/resources.ts:316-335` | `onSettled` is in the effect dependencies, so the poll restarts every 8 s and settle detection is skipped. | Hold it in a ref. | n/a |
| FE-DASH-23 | L | `ResourceDrawer.tsx:664,676-679` | A `resource_key` mismatch is dropped silently and the drawer shows "Waiting…" forever. The 4 s refetch has no backoff or cap. | Show an error; add backoff and a max. | n/a |
| FE-DASH-24 | L | `lib/resource-pages.ts` vs `lib/resources.ts` | The validator accepts `decision:'none'`, which is not in the type, so the UI shows "Decision: undefined". | Reject or handle `none`. | n/a |
| FE-DASH-25 | L | `lib/session-contract.ts` (`validateScan`) | Requires `resource_group` and `subscription_id` to be strings, so a null (AWS, GCP, K8s) fails the whole connect (Plausible). | Align with the backend `Finding` schema and allow null. | n/a |
| FE-DASH-26 | L | `components/V150Views.tsx:70`; `GitOpsPanel.tsx:81` | `href={pr_url}` from the backend has no scheme check. | Require `https:`. | n/a |
| FE-DASH-27 | L | `components/settings/WorkspaceSettings.tsx:143` | `/${setup_guide_path}` with a leading `/` becomes a protocol-relative `//host`. | Validate `^docs/[A-Z_]+\.md$`. | n/a |
| FE-DASH-28 | L | `V150Views.tsx:67-76` | No loading state: while loading or on error it shows "No paired repository actions". | Add a `loaded` flag. | n/a |
| FE-DASH-29 | L | `components/settings/AccessSettings.tsx:88-98` | Raw `fetch` with no 401 handling. `revokeObjectURL` runs immediately after `click()` (Safari). | Use the shared `downloadFile` helper. | n/a |
| FE-DASH-30 | L | `WorkspaceProvider.tsx:168,187,211`; `AppShell.tsx:147` | The bearer is stored in sessionStorage (readable by XSS; mitigated by the strict CSP). The idle timer is client-only. A transient error drops a restored session. The form clears the credential on a network failure. | Long term: HttpOnly session cookie. Short term: retry restore and keep the input on a network error. | n/a |

---

## 5. Platform portal frontend (`platform/portal/`)

| ID | Sev | Where | Problem | Fix | Verify |
| --- | --- | --- | --- | --- | --- |
| FE-PORTAL-01 | **H** | `app/api/auth/login/route.ts:13`; `lib/server/entra.ts:24-47`; `app/api/auth/callback/route.ts:49-56` | The step-up flag comes from the client (`prompt=login`) and is not stored in `Pending`. `signed_in_at` defaults to `Date.now()` when the id_token has no `auth_time`, which Entra v2 omits by default. A plain `/api/auth/login` through SSO therefore gives a "fresh" session that passes step-up. | Persist `stepUp` in `Pending`. Request the `auth_time` optional claim and require it to be within 5 min for step-up. Never default it to now. | Callback test: step-up without `auth_time` fails |
| FE-PORTAL-02 | M/H | `app/api/portal/[...path]/route.ts:57-60` | `STEP_UP` covers only `keys/revoke-all` and workspace DELETE. | Add bootstrap-key, license-tokens, key issue/rotate, customer DELETE, billing settings PUT, plan-change approve, and platform/AI settings PUT. | Table-driven route-matrix test |
| FE-PORTAL-03 | M | `components/SignIn.tsx:21-32`; `lib/server/http.ts:37-41` | Open redirect: the client accepts `/\evil.com` and the server accepts `/\t/evil.com`. The value is used in `<meta refresh>` and `location.replace`. | One shared helper: `new URL(v, origin)`, same origin, no control characters or backslashes. | Fuzz `/\x`, `/\t/x`, `/%09/x`, `//x` |
| FE-PORTAL-04 | M | `[...path]/route.ts:82-84`; `components/knowledge/KnowledgeView.tsx:117`; `identity/auth.py:114-118` | The proxy requires PlatformOperator for every non-GET, so KnowledgeReviewer and PrivacyReviewer cannot `/review` even though identity allows it and the UI shows the buttons. | Allow `knowledge/publications/{id}/review` POST for the reviewer roles. | Route test with `['KnowledgeReviewer']` |
| FE-PORTAL-05 | M | `app/api/auth/operator-key/route.ts:10-36`; `app/api/webhooks/stripe/route.ts:47` | The throttle uses the leftmost (spoofable) XFF value. The in-memory map is unbounded and per-process. With no XFF, everyone shares one key. | Use the trusted rightmost hop, keep counters in Redis, and also limit by key digest. | Rotating XFF still hits the limit |
| FE-PORTAL-06 | M/L | `callback/route.ts:39-44`; `lib/server/entra.ts:75-83` | id_token `iss` and `exp` are not checked, `tid` is optional, and `state` is compared non-constant-time. | Require iss, exp and tid. Verify the signature against JWKS if cheap. | Wrong iss, expired, missing tid |
| FE-PORTAL-07 | M | `lib/server/entra.ts:86-104` | `invalid_grant` is reported as 503 "unavailable" for up to 8 h. A concurrent refresh returns 503. | On `invalid_grant`, delete the session and return `sessionEnded`. Waiters re-read the session. | Mocked token endpoint |
| FE-PORTAL-08 | M | `components/customers/BootstrapKeyDialog.tsx:55,77`; `components/workspaces/KeyDialogs.tsx`; `LicenseTokenDialog.tsx:19` | The dialog can be dismissed while the issue request is in flight, so a one-time secret is lost and an orphan key is left behind. The license dialog reset depends on the `workspace` object identity. | Disable dismiss and cancel while busy. Make the reset depend on `open` only. | Close during the pending request |
| FE-PORTAL-09 | M/L | `lib/server/session.ts`; `route.ts:82` | Roles are cached for the 8 h session, so a removed operator keeps UI write access. | Re-fetch `/admin/v1/session` on token refresh. | Role removed gives a 403 |
| FE-PORTAL-10 | M/L | `components/SessionProvider.tsx:24-35`; `AppShell.tsx:37-40` | Any 503 from `/api/auth/session` logs every tab out. Background polls keep extending the idle timeout. | Keep the session on 503 and show a retry banner. Use non-touching reads for polls. | Mock 503 |
| FE-PORTAL-11 | L/M | `lib/server/session.ts:36-45`; `redis-session-store.ts:23`; `startup.ts` | The default store is `/tmp/.../sessions.sqlite` and production does not require Redis. The encryption key is derived from `PLATFORM_PORTAL_TOKEN`, so rotating it logs everyone out. | Dedicated `PORTAL_SESSION_SECRET` with HKDF. Fail production startup without Redis or a persistent path. | Startup test |
| FE-PORTAL-12 | L | `app/api/auth/logout/route.ts`; `session.ts:80-88` | No Entra `end_session` call. No `__Host-` cookie prefix. `Secure` is derived from spoofable XFP outside production. | Redirect via Entra logout, use `__Host-`, always set Secure except in local development. | Cookie-flag test |
| FE-PORTAL-13 | L | `components/ui/Dialog.tsx`; `KeyDialogs.tsx`; `lib/useUnsavedPolicy.ts` | Key name `maxLength=120` but the server allows 80. Dialogs have no `aria-labelledby`. `EditKeyDialog` resets on reload. Only the policy editor has a dirty guard. | Align the limits, use stable-id dependencies, add dirty guards. | Component tests |
| FE-PORTAL-14 | L | `proxy.ts:26`; `[...path]/route.ts:94-133` | Upstream bodies are not size-capped. GET queries pass through unfiltered. A missing Content-Length is treated as 0. CSP has `style-src 'unsafe-inline'`. | Cap response size, allow-list query keys, stream-count the body. | Oversized upstream test |

---

## 6. Identity / billing service (`platform/identity/`): Medium and Low

| ID | Sev | Where | Problem | Fix |
| --- | --- | --- | --- | --- |
| BE-PLAT-09 | M/H | `app.py:182-184` | `async def stripe_webhook` does blocking DB and Stripe work on the event loop. | Make it a sync `def` or use `run_in_threadpool`. |
| BE-PLAT-10 | M | `service.py:1122-1140`; `stripe_webhook.py:31` | Stripe `Session.create` runs inside a DB transaction holding `FOR UPDATE` (pool size 4), with no idempotency key, no timeout and no `customer`. This leaves orphaned or duplicate sessions and new Stripe customers that cannot be mapped. | Create the session after commit with `idempotency_key=request_id`, a timeout, and `customer=` set from the external ref. |
| BE-PLAT-11 | M | `stripe_webhook.py:103-108` | Unknown-customer events are recorded and acknowledged with 200, so they can never be replayed after the ref is linked. | Return non-2xx so Stripe retries, or store the payload for replay. |
| BE-PLAT-12 | M | `store_postgres.py:369-372` vs `store_memory.py` | `paid_at DESC` puts NULLs first in Postgres and raises TypeError in memory. A payment can be `paid` without `paid_at`. Initial `void` or `refunded` bypasses transitions. | Require `paid_at` for paid. Use `NULLS LAST`. Restrict the initial status. |
| BE-PLAT-13 | M | `service.py:557`; `knowledge/admin.py:~140`; `billing/admin.py:329` | ValueError and KeyError on bad input return 500. | Global handler mapping them to 422, or wrap in `IdentityError`. |
| BE-PLAT-14 | M | `billing/admin.py:230-262` | Retiring the default or lapsed plan is allowed. `bool("false")` is True. One price ref can map to several plans. There is no `end>start` check on update. `canceled` is allowed without `canceled_at`. | Validate each rule. |
| BE-PLAT-15 | M | `identity_migrations/versions/i0002_billing.py` | No unique `payments(customer_id, reference)`. No unique stripe ref on customers. No indexes on `subscriptions(customer_id)`, `payments(customer_id)`, `provider_events(customer_id,provider)`. No amount or period CHECKs. | New migration with partial unique indexes, an expression index and the CHECKs. |
| BE-PLAT-16 | M | `i0001`, `i0002`, `i0003`, `i0009`, `i0012`-`i0014` | Downgrades are destructive or asymmetric (CASCADE drops, a leftover column, deleted change-feed rows, no-ops). | Make them symmetric or declare forward-only. Add an up/down/up test. |
| BE-PLAT-17 | M | `service.py:232-240`, `:1164` | Cache-invalidation events are durable only when `tx` is passed (not for revoke, rotate, update, revoke_all or the customer write path). With `tx`, Redis publish happens **before** commit. | Always append inside the tx and publish after commit. |
| BE-PLAT-18 | M | `auth.py:61,65` | `environment == 'production'` is case-sensitive, so operator-key mode is possible with `Production`. The actor is always `'operator-key'`. | `.strip().lower()`. Fail closed on an unknown env. |
| BE-PLAT-19 | M | `customer/admin.py:136-200` | The claim endpoint skips throttle and failure accounting, and allows claiming a suspended workspace or customer. | Route through the throttle and `_reject`. Require active status. |
| BE-PLAT-20 | M/L | `customer/admin.py:513-518` | CSV export has no formula-injection escaping. The customer audit exposes operator `oid:name`. | Escape `= + - @`. Filter or redact operator actors. |
| BE-PLAT-21 | M/L | `service.py` `issue_key`; `license_tokens.issue`; `create_customer_payment` | No idempotency key and no issuance rate limit, so retries duplicate credentials. | `Idempotency-Key` persisted per actor. Per-workspace limit. |
| BE-PLAT-22 | M/L | `app.py:102`; `redaction.py:21-27`; `egress/proxy.py` | The size guard trusts `Content-Length` (chunked bodies bypass it; a non-numeric value gives 500). Redaction skips exceptions and dicts. Egress binds `0.0.0.0` without auth, uses `addresses[0]` only, and has no tests. | ASGI byte cap. Recursive scrub. Egress tests. |
| BE-PLAT-23 | L/M | `store_memory.py` vs `store_postgres.py` | Behaviour diverges: CHECKs, CAS, prefix vs substring search, ILIKE escaping (a trailing `\` errors), race returns 500 instead of Conflict. | Shared parametrised store-contract suite. |
| BE-PLAT-24 | L | various | Audit cursor `<` skips rows with equal timestamps. Silent 500 caps. `poll_events` holds a thread for 25 s. One StaleVersion aborts `evaluate_billing`. 1 MB access-check result vs a 16,000-byte CHECK. Knowledge audit is missing from `/admin/v1/audit`. Prometheus URL and token env are not tenant-bound (see BE-API-02). `setup_platform.py` rotation is not atomic. Redis has no auth or TLS. | Fix individually. Use `(occurred_at,id)` keyset cursors. |

---

## 7. Core API, auth and tenancy (`app/`, `services/`): Medium and Low

| ID | Sev | Where | Problem | Fix | Verify |
| --- | --- | --- | --- | --- | --- |
| BE-API-05 | M | `app/settings_api.py:136-143`; `app/tenant_registry.py:40-66` | `GET /api/v1/settings` returns `platform` (every tenant's UUID in `workspace_ui_themes`, hub role ARN, MI client id, `cloudsaver_integration`) to any role. | Return only this tenant's theme and onboarding fields. Restrict the rest to platform operators. | A Viewer sees no other tenant UUID |
| BE-API-06 | M | `app/drift/cloud_event_subscriptions.py:38-47,244-258` | Provisions EventBridge in the **platform** account with ambient credentials and fixed names that collide across tenants. `str(account)` on a dict always raises. | `aws_session(source, tenant=…)`, `account['account_id']`, tenant-unique names. | Patched session assertion |
| BE-API-07 | M | `app/collectors/observability.py:56-66` vs `:256-266` | DNS-rebinding TOCTOU: the name is resolved once for the check and again by httpx. | Connect to the validated IP while keeping Host and SNI (custom transport). | Fake resolver flips to 127.0.0.1 |
| BE-API-08 | M | `app/main.py:61`; `services/common.py:23` | `/docs`, `/redoc` and `/openapi.json` are public in production. | Set all three to `None` when env=production. | 404 without a token |
| BE-API-09 | M | `app/config.py:35-47`; `app/auth.py:121-130` | `CLOUDSAVER_ENVIRONMENT` defaults to development, so a forgotten env var gives a static key all roles, SQLite and public docs. | Refuse to start on a non-loopback bind without an explicit env, or default to production. | Startup test |
| BE-API-10 | M | `services/analysis_service_app.py:12-37` | `contexts` has no `max_length`, `scan` is an arbitrary dict, there is no body cap and no role check. | `max_length=5000`, a 2 MB bounded reader, require Viewer or higher. | 100k contexts gives 413 or 422 |
| BE-API-11 | M | `app/offline_license.py:10,50-62` | License JWTs are full API bearers for up to 366 days. Revocation is env-only, needs a redeploy and is capped at 10k entries. | Split entitlement from short-lived access, or cap interactive lifetime. Hot-reload the denylist file. | Denylisted jti gives 401 without a restart |
| BE-API-12 | M | `app/keycloak.py:96-140`; `services/gateway.py:60-62` | About 5-6 uncached Keycloak calls per request. The rate limiter runs after auth. | 5-15 s per-token cache and a pre-auth per-IP limiter. | Counting mock transport |
| BE-API-13 | L | `app/auth.py:41-43`; `app/keycloak.py:69` | An unknown `kid` makes an unauthenticated caller trigger a JWKS fetch. | Negative kid cache and a minimum refetch interval. | 100 random kids give at most 1 fetch |
| BE-API-14 | L | `app/code_mode_api.py:19-40` | `human()` is weaker than `agent_gateway.human` (a local static key counts as human). Read routes have no role check. | Reuse the agent-gateway predicate and require Viewer or higher. | Local key POST gives 403 |
| BE-API-15 | L | `services/gateway.py:40-62,829` | No pre-auth limiter (drift ingest and claim are unthrottled). A Redis outage gives a global 503. The scanner port has no limiter. | Per-IP pre-auth limiter. Decide the degraded mode. | Bad-secret flood gives 429 |
| BE-API-16 | L | `app/main.py:193-208`; `app/data_governance_api.py:42-46` | GET endpoints mutate state: they abandon stale scans and purge retention, so a Viewer triggers side effects. | Move reaping and purging to workers. | A Viewer GET leaves rows unchanged |
| BE-API-17 | L | `app/settings_api.py:75-87` | `prometheus_url` and `bearer_token_env` are returned to any role. | Return `token_configured: bool` and a redacted host, admin only. | Viewer response test |
| BE-API-18 | L | `app/runtime.py:55-72` | XFF uses `split(',')[-1]`, which assumes exactly one hop. | Walk right to left, skipping `CLOUDSAVER_TRUSTED_PROXIES`. | Two-hop test |
| BE-API-19 | L | `app/drift/event_ingress_api.py:95-109` | `str(error)` is echoed in the 422 response. | Fixed message. | Malformed base64 test |
| BE-API-20 | L (Plausible) | `app/onboarding_api.py:140-230` | `/customer/*` ID routes (suspend, revoke, rotate, service-accounts PATCH) rely only on identity-service for ownership. | Verify the role locally and pin the tenant. Cross-workspace test against real identity. | Foreign key_id gives 403 or 404 |
| BE-API-21 | L | `app/enterprise_store.py:356-357` | A per-tenant `pg_advisory_xact_lock` on **every** write transaction serialises all of a tenant's writers. **See §2.2: currently masks BE-OPS-01.** | Lock per aggregate. Fix BE-OPS-01 in the same change. | A held write does not block an unrelated write |
| BE-API-22 | L | `services/gateway.py` (outcomes, spot-arbitrage, anomalies) | Forwards `dict(request.query_params)` raw, unlike the other routes. | Use the allow-list pattern. | `?tenant_id=` is dropped |

---

## 8. Collection, analysis and money (`app/collectors`, `app/analysis_service`, finops): Medium and Low

| ID | Sev | Where | Problem | Fix | Verify |
| --- | --- | --- | --- | --- | --- |
| BE-DATA-08 | M | `app/scan_billing.py:43-70,94-98` | Refresh failures are swallowed and `billing_materialized=True` is set anyway, so stale cost looks current. | Record `billing_refresh:{status,failed_scopes,error_code}` and surface it. | Mocked raise gives `status='failed'` |
| BE-DATA-09 | M | `app/scan_commitment_evidence.py:85-106` | The hourly series is daily charges smeared over 24 h but labelled `focus_usage_charges_hourly`. P10 equals the daily trough, which supports over-commitment. | Build hourly only from hourly rows. Otherwise label it `daily_smeared` and refuse commitment evidence. | A 24 h row is not `source_verified` |
| BE-DATA-10 | M | `scan_commitment_evidence.py:90,123` | Usage-only filter ignores `Adjustment` corrections, and negative deltas break `_distribute_charge`. | Net Usage plus Adjustment per (day, resource). | 100 + (-10) gives 90 |
| BE-DATA-11 | M | `evaluators/cost.py:105-111,181`; `performance.py:63`; `operational.py:70`; `reliability.py:28,48,147` | Invented savings ratios (0.15, 0.9, 0.65, 0.05, 1.8, 1.05). Rightsizing mixes 30-day actuals with 730 h list prices and can go negative. | `savings=None` unless meter-exact. Clamp or reject negatives. | Legacy SKU gives None |
| BE-DATA-12 | M | `evaluators/cost.py:186-214`; `collectors/activity_events.py:19-24`; `evaluators/operational.py:14` | COST_SPIKE_DRIFT fires when there is no spike. OPS_IAC_DRIFT (HIGH) counts any Azure Policy, backup or autoscale write as human drift. IaC detection is a substring match (`x-terraform-y`). | Config-changing operations only. Exact principal allow-list. Rename the no-spike case. | Azure Policy write gives no drift |
| BE-DATA-13 | M | `collectors/activity_events.py:~140` | `append_activity_events` does not dedupe, so duplicates crowd out new events. | Dedupe by `event_id`, replace the bucket per collection. | Double append is idempotent |
| BE-DATA-14 | M | `app/resource_refresh.py:128-180`; `resource_timestamps.py:47-63`; `collectors/resource_pipeline.py:132` | (BE-03 open) A GET triggers a synchronous provider refresh with no atomic claim. Unsupported types refresh on every read. The budget-exceeded flag is bypassed. | Redis `SET NX` lease per resource. Cool-down on success and failure. Move refresh to a job. | 20 concurrent GETs give 1 provider call |
| BE-DATA-15 | M | `collectors/azure_live.py:61-82,150-180`; `resource_pipeline.py:117` | Per-resource N+1 (locks, snapshots per disk, watchers, 6 metrics, activity log) and `_live_resource_limit` defaults to unlimited. | Cache per RG and subscription per scan. Use the batch metrics path. Set a default cap. | 100 disks in 1 RG give 1 snapshot call |
| BE-DATA-16 | M | `azure_live.py:153,182-225` | Only same-subscription vaults are checked, so `backup_enrolled=False` is reported definitively. Subscription-scope locks are missed. | Unknown coverage gives `None`. Add subscription-scope locks. | Cross-subscription vault gives None |
| BE-DATA-17 | M | `collectors/aws_live.py:20`; `app/azure_resource_registry.py:~186` | `Stat='Maximum'` is used for additive counters (bytes, invocations, connections). SageMaker needs VariantName. | Per-metric stat (Sum for counters). | NAT bytes requested with Sum |
| BE-DATA-18 | M (Plausible) | `app/scanner.py:178` | An empty enabled-rule set means "all rules". | Test with `is None`. | `set()` gives no findings |
| BE-DATA-19 | M | `collectors/commitments.py:188`; `billing_sync.py:~422` | GCP sums vCPU and memory amounts together. BigQuery has `timeoutMs=20000` with no polling, so large exports always fail. | Keep per-type quantities. Poll `getQueryResults` with a bound. | `jobComplete:false` then true |
| BE-DATA-20 | M | `collectors/commitments.py:89` | Catches `httpx.HTTPStatusError`, but `read_json` raises `ProviderReadError`, so a 403 on savings plans drops the reservations too. | Catch `ProviderReadError` with 401, 403 or 404. | 403 still returns reservations |
| BE-DATA-21 | M | `app/pricing.py:137-140`; `domain/pricing/retail_cache.py:11` | A transient failure caches `None` for 24 h, and there is no 429 handling. | Do not cache transport errors (or use a short TTL). Use `read_json`. | 503 then success returns the price |
| BE-DATA-22 | M | `app/outcome_anomalies.py:~224-302` | (BE-06 residual) Scope is filtered in Python after `LIMIT 50001`. `max(period_end)` is unscoped. The absolute threshold `Decimal("5")` applies in any currency. Duplicates are checked only among the 501 newest. | `summary_scope_sql` in SQL. Per-currency threshold. Unique fingerprint constraint. | 60k hidden rows still detect |
| BE-DATA-23 | M | `collectors/wiz_security.py:190-275` | Silent truncation at max issues. GraphQL `errors` only logged. O(N×M) fallback. Failure looks like "no issues". | `wiz_sync:{status,truncated,error}` on the scan. Drop the linear fallback. | `errors` gives failed status |
| BE-DATA-24 | M | `app/cloud_http.py:78-87` | Quota keys without a subscription fall back to `host:global`, so one tenant's 429 delays all tenants. | Key by tenant plus host. | Two-tenant isolation |
| BE-DATA-25 | M | `collectors/azure_monitor_batch.py:154-156` | `except Exception: merged={}` swallows deferrals and auth errors, then falls back to per-resource calls against the same throttled quota. | Propagate `ProviderDeferred`. Flag other errors. | Deferral surfaces as `collection_delays` |
| BE-DATA-26 | M (Plausible) | `azure_arm_detail.py:103`; `azure_resource_graph.py:73-96`; `kubernetes.py:90` | Full ARM documents for up to 100k rows are held in RAM and in progress persistence. | Persist per resource and drop after projection. | 20k-resource memory test |
| BE-DATA-27 | L | `collectors/grafana_telemetry.py:96-101`; `grafana_rightsizing.py` | Invents timestamps when `len(times)==1`. Grafana has no 429 handling and an unbounded `.json()`. | Reject mismatched frames. Use `read_json`. | n/a |
| BE-DATA-28 | L | `grafana_telemetry.py:159` vs `telemetry_contract.py:24` | Coverage threshold 0.90 vs 0.95. `now=end` makes the freshness check a no-op. | One contract and the real `now`. | n/a |
| BE-DATA-29 | L | `collectors/kubernetes.py:121-155` | One NaN or Inf sample drops the whole metric (`raise ScanError`). | Skip the sample and mark the metric partial. | n/a |
| BE-DATA-30 | L | `analysis_service/loader.py:129`; `billing_enrich.py:137-143`; `aws_live.py:118` | `or` chains drop explicit zeros. `backend_count` vs `backend_target_count` mismatch means idle AWS LBs are never detected. | `is not None` checks and aligned keys. | n/a |
| BE-DATA-31 | L | collectors vs rules | `network_in_total_gb`, `request_count_14d`, `runtime_hours_30d`, `error_5xx_rate_pct`, `burst_credit_balance_min_pct`, `throttled_requests_count` and VM `memory_percent` are never collected, so several rules can never fire. | Collect them, or emit `unsupported_by_collector`. | n/a |
| BE-DATA-32 | L | `app/financial_balance.py`; `billing_enrich.py:77` | 30-day billed cost is compared to a 730 h retail run-rate. | Normalise to one basis. | n/a |
| BE-DATA-33 | L | `collectors/activity_ingestion_watermark.py:14-37`; billing window | Lexical ISO watermark comparison. The last 2 days are imported before finalisation. AWS `Estimated` is ignored. | Parse datetimes. Lag the window. Carry the estimated flag. | n/a |
| BE-DATA-34 | L | `finops_autopilot_planner.py:~25`; `finops_resize_playbooks.py`; `finops_resize_metrics.py:95` | The resize target is not checked against the SKU catalogue. Azure id comparison is case-sensitive. | Validate against the catalogue and lower-case Azure ids. | n/a |
| BE-DATA-35 | L | `scanner_gcp.py:157`; `gcp_live.py:209` | Zonal disks bypass the region filter. `inventory[:limit]` has no priority. | Filter zones by region and prioritise. | n/a |
| BE-DATA-36 | L | `analysis_service/declarative_rules.py:71-95,159-183` | `tag_missing` and `env_not_in` fire on uncollected tags. A rules-load error returns `()` and is re-logged every call. | Require `tags_collected`. Surface load failure on the scan. | n/a |
| BE-DATA-37 | L (Plausible) | `app/ai_advisory.py:~171-176` | Unsafe-claim detection is regex-only ("safe to delete" and percentage savings are not blocked). The schema, citations and tag exclusion are solid. | Extend the patterns or add structured claim checks. | n/a |

---

## 9. Workers, persistence, migrations, agent-worker, infra and CI: Medium and Low

| ID | Sev | Where | Problem | Fix | Verify |
| --- | --- | --- | --- | --- | --- |
| BE-OPS-01 | L (becomes **High** if BE-API-21 changes) | `app/agent_store.py:194-201` | The heartbeat reads the payload and writes back the whole payload with no version predicate. **Today the per-tenant advisory lock serialises it with `step()`, so there is no live lost update.** | Use `jsonb_set(payload,'{lease,expires_at}',…)` with a state predicate, or `FOR UPDATE` in `_row`. | Two-connection interleave test, run with the lock removed |
| BE-OPS-08 | M | `agent-worker/src/connectors.ts:87-92`; `multicloud.ts:69-70,114-117` | Stop/deallocate then modify immediately with no wait, and no restart on failure, so a production VM can be left stopped. | Poll until stopped (bounded). Best-effort start when the modify fails and the VM `wasRunning`. | Injected 409 triggers a start call |
| BE-OPS-09 | M | `compose.yaml:96,259,333-344`; `workers/tasks.py:24` | `stop_grace_period` 45 s vs `task_time_limit` 600 s (scan worker). Agent grace 120 s vs a 900 s run. | Grace of 660 s or more for scan and 900 s or more for agent. | `docker compose config` |
| BE-OPS-10 | M | `migrations/versions/0007_delivery_outbox.py:28-37`; `database/delivery.py` | No index on `delivery_events(tenant_id, job_id, kind)`. Events and audit rows are never pruned. | Add the index and an owner-run prune job. | EXPLAIN shows an index scan |
| BE-OPS-11 | M | `workers/dispatcher.py:119-169`; `grafana_k8s_rightsizing.py:19-37`; `billing_sync.py:73`; `celery_health.py:29-31` | Workers touch health as ready even when every tenant cycle fails. Billing `max_age` is about 5.3 h. Celery liveness uses the main-process heartbeat only. | `touch(ok=failures==0)`. Cap `max_age`. Probe pool progress. | DB down gives 503 within one interval |
| BE-OPS-12 | M | `app/drift/outbox_store.py:86-201` | Leases use the app-server clock, not `clock_timestamp()`. | Do lease maths in SQL with the DB clock. | Monkeypatched app clock has no effect |
| BE-OPS-13 | M | `workers/delivery_worker.py:29-56`; `workers/event_drift_worker.py:39-46` | 120 s and 30 s leases with no renewal during VCS or AI calls. 10 intents are claimed under one lease. | Heartbeat thread or renew around each remote call. Claim 1-2 at a time. | Slow-executor test |
| BE-OPS-14 | M | `workers/dispatcher.py:64-80`; `database/delivery.py` | A `finish()==False` after a 2xx webhook is ignored, so the message is re-sent. `except Exception: pass` hides bugs. | Log both cases. Renew before HTTP. Include the event id in the body. | Warning emitted |
| BE-OPS-15 | M | `workers/tasks.py:257,341-346` | `except (UnauthorizedJob, ValueError)` turns a pydantic `ValidationError` into a permanent `unauthorized_scope`. | Catch `UnauthorizedJob` only. | ValidationError is retryable |
| BE-OPS-16 | M | `workers/health.py:41-51`; `agent-worker/src/health.ts:24` | Single-threaded `HTTPServer` with no socket timeout, bound to `0.0.0.0`. An idle connection hangs the probes. | `ThreadingHTTPServer`, `timeout=5`, bind to 127.0.0.1. | A silent socket does not block |
| BE-OPS-17 | M | `agent-worker/src/multicloud.ts:20-29`; `main.ts:25`; `health.ts:10` | AWS and GCP SDK calls have no timeout and there is no per-step budget. Liveness returns 503 during drain, so k8s would kill the pod mid-write (Plausible). | `NodeHttpHandler` timeouts and `AbortSignal.timeout` per step. Flip readiness only. | Stalled-client test |
| BE-OPS-18 | M | `app/agent_store.py:105-106,156-157` | N+1 load of up to 1,000 full payloads per tenant every 3 s. | A single query with the filters pushed into SQL. | Query-count test |
| BE-OPS-19 | M | `app/data_retention.py:49-67` | Filters on unindexed jsonb expressions. Timestamps are compared as text. | Promote to indexed columns and compare as `timestamptz`. | EXPLAIN |
| BE-OPS-20 | M | `app/control_plane/store.py:189-199` | Three correlated subqueries per version on `engineering_events` with no `(tenant_id, version_id)` index. | Add the index. | EXPLAIN |
| BE-OPS-21 | M | migrations `0028`-`0032`, `0034`, `0036` | Import mutable app modules for DDL. `app/drift/schema.py` already contains columns that `0033` adds, so a fresh upgrade differs from an incremental one. | Freeze DDL inline. Add a schema-snapshot test. | `pg_dump --schema-only` fresh vs incremental |
| BE-OPS-22 | M | migrations `0005`-`0010`, `0015`-`0017`, `0020`-`0025`, `0035`, `0036`, `0038` | Unguarded `DROP TABLE` on downgrade. `0034` downgrade is lossy. | Use the `0028` refuse-if-rows pattern, or document as destructive. | Round-trip CI test |
| BE-OPS-23 | M | `app/code_mode_store.py:114-123`; `migrations/versions/0038_code_mode_runs.py:41-49` | User `input` (up to 8 KB) is stored unredacted forever. No quota. No list index. | Redact or hash, add retention purge, `(tenant_id,created_at DESC,id DESC)` index, daily cap. | 101st run rejected |
| BE-OPS-24 | M | `scripts/release.py:8-14` | Walks the filesystem rather than git, so it can ship `*.pem`, `*.key`, `compose.override.yaml` and the contents of `.env.local-stack/`. Drops any path segment named `data` or `platform`. Version hard-coded to `1.3.0`. | Build from `git ls-files` or `git archive`, then run `scan_secrets.py` on the staged tree. Single version source. | Scratch `x.pem` is not in the zip |
| BE-OPS-25 | M | `k8s/base/deployment.yaml`; `k8s/overlays/aks-loadbalancer*` | No container securityContext, NetworkPolicy, PDB or startupProbe. One replica. `:latest` image. `CLOUDSAVER_ENVIRONMENT=development` with a demo key, publicly exposed by the LoadBalancer overlays. | Harden. Pin by digest. Use `secretKeyRef`. LB overlays must refuse the dev env. | kubeconform and kube-linter in CI |
| BE-OPS-26 | M | `compose.yaml:366-391`; `platform/compose.yaml` | Postgres, Redis, dashboard, portal and identity have no limits, `cap_drop` or `no-new-privileges`. Redis has no `requirepass`. `maxmemory 128mb noeviction` means lease acquisition fails when it fills. | Redis ACLs with credentialed URLs, raise maxmemory, harden every service, alert on memory. | `docker compose config` / inspect |
| BE-OPS-27 | L/M | compose env | Every worker shares `cloudsaver_app`, which has UPDATE on the global `tenant_registry` (key hashes, webhook URLs). | Per-worker roles with minimal grants. | `\dp` |
| BE-OPS-28 | L/M | `.github/workflows/verify.yml:41`; `.github/dependabot.yml` | Coverage gate excludes `workers.*`, `database.*`, `app.drift.*`, retention, code mode and enterprise_store. No migration round trip and no non-superuser migration test. No single-head check, image build, Trivy, hadolint, compose or k8s validation. `ruff` runs `F821,F823` only. bandit runs `-lll -iii`. No docker ecosystem in Dependabot. | Add each gate (see §10). | PR that breaks each |
| BE-OPS-29 | L | `workers/lease.py:92-108`; `workers/tasks.py:287-291` | One Redis renew error marks the lease lost, and the scan fails only at the end. | Retry the renew and check `heartbeat.lost` inside the loop. | One injected timeout survives |
| BE-OPS-30 | L | `workers/delivery_worker.py:29`; `event_drift_worker.py:39` | A `NamedRedisLease` is created per intent and never closed, so sockets leak. | One client per cycle, then close it. | Connection count |
| BE-OPS-31 | L | `workers/billing_sync.py`, `observability_sync.py`, `grafana_k8s_rightsizing.py`, `data_retention.py`, `governance_monitor.py` | `run_once` ignores the stop flag. A standby that loses the advisory lock exits 0 and crash-loops. | Pass `should_stop`. Idle-retry the lock. | SIGTERM mid-sweep exit time |
| BE-OPS-32 | L | `scripts/start_stack.py:88-90,318,329,361,373-385` | Private keys are `chmod 0644`. `write_text` uses the default umask. `.env` is opened with `O_TRUNC` (a crash loses DB passwords). | Temp file plus rename with `fchmod 0600`. | File-mode check |
| BE-OPS-33 | L | Dockerfiles, compose, `database/Dockerfile`, k8s | Floating images (`python:3.12-slim`, `redis:7-alpine`, `pgvector:pg16`, `:latest`). Dependencies not hash-pinned. | Pin by digest. Add Dependabot docker. | CI lint for `@sha256` |
| BE-OPS-34 | L | `agent-worker/src/main.ts:10`; `connectors.ts:18-20` | Plain `http://` to the gateway is allowed unless env=production. The `states`, `inspected`, `disks` and `inspections` maps are never cleared. | Require https by default. Clear the maps per task. | Unit tests |
| BE-OPS-35 | L | `migrations/versions/0036_typed_resource_tables.py:20`; `0037` | `scan_id` FK is not composite with `tenant_id`, so a cross-tenant reference works as an existence oracle. `0037` grants duplicate the bootstrap grants, and its downgrade diverges. | `FOREIGN KEY (scan_id, tenant_id) REFERENCES scans(id, tenant_id)`. | Cross-tenant insert fails |

---

## 10. Test and CI gaps to close alongside the fixes

1. **Platform Postgres integration tests for billing:** webhook end-to-end (BE-PLAT-01, 02, 05, 06, 11), custom plan (BE-PLAT-07), entitlements (BE-PLAT-03).
2. **Store-contract suite** parametrised over `store_memory` and `store_postgres`. It would have caught BE-PLAT-01, 07 and 12.
3. **Static check** that every `actor_type`, `plan_tier` or status literal used in code appears in its migration CHECK.
4. **Portal route tests:** the `[...path]` ROUTES × roles × STEP_UP matrix, callback validation (state, nonce, iss, exp, tid, auth_time), `safeReturnPath` fuzz, and operator-key throttle.
5. **Dashboard unit tests** (none today): `session-contract.ts`, `resource-csv.ts`, `repo-docs.ts`, `resource-pages.ts`, `plan-outbox.ts`, `control-plane.ts#actionEvidenceFromResource`, scan-poll timers and the connect-while-polling race.
6. **Container smoke test** for the dashboard image (`/docs/*` returns 200; FE-DASH-03).
7. **Migrations:**
   - Single-head assertion.
   - `upgrade head → downgrade base → upgrade head` on seeded data.
   - Upgrade as a **non-superuser owner** (BE-OPS-05).
   - Fresh vs incremental schema diff (BE-OPS-21).
   - The same for `platform/identity_migrations`.
8. **Coverage gate** extended to `workers`, `database`, `app.drift`, `app.data_retention`, `app.code_mode_store`, `app.enterprise_store`, `app.collectors`, `app.analysis_service`.
9. **Security tests:**
   - SSRF: Grafana and DNS rebinding (BE-API-01, 07).
   - Cross-tenant `secret_ref` (BE-API-02).
   - `ExternalId` on every `aws_session` caller (BE-API-03).
   - Drift-ingest tenant binding (BE-API-04).
   - CustomerAdmin escalation (BE-PLAT-04).
10. **Money tests:**
    - Billing import of more than 5,000 rows (BE-DATA-01).
    - Commitment grain (BE-DATA-02).
    - Mixed currency (BE-DATA-03, 04).
    - Untagged and orphan-IP savings (BE-DATA-05, 06).
    - Unassessed scoring (BE-DATA-07).
11. **Infra gates:** `docker compose config`, image build, Trivy or Grype, hadolint, kubeconform and kube-linter, digest-pin lint, Dependabot `docker` ecosystem, broader `ruff` and `bandit` rule sets.
12. **CR-12 real-stack journeys:** at least one Playwright run against the composed stack (not fixtures) for connect → scan → resource drawer → plan → approval.

## 11. Closure rules

- A finding closes only with a code change **and** the listed verification test merged in the same PR.
- Coupled items (§2.2) close together.
- Do not reopen items listed as fixed in §1 without a failing regression test.
- Update this file's tables (add a `Status` note per row) as items close, rather than writing a new review doc.
