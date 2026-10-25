# AI assessments

AI assessments let you ask an operator-approved large language model for an advisory review of a resource or finding, using only a sanitized, allowlisted evidence context. You can run per-finding AI risk advisories, queue background AI assessments for up to 500 resources at a time, and ask up to five follow-up questions per resource per scan. Every attempt is recorded in a durable inference ledger, governed by a platform policy and a purpose-bound data governance approval, and is always advisory: CloudSaver never executes a model suggestion. AI is off by default and stays blocked until the operator, the platform policy and a workspace administrator all enable it. This page reflects the code as of Oct 25, 2026.

## Where to find it

- **Resources** (`/resources`): **Run AI assessment** in the page header (admins only), the batch progress banner, the **AI status** and **AI risk** filters, and the **AI** tab of the **Resource details** drawer with **Ask question**.
- **Resource details > Findings**: the **AI risk advisory** section with **Request AI advisory** (admins only) and "Inspect the exact evidence sent to the model".
- **Settings > AI & data governance** (`/settings?tab=ai`): **AI Foundry configuration** (provider bindings, policy, budgets and **Test connection**) and the data governance workspace (retention, legal holds and erasure).
- **Activity** (`/activity`), **AI assessments** tab: the assessment history and 30-day usage.
- Who can see it: any workspace role can read AI results, history, usage and governance status. Only `TenantAdmin` can start, cancel or configure AI processing.

## What you can do

- **Run AI assessment** for selected resources or all resources in a scan. Choose an available target, acknowledge external processing of the sanitized context, then select **Start assessment**. Only one batch can be active per scan.
- **Follow batch progress**: the banner shows whether the batch is in progress, paused until the hourly limit resets, cancelled or completed. Admins can **Cancel** queued items.
- **Review AI results** in the drawer's **AI** tab: advice, confidence band, validation block and warning, alongside the deterministic assessment.
- **Ask question** about a resource (3 to 500 characters, up to 5 per resource per scan). The question must reference the current evidence digest.
- **Request AI advisory** for a single finding from the Findings tab, after inspecting the exact payload.
- **Configure AI Foundry** (admins): bind each provider to an operator-approved target, set the routing mode, primary provider, token limits, hourly attempt budget and optional monthly token limit, then select **Save AI configuration**. Use **Test connection** for a non-invoking metadata check.
- **Govern AI data** (admins): **Place legal hold** (expiry within 30 days), **Erase AI content** and **Release hold**, each with a review reference.
- **Audit usage**: page through AI assessment history and view token usage grouped by provider, model, target, cost center and application.

## How it works

1. **Targets and gateway**: `AIGateway` in [app/ai_advisory.py](../../app/ai_advisory.py) loads operator-approved targets from `CLOUDSAVER_AI_TARGETS`. Each target fixes the tenant, provider (`azure`, `aws` or `gcp`), model, region or endpoint, authentication (`customer_federated`, or `managed_identity` for Azure), token and context limits, and allowed source providers. `available()` returns only targets that pass the workspace settings, the platform policy and a current data governance processor approval.
2. **Platform policy**: [app/ai_platform_policy.py](../../app/ai_platform_policy.py) reads the current policy from the identity service (`/internal/v1/ai-policy`) when `CLOUDSAVER_KEY_VERIFIER` is `identity` or `shadow`, otherwise from `CLOUDSAVER_AI_PLATFORM_POLICY`. If the policy can't be read or validated, inference is blocked with 503; there's no permissive fallback.
3. **Workspace settings**: `FoundryController` in [app/foundry.py](../../app/foundry.py) with schemas in [app/foundry_config.py](../../app/foundry_config.py) stores versioned `ai_foundry` preferences in the tenant registry. Only `same_cloud_only` routing is accepted, bindings must match approved targets exactly, the plan must allow AI advisory, and Kubernetes sources are excluded from same-cloud inference. The effective hourly limit is the lowest of the workspace budget, the platform ceiling and the deployment limit. [app/foundry_diagnostics.py](../../app/foundry_diagnostics.py) runs metadata probes that never invoke a model.
4. **Context and data governance**: [app/assessment.py](../../app/assessment.py) builds an allowlisted `ai_context` (no names, IDs or tags). [app/data_governance.py](../../app/data_governance.py) and [app/data_policy.py](../../app/data_policy.py) sanitize the context (dropping identifiers and billed cost, redacting IDs, emails and IP addresses, blocking secrets), check the processor approval for the purpose (`assessment`, `resource_assessment`, `followup` or `agent_planning`), issue a 60-second processing grant, record an `ai_data_events` row and sanitize model output.
5. **Provider call**: `CloudAdapter` calls Azure OpenAI or Azure AI Foundry chat completions, Amazon Bedrock `converse` (with optional guardrail) or Vertex AI `generateContent`, at temperature 0 with JSON output. Responses with tool calls or incomplete finishes are rejected.
6. **Ledger and budget**: [app/inference_ledger.py](../../app/inference_ledger.py) claims each attempt idempotently by request key in `ai_inference_attempts` (status `pending`, `completed` or `uncertain`) and `ai_inference_events`, enforces the hourly attempt budget from the top of the hour and the monthly token reservation per UTC calendar month, and attributes usage to cost center and application tags kept only in the ledger.
7. **Background batches**: [app/resource_api.py](../../app/resource_api.py) creates batches in `ai_batches` and `ai_batch_items` ([app/resource_store.py](../../app/resource_store.py)). The Celery task `process_ai_batches` in [workers/tasks.py](../../workers/tasks.py) runs every `CLOUDSAVER_AI_BATCH_TICK_SECONDS` under a Redis lock and calls `process_batches` in [app/resource_batches.py](../../app/resource_batches.py). Items are skipped when the resource is missing or its evidence changed, marked `uncertain` after 15 minutes stuck, and the batch moves to `waiting_for_budget` when the hourly limit is reached.
8. **Per-finding advisory**: `POST /api/v1/scans/{scan_id}/ai-risk-evaluation` in [app/assessment_api.py](../../app/assessment_api.py) checks the evidence digest and calls `gateway.evaluate`.
9. **Retention**: [app/data_retention.py](../../app/data_retention.py) tracks `ai_data_retention` and `ai_data_holds`. The worker [workers/data_retention.py](../../workers/data_retention.py) purges expired content that isn't on hold every 600 seconds. [app/data_governance_api.py](../../app/data_governance_api.py) exposes status, erase, hold and release.

Each AI response carries `advisory_only: true`, `automatic_execution: false`, a `confidence_band`, a `validation` block with `semantic_claims_verified: false` and a warning.

## API reference

Paths are the same on the core API and the API gateway ([services/gateway.py](../../services/gateway.py)), which applies a 120 requests per minute per workspace limit.

| Method | Path | Purpose | Required role/scope |
| --- | --- | --- | --- |
| GET | `/api/v1/ai/targets` | Effective AI availability, limits, usage and targets | Any workspace role; `agnostic` |
| GET | `/api/v1/ai/assessments` | Assessment history. Query: `limit` (1–50, default 25), `before`, `scan_id`, `resource_reference` | Any workspace role; `scoped_read` |
| GET | `/api/v1/ai/assessments/{assessment_id}` | One assessment record | Any workspace role; `scoped_read` |
| GET | `/api/v1/ai/usage` | Token usage. Query: `days` (1–90, default 30) | Any workspace role; `scoped_read` |
| POST | `/api/v1/scans/{scan_id}/ai-batches` | Queue a background AI assessment. Body: `resource_keys` (up to 500) or `all`, `target_id`, `idempotency_key`, `acknowledge_external_processing` | `TenantAdmin`; `scan_write` |
| GET | `/api/v1/ai-batches` | List batches. Query: `scan_id`, `limit` (1–50, default 20) | Any workspace role; `scoped_read` |
| GET | `/api/v1/ai-batches/{batch_id}` | One batch with item counts | Any workspace role; `scoped_read` |
| POST | `/api/v1/ai-batches/{batch_id}/cancel` | Cancel queued items | `TenantAdmin`; `scoped_read` |
| POST | `/api/v1/scans/{scan_id}/resources/{resource_key}/questions` | Ask a follow-up question. Body includes `question`, `target_id`, `idempotency_key`, `evidence_digest`, `acknowledge_external_processing` | `TenantAdmin`; `scan_write` |
| POST | `/api/v1/scans/{scan_id}/ai-risk-evaluation` | Per-finding AI risk advisory | `TenantAdmin`; `scan_write` |
| GET | `/api/v1/settings/ai` | Workspace AI Foundry settings and effective policy | Any workspace role; `full_scope` |
| PUT | `/api/v1/settings/ai` | Save versioned AI Foundry settings. Body: `version`, `ai_foundry`, `acknowledge_external_processing` | `TenantAdmin` (unrestricted); `full_scope` |
| POST | `/api/v1/settings/ai/test-connection` | Non-invoking metadata probe. Body: `provider`, `target_id` | `TenantAdmin`; `full_scope` |
| GET | `/api/v1/ai/governance` | Data governance status, retention and holds | Any workspace role; `scoped_read` |
| POST | `/api/v1/ai/governance/records/{attempt_id}/{decision}` | Erase or hold an AI record (`decision` is `erase` or `hold`) | `TenantAdmin` human user; `full_scope` |
| POST | `/api/v1/ai/governance/holds/{hold_id}/release` | Release a legal hold with a reason and ticket | `TenantAdmin` human user session with full workspace access; `full_scope` |

Common errors: 429 when the hourly budget is reached (with `Retry-After: 3600` on follow-ups), 409 for a pending or uncertain attempt, an idempotency mismatch, changed evidence or an active batch conflict, 422 for an oversized context or missing acknowledgement, and 503 when the platform policy is unavailable.

## Data and evidence

- **Tables**:
  - Inference: `ai_inference_attempts`, `ai_inference_events`.
  - Batches and questions: `ai_batches`, `ai_batch_items`, `ai_followups`.
  - Diagnostics: `ai_connection_diagnostics`.
  - Governance: `ai_data_retention`, `ai_data_holds`, `ai_data_events`.
  - Migrations: [migrations/versions/0009_enterprise_evidence.py](../../migrations/versions/0009_enterprise_evidence.py), [migrations/versions/0010_resource_assessment.py](../../migrations/versions/0010_resource_assessment.py), [migrations/versions/0015_ai_foundry_diagnostics.py](../../migrations/versions/0015_ai_foundry_diagnostics.py), [migrations/versions/0018_ai_data_governance.py](../../migrations/versions/0018_ai_data_governance.py).
- **What's sent**: only the sanitized, allowlisted facts in `ai_context`. Names, resource IDs, tags and billed cost aren't sent. You can inspect the exact payload in the dashboard before sending.
- **What's stored**: request and response metadata, token counts, status, purpose, target and attribution. Response content is retained for the policy's `response_retention_days` (1 to 30, default 7) unless held.
- **Usage**: token usage is reported, but `billed_cost_available` is false; usage isn't a billed AI cost.
- **Not proven**: AI output is advisory. `semantic_claims_verified` is false, and the deterministic assessment and current evidence remain the source of truth.

## Permissions

- Reading targets, results, history, usage, batches and governance status: any workspace role.
- Starting batches, cancelling batches, asking questions and requesting per-finding advisories: `TenantAdmin`.
- Saving AI Foundry settings: an unrestricted `TenantAdmin`. Test connection: `TenantAdmin`.
- Erase and hold: `TenantAdmin` acting as a human user, not a service account. Release: a `TenantAdmin` human user session with full workspace access, not a key-based session.
- Keys restricted to some providers or scopes can't call `full_scope` routes and only see batches for visible scans ([app/provider_access.py](../../app/provider_access.py), [app/route_inventory.py](../../app/route_inventory.py)).
- The dashboard hides admin-only controls unless you hold `TenantAdmin` ([web-dashboard/components/WorkspaceProvider.tsx](../../web-dashboard/components/WorkspaceProvider.tsx)).

## Configuration

Variable names only; never commit secret values. See [docs/ENVIRONMENT.md](../ENVIRONMENT.md) for full details.

| Variable | Purpose | Default |
| --- | --- | --- |
| `CLOUDSAVER_AI_ENABLED` | Deployment switch for AI processing and the batch worker | Off (unset) |
| `CLOUDSAVER_AI_TARGETS` | JSON list of operator-approved targets (for example `[{"target_id": "YOUR_TARGET_ID", "tenant_id": "YOUR_TENANT_ID", ...}]`) | `[]` |
| `CLOUDSAVER_AI_HOURLY_ATTEMPTS` | Deployment hourly attempt limit (1 to 100) | `10` |
| `CLOUDSAVER_AI_PLATFORM_POLICY` | JSON platform AI policy when the identity service isn't used | `{}` (blocks inference) |
| `CLOUDSAVER_KEY_VERIFIER` | `identity` or `shadow` reads the platform policy from the identity service; `local` uses `CLOUDSAVER_AI_PLATFORM_POLICY` | `local` |
| `CLOUDSAVER_DATA_ENVIRONMENT_ID` | Must match the policy's registered `environment_id` | Unset (blocks processing) |
| `CLOUDSAVER_DATA_AZURE_TENANT_ID` | Must match the policy's `azure_tenant_id` for Azure processors | Unset |
| `CLOUDSAVER_AI_BATCH_TICK_SECONDS` | Batch worker interval | `30` |
| `CLOUDSAVER_AI_BATCH_ITEMS_PER_TICK` | Items processed per worker tick | `10` |
| `CLOUDSAVER_ENVIRONMENT` | `production` rejects Bedrock `DRAFT` guardrails | Unset |
| `CLOUDSAVER_TENANT_REGISTRY` | Must be `database` to save workspace AI settings | `env` |
| `CLOUDSAVER_DIRECTORY_MODE` | `cutover` locks AI settings changes | Unset |
| `REDIS_URL` | Batch worker lock and broker | `redis://redis:6379/1` |

Provider credentials come from customer-federated identities or managed identities, not from static keys in configuration. See [docs/MANAGED_IDENTITY_ROLES.md](../MANAGED_IDENTITY_ROLES.md).

## Guardrails and limitations

- AI is off by default and requires the deployment switch, approved targets, a valid platform policy, a current data governance processor approval, a plan that allows AI advisory and an enabled workspace setting.
- Same-cloud routing only; Kubernetes sources aren't sent for inference.
- Hourly attempt budget: up to 100 per hour, from the top of the hour. Monthly token limits use the UTC calendar month.
- Batches: 1 to 500 resources, one active batch per scan; selected resources must come from providers the target allows.
- Follow-ups: 5 per resource per scan, 3 to 500 characters, current evidence digest required.
- Diagnostics never invoke a model and are limited to 3 per minute.
- Retention: 1 to 30 days; legal holds expire within 30 days and block purge and erasure while active.
- Model output is never executed and never changes resource dispositions, decisions or savings.

## Tests

- Backend:
  - Advisory and foundry: [tests/test_ai_advisory.py](../../tests/test_ai_advisory.py), [tests/test_foundry_governance.py](../../tests/test_foundry_governance.py).
  - Data governance: [tests/test_data_governance.py](../../tests/test_data_governance.py).
  - Batches and per-finding advisory: [tests/test_resource_assessment.py](../../tests/test_resource_assessment.py), [tests/test_assessment_api.py](../../tests/test_assessment_api.py).
  - Ledger, persistence and earlier releases: [tests/test_v140.py](../../tests/test_v140.py), [tests/test_postgres.py](../../tests/test_postgres.py), [tests/test_enterprise.py](../../tests/test_enterprise.py).
- Dashboard: [web-dashboard/e2e/foundry.spec.ts](../../web-dashboard/e2e/foundry.spec.ts), [web-dashboard/e2e/data-governance.spec.ts](../../web-dashboard/e2e/data-governance.spec.ts), [web-dashboard/e2e/assessment.spec.ts](../../web-dashboard/e2e/assessment.spec.ts), [web-dashboard/e2e/v140.spec.ts](../../web-dashboard/e2e/v140.spec.ts).

## Related docs

- [docs/ASSESSMENT_AI.md](../ASSESSMENT_AI.md)
- [docs/AI_DATA_GOVERNANCE.md](../AI_DATA_GOVERNANCE.md)
- [docs/RESOURCE_ANALYSIS_FOUNDRY_IMPLEMENTATION.md](../RESOURCE_ANALYSIS_FOUNDRY_IMPLEMENTATION.md)
- [docs/RESOURCE_ANALYSIS_AND_AI_FOUNDRY_SETTINGS_README.md](../RESOURCE_ANALYSIS_AND_AI_FOUNDRY_SETTINGS_README.md)
- [docs/MANAGED_IDENTITY_ROLES.md](../MANAGED_IDENTITY_ROLES.md)
- [Resources](resources.md)
- [Services](services.md)
