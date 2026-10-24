# Human-approved agent gateway and TypeScript worker

CloudSaver can now assign resource tasks to a containerized TypeScript worker. AI drafts a connector plan; a human reviews its exact resource, arguments and recovery limits; the agent gateway then releases that approved version for execution. This implementation uses direct connector APIs and TypeScript `runCode`, with no MCP client/server.

The subsequent [AI data governance increment](AI_DATA_GOVERNANCE.md) adds mandatory processor/purpose approval, minimized model context, retention and erasure. Generic HTTP action transfers are now blocked. Follow that guide's migration and registration steps as well as the worker setup below.

| Component | Responsibility |
| --- | --- |
| `agent-gateway`, FastAPI, port 8006 | Durable task queue, authenticated review, Foundry-governed AI planning, approval hashes/expiry, worker grants, leases, step permits and audit |
| `agent-worker`, Node/TypeScript container | Poll assigned workspaces, request AI drafting, execute approved programs and report bounded connector outcomes |
| `/agents` dashboard | Assign a task from inventory, inspect connector arguments and TypeScript, approve/reject/redraft/cancel, follow execution and audit history |
| Migration `0017_agent_execution` | `agent_tasks` and append-only `agent_task_events`, both with forced tenant RLS and versioned state changes |

Human APIs are forwarded through the existing edge gateway/BFF. Worker APIs are private and are not forwarded by either. Workers receive dedicated machine tokens, never human workspace keys. Resource scope checks apply at creation, read, assignment and execution; removing a scope from a workspace blocks further worker use of its tasks.

## Workflow

1. Select an exact inventory resource from a completed live scan less than 24 hours old. Demo scans cannot create execution tasks.
2. In **Agent workspace**, select an approved same-cloud Foundry target and connector permissions. Enter an explicit instruction, for example `Inspect the tags, then set CostCenter to FINOPS-42.`
3. A worker claims the drafting assignment and requests inference through the gateway. Planning uses existing AI Foundry platform/workspace policy, plan entitlement, same-cloud routing, hourly limits and durable monthly token reservations. Existing advisory endpoints keep their prohibition on executable instructions.
4. The model returns structured steps, not arbitrary executable source. Validation rejects unsupported operations/arguments, more than eight steps, multiple writes, and tag mutations without a preceding inspection. Each step must explain its purpose, verification and recovery limitations.
5. The task waits in `awaiting_approval`. A human `TenantAdmin` reviews the resource, exact arguments, connector destinations and TypeScript, then approves the displayed version/hash for 1–60 minutes (15 default). API keys and service-account principals cannot approve; a verified human session is required. Viewers can inspect scoped plans and history.
6. The gateway assigns execution only for the approved plan. Before **every call**, it durably records an ordered, single-use step permit. Expiry, cancellation, changed connector bindings, revoked worker grants, mismatched hashes and lost leases prevent new calls.
7. The worker makes the connector request once and reports its outcome. Task success establishes completion of the connector contract; financial savings remain unverified and require independently reconciled billing evidence.

## TypeScript `runCode`

The deterministic compiler produces a real TypeScript module:

```ts
type AgentContext = { call(index: number): Promise<unknown> };
export async function run(ctx: AgentContext): Promise<unknown[]> {
  const results: unknown[] = [];
  results.push(await ctx.call(0));
  results.push(await ctx.call(1));
  return results;
}
```

The approved structured plan defines each index's exact connector, operation and arguments. Approval hash schema 4 binds saved expected state as part of the plan. Its SHA-256 binds the plan, generated source, task/resource/tenant/scope and connector configuration. The worker compares assigned connector bindings with its independently deployed catalog, and compares source byte for byte with its own compiler before using Node's `stripTypeScriptTypes` and importing the generated program. Context calls must be sequential and obtain gateway permits.

This is a limited connector runtime, not a general code sandbox. The compiler inserts numeric indices only; model strings never enter executable source. Free-form model code, imports, shell commands, dependency installation, filesystem tools, browser automation and unrestricted network tools are not exposed. Adding arbitrary code later requires a separate disposable execution boundary; Node `vm` alone is insufficient isolation.

## Direct connectors

v1.4 adds AWS inspection/tags/KMS safety snapshots, GCP inspection/labels/snapshots, Kubernetes inspection/recommendation annotations, and Azure managed-disk snapshots. Read [supported targets, identity requirements and approval invalidation](LEAN_CORE_IMPLEMENTATION.md#execution-and-data-governance) before configuring them. Use a tag-only Azure binding for non-disk targets; snapshot-enabled bindings require managed disks.

The following Azure tag semantics remain in place.

### Azure ARM tags

An `azure_arm` binding supports `resource.inspect` (read current supported resource metadata and tags through fixed ARM APIs) and `tags.merge` (merge up to ten explicit tags after inspection, preserve other keys, and read back the requested values). Inspection now reads supported resource metadata as well as tags, compares the saved expected disk/VM/application state, and rechecks metadata before mutation. Unsupported metadata resource types fail closed. This is not a complete resource safety assessment. Reserved Microsoft/Azure/hidden tag prefixes and unbounded keys/values are rejected. Models cannot provide alternative ARM URLs, resource IDs or API versions.

The worker uses managed identity or workload identity, fixed `management.azure.com` endpoints, exact subscription/resource matching, bounded responses, TLS and no redirects. Dot-segment paths are rejected. It re-reads tags before mutation and refuses drift from the earlier inspection. An ETag is sent as `If-Match` when returned; this is a best-effort check, not a universal atomic concurrency guarantee from ARM. Post-write readback is required for success.

Disk deletion, VM stop/delete, resizing, Kubernetes patching, Terraform apply and commitment purchases are not implemented by this connector. Their existing backup/SLO/remediation requirements remain. Add a separately reviewed typed adapter and operation-specific preconditions before enabling such mutations.

### HTTP JSON compatibility schema

The configuration schema still recognizes historical `http_json` bindings, but data governance blocks their assignment, plan approval and worker invocation before resolving credentials or sending HTTP. Human approval cannot enable this transfer. Use the reviewed typed Azure, AWS, GCP or Kubernetes adapter for supported operations.

## Deployment configuration

Apply migration through `0019_multicloud_governance_and_pillars` before starting upgraded services, following the retention review steps in the data governance guide:

```bash
docker compose build migrate agent-gateway agent-worker
docker compose run --rm migrate
```

Configure non-secret bindings in deployment configuration; replace template UUIDs:

```dotenv
CLOUDSAVER_AGENT_ENABLED=true
CLOUDSAVER_AGENT_CONNECTORS=[{"id":"azure-tags","tenant_id":"<workspace UUID>","provider":"azure","scope_id":"<subscription UUID>","kind":"azure_arm","operations":["resource.inspect","tags.merge"]}]
CLOUDSAVER_AGENT_WORKERS=[{"id":"worker-a","token_sha256":"<SHA256>","tenant_ids":["<workspace UUID>"],"connector_ids":["azure-tags"]}]
CLOUDSAVER_AGENT_TENANT_IDS=["<workspace UUID>"]
CLOUDSAVER_AGENT_AZURE_IDENTITY=managed_identity
CLOUDSAVER_AGENT_AZURE_CLIENT_ID=<execution identity client UUID>
```

Generate a random worker token of at least 32 characters. Store its **value** in a deployment secret bound to `CLOUDSAVER_AGENT_WORKER_TOKEN`; put only its SHA-256 digest in the gateway grant. Use a separate token per worker trust domain. Replicas may share a grant and compete safely for leases. Never reuse workspace, platform-caller or billing tokens.

Use identical non-secret connector definitions in gateway and worker deployments. Altering endpoint, ownership, operation list or secret reference invalidates pending approval. Rotating the secret value behind the same reference preserves the binding hash. Removing a worker grant blocks further gateway calls immediately.

### Identity and model access

Upgrade the platform identity service to recognize the new `agent` caller. It has verification/policy-read access, not directory-write or platform-admin privileges. Add its distinct identity caller token and platform digest with the existing configuration helpers:

```bash
python scripts/setup_compose.py --add-identity
python platform/scripts/setup_platform.py --add-callers .env
```

The helpers update untracked local configuration. Restart affected identity services after changing allowed digests. `CLOUDSAVER_IDENTITY_TOKEN_AGENT` authenticates the gateway to the identity service; it is distinct from the worker token. The separate platform project must remain reachable over `platform-link`.

Planning requires `CLOUDSAVER_AI_ENABLED=true`, a permitted subscription plan, existing Foundry consent and a reviewed processor approved specifically for `agent_planning`. Matching logical ownership identifiers must be deployed. A reviewed keyless Bedrock or Vertex processor can also be approved for this purpose under the v1.4 provider-specific registration contract; existing source-cloud routing still applies. Model invocation stays in the gateway's existing provider adapter, so the TypeScript worker needs no model key. Failed/uncertain model attempts remain in the durable AI ledger. A human can request a new draft after inspecting the cause, up to five drafts per task.

Planning attempts count toward shared AI usage/budgets but are excluded from advisory assessment history/detail APIs because their response schema is a task plan. Review their plan and lifecycle in the Agent workspace.

Model context contains the explicit instruction, resource **type** and connector IDs/kinds/operations. Resource identifiers/names, current tag values, destinations and credential references are excluded. User instructions can still contain sensitive data: do not enter secrets or personal information. Task data and results are not contributed to shared knowledge or used as training inputs.

### Compose

```bash
docker compose build agent-gateway agent-worker
docker compose up -d agent-gateway api-gateway web-dashboard
docker compose --profile agentic up -d agent-worker
docker compose logs -f agent-gateway agent-worker
```

Compose starts the disabled-by-default gateway so catalog/history exist; the worker is opt-in via the `agentic` profile. Its container uses non-root UID, a read-only filesystem, dropped capabilities, no-new-privileges and CPU/memory/PID limits, without a Docker socket. Stop it using `docker compose --profile agentic stop agent-worker`. The feature kill switch blocks assignment/new permits but cannot undo a dispatched request.

Use a separate execution identity from discovery with the minimum resource/tag RBAC. Prefer one workspace/credential trust domain per worker deployment. Local Docker does not gain Azure managed identity merely from an environment variable; use a correctly configured Azure host or workload-identity projected token. Do not mount a developer Azure CLI cache into production.

### Azure Container Apps

Build/push `agent-worker/Dockerfile` to your registry. Deploy the worker as a separate long-running Container App, **no ingress**, minimum replicas 1, with its execution identity. Deploy the gateway with internal-only TLS ingress on port 8006, PostgreSQL connectivity and separate model/identity-service permissions. Set edge `AGENT_GATEWAY_URL` to this service. Workers must not receive migration owner credentials or platform database access.

The worker has its own build context and dependency lockfile:

```bash
docker build -t <registry>/cloudsaver-agent-worker:1.0.0 ./agent-worker
docker push <registry>/cloudsaver-agent-worker:1.0.0
```

Set worker `CLOUDSAVER_AGENT_GATEWAY_URL` to the gateway's internal **HTTPS** FQDN and `CLOUDSAVER_ENVIRONMENT=production`; production workers reject HTTP. Bind the worker token through Container Apps secrets or Key Vault references. For managed identity, bind the chosen execution identity. For workload identity, set `CLOUDSAVER_AGENT_AZURE_IDENTITY=workload_identity` and provision `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_FEDERATED_TOKEN_FILE` and the platform-projected token mount through private deployment configuration.

Restrict egress to the assigned gateway, token service and connector destinations. Application grants supplement cloud RBAC/network policy. Multiple replicas can safely contend for assignments; this durable queue needs no Redis broker. No production deployment or separate infrastructure-repository update is performed by this increment.

## Failure and audit semantics

- State changes increment the task version and append an event. Runtime SQL privileges cannot alter/delete events or rewrite resource/ownership columns.
- Leases last 120 seconds with 20-second heartbeats and a 15-minute assignment limit. Approved work takes precedence. Initial limits are 100 new tasks per workspace per rolling day and 50 recent visible tasks returned from a bounded recent window.
- A crash after a step permit becomes `needs_reconciliation` on the next queue pass or detail read after lease expiry. Lost acknowledgements are conservatively uncertain; actions are never automatically replayed.
- Tasks with attempted writes cannot be redrafted to replay them. Reconcile provider state before creating a separate change. Recovery text is a review requirement, not an automated rollback implementation.
- Cancellation blocks subsequent steps; an in-flight request may still complete and be recorded under its live lease. The UI explains this race.
- Results contain status codes and evidence digests, not raw provider responses, tag values or secrets. Worker outcomes are not independent provider audit attestations or savings proof.
- Approval uses existing workspace/Entra authentication. Shared legacy admin keys identify key holders, not independently verified natural persons. Fresh step-up, four-eyes review, continuous revalidation of an approval principal after key revocation, and external execution attestations remain future work. TTL, cancellation and the kill switch bound current authority.

## APIs

Human: `GET /api/v1/agents/catalog`, `GET|POST /api/v1/agents/tasks`, `GET /api/v1/agents/tasks/{id}`, `POST /api/v1/agents/tasks/{id}/review`. Decisions are `approve`, `reject`, `redraft`, `cancel`. Reviews require the current version; approve/reject also require the exact hash.

Worker: `POST /internal/v1/agent/claim`, `/internal/v1/agent/tasks/{id}/heartbeat`, `/draft`, `/fail`, `/steps/{index}/start`, `/steps/{index}/complete`. These require a dedicated worker token, an assigned workspace, and after claim the task-specific unexpired lease token. None is exposed by the edge/BFF route map.

## Verification

The following counts record the original worker increment. The later data-governance changes have additional backend, worker and browser checks described in the governance guide.

- Full backend/platform suite against disposable PostgreSQL 16 and Redis 7: **783 passed**. Includes forced-RLS audit privileges, worker claim contention, approval/lease fences, shared metering and Python-to-TypeScript execution through real gateway step permits.
- Complete dashboard browser suite: **52 passed**, including explicit approval, viewer/mobile access, uncertain outcomes, live drafting-to-review polling, sidebar navigation and automated accessibility checks.
- Worker TypeScript checks and dashboard production build passed. Compose configuration and `git diff --check` passed.
- The independent worker Docker image built successfully. All **8 worker/runtime tests passed inside the Node 24.22.1 container**, running as non-root with a read-only filesystem, dropped capabilities and networking disabled. Provider HTTP calls in these tests are mocked.

Backend tests emitted one upstream Starlette/httpx deprecation warning. Node emits an experimental warning for `stripTypeScriptTypes`; the release image pins the tested Node version. Host build/typecheck checks used Node 24.19.0; use the declared >=24.22.1 version for local development. Tests use synthetic model responses and receipts; no live cloud mutation, customer-data export or production deployment was performed. Temporary QA servers, containers and validation image/cache were stopped or removed.

Local worker checks:

```bash
cd agent-worker
npm ci
npm run typecheck
npm test
```
