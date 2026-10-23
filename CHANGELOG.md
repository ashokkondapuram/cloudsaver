# CloudSaver changelog

## v1.3.0 — Platform separation and platform-managed plans (Oct 23, 2026)

- Move identity-service, the platform database, the platform portal and their tests into `platform/`, a separate
  product (platform 1.0.0) with its own compose project, images, `.env` and Redis. CloudSaver reaches
  identity-service only over the internal, external-named network `platform-link`.
- Stop sharing code with the platform in both directions. Boundary tests fail on cross-imports, and the
  versioned HTTP contract `platform/contracts/identity-v1.md` has shared JSON fixtures.
- Replace the Redis revocation subscriber with the identity-service long-poll endpoint `/internal/v1/events`.
  The grant cache turns off while polling fails, and directory events trigger an immediate projector sync.
- Take plan limits from platform entitlements (verify response and directory projection) instead of the
  hard-coded plan table, which remains only as a logged fallback. Migration `0013_billing_projection` adds the
  projected billing columns.
- Remove Stripe from CloudSaver: the checkout and webhook endpoints return `410`, and the `stripe` dependency,
  settings and code are gone. `scripts/export_billing.py` exports existing billing data for the platform
  importer. The old Stripe columns and `stripe_events` become read-only and are dropped in 1.4.0.
- Dashboard: a Plan tab with Manage billing or "Contact your account manager", past-due and lapsed banners,
  "Not included in your plan" gates, and "Cloud billing data" naming.
- `scripts/setup_compose.py` keeps only CloudSaver's caller tokens and adds `--prune-platform`. Start the
  platform first with `make platform-up` (or `make up` for both).

## v1.0.0 — Durable AI evidence and billing-backed FinOps

- Apply the exact Drive v1.0.0 master guide to the current verified code, preserving the original Drive artifact and documenting the inspected ZIP's older implementation.
- Add SQL-persisted inference attempt intent, permanent idempotency fences, finalized outcomes, lifecycle events and provider-reported usage by model/target/structured observed attribution.
- Harden permitted boundary-value monetary ratios/projections with isolated decimal precision and a regression test.
- Add finance-only normalized FOCUS-subset imports, decimal-preserving monetary records, current cloud scope enforcement, transactional deduplication and currency-isolated billing summaries.
- Derive provisional month-end projections and 30-day nonseasonal Z-scores only from sufficient closed-day coverage; keep missing data, unreconciled billing and realized savings explicit.
- Add migration 0009 with forced RLS on four evidence tables, append-only runtime billing/audit grants and protected terminal inference outcomes.
- Add billing upload/coverage/budget controls and saved AI assessment/usage inspection to the console, with keyboard-accessible scroll regions and late-response cancellation.
- Run at most four independent cloud readers concurrently, retaining stable results and all-or-nothing failure behavior.

## v0.11.0 — Core assessment and enterprise AI governance

- Expand saved-evidence service checks with a versioned policy, explicit inputs/gaps, freshness, reproducible fingerprints and bounded risk-prioritized review queues.
- Require complete typed Kubernetes P95 summaries; retain explicit Azure encryption/plan controls and AWS upgrade configuration without extra cloud calls.
- Validate current cloud scope across the entire analysis snapshot, including summary requests.
- Bound target context/output and source providers; validate pillar citations, observed-risk floors and terminal provider responses; expose provider-reported token usage with unknown billed cost.
- Add console provenance, stale-evidence warnings, review queue drill-down and usage disclosure. Keep independent approval, protected intent and keyless identity.

## v0.10.0 — Advanced console experience

- Apply the newest Drive UI/UX guide to the latest v0.9.0 code: default dark slate theme, explicit remembered light preference, matching chart colors and 64px collapsed navigation.
- Add counted cloud/category facets, protected/unpriced quick views, scope/rule token search, exact tag-existence queries, observed sizing and pricing-coverage summaries.
- Add filtered/sorted drawer comparison, a five-pillar evidence radar, contained pillar navigation, telemetry facts and keyboard tab endpoints.
- Keep unknown data explicit and server permissions authoritative. Protected intent blocks Bash export in the UI, while review-only Terraform stays available when permitted.
- Expand browser and accessibility verification across both themes and all six workspace views.

## v0.9.0 — Evidence-led service analysis and cloud AI advisory

- Add five-pillar resource assessments and service/category breakdowns, preserving unknown billing, dependencies and incomplete telemetry.
- Retain observed cloud tags and AWS configuration facts. Block destructive scripts for protected intent and re-read live tags; require a successful managed snapshot and post-snapshot attachment check before disk deletion.
- Add opt-in, operator-bound Azure OpenAI/Bedrock/Vertex advisory using keyless identities, minimized context, explicit admin acknowledgement and strict output validation.
- Coordinate inference with tenant-scoped atomic Redis attempt budgets, idempotency, cached results, uncertain-attempt suppression and fenced completion.
- Add dashboard assessment/context/advisory workflows with stale-request cancellation, accessible native-dialog handling and service-level evidence views.
- Preserve upstream v0.8.0 registry/settings/managed-identity work. Document activation, source mapping and remaining guide milestones.

Earlier release source and verification packages remain available in the project Drive folder. See repository history for their changes.
