# Platform billing — operations and implementation boundaries

This guide describes **what the current source revision actually does** for commercial billing on the platform stack and how CloudSaver consumes it. Target behavior lives in [approved billing architecture](../specs/approved/2026-10-23-platform-separation-billing.md) and [admin billing API contract](../platform/contracts/admin-billing-v1.md). When those documents disagree with registered routes and handlers, **trust the runtime sources** listed at the end of this page.

Configuration for billing flags and Stripe secrets is **platform-only** (`platform/.env`); see [Environment reference](ENVIRONMENT.md#billing-platformenv-only).

---

## Payment providers and Stripe

- **Manual** subscription and payment creation endpoints record ledger and directory state in the platform database. They do **not** become Stripe API operations when `PLATFORM_BILLING_PROVIDER` is set to `stripe`.
- The admin settings response `provider.configured` checks whether both Stripe secret **environment variables** are non-empty. It does **not** resolve optional Key Vault fallbacks or prove end-to-end webhook readiness.
- Comments and helpers describing fail-fast provider configuration (`load_provider` in `providers.py`) do **not** by themselves establish that application startup invokes that loader on every deployment path. Verify startup behavior in your environment before assuming Stripe is live.
- Legacy CloudSaver **checkout** and **billing webhook** routes return HTTP **410**. They are not a workaround for platform billing. Do not route real payments through this revision on the assumption that a configuration flag completes the integration.

---

## Storage, migrations, and audit

### Schema ownership

| Schema / area | Billing-related records |
| --- | --- |
| `directory` | Customer billing contact/reference fields and stored billing state; workspaces and projected entitlement metadata |
| `billing` | Plans, settings, subscriptions, payments, provider events, and plan-change requests |
| `identity` | Keys, cache invalidation events, and identity-related metadata |
| CloudSaver application database | Workspace directory/plan projection and legacy billing compatibility state |

The platform database and CloudSaver application database have **separate migration histories**. Their migrations are not interchangeable.

### Relevant migration files

| Migration | Purpose |
| --- | --- |
| Platform `i0001_directory_identity` | Base directory and identity schema |
| Platform `i0002_billing` | Billing schema, catalog/settings seeds, customer/workspace billing fields, provider events, and cache event support |
| Platform `i0003_resource_access` | Resource access settings, separate from commercial charging |
| Platform `i0004_plan_change_requests` | Plan-change approval queue and review metadata |
| CloudSaver `0013_billing_projection` | Local billing/entitlement projection compatibility changes |

The billing seed migration stores **partial** seed entitlement JSON; the service view enriches known plans with catalog defaults. Raw database rows can differ in shape from the plan API response.

The current subscription uniqueness constraint is customer-scoped and excludes only `canceled` / `expired` statuses. Payment external references and provider event identifiers have separate uniqueness constraints. Plan-change requests have queue indexes but **no** database uniqueness constraint enforcing one pending request per workspace.

### Isolation and audit boundaries

Billing tables enable and force PostgreSQL RLS, but the inspected policies grant the internal `identity_app` role access using `USING (true)` and `WITH CHECK (true)`. This is privileged service access, not automatic per-customer row isolation. Operator authorization, internal service credentials, network boundaries, and explicit customer/subscription ownership checks remain essential.

Registered operations produce audit events such as `billing_settings_updated`, `subscription_created`, `subscription_changed`, `payment_recorded`, `plan_change_requested`, `plan_change_pending_payment`, and `plan_change_rejected`. Manual plan approval records a workspace update linked to the request. Event actor fields and request correlation IDs support review; they are **not** a substitute for externally verified financial settlement.

An export helper exists in [`scripts/export_billing.py`](../scripts/export_billing.py), but the proposed `platform/identity/billing/importer.py` module is **absent**. Do not use an importer command from a design document as if it were an available migration tool.

---

## Implementation gaps and operational implications

The approved billing specification and API contract describe a broader target than the registered runtime. This table separates those targets from observed behavior.

| Area | Current source behavior | Operational implication |
| --- | --- | --- |
| Plan catalog administration | Read endpoints exist; create/edit/retire routes are absent | Do not promise self-service custom plan management |
| Published prices | Seed prices are null | Confirm agreed pricing separately; null is not free |
| Subscription detail/cancel actions | List/create/PATCH exist; dedicated detail and cancel action routes are absent | Do not assume every contract route is usable |
| Subscription plan changes | PATCH does not parse `plan_code` | A successful PATCH is not proof of a plan change; inspect its response |
| Overrides during creation | Subscription creation stores no overrides | Apply supported overrides with a subsequent versioned PATCH |
| Override enforcement | Customer-level effective view works; complete grant/snapshot plan block is missing | CloudSaver may keep using local fallback limits |
| Manual workspace approval | Updates the requested workspace only | Commercial subscription and other workspaces can diverge |
| Customer subscription creation | Applies its tier to existing customer workspaces when billing is enabled | Review multi-workspace impact before creation |
| Manual payments | Ledger create/list only | No fund collection, automatic service extension, refund execution, or payment editing |
| Stripe mode | Partial helpers, forwarder, and queue status | No complete Checkout or webhook-to-entitlement flow |
| Automatic renewals | Period/interval fields are stored | No demonstrated invoice generation or automatic period advancement |
| Lapsed account actions | Policy settings and state derivation exist | No fully wired downgrade/suspension evaluator |
| Key issuance policy | `issuance_blocked` is returned by entitlement reads | Current issue/rotate paths do not enforce that billing guard |
| Retention | Catalog value exists | No automatic purge guarantee follows from the plan value |
| Customer billing overview | Stored state and bounded post-fetch filters | State can lag; filtered pagination is not an accounting export guarantee |
| Pending request protection | Service pre-insert lookup | Concurrent duplicates are not prevented by a dedicated unique constraint |
| API contract/BFF allowlist | Includes some target routes without handlers | An allowed proxy path or visible UI action does not prove backend support |

For a production billing rollout, resolve the relevant gaps before presenting the corresponding features as available. In particular, financial settlement, subscription terms, workspace assignment, and observed entitlement enforcement must be reconciled independently in this revision.

---

## Troubleshooting

| Symptom | Likely explanation | What to inspect |
| --- | --- | --- |
| HTTP 401 on platform admin calls | Missing/invalid internal caller credential or operator session/token | Portal service configuration, session, and token audience |
| HTTP 403 for customer plan actions | Workspace principal lacks BillingAdmin/TenantAdmin access | Current workspace membership and effective role |
| Billing buttons hidden or disabled | Session billing flag is off, or user is not a platform operator | Effective environment flags and refreshed portal session |
| HTTP 409 on subscription creation | Customer already has a non-ended subscription | Current/history response and stored status, not just end date |
| HTTP 409 on plan request/review | Pending request exists, request is already reviewed, or version is stale | Reload current pending request/version before retrying |
| HTTP 409 recording payment | Non-void reference already exists for the customer | Existing payment ledger; avoid duplicate settlement entries |
| HTTP 422 on customer plan request | Invalid plan/body, no associated customer, or rejected upstream input | Strict `plan_tier`/`version` payload and workspace customer link |
| HTTP 503 on request submission/status | Identity request service unavailable | Service URL, internal credentials, network access, and service health |
| Plan list succeeds but pending request is absent | Plan listing suppresses pending-lookup unavailability | Explicit request-status endpoint and identity availability |
| Stripe webhook gets upstream 404 | Identity webhook receiver is not registered | Current implementation gap, not only the public portal URL |
| Request disappears after Stripe approval | Default queue shows pending approval only | Query `status=pending_payment`; no Checkout URL is generated |
| Workspace tier changed but commercial plan did not | Manual approval is workspace-scoped | Customer subscription and requested workspace separately |
| Override visible in platform but not in CloudSaver | Complete plan block was not projected | Workspace directory payload, effective source, and fallback limits |
| Payment exists but account remains past due | Payment creation does not renew/update the subscription | Subscription status and period, confirmed commercial instructions |
| Tier PATCH returns success but plan is unchanged | `plan_code` is not parsed by that handler | Returned subscription fields and supported operations |
| Customer list shows old billing state | Overview reads stored state; time-based evaluator is incomplete | Entitlement endpoint's derived state versus persisted state |
| HTTP 402/403 on a paid feature | Effective plan restriction, fallback values, or missing separate permissions | Effective entitlements, scope/key grants, and cloud access configuration |

Never resolve a stale version by overwriting another operator's changes. Reload, compare the current record, and submit a new intentional update.

---

## Source references

Runtime sources take precedence over target specifications when describing what is currently registered and connected.

| Topic | Path |
| --- | --- |
| Billing catalog and entitlement validation | [`platform/identity/billing/catalog.py`](../platform/identity/billing/catalog.py) |
| Billing vocabulary, money/date validation, and state calculation | [`platform/identity/billing/domain.py`](../platform/identity/billing/domain.py) |
| Billing admin operations | [`platform/identity/billing/admin.py`](../platform/identity/billing/admin.py) |
| Provider helpers and Stripe event handling | [`platform/identity/billing/providers.py`](../platform/identity/billing/providers.py) |
| Identity app and registered routes | [`platform/identity/app.py`](../platform/identity/app.py) |
| Identity service and plan-request review | [`platform/identity/service.py`](../platform/identity/service.py) |
| Billing API contract (includes target endpoints) | [`platform/contracts/admin-billing-v1.md`](../platform/contracts/admin-billing-v1.md) |
| Approved architecture specification (target design) | [`specs/approved/2026-10-23-platform-separation-billing.md`](../specs/approved/2026-10-23-platform-separation-billing.md) |
| Initial billing migration | [`platform/identity_migrations/versions/i0002_billing.py`](../platform/identity_migrations/versions/i0002_billing.py) |
| Plan-change request migration | [`platform/identity_migrations/versions/i0004_plan_change_requests.py`](../platform/identity_migrations/versions/i0004_plan_change_requests.py) |
| Customer workspace billing routes | [`app/settings_api.py`](../app/settings_api.py) |
| CloudSaver entitlement normalization and enforcement | [`app/entitlements.py`](../app/entitlements.py) |
| CloudSaver directory projector | [`app/directory_projector.py`](../app/directory_projector.py) |
| CloudSaver plan response | [`app/billing_plan.py`](../app/billing_plan.py) |
| Portal request queue | [`platform/portal/components/billing/PlanChangeQueue.tsx`](../platform/portal/components/billing/PlanChangeQueue.tsx) |
| Portal Stripe webhook forwarder | [`platform/portal/app/api/webhooks/stripe/route.ts`](../platform/portal/app/api/webhooks/stripe/route.ts) |
| Portal API proxy and authorization | [`platform/portal/app/api/portal/[...path]/route.ts`](../platform/portal/app/api/portal/%5B...path%5D/route.ts) |
| Environment reference | [ENVIRONMENT.md](ENVIRONMENT.md) |

Application behavior and deployment configuration remain those of the referenced source revision unless a later change explicitly updates this guide.
