# Per-resource AI assessment

**Status:** Draft
**Date:** Oct 23, 2026
**Author:** Engineering
**Builds on:** v1.0.0 five-pillar assessment (`app/assessment.py`), AI advisory (`app/ai_advisory.py`),
inference ledger (migration `0009_enterprise_evidence`)

## Problem statement

The five-pillar assessment and the AI advisory work one finding at a time:

- A resource with several findings (for example, an unattached disk that is also unencrypted) is assessed
  separately per finding, so nobody sees the resource as a whole.
- AI review is a manual click in one drawer tab, with a fresh acknowledgement each time. Reviewing a
  scan of 200 resources takes 200 clicks and exceeds the 10-attempt hourly budget with no way to queue.
- AI results appear nowhere else: not in the analysis page, not in the findings grid, not in exports.
- There is no history (did this resource's risk change since the last scan?), no structured next steps,
  no way to ask a follow-up question, and no record of what a reviewer decided.

## Proposed solution

1. **Resource as the unit.** Group a scan's findings by resource identity and produce one deterministic
   assessment per resource that merges all of its findings.
2. **Resource analysis page.** One row per resource with pillar status, review priority, AI risk,
   AI status and reviewer decision. Filter, select, export and run AI from here.
3. **Batch AI assessment.** A workspace admin selects resources (or the whole scan), acknowledges external
   processing once for the batch, and the worker processes items in the background within the hourly
   budget. Items over budget wait for the next hour instead of failing.
4. **Recommended next steps.** The AI response adds structured, advisory-only actions with effort,
   change risk and confidence, each citing saved evidence. Nothing is executed or generated as code.
5. **History.** Compare a resource's deterministic assessment and AI results across scans and flag what
   changed. An AI result whose evidence fingerprint no longer matches is marked stale.
6. **Findings grid.** Add AI risk, AI status and decision columns and filters.
7. **Follow-up questions.** An admin can ask up to 5 questions per resource per scan, answered from the
   same sanitized evidence plus the prior advice.
8. **Export.** CSV download of the resource table and a print-ready report page for PDF.
9. **Reviewer decisions.** Accept, dismiss or defer (with a note and optional date) per resource. Decisions
   persist across scans, are audited, and are flagged when the evidence changes after the decision.
10. **Azure AI Foundry target.** Support Foundry model endpoints with keyless Entra authentication.

## Detailed design

### Resource identity and merged assessment

- `resource_key = sha256(provider + '|' + normalized resource_id)`. Azure IDs are lowercased, as in the
  existing `resource_key`. The existing per-finding key (which includes `rule_id`) stays unchanged.
- The merged assessment runs `assess()` per finding, then combines:
  - each check by code, keeping the most severe status (`risk` over `unknown` over `observed`);
  - each pillar status from its merged checks;
  - guardrails as a union, protection reasons as a union (any protected finding protects the resource);
  - review priority as the most severe across findings;
  - retail estimate as the sum of known estimates (unknown if none is known).
- `resource_evidence_digest` covers the merged sanitized context and policy version only.
- The AI context reuses the existing allowlist per finding (no names, IDs, raw tags or free text) and adds
  `rule_ids` and per-finding facts under the resource reference.

### AI response schema (version 4)

Extends the current `Advice` model:

- `summary`, `risk_level` (`high` or `unknown`, never below the deterministic floor), five `pillars`,
  `review_questions` (1–6), as today.
- `recommended_actions` (0–6), each with:
  - `title` (≤ 160 chars), `rationale` (≤ 500 chars)
  - `kind`: `verify`, `investigate`, `configure`, `rightsize`, `retain`, `decommission`
  - `pillar`, `effort` / `change_risk` / `confidence`: `low`, `medium`, `high`
  - `evidence_codes`: only observed check codes for that pillar
  - `prerequisites` (≤ 4 short strings)

Server validation, in addition to today's checks:

- `decommission` is rejected when the resource is protected or any guardrail blocks destructive actions.
- Text containing URLs, code fences, shell or IaC syntax is rejected (the model has no tools; this keeps
  the output advisory).
- Any validation failure records the attempt as failed. Nothing partial is stored.

Follow-up answer schema: `answer` (≤ 1,500 chars), `evidence_codes`, `limitations` (≤ 3 strings).
Same citation and text rules.

### Batch processing

- Creating a batch stores one item per selected resource with the resource evidence digest at that time.
- The scan worker processes items one at a time through the existing `AIGateway` and durable ledger, so
  each item has its own idempotency key and is never repeated automatically once pending or uncertain.
- When the hourly budget is reached, the batch moves to `waiting_for_budget`. The scheduler tick resumes
  it in the next hour.
- If a resource's evidence digest changed since the batch was created (a newer scan replaced it), the
  item is `skipped` with reason `evidence_changed`.
- Admins can cancel a batch. Running items finish; queued items are cancelled.
- One active batch per workspace and scan; up to 500 items per batch.

### Data model (migration `0010_resource_assessment`)

All tables are tenant-owned with forced row-level security, like migration 0009.

- `ai_batches(id, tenant_id, scan_id, target_id, status, total, completed, failed, skipped, actor,
  created_at, updated_at)`. Status: `queued`, `running`, `waiting_for_budget`, `completed`, `cancelled`.
- `ai_batch_items(id, tenant_id, batch_id, resource_key, evidence_digest, status, attempt_id NULL,
  reason NULL, updated_at)`, unique `(batch_id, resource_key)`. Status: `queued`, `running`, `completed`,
  `failed`, `skipped`, `uncertain`, `cancelled`.
- `ai_followups(id, tenant_id, scan_id, resource_key, attempt_id, question, created_at)`. Insert-only.
  The question is stored because it was sent to the model.
- `resource_decisions(id, tenant_id, resource_key, scan_id, decision, note, defer_until NULL,
  evidence_digest, actor, created_at)`. Insert-only; the latest row is the current decision.
  Decision: `accepted`, `dismissed`, `deferred`.
- `ai_inference_attempts.metadata` gains `kind` (`resource_assessment` or `followup`) and `resource_key`.
  No column change.

### API changes

All routes are under `/api/v1`, tenant-scoped, proxied through the gateway and the dashboard allowlist.

| Method | Path | Role | Purpose |
| --- | --- | --- | --- |
| GET | `/scans/{scan_id}/resources` | Viewer | Paged resource rows with filters (provider, category, priority, AI status, AI risk, decision) |
| GET | `/scans/{scan_id}/resources/{resource_key}` | Viewer | Merged assessment, findings, sanitized AI context, latest AI result, decision |
| GET | `/scans/{scan_id}/resources/export.csv` | Viewer | CSV of the filtered resource table |
| POST | `/scans/{scan_id}/ai-batches` | TenantAdmin | Create a batch (`resource_keys` or `all`, `target_id`, acknowledgement, idempotency key); returns 202 |
| GET | `/ai-batches` and `/ai-batches/{id}` | Viewer | Batch progress and items |
| POST | `/ai-batches/{id}/cancel` | TenantAdmin | Cancel queued items |
| POST | `/scans/{scan_id}/resources/{resource_key}/questions` | TenantAdmin | Ask a follow-up question (≤ 500 chars) |
| GET | `/resources/{resource_key}/history` | Viewer | Deterministic and AI results across the last 10 scans, with change flags |
| GET / POST | `/resources/{resource_key}/decisions` | Viewer / TenantAdmin | Read or record a decision |

CSV cells that begin with `=`, `+`, `-` or `@` are escaped to prevent spreadsheet formula injection.

### AI target: Azure AI Foundry

- New target option `auth`: `managed_identity` (CloudSaver's own identity, for a model hosted in
  CloudSaver's subscription) or `customer_federated` (today's behavior, the customer's directory).
- Allowed Azure hosts: `*.openai.azure.com`, `*.cognitiveservices.azure.com` and
  `*.services.ai.azure.com` (Foundry model inference). Root endpoint only, HTTPS, no credentials in URL.
- Token scope `https://cognitiveservices.azure.com/.default`. The managed identity needs the
  **Cognitive Services OpenAI User** role on the Foundry resource (or **Azure AI User** on the project).
- No API keys are stored or accepted.

### UI changes

- **Resources page (new, `/resources`):** table with name, provider, category, finding count, review
  priority, five pillar dots, AI risk, AI status (not run, queued, completed, stale, failed), decision and
  last change. Filters, row selection, **Run AI assessment**, **Export CSV** and **Print report**.
- **Run AI assessment dialog:** selected count, target, the exact field list sent to the model and one
  sample sanitized context, estimated duration at the hourly budget, acknowledgement checkbox, **Start**.
- **Batch progress banner:** progress, waiting-for-budget state with the next resume time, **Cancel**.
- **Resource drawer (new):** tabs for *Overview* (merged pillars and the resource's findings),
  *AI assessment* (summary, pillars, recommended next steps as cards), *Questions*, *History*
  (timeline across scans) and *Decision*.
- **Findings grid:** AI risk, AI status and decision columns and filters. Selecting the AI status opens
  the resource drawer.
- **Finding drawer:** the 360° assessment tab links to the resource view.
- **Print report:** print-styled resource report per scan for browser PDF export.

## Acceptance criteria

- [ ] Findings with the same provider and resource ID appear as one resource with a merged assessment.
- [ ] A protected finding makes the whole resource protected and blocks `decommission` actions.
- [ ] An admin can run AI assessment for selected resources or the whole scan with one acknowledgement.
- [ ] Batches continue across hours when the budget is reached and can be cancelled.
- [ ] Pending or uncertain items are never retried automatically; completed items are not re-billed.
- [ ] Items whose evidence changed are skipped, and stale AI results are labeled.
- [ ] AI responses with uncited evidence, a downgraded risk, URLs, code or commands are rejected.
- [ ] Resources page, findings grid columns and filters show AI risk, AI status and decision.
- [ ] History shows changes across the last 10 scans for a resource.
- [ ] Follow-up questions are limited to 5 per resource per scan and are recorded.
- [ ] CSV export matches the filtered table and is safe to open in a spreadsheet.
- [ ] Decisions are audited, persist across scans and are flagged when evidence changes.
- [ ] A Foundry target works with the managed identity and no API key.
- [ ] Tenant isolation is enforced by row-level security on every new table (Postgres tests).
- [ ] Unit tests cover merging, schema validation, batch budget behavior and the new routes.

## Out of scope

- Running AI automatically after every scan.
- Executing, scheduling or generating code for any recommended action.
- Open-ended chat beyond 5 follow-up questions per resource per scan.
- Billed cost per AI call (provider-reported token usage only, as today).
- Jira or ServiceNow ticket creation from decisions.
- API-key authentication for model targets.

## Open questions

1. **Foundry authentication:** you mentioned providing keys. This spec uses the managed identity instead
   (no key to store or rotate). Is a key-based option required, for example for a Foundry resource in
   another tenant? If so, it would be read from Azure Key Vault by reference, never from `.env` or the UI.
2. **Plan gating:** should batch AI, follow-ups and export be Growth and Enterprise only?
3. **Budget:** keep the 10 attempts per hour default, and let the operator set a per-workspace limit
   (up to 100) in the operator console?
4. **Retention:** how long should follow-up question text and AI results be kept (for example, 365 days)?

## Delivery plan

1. **Phase 1, no AI needed:** resource grouping and merged assessment, Resources page, grid columns,
   decisions, CSV export and print report.
2. **Phase 2:** Foundry target, response schema v4 with recommended actions, batch processing.
3. **Phase 3:** history and follow-up questions.

## Dependencies

- Azure AI Foundry resource with a chat model deployment (endpoint and deployment name, no key).
- Role assignment for the managed identity on that resource (see AI target above).
- Scan worker and scheduler running (Compose profile `scheduled`).
