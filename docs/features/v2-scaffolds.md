# v2 scaffolds

CloudSaver contains several v2 scaffolds: small, tested modules that define a contract or a calculation for a future capability but aren't connected to live collection, scans, the dashboard or any cloud write API. Two scaffolds are exposed as read-only API endpoints, and one placeholder endpoint (`GET /api/v1/auth/consent-url`) always returns 501. This page describes each scaffold's purpose, current state, inputs and outputs, and what you need to build before it's production-ready.

Last reviewed: Oct 25, 2026.

## Where to find it

| Scaffold | Module | Wired to |
| --- | --- | --- |
| GPU idle detection | [app/scanner_ai_gpu.py](../../app/scanner_ai_gpu.py) | Nothing (tests only) |
| Commitment ladder | [app/autopilot_commitments.py](../../app/autopilot_commitments.py) | Nothing (tests only) |
| Karpenter NodePool drafts | [app/k8s_karpenter_sync.py](../../app/k8s_karpenter_sync.py) | Nothing (tests only) |
| Model routing savings | [app/ai_workload_optimizer.py](../../app/ai_workload_optimizer.py) | Nothing (tests only) |
| Cloud event streams | [app/collectors/event_stream.py](../../app/collectors/event_stream.py) | Nothing (tests only) |
| GitOps resource index | [app/gitops_ast_mapper.py](../../app/gitops_ast_mapper.py) | `GET /api/v1/gitops/resource-mapping` in [app/gitops_api.py](../../app/gitops_api.py) |
| Unit economics | [app/unit_economics.py](../../app/unit_economics.py) | `GET /api/v1/finops/unit-economics/preview` in [app/finops_api.py](../../app/finops_api.py) |
| Interactive consent | [app/main.py](../../app/main.py) | `GET /api/v1/auth/consent-url` (returns 501) |

None of these have dashboard screens. The README lists them as having "no production wiring yet".

## What you can do

- Call the unit economics preview to compare cost and volume change between two aligned periods.
- Look up which repository file manages a cloud resource, if your operator has configured a GitOps index.
- Use the remaining modules from Python code and tests to prototype the v2 roadmap.

You can't run GPU, commitment, Karpenter, model routing or event-stream features from the API or dashboard.

## How it works

### GPU idle detection

- **Purpose**: detect idle GPUs from DCGM-style metric samples.
- **Current state**: contract validation only; there's no GPU metric collector.
- **Inputs**: `validate_dcgm_sample(sample)` requires `gpu_utilization`, `memory_used_mb` and `memory_total_mb`. Utilization must be between 0 and 100.
- **Outputs**: `{valid, idle, utilization}`, where `idle` is utilization below 5. `idle_gpu_candidates(samples, min_idle_hours=24.0)` returns idle samples with `recommendation: review_hibernation`.
- **Limitation**: `min_idle_hours` must be positive but isn't otherwise used, so a single idle sample qualifies. Memory fields aren't validated beyond being present.
- **To make it production-ready**: a tenant-bound DCGM or Prometheus collector, a duration check that honors `min_idle_hours`, inventory and source-ledger integration, a rule in the catalog, and pricing evidence.

### Commitment ladder

- **Purpose**: plan staged, human-approved savings plan or reservation purchases.
- **Current state**: scenario only; no purchase APIs.
- **Inputs**: `commitment_ladder(raw_p10_hr, waste_hr, existing_hr, steps=("25", "50", "75"))`, as decimal strings passed to `calculate_clean_commitment_baseline` in [app/commitment_arbitrage.py](../../app/commitment_arbitrage.py).
- **Outputs**: one row per step with `step_pct`, `recommended_new_commitment_hr`, `purchase_authorized: False` and `status: scenario_only`.
- **Limitation**: every step returns the same full ceiling; `step_pct` isn't applied to the amount.
- **To make it production-ready**: apply the step percentage, source hourly baselines from billing data, add an API and approval workflow, and keep purchases outside CloudSaver or behind explicit human approval.

### Karpenter NodePool drafts

- **Purpose**: draft Karpenter NodePool manifests from sizing inputs.
- **Current state**: returns a dictionary; nothing is applied to a cluster.
- **Inputs**: `draft_node_pool(name, instance_types, cpu_limit, consolidation="WhenEmpty")`. `name` and `instance_types` are required.
- **Outputs**: a `karpenter.sh/v1` `NodePool` with on-demand and spot capacity types, the instance-type requirement, a CPU limit and the consolidation policy.
- **To make it production-ready**: derive inputs from Kubernetes rule evidence and SLOs, validate `consolidation` and `cpu_limit`, and deliver drafts through the GitOps review flow rather than cluster writes.

### Model routing savings

- **Purpose**: estimate savings from routing part of an AI workload to a smaller model.
- **Current state**: pure decimal math.
- **Inputs**: `routing_savings_usd(requests, large_cost_per_1k, small_cost_per_1k, routable_fraction)`. `requests` must be nonnegative; `routable_fraction` must be between 0 and 1.
- **Outputs**: `baseline_usd`, `optimized_usd`, `estimated_savings_usd` (never negative) as decimal strings, and `advisory_only: True`.
- **To make it production-ready**: measured request volumes and per-model prices from AI usage data, a quality guardrail for routed requests, and an API and dashboard view.

### Cloud event streams

- **Purpose**: react to cloud change events instead of waiting for the next scan.
- **Current state**: parsing and buffering only.
- **Inputs and outputs**:
  - `InMemoryEventBuffer(capacity=1000)`: `push(event)` requires a mapping with `source` and adds `received_at`; `drain()` returns and clears events. Capacity must be positive; the oldest events are dropped when full.
  - `EventStreamConsumer.parse_eventbridge`, `parse_eventgrid` and `parse_pubsub` normalize envelopes to `{source, provider, action, resource_id, raw}`.
  - `subscribe_eventbridge`, `subscribe_eventgrid` and `subscribe_pubsub` raise `NotImplementedError` ("… subscription is not wired in v1.7.x").
- **To make it production-ready**: authenticated, tenant-bound subscriptions for AWS EventBridge, Azure Event Grid and GCP Pub/Sub; a durable queue instead of the in-memory buffer; scope validation of each resource ID; and a worker that triggers targeted rescans.

### GitOps resource index

- **Purpose**: map a cloud resource to the repository file that manages it, and preview an IaC change.
- **Current state**: a read-only lookup from a static index, plus a placeholder patch preview.
- **Inputs**: the index comes from `CLOUDSAVER_GITOPS_AST_INDEX`, a JSON object keyed by cloud resource ID. Each entry has `repository`, `file_path` and `iac_kind`. `lookup(resource_id)` accepts 1 to 2,048 characters.
- **Outputs**: `ResourceMapping` with `cloud_resource_id`, `repository`, `file_path` and `iac_kind`. `patch_preview(mapping, change)` returns a placeholder Terraform or OpenTofu `import` block for those kinds and raises `NotImplementedError` for any other kind (for example Bicep). `change` isn't used.
- **Limitation**: the configured index is deployment-wide, but the API enforces owned observation, cloud scope and workspace repository grants before disclosing an entry. No code builds the index from repositories.
- **To make it production-ready**: a tenant-scoped index built by parsing your repositories, real diffs generated from the requested change, support for more IaC kinds, and integration with the existing GitOps review routes.

### Unit economics preview

- **Purpose**: tell you whether cost grew faster than business volume between two aligned periods.
- **Current state**: an API endpoint over pure decimal math; there's no dashboard view.
- **Inputs**: `prior_cost`, `current_cost`, `prior_volume`, `current_volume` as strict decimal strings (1 to 32 characters each).
- **Outputs**: `cost_change_ratio`, `volume_change_ratio`, `elasticity_ratio` and `advisory_only: True`, plus `unit_efficiency_regression: True` when elasticity exceeds 1.15. Prior cost must be positive; a zero baseline is rejected rather than reported as zero growth.
- **Errors**: 422 when either volume isn't positive or both volumes are equal.
- **To make it production-ready**: source costs from FinOps imports and volumes from a business metric feed, align the periods automatically, and add a dashboard view.

### Interactive consent

- **Purpose**: generate a cloud consent URL so you can connect cloud accounts yourself.
- **Current state**: the route requires `TenantAdmin` and then always returns 501 "Interactive consent onboarding is not implemented; ask your platform operator to add cloud accounts in the platform portal". Operators add cloud accounts in the platform portal instead.
- **To make it production-ready**: a consent flow per provider, a callback that records the grant in identity-service, and an access check before the scope becomes active.

## API reference

| Method | Path | Purpose | Required role/scope |
| --- | --- | --- | --- |
| GET | `/api/v1/finops/unit-economics/preview` | Cost and volume elasticity | `BillingAdmin` (or `TenantAdmin`); `scoped_read` |
| GET | `/api/v1/gitops/resource-mapping` | Look up the repository file for `resource_id` | Any role; `scoped_read` |
| GET | `/api/v1/auth/consent-url` | Placeholder; always returns 501 | `TenantAdmin`; `agnostic` |

All three are forwarded by [services/gateway.py](../../services/gateway.py). The dashboard proxy forwards both advisory read endpoints as GET operations. Resource mapping additionally requires an observed owned resource and a workspace-granted repository; it is not an unrestricted global index lookup.

## Data and evidence

- None of the scaffolds write to the scan store or produce findings.
- Every money or ratio output is a decimal string, and the modules that produce recommendations mark them `advisory_only` or `scenario_only`.
- The resource-mapping endpoint returns only what's in the configured index.

## Permissions

- Unit economics uses the finance dependency, which requires `BillingAdmin`; `TenantAdmin` satisfies it.
- Resource mapping accepts any authenticated workspace role.
- Consent URL requires `TenantAdmin`.

## Configuration

| Variable | Purpose | Default |
| --- | --- | --- |
| `CLOUDSAVER_GITOPS_AST_INDEX` | JSON object mapping resource IDs to `repository`, `file_path` and `iac_kind` | `{}` |

A malformed index returns 422 from the resource-mapping endpoint.

## Guardrails and limitations

- No scaffold calls a cloud write API, purchases commitments or applies manifests.
- `idle_gpu_candidates` ignores `min_idle_hours`, and `commitment_ladder` ignores the step percentage.
- Event subscriptions raise `NotImplementedError`.
- Patch preview is a placeholder for Terraform and OpenTofu and raises `NotImplementedError` for other kinds.
- The GitOps index isn't tenant-scoped.
- Two of the endpoints aren't reachable through the dashboard proxy.

## Tests

- [tests/test_v2_advanced_scaffolds.py](../../tests/test_v2_advanced_scaffolds.py): GPU, commitment ladder, Karpenter and routing savings.
- [tests/test_event_stream.py](../../tests/test_event_stream.py): buffer, parsing and unimplemented subscriptions.
- [tests/test_gitops_ast_mapper.py](../../tests/test_gitops_ast_mapper.py): lookup, patch preview and index loading.
- [tests/test_unit_economics.py](../../tests/test_unit_economics.py): elasticity math.
- [tests/test_v041_api.py](../../tests/test_v041_api.py): consent URL returns 501.

## Related docs

- [V2_0_ARCHITECTURAL_ROADMAP.md](../V2_0_ARCHITECTURAL_ROADMAP.md)
- [Scanning and analysis rules](scanning-and-analysis-rules.md)
- [Onboarding and access](onboarding-and-access.md)
- [Platform portal](platform-portal.md)
