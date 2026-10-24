# Resource analysis and AI Foundry implementation

Source: [the resource-analysis and AI Foundry engineering guide](https://docs.google.com/document/d/19Ttsj8kI2HpvO7OsrXF8DzE6dB3NuBSQfVqcWFnkiHU).
Baseline: `1c7ae52364f654727566892d30c07e5d24b16ed6`, following the previous README implementation already merged to `main`.
Branch: `feat/resource-analysis-ai-foundry`.

This is a substantial implementation increment focused on the guide's resource-evidence and governed AI-configuration requirements. It does not complete every phase of the comprehensive blueprint. Existing access management, billing import/reconciliation and separate knowledge storage are retained.

## Delivered changes

| Area | Implementation |
| --- | --- |
| Canonical observations | Scans normalize resource/provider/service/scope/region, configuration snapshot, observed time, collector/schema version, protection signals and typed relationships. Duplicate identical inventory rows collapse; conflicting observations fail the scan. |
| Coverage | New `coverage_manifest` includes overall and provider/service coverage, the six resource counters, `failed_scopes`, and explicit baseline semantics. Unsupported, unknown and disabled evaluations never become passes. Collector failures still abort a snapshot; failed/partial scope findings are not silently merged into a clean baseline. |
| Telemetry | `TimeSeriesEvidenceContract` and structured results expose expected/valid samples, coverage, maximum gap, source window, observed value and a specific insufficiency reason. Five-minute, 30-day windows require >=95% valid samples, freshness <24 hours, no gap >60 minutes and verified resource age when required. Invalid, duplicate, nonfinite, negative and unaligned samples fail validation. |
| Rule results and protection | The eight-state taxonomy distinguishes evaluation failure, unsupported collectors and policy disablement. Protected resources retain their assessment results while destructive-action blocks remain explicit. Protection recognizes management locks, backup/replication enrollment and retention/migration tags when those facts are returned. |
| Dependency evidence | Azure ARG records returned VM–disk, VM–NIC, NIC–IP and app–plan relationships with timestamps and verification states. Only observed authorized nodes are exposed; inferred, unavailable or stale links cannot establish an opportunity group. |
| Financial overlap | Verified VM/disk/NIC/IP components share an opaque workload group when exactly one VM parent is known. Workspace/backend and frontend subtotals use the maximum competing alternative per group/resource. Unknown alternatives keep complete totals unknown. Multiple-parent ambiguity does not establish a group. |
| Resource UX | The resource drawer has eight sections: Overview, Evidence, Rules, Cost, Dependencies, AI Advice, History and Decisions. It separates five financial fields, exposes frozen rule outcomes/provenance and displays financial overlap. Collection timestamps alone no longer classify a configuration as changed in service comparisons. |
| Platform policy | New versioned operator policy controls global/provider kill switches, exact model/region allowlists, token/attempt ceilings and independent candidate-consent permission. The Platform portal has an AI guardrails editor. Empty allowlists allow nothing; the migration starts global inference disabled. |
| Plan enforcement | `can_use_ai_advisory` is projected and enforced in addition to operator policy and workspace opt-in. The new migration fills missing values for built-in Growth/Enterprise plans and defaults other plans to false. Explicit existing values are preserved. Plan authoring/override controls expose the entitlement. Old verify payloads lacking the flag fail closed for AI. |
| Workspace settings | `/settings/ai` and the Resource access settings tab provide three provider cards, approved binding selection, exact destination/identity details, bounded budgets, independent advisory/candidate toggles, acknowledgement, usage and diagnostic history. GET/PUT `/api/v1/settings/ai` are versioned; GET/PUT `/api/v1/settings` also carry the configuration block. |
| Binding validation | Workspace configuration cannot change a tenant-bound operator template's endpoint, model, region, identity or guardrail. Raw API-key fields are rejected. Azure root endpoints and provider identifiers are validated even when a provider is disabled. |
| Inference enforcement | API and background batch workers read fresh workspace preferences and current platform policy. Same-cloud affinity, entitlement, provider switches, approved regions/models and output/context/input limits apply before inference. Unknown Kubernetes hosting-cloud identity is blocked rather than guessed. |
| Durable budgets | SQL reservation uses the existing tenant transaction lock. It atomically reserves the full bounded input/output allowance under a UTC calendar-month cap. Pending, uncertain and partially metered attempts retain their reservation. Only complete provider metering releases unused capacity. Legacy unmetered attempts without a reservation block capped inference for the applicable period. Cached completed attempts do not reserve again. |
| Bedrock | Converse attaches the approved guardrail identifier/version. Production rejects DRAFT guardrails. Cross-region inference profiles are read before invocation and rejected if their model destinations are inactive, unverified or outside current approved regions. |
| Diagnostics | POST `/api/v1/settings/ai/test-connection` performs bounded identity/metadata reads with no model invocation or client-resource payload. Append-only records are tenant-isolated, with three diagnostic attempts/minute. Inference RBAC/quota and retention controls remain explicitly unverified; metadata success is not presented as full readiness. |
| Transparency/quality | Pre-inference disclosure identifies provider/model/region, source policy, knowledge configuration and the last measured hourly quota. AI results display deterministic confidence and validated publication references. Numeric currency claims, unsupported check/publication citations, code/links/commands and protected-resource change suggestions fail response validation. No client-contribution or training pipeline is activated. |

## Storage and migrations

Apply owner-role migrations before starting the updated runtime:

```bash
# Platform database, with PLATFORM_IDENTITY_MIGRATION_URL from secret storage
cd platform
python -m alembic -c identity_alembic.ini upgrade head
# New head: i0011_ai_foundry_policy

# CloudSaver database, with CLOUDSAVER_MIGRATION_URL from secret storage
cd ..
python -m alembic upgrade head
# New head: 0015_ai_foundry_diagnostics
```

`0015` creates forced-RLS, INSERT/SELECT-only diagnostic history. It deliberately leaves the reserved legacy-billing removal migration untouched. Existing commercial data is not dropped.

AI preferences remain in the existing versioned tenant-registry JSON configuration and survive directory snapshot projection. Writes emit `ai_settings_updated` in the same transaction. Diagnostic starts/completions are append-only. The Platform policy lives in its own forced-RLS control-plane table, and policy updates emit `ai_policy_updated`.

The optional knowledge database still uses its independent credentials and `k0001_publications` migration. See [the previous implementation guide](IMPLEMENTATION_STATUS.md) for provisioning and publication review.

## Activate governed inference

1. Keep `CLOUDSAVER_AI_ENABLED=false` until migration, binding and policy review are complete. There is no automatic cloud scan, model invocation, payment operation or deployment in this implementation task.
2. Register tenant-specific, non-secret `CLOUDSAVER_AI_TARGETS` in the deployment configuration. Azure entries now need an approved destination region for governed routing. Target identity bindings remain operator-owned; users select a registered binding rather than supplying arbitrary endpoints or identities.
3. In Platform portal → Settings → AI platform guardrails, populate exact model and region allowlists and appropriate ceilings. Enable only reviewed providers. Keep cross-provider routing disabled.
4. Ensure the verified subscription/plan includes `can_use_ai_advisory`. Plan entitlement alone does not enable either workspace consent or the deployment switch.
5. Configure the workspace through `/settings/ai` or Settings → Resource access. Choose an approved binding, set bounded budgets, independently select advisory consent and acknowledge the destination. Optimistic version conflicts require refresh; changes are not silently retried.
6. Run identity/metadata diagnostics. Azure deployment metadata additionally needs the optional operator `azure_resource_id` on the target. A successful token or metadata read does not prove permission to invoke the model, available paid quota, PTU capacity, private-network connectivity for inference, ZDR or abuse-monitoring opt-out.
7. Enable the deployment switch only for an approved rollout. `CLOUDSAVER_AI_HOURLY_ATTEMPTS` remains an additional deployment ceiling. The effective attempt quota is the minimum of deployment, platform and workspace limits; each approved target can further narrow input/output limits.

Identity and shadow-verifier modes fetch live policy from the authenticated Platform internal endpoint. Policy-read failure blocks inference. An explicitly local verifier can use `CLOUDSAVER_AI_PLATFORM_POLICY` with the versioned envelope in [the contract fixture](../platform/contracts/fixtures/ai-policy-v1.json); leaving it unset fails closed.

The guide explicitly requires writes to remain locked during `CLOUDSAVER_DIRECTORY_MODE=cutover`. This implementation retains that restriction. Preferences configured before cutover are preserved and enforced; self-service writes require a registry-managed configuration workflow. Do not change verifier or directory mode merely to bypass governance.

Monthly enforcement uses the **UTC calendar month**. The usage display separately reports the preceding 30 days. The input-token check uses a conservative UTF-8/escaped-text allowance plus protocol framing, not a claim of exact provider tokenization. No provider pricing, billable money, or model-accuracy rate is inferred from tokens.

## Boundaries still requiring implementation or provider acceptance

- Full Azure Monitor/CloudWatch/Cloud Monitoring history collectors, complete attachment transitions, snapshot/backup/ASR discovery and exhaustive lock/dependency verification. The new telemetry module validates evidence supplied to it; it does not manufacture missing history. ARG explicitly marks unsupported high-resolution rule contracts.
- Time-bounded scoped rule-exception administration and policy rollout approvals. The outcome taxonomy reserves exception semantics; no exception is fabricated from a missing metric or a protection tag.
- Compatible target SKU modeling, period/currency-specific billed-cost attribution in the drawer, snapshot/transfer overhead and verified post-change realized savings. Those financial fields remain unknown without the required evidence.
- The guide's six-state decision lifecycle; the existing accept/dismiss/defer workflow and evidence-change warnings remain.
- Self-registration of arbitrary tenant endpoints, custom managed-identity overrides, workspace-specific GCP WIF-provider overrides, PrivateLink endpoint settings, AI Search/RAG endpoint configuration and verified provider retention/VPC-SC attestations. Current configuration selects validated operator templates.
- Human OIDC/PKCE sessions, capability subsetting and verified fresh step-up. Cross-provider routing is rejected until that proof is supported. A key or consent checkbox is not treated as fresh human reauthentication.
- Authoritative Kubernetes hosting-cloud identification. Same-cloud policy blocks Kubernetes inference while this is unknown.
- Client-derived knowledge contributions, private structured feedback, semantic indexing, automatic public-source ingestion and empirically calibrated model-accuracy/citation benchmarks. Candidate consent does not activate data sharing; HIGH confidence is not fabricated from incomplete telemetry.
- Live Azure, Bedrock, Vertex, Entra and billing acceptance. Offline SDK fixtures and browser interception verify application behavior, not remote permissions or end-to-end provider readiness.

Before rolling back to software that predates these workspace policy controls, disable deployment AI and stop batch workers. Restore a matching database/configuration backup; older binaries do not enforce the new preferences and entitlements.

## Verification

Validation completed:

- Full backend suite with disposable PostgreSQL 16 and Redis 7: **674 passed**. This includes both migration chains, tenant RLS, diagnostic append-only grants, identity policy and concurrent inference reservations.
- After the additional private-dependency filtering fix, the relevant resource-evidence, inventory-scope and identity API suites: **45 passed**.
- Dashboard browser suite: **37 distinct workflows passed**, including automated accessibility checks. The first run passed 36 workflows and found a missing mock for active-batch polling in the new resource-drawer test. After adding that response, all four AI Foundry/resource-drawer workflows passed on retry.
- Dashboard and Platform portal production builds (`npm run build -- --webpack`) passed, including TypeScript validation. A final dashboard `npm run typecheck` also passed after the browser fixture correction.
- `git diff --check` passed.

Tests use synthetic evidence, disposable PostgreSQL/Redis instances, SDK stubs and intercepted browser APIs. No live model inference was performed. Temporary test infrastructure was removed; the existing local deployment was not changed.

Both frontend builds include TypeScript validation. Local Node is 24.19.0; production should use the repository's supported Node >=24.22.1 image. The Python suite reports an upstream Starlette/httpx deprecation warning.
