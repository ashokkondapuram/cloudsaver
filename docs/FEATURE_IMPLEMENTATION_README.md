# Activity Log Drift Pipeline & GitHub App PR Wiring

This document describes the v2 control-plane drift path from cloud Activity Log / CloudTrail events through live verification, agent permit fencing, and GitOps remediation pull requests.

## 1. Cloud activity payloads → `CloudDriftSignal`

`app/collectors/event_stream.py` ingests:

- **Azure Event Grid** — `Microsoft.Resources.ResourceWriteSuccess` (ARM write scope in `data.authorization.scope`)
- **AWS EventBridge** — `AWS API Call via CloudTrail` (`ModifyVolume`, `RunInstances`, etc.)

Both normalize to:

```json
{
  "workspace_id": "<tenant UUID>",
  "provider": "azure|aws",
  "account_or_subscription_id": "...",
  "canonical_resource_id": "...",
  "operation": "...",
  "actor_principal": "...",
  "event_timestamp_utc": "..."
}
```

Workspace ownership is resolved via an injected subscription/account → `workspace_id` callback (production: tenant registry bindings).

Each signal enqueues a **`DRIFT_INSPECT_RESOURCE`** row in `platform_outbox_intents` with a deterministic SHA-256 idempotency key.

## 2. Drift worker (`workers/event_drift_worker.py`)

1. Claims pending outbox intents (RLS-scoped).
2. Acquires Redis lease `lease:drift_inspect:{workspace_id}:{resource_hash}` (30s TTL) to collapse burst writes.
3. Calls `app/drift/drift_manager.py`:
   - Read-only live metadata via injectable `live_reader` (Compute `get` / EC2 `describe_volumes` in production).
   - Compare against saved baseline fields (`vm_size`, `etag`, `tags`, …).
4. On drift:
   - **Agent gateway:** `abort_agent_permits_for_drift` sets `permit_status=ABORTED_STATE_DRIFT` and cancels approved/running tasks; `agent_store.step(start)` rejects new permits.
   - **GitOps:** If `CLOUDSAVER_GITOPS_AST_INDEX` maps the resource, stage `DRIFTED_FROM_IAC` automation preview metadata.

## 3. GitOps remediation PR (`POST /api/v1/gitops/pull-requests`)

Human-reviewed request from `/automation` → core API (`app/gitops_api.py`):

1. Validates owned resource + AST mapping (`start_line`, `end_line`, `indexed_commit_sha`).
2. Computes idempotency key: `sha256(workspace_id + canonical_resource_id + attribute diff + indexed_commit_sha)`.
3. Single transaction: `gitops_remediation_requests` (`QUEUED`) + `platform_outbox_intents` (`GITOPS_CREATE_PR`).

`workers/delivery_worker.py`:

1. Redis lock `gitops:pr:{idempotency_key}`.
2. Verifies live Git file block still matches indexed AST snapshot (`app/gitops/ast_hcl_indexer.py`); otherwise `REPO_DRIFT_REINDEX_REQUIRED`.
3. Surgical attribute patch inside the line range.
4. GitHub App / Azure DevOps / GitLab / Bitbucket flow (`app/gitops_vcs.py` + `app/gitops_remediation_flow.py`): provider-specific branch, commit, and pull/merge request creation with shared AST patching and repo-block verification.

## 4. Supported version-control providers

| Provider | `vcs_provider` | Target binding | Credential |
|----------|----------------|----------------|------------|
| GitHub | `github` (default) | `repository`, `repository_id`, `installation_id` | GitHub App (`CLOUDSAVER_GITHUB_APP_*`) |
| Azure DevOps | `azure_devops` | `organization`, `project`, `repository`, `repository_id` | `CLOUDSAVER_AZDO_PAT` |
| GitLab | `gitlab` | `project_path`, `project_id`, optional `gitlab_host` | `CLOUDSAVER_GITLAB_TOKEN` |
| Bitbucket Cloud | `bitbucket` | `workspace`, `repository_slug`, `repository_id` | `CLOUDSAVER_BITBUCKET_TOKEN` |

AST index entries use `repository` as the provider-specific label (`owner/repo`, `org/project/repo`, GitLab `group/project`, or `workspace/slug`). Optional `vcs_provider` on the mapping must match the selected target.

## 5. Operations

| Component | Env / table |
|-----------|-------------|
| AST index | `CLOUDSAVER_GITOPS_AST_INDEX` JSON |
| Outbox | PostgreSQL `platform_outbox_intents`, `gitops_remediation_requests` (migration `0028`) |
| Leases | `REDIS_URL` |
| Drift live reads | `CLOUDSAVER_DRIFT_LIVE_READERS=true` (ARM/EC2 metadata via workspace credentials) |
| Outbox dispatch tick | `CLOUDSAVER_PLATFORM_OUTBOX_DISPATCH=true` (Celery beat → `workers.tasks.dispatch_platform_outbox_all`) |
| Drift webhook ingress | `CLOUDSAVER_DRIFT_WEBHOOK_SECRET` + `POST /api/v1/drift/cloud-events/ingest` |
| AST DB sync | `POST /api/v1/gitops/ast/sync` persists `CLOUDSAVER_GITOPS_AST_INDEX` into `gitops_*` tables |
| GitHub | `CLOUDSAVER_GITHUB_APP_*`, `CLOUDSAVER_GITOPS_PUBLISH` |
| Azure DevOps / GitLab / Bitbucket | `CLOUDSAVER_AZDO_PAT`, `CLOUDSAVER_GITLAB_TOKEN`, `CLOUDSAVER_BITBUCKET_TOKEN` (as needed per target) |

## 6. Tests

- `tests/test_drift_event_pipeline.py` — normalization, outbox idempotency, worker lease skip, AST patch, PR package guardrails.

## 7. FinOps resize autopilot (hands-free agent execution)

Per-resource resize knowledge lives in `app/finops_resize_playbooks.py` (Azure VM, AWS EC2, GCE instance). The autopilot API builds a **deterministic** two-step agent program (no LLM drafting):

1. `resource.inspect` with bounded `expected_state` (power/state + current SKU)
2. `compute.resize` with `target_size` and `restore_power: true` (deallocate/stop → resize → start when needed)

| Endpoint | Purpose |
|----------|---------|
| `GET /api/v1/finops/autopilot/playbooks` | List supported `finops_action`, resource types, and agent step sequence |
| `POST /api/v1/finops/autopilot/resize` | Create agent task, install plan via `install_finops_plan`, optional auto-approve |

**Environment**

| Variable | Purpose |
|----------|---------|
| `CLOUDSAVER_FINOPS_AUTOPILOT=true` | Enable autopilot API |
| `CLOUDSAVER_FINOPS_AUTOPILOT_AUTO_APPROVE=true` | With `auto_execute: true`, skip human approval (`state=approved`) |
| `CLOUDSAVER_AGENT_ENABLED=true` | Required when `auto_execute` is true |
| `CLOUDSAVER_AGENT_CONNECTORS` | Each compute connector must include `compute.resize` for its cloud kind |

**Example request** (connector omitted → first matching connector with `compute.resize`):

```json
{
  "scan_id": "00000000-0000-4000-8000-000000000001",
  "resource_id": "/subscriptions/{sub}/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1",
  "request_key": "00000000-0000-4000-8000-000000000002",
  "target_id": "finops-resize-vm1",
  "target_size": "Standard_D4s_v5",
  "auto_execute": true
}
```

Worker implementation: `agent-worker/src/connectors.ts` (Azure), `agent-worker/src/multicloud.ts` (AWS/GCP). Tests: `tests/test_finops_autopilot_planner.py`.

**Playbooks (6):** Azure VM, App Service plan, managed disk; AWS EC2 and RDS; GCE instance. Each maps a Terraform attribute for optional IaC sync.

**IaC after cloud resize:** set `sync_iac: true` and `gitops_target_id` on `POST /api/v1/finops/autopilot/resize` to append `gitops.terraform.sync` with `patch_mode: rightsize_sku` (AST-mapped PR via `app/agent_gitops_sync.py`).

**Human approval:** tasks stay `awaiting_approval` unless both `auto_execute: true` on the request and `CLOUDSAVER_FINOPS_AUTOPILOT_AUTO_APPROVE=true` in the environment.

## 8. GitHub App AST repository indexer

When `CLOUDSAVER_GITOPS_AST_INDEX_FROM_GITHUB=true`, `POST /api/v1/gitops/ast/index-repositories` uses the GitHub App to resolve each target’s `base_branch` SHA, list `.tf` files, parse Terraform resource blocks (`app/gitops_terraform_ast_indexer.py`), and persist mappings into `gitops_ast_*` tables (line ranges + `indexed_block` at commit). Env JSON sync remains on `POST /api/v1/gitops/ast/sync`.

## 9. Semantic embedding pgvector backfill

`SemanticEmbeddingsStore.upsert` copies jsonb embeddings into `embedding_vector` when migration **0032** is applied. `POST /api/v1/semantic/embeddings/backfill-vectors` (requires `CLOUDSAVER_SEMANTIC_EMBEDDINGS_PIPELINE=true`) backfills rows where `embedding_vector IS NULL`.

## 10. Drift Event Grid / EventBridge wiring

Set `CLOUDSAVER_DRIFT_INGEST_URL` to the public gateway URL for `POST /api/v1/drift/cloud-events/ingest` and `CLOUDSAVER_DRIFT_WEBHOOK_SECRET`. With `CLOUDSAVER_DRIFT_SUBSCRIPTION_WIRING=true`, `POST /api/v1/drift/cloud-events/subscriptions/ensure` provisions:

- **AWS:** EventBridge rule + API destination + connection (header `X-CloudSaver-Drift-Webhook-Secret`; requires `CLOUDSAVER_DRIFT_EVENTBRIDGE_ROLE_ARN`)
- **Azure:** Subscription-scoped Event Grid webhook for `Microsoft.Resources.ResourceWriteSuccess` (ingress handles `SubscriptionValidationEvent`)

Ingress also accepts a raw EventBridge envelope (single event body) for API destination delivery.
