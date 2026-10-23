# Service architecture assessment and cloud AI advisory (v1.0.0)

Source: [CloudSaver Enterprise FinOps Platform & Multi-Cloud Optimization Engine — optimization, 360° analysis and AI integration guide](https://docs.google.com/document/d/1u_9HSbjE41srku4ZjDAbkSQ39wmeENOBMn2OGVO3oYs/edit), read October 23, 2026. This release implements an evidence-led milestone from that guide. The guide's full hierarchy, billing pipeline, autonomous operation and performance targets are not release acceptance evidence.

## v1.0.0 runtime update

The API now uses the SQL inference ledger described in [the master-guide integration](V1_MASTER_GUIDE.md). Apply migration 0009 first. Attempt intent, outcomes, lifecycle and usage survive restarts without Redis TTL expiry; uncertain requests do not automatically repeat. New history/usage endpoints and observed structured attribution remain separate from model input. The historical Redis section below describes the earlier coordinator and direct-SDK compatibility, not the current default API. There is still no reconciled dollar budget or semantic truth guarantee.

## Working workflow

1. Select a completed live scan. Cost allocation now includes a service architecture breakdown over **all findings in that snapshot**, independent of the page's account filters. Findings are grouped by provider and storage/database/application/network/compute/other category. Known retail subtotals, unknown price counts, observed risk counts and protected intent are distinct. A finding subset is not a full inventory or estate health score.
2. Open a finding and choose **360° assessment**. Cost, reliability, performance, security and operations each show their actual checks. A setting can be observed, a known risk, or unknown. Missing metrics, backups, dependency graphs or billing never become a pass or zero cost. Saved scan timestamps remain the observation time; this is not a live assessment.
3. Explicit retention or disaster recovery intent suppresses Azure destructive Bash generation. Normalized tag keys `DoNotTouch`, `DoNotDelete`, `Retain`, `LegalHold` with true/yes/1/enabled, or `Role`/`Purpose`/`DisasterRecovery` with DR-Standby/DisasterRecoveryStandby/ActiveStandby/ColdSpare/Witness/DoNotTouch are recognized. AWS RDS `DeletionProtection=true` is also recognized by analysis. These are conservative signals, not a complete enterprise intent registry.
4. Disk scripts require human confirmation, current unattached state, a **new managed snapshot**, a nonempty snapshot identity and `Succeeded` provisioning state, another unattached-state read, and a live protection-tag read before deletion. All supported destructive scripts re-read live tags; missing/malformed reads abort. Snapshots carry `CloudSaverRetentionDays=90`, which is **an operator instruction, not automatic retention enforcement or a restore test**. Snapshot creation adds cost. Operators must enforce retention, verify restores and grant appropriate snapshot permissions. State/tag reads and deletion are not atomic; a concurrent change remains possible. CloudSaver never runs these scripts.
5. Optionally request a cloud model advisory after inspecting the exact allowlisted context and checking external-processing acknowledgement. The UI and API require a workspace administrator for inference. Viewers can inspect deterministic assessment. Model output is unverified text; it cannot approve execution, change guardrails, generate code, or establish live dependencies or savings.

## Evidence collected without more cloud calls

Azure ARG observations now retain resource tags and numeric disk size. AWS EC2/RDS observations retain returned tags, encryption flags, MultiAZ, backup retention, public accessibility, deletion protection, volume size and IOPS when explicitly present. Google observations retain returned labels. Kubernetes observations preserve their full 14-day hourly P95 window. False and zero are preserved; absent fields are not invented. Existing saved scans retain their original evidence and can consequently show more unknown checks.

There are no new live dependency, snapshot, backup, encryption or utilization queries in this release. Only the existing collector responses support deterministic checks. The operations pillar explicitly states that a complete dependency graph is unavailable. A 14-day Kubernetes metric window supports request review, not a dollar savings calculation or performance certification.

## Operator activation (disabled by default)

The scanner process reads these variables. Compose forwards them to `scanner-service`; the browser receives only public target identifiers, provider and model names.

```dotenv
CLOUDSAVER_AI_ENABLED=false
CLOUDSAVER_AI_TARGETS=[]
CLOUDSAVER_AI_HOURLY_ATTEMPTS=10
```

An operator can provision one or more tenant-bound targets, then explicitly enable inference. Model/deployment IDs are operator-selected; there is no obsolete model default or API key fallback. Identifiers below are placeholders, not credentials:

```json
[
  {"target_id":"azure-review","tenant_id":"11111111-1111-4111-8111-111111111111","provider":"azure","model":"approved-deployment","endpoint":"https://approved.openai.azure.com"},
  {"target_id":"bedrock-review","tenant_id":"11111111-1111-4111-8111-111111111111","provider":"aws","model":"approved-model-id","region":"us-east-1","role_arn":"arn:aws:iam::123456789012:role/CloudSaverAIReviewer"},
  {"target_id":"vertex-review","tenant_id":"11111111-1111-4111-8111-111111111111","provider":"gcp","model":"approved-model-id","project":"tenant-project","region":"us-central1","service_account":"reviewer@tenant-project.iam.gserviceaccount.com"}
]
```

- **Azure AI Foundry / Azure OpenAI deployments:** this adapter supports Azure OpenAI chat-completions deployments under the exact HTTPS `*.openai.azure.com` root domain, API `2024-10-21`; it is not a generic Foundry model-catalog adapter. The existing per-tenant keyless Azure credential requests the Cognitive Services audience. Grant the tenant application/identity **Cognitive Services OpenAI User** only on the intended resource. Choose a deployment supporting JSON response mode, temperature and max_tokens. Unsupported deployment options fail closed.
- **Bedrock:** the existing managed-identity → hub role → operator-bound tenant role flow uses the workspace tenant UUID as ExternalId. Grant only `bedrock:InvokeModel` on approved model/inference-profile resources. The Converse adapter supplies no tools and disables SDK inference retries. The customer role's trust policy and model access must be accepted separately; scanner read roles need not gain inference permissions.
- **Vertex AI:** existing managed-identity WIF impersonates the operator-assigned service account. The adapter explicitly requests the cloud-platform scope while scan credentials retain their read-only scope. Grant only necessary prediction/model permissions in the bound project, typically a reviewed Vertex AI User binding. Publisher is fixed to Google, endpoint is regional, and model ID cannot contain a URL or path. Use a model supporting JSON output. Federation refresh requests and provider HTTP requests have timeouts; provider acceptance and overall identity latency still need staging verification.

Use separate inference roles/service accounts and restricted model permissions, control-plane target review, provider quotas, regional policy and provider billing alarms before enabling. Developer mode retains the existing local az/AWS SSO/gcloud credential workflow. The deployment does not store cloud API keys or service-account key files. See [keyless onboarding](CLOUD_SOURCES.md).

## Data and inference boundary

The server selects an exact resource ID **and rule ID** from a tenant-owned completed live scan and revalidates current scope. Users cannot provide prompts, models, endpoints, roles, projects or context. Extra request properties are rejected. The returned context preview contains a SHA-256 resource reference, provider/category/rule codes, bounded numeric/boolean facts, protected boolean, guardrail codes and saved check references. It excludes names, raw resource IDs, raw tags/labels, owner emails, endpoints and free-text findings. This minimizes context but is not a formal anonymity guarantee. A fixed system instruction is also sent.

Responses use the approved target output ceiling (default 1,800 requested tokens) and validated against a strict JSON schema: one of each of the five pillars, summary, high/unknown suggested risk and review questions. Extra approval/code/tool properties and fabricated check references are rejected. Schema validation cannot prove text is true or prevent every misleading statement. Render model text as escaped plain React text, label it unverified, and retain deterministic protection and human approval independently.

HTTP provider responses have a 64 KiB body bound, no redirects and no automatic HTTP retries. Parsed model JSON is capped at 16 KiB. Raw provider errors, credentials and responses are not exposed as error details. Cloud identity acquisition follows the existing keyless trust chain; no external provider was invoked in the release tests.

## Historical v0.9–v0.11 Redis coordination and limits

Redis atomically claims a tenant + UUID idempotency key and increments an attempt counter for the Redis server's UTC hour. Default 10 attempts/hour, configurable from 1–100. The same key and fingerprint returns a cached result after success. Different fingerprints conflict. An in-flight, failed, malformed, timed-out or uncertain attempt retains its fence and is not automatically re-invoked. Failure to coordinate returns 503 before inference. Uncertain outcomes can consume both an attempt and provider charges. Rate-limit responses are 429.

Fences and cached advisories expire after 24 hours; UTC-hour counters expire after 3,900 seconds. Cached model text is stored in Redis under tenant-prefixed keys: secure Redis, encrypted transport/network access, persistence, backups and retention according to deployment policy. This is not a durable immutable inference audit, reconciled token-cost ledger, hard dollar budget, Redis Cluster implementation or an exactly-once guarantee after Redis loss/expiration. Use provider quotas too. Browser retries reuse the key while that finding assessment remains mounted; reopening creates a new user-initiated attempt. An administrator can deliberately submit another UUID, subject to the shared budget. Redis must be healthy for scanner readiness when AI is enabled.

## API

All paths retain the existing bearer authentication and tenant ownership:

| Method and route | Behavior |
| --- | --- |
| GET `/api/v1/scans/{scan_id}/analysis` | Provider/service summary from saved findings |
| POST `/api/v1/scans/{scan_id}/analysis/resource` | `{resource_id,rule_id}` → deterministic assessment and context preview |
| GET `/api/v1/ai/targets` | Enabled flag, attempt limit, public targets for this tenant only |
| POST `/api/v1/scans/{scan_id}/ai-risk-evaluation` | Admin-only `{resource_id,rule_id,evidence_digest,target_id,idempotency_key,acknowledge_external_processing:true}` → advisory-only result |

Legacy synthetic or incomplete snapshots return 409. Missing or foreign scans/findings return 404. Changed scope rejects summary, resource and AI review with 409. A missing evidence digest returns 422; a stale or mismatched preview digest returns 409 before reserving an inference attempt. Invalid inputs return 422, unauthorized roles 403. Model/schema failures return sanitized 502. A successful response contains deterministic disposition and required guardrails separately from the unverified advice. No database migration or v2 ownership bypass is introduced.

## Remaining guide milestones

FOCUS billed/effective/amortized cost ingestion; ESR reconciliation; seasonally evaluated anomaly models; complete resource/dependency and SLO telemetry; hierarchy/membership delegation; richer tag and retention policies; durable audited AI usage/cost tracking; conversational retrieval and evaluated accuracy; model-specific cloud staging acceptance. These remain roadmap work. PTU capacity optimization, durable token/cost accounting and “zero hallucinations” are not implemented or claimed. Destructive or autonomous execution remains unavailable.


## v0.11.0 evidence policy and core improvements

Policy `2026-10-23.1` lives in `app/assessment_policy.py`. Every assessment returns policy version, evaluated evidence fields, explicit gap/risk codes, saved-observation freshness, review priority and an SHA-256 evidence fingerprint. The fingerprint covers the allowlisted context and saved retail estimate; it excludes free text and names and is **not** a signature, independent verification or durable audit record. Fact, policy, timestamp/freshness or protection changes affect the fingerprint. No historical observations are rewritten.

Observations at most 24 hours old are `recent`; older observations are `stale`, future timestamps are `invalid`, missing/naive/malformed timestamps are `unknown`. All except recent add `REFRESH_OBSERVATION`. Risks remain visible on stale evidence; recent still means a saved snapshot, not live state. Before inference, the caller must supply the `assessment.evidence_digest` from the resource-preview response. Mismatches return 409 before the budget/provider is invoked. Refresh the preview and review it again; do not automatically retry paid inference.

Expanded service checks evaluate explicit saved controls: compute metadata-v2/public-admin-ingress/monitoring/patch age; database TLS, engine support and minor upgrades; application health probes, managed secrets and empty-plan density; network flow logging; storage snapshot exposure/age and unattached duration. Patch age over 90 days, snapshot age over 24 hours, unattached duration over 14 days and explicitly empty plans produce review risks. A single hosted application alone is not declared over-provisioned. These are review thresholds, not compliance or action-approval criteria. Fields not collected remain unknown. Azure ARG now projects explicit disk encryption type and App Service plan site count/zone redundancy; known encryption enum values yield observed encryption, absence does not yield false. AWS retains returned `AutoMinorVersionUpgrade`. No extra cloud API calls are added. The remaining expanded controls require future collector coverage or existing saved evidence; this release does not claim new live telemetry integrations.

Kubernetes utilization requires a typed complete collector summary: 14 days, 337 hourly samples including both endpoints, valid ordered UTC-aware boundaries exactly 14 days apart, the current scan within one hour of the end, nearest-rank P95, CPU/cores or memory/bytes and positive requests. Invalid/missing summaries remain unknown. P95 above the saved minimum request produces a request-headroom review risk; requests are not resource limits, and no OOM or dollar-saving conclusion follows. Raw-series completeness is enforced by the collector; assessment does not reconstruct unsaved series.

The service summary retains all provider/category counts and returns a queue capped at 50 findings in memory and response (the UI shows six). Security exposures rank first, then other observed risks, then evidence gaps; equal priority uses the stable resource key, not estimated savings. `review_queue_total` describes all findings. This is not a full-inventory risk score, a deduplicated resource count or an execution plan. All findings must still lie inside the workspace's **current** authorized cloud scope, or the entire request returns 409.

## v0.11.0 enterprise inference controls

Optional operator target fields (defaults preserve existing bindings):

```json
{
  "max_output_tokens": 1800,
  "max_context_bytes": 16384,
  "allowed_source_providers": ["azure", "aws", "gcp", "kubernetes"]
}
```

Output limits accept strict integers 256–4096; context limits accept strict integers 2048–32768 bytes. The context byte limit is a conservative serialized evidence bound, not a tokenizer estimate or a dollar budget. Source-provider policy and context size are checked before a paid attempt. All three adapters send the approved output ceiling. Operator target configuration and instruction version, assessment digest, scan and context are fingerprinted, preventing an old cached result from silently bypassing changed controls.

Advice JSON rejects ambiguous duplicate properties. Citations must be unique, observed, and belong to their pillar. Each pillar with observed risk must cite at least one of its risk checks. The model cannot lower deterministic `high` risk to `unknown`. Azure must finish with `stop`, Bedrock with `end_turn`, Vertex with `STOP`; missing/truncated/filtered/tool responses are rejected and retain the uncertain-attempt fence. Structural validation does not establish that all prose is true. The response explicitly reports `semantic_claims_verified:false`, with independent guardrails retained.

Actual adapters normalize provider-reported input/output token counters into `usage`. Missing/invalid counters remain null, real zero remains zero, and `billed_cost_usd` is always null. Cached responses show original attempt usage and do not invoke another model. This is per-response metadata within the existing 24-hour Redis cache, not durable usage accounting, cost attribution or billing reconciliation. There is no new inference audit table or monetary budget. Live IAM/provider/model acceptance and model-quality evaluation remain required before deployment.
