# CloudSaver v1.4.0 — focused resource intelligence

CloudSaver provides one five-pillar review per cloud resource, separate billing and retail evidence, Kubernetes capacity analysis, and human-approved TypeScript agent tasks. Discovery is read-only. An AI suggestion never authorizes a cloud change.

This revision implements the [lean architecture and existing-feature improvements](docs/LEAN_CORE_IMPLEMENTATION.md). It removes duplicate finding/service explorers, manual optimization forms and cases, CLI/Terraform generators, GitOps publishing, and shared knowledge harvesting. Historical database records are retained; the upgrade does not drop customer history.

## Five customer views

| View | Purpose |
| --- | --- |
| `/` | Deduplicated review opportunities, protection counts, scan trends, billing evidence and an hourly commitment ceiling when complete evidence exists |
| `/resources` | Inventory and findings merged into one resource assessment; service/provider/pillar filters, billing columns, scan deltas, CSV, AI review, decisions and agent handoff |
| `/kubernetes` | API/Prometheus/OpenCost provenance, allocation slack, backing node billing and carefully gated consolidation models |
| `/agents` | Exact connector plans, verified human approval, expiring single-use permits and bounded execution evidence |
| `/settings` | Four tabs: Cloud scopes & billing, Analysis rules, AI & data governance, Access & API keys |

The platform portal remains a separate operator application for customer, workspace, identity, plan and policy administration. Its knowledge-publishing pages and APIs have been removed.

## Architecture

- `app.main:create_app`: core API, scanners, settings, resource decisions, billing and governance on internal port 8002.
- `services.gateway:create_app`: authenticated edge on port 8000; fixed internal destinations and workspace request limits.
- `services.agent_gateway:create_app`: isolated task/approval/permit gateway on port 8006.
- `agent-worker/`: separately deployed TypeScript worker. Numeric `ctx.call(index)` programs only; no MCP, arbitrary model source, shell or generic HTTP actions.
- `web-dashboard/`: Next.js customer console on port 3000.
- `workers/`: durable scan jobs, scheduling, delivery and AI batch processing. PostgreSQL transactions and outbox intents fence retries; Redis bounds leases and queues.
- `platform/`: independent identity database, identity API and operator portal.

Tenant isolation uses PostgreSQL forced RLS and scoped application queries. Do not run runtime services with owner, superuser or BYPASSRLS credentials.

## Run locally

Use the existing deployment configuration and the separate platform project. `.env.example` documents non-secret settings and required secret references. Do not commit `.env`, cloud credentials or workspace keys.

```bash
cp .env.example .env
# Configure reviewed workspace scopes, database roles and platform caller credentials.
make platform-up
make build
docker compose run --rm migrate
make up
make status
```

Open `http://localhost:3000` and connect with your authorized workspace credential or configured human identity. In Settings, review scopes, billing, rules, processor approvals and delegated access before scanning or enabling inference.

For an existing installation, apply platform revision `i0013_multicloud_analysis_catalog` and core revision `0019_multicloud_governance_and_pillars` using their schema-owner migration jobs. Rebuild the stack and remove the obsolete tenant/analytics/notification containers with `docker compose up -d --remove-orphans` after checking this deployment's orphan list. This does not remove database volumes. The core service now owns the directory projector; only one core replica should run it.

```bash
docker compose build
docker compose run --rm migrate
docker compose up -d --remove-orphans
```

Deploy the optional agent worker only after reviewing identity mounts, connector grants and approval policy:

```bash
docker compose --profile agentic build agent-worker
docker compose --profile agentic up -d agent-worker
```

## Evidence, pricing and billing

The catalog covers 36 resource families across Azure, AWS, GCP and Kubernetes. Rule enablement and threshold delegation stay under platform policy, with customer preview/save in Settings. A catalog entry does not prove every API permission, pricing input or telemetry series is available.

```dotenv
CLOUDSAVER_LIVE_EVIDENCE_ENABLED=true
CLOUDSAVER_LIVE_EVIDENCE_MAX_RESOURCES=25
```

Live enrichment is opt-in and bounded. Rules require validated history and fresh observations; missing samples are never zero-filled. No-event audit history does not prove continuous idleness. Rightsizing checks include SLO burn, latency sensitivity, throttling and recovery constraints.

FOCUS imports preserve billed, effective and list costs, currency, source identity and charge periods. Resource joins use the exact authorized resource, provider and account. The resource columns show the preceding 30 complete UTC days as of the saved scan, in USD. Other currencies stay in their own finance summaries. Imported billing is not provider reconciliation or verified savings.

Azure retail attribution accepts exact regional consumption meters and explicit component quantities for disks, VM compute/storage, compatible target SKUs and gateway fixed/capacity charges. Snapshot storage is deducted from unattached-disk estimates. AWS/GCP regional meters must have an exact provider/region/product/unit identity and a current operator review in `CLOUDSAVER_REGIONAL_PRICE_CATALOG`. No universal or stale rate is silently installed. See the [meter contract and calculation examples](docs/LEAN_CORE_IMPLEMENTATION.md).

Kubernetes workload allocation estimates remain separate from node costs. Accountless EKS node identities must match exactly one regional EC2 inventory instance. Physical consolidation remains unknown without complete billing, verified scheduling/PDB/autoscaler constraints and commitment disposition.

## AI and execution governance

AI processing requires an approved processor in the owning logical environment, the correct purpose, workspace consent, model/region policy and budget. Azure, AWS and GCP bindings use reviewed keyless identities. Field allowlists, secret filtering, output validation, retention, erasure and legal holds remain enforced. Cross-tenant learning, shared knowledge harvesting and training on client observations are disabled and have no ingestion API.

Human TenantAdmin sessions approve worker plans. API keys and service accounts cannot approve execution. The plan binds the saved expected operational state; live metadata is checked during inspection and again before mutation. State drift stops the task even when tags have not changed. Provider calls have bounded responses and no automatic write retry. Ambiguous writes require reconciliation.

Read the [agent deployment guide](docs/AGENTIC_WORKER.md) and [AI data governance guide](docs/AI_DATA_GOVERNANCE.md). Processor declarations record the owner's review; they do not independently prove a cloud provider's internal retention, training behavior or residency.

## Verify

```bash
# Full backend/platform suite with disposable PostgreSQL and Redis
PYTHONPATH=platform python scripts/test_postgres.py tests platform/tests --tb=short
npm --prefix agent-worker run typecheck
npm --prefix agent-worker test
npm --prefix web-dashboard run build
npm --prefix platform/portal run build
# Start the built dashboard, then run browser checks against its URL.
npm --prefix web-dashboard run test:e2e
```

Verification results and deployment boundaries are recorded in the [lean implementation guide](docs/LEAN_CORE_IMPLEMENTATION.md). Live customer cloud permissions, metrics, reviewed rates and operational acceptance still require environment-specific validation. The documented upstream Azure Identity/MSAL advisory remains under review; the worker does not expose its affected interactive authorization-code flow.
