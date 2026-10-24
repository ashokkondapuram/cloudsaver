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

On Windows, follow the [PowerShell setup without installing Python](#windows-powershell-setup-without-installing-python) below.

```bash
# New installation: generate private env files rather than copying blank templates.
python3 scripts/setup_compose.py
(cd platform && python3 scripts/setup_platform.py)
(cd platform && python3 scripts/setup_platform.py --add-callers ../.env)
# Configure reviewed workspace scopes and identity bindings.
make platform-up
make build
docker compose run --rm migrate
make up
make status
```

Open `http://localhost:3000` and connect with your authorized workspace credential or configured human identity. In Settings, review scopes, billing, rules, processor approvals and delegated access before scanning or enabling inference.

If you already copied `.env.example` into `.env` for a **new, empty database**, fill its blank database passwords without replacing other settings:

```bash
python3 scripts/setup_compose.py --init-db-passwords
docker compose --env-file .env config --quiet
```

An existing PostgreSQL volume needs its original `POSTGRES_PASSWORD` and `CLOUDSAVER_DB_PASSWORD`. Editing `.env` does not change database role passwords. Recover those existing values from your deployment's secret store instead of initializing replacements. Run Compose from the repository root or supply its `.env` path explicitly.

### Windows PowerShell: setup without installing Python

Start Docker Desktop with Linux containers, then open **PowerShell**. These commands run the setup scripts inside a temporary Python container; Windows does not need Python or Make installed. They assume the repository was extracted to your Downloads folder; adjust `Set-Location` if necessary.

Use this workflow for a **fresh installation**. If database volumes already contain data, restore the original environment files and credentials instead of generating replacements. The setup scripts refuse to overwrite existing `.env` files.

```powershell
Set-Location "$HOME\Downloads\cloudsaver"
$mount = "type=bind,source=$($PWD.Path),target=/work"

# Create cloudsaver\.env with generated database passwords and service tokens.
docker run --rm --mount $mount -w /work python:3.12-alpine python scripts/setup_compose.py

# Create platform\.env. Skip this command if that file already exists.
docker run --rm --mount $mount -w /work/platform python:3.12-alpine python scripts/setup_platform.py

# Register CloudSaver service-token digests with the platform.
docker run --rm --mount $mount -w /work/platform python:3.12-alpine python scripts/setup_platform.py --add-callers ../.env

# Start the platform first; it creates the shared platform-link network.
docker compose --env-file .\platform\.env -f .\platform\compose.yaml up --build -d

# Validate the root environment, then start CloudSaver.
docker compose --env-file .\.env config --quiet
docker compose --env-file .\.env up --build -d
```

Save the operator key printed once during platform setup. The platform portal is at `http://localhost:3100`; CloudSaver is at `http://localhost:3000`.

The root file is `cloudsaver\.env`, **not** `cloudsaver.env` or `.env.txt`. The second project uses `cloudsaver\platform\.env`; the explicit `--env-file` arguments select the correct file for each project. A Windows “Python was not found” message means a host-side setup command did not run; use the Docker commands above.

For a **new, empty database** where you already copied a template into the root `.env`, run this from the same PowerShell session to fill blank database passwords without replacing configured values:

```powershell
docker run --rm --mount $mount -w /work python:3.12-alpine python scripts/setup_compose.py --init-db-passwords
docker compose --env-file .\.env config --quiet
```

If the copied template also has blank service tokens, use the same Docker command with `--add-identity`, then repeat the platform `--add-callers ../.env` command before starting services. None of these helpers changes passwords stored in an existing PostgreSQL volume.

### Upgrade an existing installation

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
