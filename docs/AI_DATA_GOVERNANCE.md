# AI data governance

CloudSaver now applies a data-use contract before real model invocation. The contract controls permitted facts, processing purposes, registered processors, reuse, local retention, privacy erasure and audit evidence. This increment does not change network configuration. An environment identifier expresses a reviewed ownership boundary; it does not configure or prove network isolation.

New model calls are blocked until an operator registers the owning environment and an exact, reviewed processor for the workspace and purpose. Workspace consent, a paid plan, human task approval and a valid worker token cannot override this requirement. Existing Foundry consent, model/region allowlists, same-cloud rules and usage budgets continue to apply.

## Implemented controls

| Data or operation | Enforced behavior |
| --- | --- |
| Resource context | Purpose-specific top-level fields and allowlisted operational facts only; raw inventory, resource names/IDs, tenant/account identifiers, raw tags, telemetry and billing fields are excluded from model context |
| Identifiers in accepted text | Recognized Azure paths, ARNs, UUIDs, email addresses, IPv4 addresses, SSN-shaped values and internal hostname patterns are redacted |
| Credentials | Recognized secret fields and secret-shaped values block processing; output is checked before persistence |
| Agent instructions | Identifying action values are rejected rather than silently changed; exact action arguments still require human approval |
| Processor | Exact workspace, target, Azure AI account resource ID, endpoint, deployment, allowed purpose and unexpired documented review |
| Real provider invocation | A short-lived grant binds tenant, target, purpose, minimized payload and current policy digest; the native adapter checks it before requesting credentials or invoking a model |
| Training and reuse | Customer-data training, cross-tenant reuse and generic HTTP action data transfer cannot be enabled through this policy |
| Knowledge | No automatic learning from client prompts, plans or outcomes; the existing separately stored, reviewed public/synthetic knowledge publication workflow remains separate |
| Saved model content | Tenant-owned retention record, default seven days for new content; configurable from one to thirty days |
| Privacy actions | Human `TenantAdmin` can erase AI content or place a bounded legal hold; viewers can inspect evidence |
| Audit | Metadata-only decision codes, policy hashes, counts and actor references; database runtime privileges prohibit updating/deleting governance events |

The supported processor boundary is currently Azure managed-identity inference. AWS, GCP and unverified Kubernetes model processing remain blocked by this contract. They are not silently rerouted into Azure. Discovery and non-AI resource analysis are independent of model processing approvals.

Filtering is pattern based and is **not proof of anonymization**. Unknown business-sensitive free text may evade identifier detection. Do not submit secrets, personal information or confidential business narratives. Treat any allowed processor as a recipient of the minimized context. CloudSaver does not independently verify that an Azure account belongs to the declared directory or certify a provider's internal retention, training, abuse-monitoring or processing-location behavior. An authorized owner must review those settings and contractual controls before registration.

## Operator setup

Apply migration `0018_ai_data_governance` using the existing schema-owner migration process before starting upgraded backend services. Use the runtime role for applications and the retention worker; never give either schema-owner credentials.

Set matching logical ownership values in the application deployment:

```dotenv
CLOUDSAVER_DATA_ENVIRONMENT_ID=company-production
CLOUDSAVER_DATA_AZURE_TENANT_ID=<owning Azure directory UUID>
```

These variables contain identifiers, not provider secrets. A mismatch with operator policy blocks processing.

In the platform portal's AI policy editor, configure **AI data governance** and save the versioned policy. Register an exact workspace and its existing Foundry target. Record a bounded internal review reference, an expiry including its timezone, permitted purposes and explicit acknowledgement that provider controls were reviewed. The policy supports up to fifty workspace/target approvals. A target can have multiple approved purposes; duplicate workspace/target registrations are rejected.

Example `data_governance` object within the existing complete AI policy:

```json
{
  "environment_id": "company-production",
  "azure_tenant_id": "11111111-1111-4111-8111-111111111111",
  "response_retention_days": 7,
  "allow_training": false,
  "allow_cross_tenant_reuse": false,
  "allow_external_action_data": false,
  "processors": [
    {
      "workspace_id": "22222222-2222-4222-8222-222222222222",
      "target_id": "approved-review",
      "azure_resource_id": "/subscriptions/33333333-3333-4333-8333-333333333333/resourceGroups/ai-production/providers/Microsoft.CognitiveServices/accounts/company-review",
      "endpoint_url": "https://company-review.openai.azure.com",
      "deployment_name": "company-review",
      "purposes": ["assessment", "resource_assessment", "followup", "agent_planning"],
      "review_reference": "DATA-REVIEW-42",
      "review_expires_at": "2027-01-01T00:00:00Z",
      "provider_controls_reviewed": true
    }
  ]
}
```

Replace all example identifiers, endpoint, deployment and date. Use only purposes actually reviewed. Registration does not create a Foundry target, assign cloud RBAC or enable model invocation by itself. The target must use managed identity and exactly match its approved account, endpoint and deployment. The application rechecks policy at invocation; changed policy invalidates an outstanding grant. Expired reviews deny new processing.

Old policies without `data_governance` receive the locked default rather than implicit approval. Upgrading therefore intentionally blocks previously configured model calls until registration is complete. Resource scanning and deterministic assessments can continue.

## Retention and legal preservation

Each inference claim records its content expiry and policy digest. Policy TTL changes apply to newly created records, not existing snapshots. Usage counters, request fingerprints, completed/uncertain status and request keys remain after erasure. Repeating an erased request returns HTTP 410 and never creates a replacement model call under that key.

The default Compose service `data-retention-worker` performs database-only maintenance every 600 seconds, including inactive workspaces. Each workspace pass processes up to 200 eligible inference records and up to 200 eligible task copies. Maintenance logs aggregate success/failure counts; it does not invoke models, connectors, exports or knowledge ingestion. Relevant reads also enforce content expiry. Monitor worker failures and database capacity; expired rows can remain at rest until a successful maintenance pass.

Erasure clears saved model responses and associated follow-up question text. For the linked current agent draft it also clears stored instructions, plan, steps, approval, connector bindings and lease. Pending work is cancelled; work that had already started becomes `needs_reconciliation`. An already dispatched provider action cannot be undone by erasure. Task resource identity, hashes, versions and operational outcomes remain for reconciliation and accountability. Old event copies of plan bodies are removed during migration; hashes remain.

A legal hold lasts at most thirty days per record. It prevents content erasure while active. Placement is serialized with erasure so a hold cannot claim to preserve content already erased. The hold does **not** authorize normal reading or reusing expired content, new inference, or an extension of execution approval. The governance screen shows active holds and their internal references. There is no early-release endpoint in this increment; holds expire automatically. Review preservation requirements before their expiry.

The APIs are:

| Route | Permission and effect |
| --- | --- |
| `GET /api/v1/ai/governance` | Workspace viewer: reviewed processor configuration, latest 100 retention records, latest 100 events, active holds and aggregate decision counts |
| `POST /api/v1/ai/governance/records/{attempt_id}/erase` | Human `TenantAdmin`; body `{"review_reference":"PRIVACY-42"}`; irreversible content erasure |
| `POST /api/v1/ai/governance/records/{attempt_id}/hold` | Human `TenantAdmin`; body includes `review_reference` and timezone-aware ISO `hold_until` within thirty days |

Use authenticated workspace access as for other APIs. Service accounts cannot perform privacy mutations. These endpoints require full-workspace scope; restricted provider/scope keys are denied until the metadata views support equivalent filtering. Cross-tenant attempt IDs do not grant access. Internal references must contain 3–120 bounded characters, not personal information, ticket descriptions or secrets.

This is AI-content erasure, not a full customer-deletion or DSAR implementation. Source inventory, task resource identity, financial records, billing evidence, metadata audits and usage fences retain their existing lifecycle. Database backups, replicas/WAL, exported historical artifacts and provider-side copies require separately reviewed retention/deletion procedures. Application erasure cannot retroactively delete them.

## Agent behavior

Generic `http_json` action connectors are blocked during task creation, plan validation and worker execution, before secret resolution or HTTP invocation. Their compatibility schema is not permission to transfer data. Typed first-party Azure tag operations remain available with exact resource binding, human approval and credential-shaped argument rejection. Do not put client-sensitive information into tag arguments.

The approval program hash now includes data-governance contract version 1 and hash schema version 2. Old approval hashes cannot authorize new execution. Re-review eligible plans under the new contract; do not copy old approvals. The worker still executes deterministic TypeScript from typed plans, without MCP or arbitrary model-generated source.

## Upgrade sequence and migration behavior

1. Review backups and the local/provider retention requirements. Inventory historical model content and active agent tasks before upgrading.
2. Stop old AI writers and agent workers during the schema/application transition. Build the upgraded platform identity service, scanner, gateway, agent gateway, retention worker, dashboard and portal through their existing deployment pipelines.
3. Apply owner migration `0018_ai_data_governance`. It gives historical inference records and tasks without an expiry a **seven-day review window from migration time**, regardless of their original age. It does not immediately erase a year-old response based on its original creation date. Forced RLS is restored within the migration transaction after owner-only backfills across tenants.
4. Start the upgraded API and control-plane services. Configure matching ownership identifiers and reviewed processors; inspect the tenant governance screen. Place required legal holds before the legacy review window ends.
5. Start `data-retention-worker` and eligible agent workers. Confirm maintenance health and blocked/unregistered processor behavior using synthetic data before enabling real inference.

For Compose, after reviewing local configuration and the preservation window:

```bash
docker compose build migrate scanner-service api-gateway agent-gateway data-retention-worker web-dashboard
docker compose run --rm migrate
docker compose up -d scanner-service api-gateway agent-gateway data-retention-worker web-dashboard
```

The platform identity service and portal run in their separate Compose/deployment project and must be upgraded there as well. Existing agent worker activation remains opt-in. No production rollout or live customer erasure was performed while developing this increment.

Erasure is irreversible. Once any `content_erased_at` marker exists, migration downgrade to `0017_agent_execution` deliberately fails: the old schema requires every completed attempt to have a response. The transaction preserves the new schema and forced RLS. Use a forward fix; never fabricate responses or restore deleted content merely to satisfy rollback.

## Verification

- Full backend/platform regression suite against disposable PostgreSQL 16 and Redis 7: **802 passed**.
- Dashboard browser suite: **56 passed**, including governance confirmation, viewer/mobile access and automated accessibility checks.
- Worker TypeScript checks and **9 runtime tests passed**. Dashboard and platform portal TypeScript checks and production builds passed.
- `git diff --check` passed. The backend suite emits one upstream Starlette/httpx deprecation warning. Worker tests use host Node 24.19.0; use the declared >=24.22.1 runtime for deployment. Node emits the expected experimental `stripTypeScriptTypes` warning.

The automated checks cover processor/purpose/environment mismatch, review expiry, grant revocation and payload binding, direct-adapter default denial, secret blocking, minimization, tenant isolation, legal holds, expiry, linked agent content erasure and usage/replay preservation. PostgreSQL tests exercise real restricted runtime privileges, irreversible rollback protection and backfilling two legacy tenants under a non-superuser migration owner. Browser checks cover human confirmation, read-only/mobile views and accessibility. Model and connector responses in tests are synthetic; these checks do not certify a live provider's handling of data.
