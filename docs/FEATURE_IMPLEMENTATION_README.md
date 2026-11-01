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
| GitHub | `CLOUDSAVER_GITHUB_APP_*`, `CLOUDSAVER_GITOPS_PUBLISH` |
| Azure DevOps / GitLab / Bitbucket | `CLOUDSAVER_AZDO_PAT`, `CLOUDSAVER_GITLAB_TOKEN`, `CLOUDSAVER_BITBUCKET_TOKEN` (as needed per target) |

## 6. Tests

- `tests/test_drift_event_pipeline.py` — normalization, outbox idempotency, worker lease skip, AST patch, PR package guardrails.
