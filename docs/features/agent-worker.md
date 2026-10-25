# Agent worker

The agent worker turns a resource task into an AI-drafted connector plan that a human workspace administrator reviews and approves before anything runs. A private agent gateway stores tasks, validates every plan against strict connector grants and hands out short leases and single-use, ordered step permits. A separate TypeScript worker claims approved work, runs a deterministic program compiled from the approved plan, and calls only the typed cloud adapters you configured. Uncertain writes are never replayed automatically, and task success does not prove realized savings.

Last reviewed against the code on Oct 25, 2026.

## Where to find it

- **Route:** `/agents` ([web-dashboard/app/agents/page.tsx](../../web-dashboard/app/agents/page.tsx) renders [AgentWorkspace.tsx](../../web-dashboard/components/agents/AgentWorkspace.tsx)).
- **Navigation label:** **Agent worker**, in the **ACT & GOVERN** group ([AppShell.tsx](../../web-dashboard/components/AppShell.tsx)). The keyboard shortcut **G then A** also opens it.
- **Who can see it:**
  - Every signed-in user can open the page, see the connector catalog and inspect the task queue, plans and audit history.
  - Only a `TenantAdmin` sees the **Assign a resource task** form and the cancel and redraft controls.
  - Only a verified human `TenantAdmin` session (not an API key or service account) can approve or reject a plan. Other administrators see a notice asking them to sign in as a verified human.
  - A warning appears when the operator has not enabled agent execution.

## What you can do

### Request a plan

1. Select a recent, completed, live (non-demo) scan in the workspace.
2. In **Assign a resource task**, choose a resource from the scan, an approved planning model and one or more connector permissions that match the resource's provider and scope.
3. Write a task instruction (5–1,500 characters), for example "Inspect the tags, then set CostCenter to FINOPS-42." Do not include credentials or personal information.
4. Select **Request AI execution plan**. The task enters the queue in the `draft_queued` state.

The queue refreshes every five seconds while any task is active.

### Review and approve

1. Open a task in **Task queue**. The **Plan & execution review** panel shows the plan summary and, for every step, the operation, connector, exact JSON arguments, purpose, verification and recovery text.
2. Expand **Approved connector destinations** and **Worker program** to inspect the bindings and the generated program. The plan's SHA-256 hash is shown.
3. If the plan includes a paired GitOps step, an infrastructure-as-code preview of the repository fragment is also shown.
4. Choose an approval validity of 5, 15, 30 or 60 minutes, confirm that you reviewed the resource, destinations, arguments and recovery limits, then select **Approve this plan**. You can also select **Reject plan**.

### Follow execution and recover

- Each step shows `pending`, `started`, `succeeded`, `failed` or `uncertain`, with a result code.
- Select **Request new AI draft** for tasks in `awaiting_approval`, `rejected`, `failed` or `approval_expired` (up to five drafts per task, and only if no write was attempted).
- Select **Cancel task** to block further steps. An in-flight connector call may still complete.
- If a task enters `needs_reconciliation`, an action may have reached its connector. Inspect the provider's audit trail and current state yourself; the task will not replay.
- Expand **Approval & execution audit** to see every recorded event.

## How it works

1. **Task creation.** `POST /api/v1/agents/tasks` on the API gateway ([services/gateway.py](../../services/gateway.py)) is forwarded to the agent gateway ([services/agent_gateway.py](../../services/agent_gateway.py)). The agent gateway checks that execution is enabled, the scan is completed, live and less than 24 hours old, the resource is in the scan, the ARM ID is well formed (Azure), the connectors are bound to this workspace and scope and support the resource type, and data governance allows the instruction. [app/agent_store.py](../../app/agent_store.py) (`AgentRepository.create`) records the task with an idempotency key and the expected live state from the scan.
2. **Drafting.** The worker claims the task (`phase: draft`) and calls `/draft`. The gateway runs [app/agent_planner.py](../../app/agent_planner.py), which sends only the instruction, resource type and connector IDs, kinds and operations to the approved AI Foundry target through the durable AI ledger and token budgets. Model output is parsed and validated by [app/agent_contract.py](../../app/agent_contract.py) (`validate_plan`). The task moves to `awaiting_approval` with a plan hash.
3. **Plan rules.** A plan has 1–8 steps and at most one write. Every write requires an earlier inspection with the same connector. Tag, label and annotation keys and values are bounded, snapshots need a 7–90 day retention and a bounded name prefix, and generic `http_json` actions are blocked by data governance.
4. **Approval binding.** `program_hash` covers the task, resource, plan, the rendered program and the connector bindings. Approval requires that exact hash and records an expiry. Any change to the plan or connector configuration invalidates the approval.
5. **Execution.** The worker ([agent-worker/src/main.ts](../../agent-worker/src/main.ts)) polls `/internal/v1/agent/claim` for each assigned workspace. For an execute assignment, [agent-worker/src/runtime.ts](../../agent-worker/src/runtime.ts) (`runCode`) verifies the approval and that the program matches `renderCode` byte for byte ([agent-worker/src/contracts.ts](../../agent-worker/src/contracts.ts)), then imports it. Each `ctx.call(index)` must be in order, requests a single-use permit from `/steps/{index}/start`, runs the connector and reports the outcome to `/steps/{index}/complete`.
6. **Connectors.** [agent-worker/src/connectors.ts](../../agent-worker/src/connectors.ts) handles Azure Resource Manager tag inspection and merges (with `If-Match`) and managed-disk snapshots. [agent-worker/src/multicloud.ts](../../agent-worker/src/multicloud.ts) handles AWS (EC2 and RDS tags, encrypted EBS snapshots), Google Cloud (Compute and Cloud SQL labels, disk snapshots) and Kubernetes (CloudSaver recommendation annotations). Writes recheck the live state digest captured during inspection and verify the result afterward. All HTTP goes through [agent-worker/src/http.ts](../../agent-worker/src/http.ts) with a 45-second timeout, no redirects and a 1 MB response cap.
7. **Paired GitOps step.** When a plan uses a `gitops_terraform` connector, the gateway appends a final `gitops.terraform.sync` step that must match the single approved metadata merge. When that step starts, the gateway itself builds and publishes a draft pull request with [app/agent_gitops_sync.py](../../app/agent_gitops_sync.py); the worker only relays the server-side outcome. See [Automation and GitOps](automation-and-gitops.md).

### Task states

| State | Meaning |
| --- | --- |
| `draft_queued`, `drafting` | Waiting for or running AI planning |
| `awaiting_approval` | Plan drafted; a human must review it |
| `approved` | Approved and waiting for a worker |
| `running` | Worker holds the lease and is executing steps |
| `cancel_requested` | Cancellation requested while a step is in flight |
| `succeeded`, `failed`, `rejected`, `cancelled`, `approval_expired` | Final |
| `needs_reconciliation` | Final; a write may have happened and needs manual reconciliation |

## API reference

Human routes are available on the API gateway and forwarded to the agent gateway. Worker routes exist only on the agent gateway and are not exposed by the API gateway.

| Method | Path | Purpose | Required role/scope |
| --- | --- | --- | --- |
| GET | `/api/v1/agents/catalog` | Connectors visible to your workspace and scope, plus `enabled`, `approval_required` and runtime flags | Any authenticated workspace caller |
| GET | `/api/v1/agents/tasks` | Up to 50 recent visible tasks | Any authenticated workspace caller |
| GET | `/api/v1/agents/tasks/{task_id}` | Task detail, events and rendered program | Any authenticated workspace caller |
| POST | `/api/v1/agents/tasks` | Create a task (`scan_id`, `resource_id`, `request_key`, `intent`, `target_id`, `connector_ids`) | `TenantAdmin`; agent execution enabled |
| POST | `/api/v1/agents/tasks/{task_id}/review` | `approve`, `reject`, `redraft` or `cancel` with the current `version` (and `plan_hash` for approve or reject) | Verified human `TenantAdmin`; execution enabled for approve and redraft |
| POST | `/internal/v1/agent/claim` | Claim the next draft or execute assignment for a workspace | Worker token; workspace in the worker grant |
| POST | `/internal/v1/agent/tasks/{task_id}/heartbeat` | Extend the lease by 120 seconds | Worker token and current lease token |
| POST | `/internal/v1/agent/tasks/{task_id}/draft` | Run AI planning and save the validated plan | Worker token and current lease token |
| POST | `/internal/v1/agent/tasks/{task_id}/steps/{index}/start` | Request the single-use permit for step `index` | Worker token, lease token and matching plan hash |
| POST | `/internal/v1/agent/tasks/{task_id}/steps/{index}/complete` | Report the step outcome | Worker token, lease token and matching plan hash |
| POST | `/internal/v1/agent/tasks/{task_id}/fail` | Stop the assignment without retry | Worker token and current lease token |

## Data and evidence

- **Tables:** `agent_tasks` and `agent_task_events`, created by [migrations/versions/0017_agent_execution.py](../../migrations/versions/0017_agent_execution.py). Every state change increments the task version and appends an event with the actor (`gateway`, `worker:<id>` or the human actor).
- **Task payload:** intent, connector IDs, resource type, expected state, plan, plan hash, approval (actor, plan hash, approved and expiry times), per-step state and result, connector bindings and a data-retention expiry. Lease token hashes are stored but never returned.
- **Step results:** status, an uppercase result code (for example `TAGS_VERIFIED` or `TAG_UPDATE_REQUIRES_RECONCILIATION`), an optional HTTP status and an optional evidence digest. Raw provider bodies, tag values and credentials are never recorded.
- **Retention:** Task content expires after the workspace's AI response retention period. Expired tasks show `[AI CONTENT EXPIRED]`, keep their audit hashes and outcomes, and cannot be approved, redrafted or executed.
- **Paired GitOps journal:** Recorded in the `agent_gitops_syncs` workflow with the task ID, plan hash and step evidence digest.

## Permissions

| Actor | Can do |
| --- | --- |
| Viewer or other workspace role | View the catalog, task queue, plans and audit history |
| `TenantAdmin` | Create tasks, request redrafts and cancel tasks |
| Verified human `TenantAdmin` session | Approve or reject a plan |
| Agent worker | Claim, heartbeat, draft, start and complete steps, and fail assignments, only for workspaces and connectors in its grant |

Paired GitOps connectors also require the Terraform export entitlement. API keys can never approve execution.

## Configuration

**Agent gateway** (`agent-gateway` service in [compose.yaml](../../compose.yaml)):

| Variable | Purpose | Default |
| --- | --- | --- |
| `CLOUDSAVER_AGENT_ENABLED` | Kill switch for task creation, approval, redraft and all worker routes | `false` |
| `CLOUDSAVER_AGENT_CONNECTORS` | JSON array (at most 100) of connector grants: `id`, `tenant_id`, `provider`, `scope_id`, `kind` (`azure_arm`, `aws_sdk`, `gcp_rest`, `k8s_api`, `gitops_terraform`, `http_json`), `operations` and kind-specific bindings | `[]` |
| `CLOUDSAVER_AGENT_WORKERS` | JSON array (at most 100) of worker grants with exactly `id`, `token_sha256`, `tenant_ids` and `connector_ids`. Store only the token's SHA-256 digest here. | `[]` |
| `CLOUDSAVER_IDENTITY_TOKEN` | Identity-service caller token for the gateway (set from `CLOUDSAVER_IDENTITY_TOKEN_AGENT` in Compose) | Unset |
| `CLOUDSAVER_AI_ENABLED` | Enables AI planning through the configured AI gateway | Unset (disabled) |
| `CLOUDSAVER_GITOPS_TARGETS`, `CLOUDSAVER_GITOPS_PUBLISH`, `CLOUDSAVER_GITHUB_APP_ID`, `CLOUDSAVER_GITHUB_APP_PRIVATE_KEY` | Repository targets and GitHub App used by paired GitOps steps | `[]`, `false`, unset, unset |

**API gateway:** `AGENT_GATEWAY_URL` sets where agent routes are forwarded (default `http://agent-gateway:8006`).

**TypeScript worker** (`agent-worker` service, `agentic` Compose profile):

| Variable | Purpose | Default |
| --- | --- | --- |
| `CLOUDSAVER_AGENT_GATEWAY_URL` | Agent gateway origin (no path, credentials or query) | `http://agent-gateway:8006` |
| `CLOUDSAVER_ENVIRONMENT` | When `production`, the gateway URL must use HTTPS | `development` (Compose) |
| `CLOUDSAVER_AGENT_WORKER_TOKEN` | Worker credential (at least 32 characters). Bind from a secrets manager. | Required |
| `CLOUDSAVER_AGENT_TENANT_IDS` | JSON array of 1–100 workspace UUIDs to poll | Required |
| `CLOUDSAVER_AGENT_CONNECTORS` | Connector definitions; must match the gateway's exactly | `[]` |
| `CLOUDSAVER_GITOPS_TARGETS` | Repository targets for validating `gitops_terraform` bindings | `[]` |
| `CLOUDSAVER_AGENT_AZURE_IDENTITY` | `workload_identity` selects workload identity; any other value uses managed identity | `managed_identity` (Compose) |
| `AZURE_CLIENT_ID` | Optional managed identity client ID (set from `CLOUDSAVER_AGENT_AZURE_CLIENT_ID` in Compose) | Unset |
| `AWS_WEB_IDENTITY_TOKEN_FILE` | Required for AWS connectors; static `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` must not be set | Unset |
| `CLOUDSAVER_AGENT_K8S_TOKEN_*` | Kubernetes service-account token named by a connector's `token_env` | Unset |

## Guardrails and limitations

- **Disabled by default.** The gateway rejects creation, approval, redraft and all worker calls until `CLOUDSAVER_AGENT_ENABLED=true`. The worker runs only under the `agentic` Compose profile.
- **No arbitrary code.** The worker only imports the deterministic program rendered from the approved plan, and model output is treated as data.
- **Single-use, ordered permits.** A step can start only once, only after all earlier steps succeeded, and only while the approval and data retention are unexpired and the connector configuration still matches the approved hash.
- **Leases.** Leases last 120 seconds, heartbeats run every 20 seconds, and one assignment can last at most 15 minutes. A lost lease ends in `failed`, or `needs_reconciliation` if a write may have started.
- **No automatic retry.** On any worker error the task is failed or fenced for reconciliation. Tasks with attempted writes cannot be redrafted.
- **Rate limits.** Each workspace can create at most 100 new tasks per rolling day.
- **Fresh data only.** Tasks require a completed live scan less than 24 hours old, and the workspace directory must be fresh for worker access.
- **Live drift checks.** Writes fail with `LIVE_STATE_CHANGED` or `LIVE_RESOURCE_STATE_DRIFTED` if the resource changed since inspection.
- **Sensitive data.** The worker refuses step arguments that look like passwords, keys, tokens or signed URLs.
- **Not savings proof.** A succeeded task does not establish realized savings. Use the verified savings workflow for billing evidence.

## Tests

- [tests/test_agent_execution.py](../../tests/test_agent_execution.py) — task lifecycle, approval and lease fences, permits and connector validation.
- [tests/test_v150_workflows.py](../../tests/test_v150_workflows.py) — paired agent GitOps synchronization.
- [tests/test_data_governance.py](../../tests/test_data_governance.py) — data-governance blocks on agent planning and actions.
- [tests/test_route_inventory.py](../../tests/test_route_inventory.py) — edge route inventory, including agent routes.
- [tests/test_postgres.py](../../tests/test_postgres.py) — PostgreSQL behavior, including agent persistence.
- [agent-worker/tests/runtime.test.ts](../../agent-worker/tests/runtime.test.ts), [agent-worker/tests/multicloud.test.ts](../../agent-worker/tests/multicloud.test.ts), [agent-worker/tests/azure-identity.test.ts](../../agent-worker/tests/azure-identity.test.ts) — worker runtime, connectors and identity selection (`npm test` in `agent-worker/`).
- [web-dashboard/e2e/agents.spec.ts](../../web-dashboard/e2e/agents.spec.ts) — browser coverage of the Agent worker page.

## Related docs

- [Human-approved agent gateway and TypeScript worker](../AGENTIC_WORKER.md)
- [AI data governance](../AI_DATA_GOVERNANCE.md)
- [GitOps and pre-merge guardrails](../GITOPS.md)
- [Automation and GitOps](automation-and-gitops.md)
- [Risk and compliance](risk-and-compliance.md)
- [Environment variables](../ENVIRONMENT.md)
