# CloudSaver v1.7.0 — full FinOps workspace

v1.7.0 adds workload assessments (application and environment roll-ups of five-pillar evidence), alongside keyless cloud billing synchronization, approval-bound agent metadata/IaC review workflows, service matrices and automatic planning evidence. Read [setup, boundaries and upgrade steps](docs/V1_5_0_IMPLEMENTATION.md) before enabling the new connectors. For workload grouping and ownership rules, see [workload assessments](docs/WORKLOAD_ASSESSMENTS.md). Existing restored workflows and deployment fixes remain available.


CloudSaver provides one five-pillar review per cloud resource, separate billing and retail evidence, Kubernetes capacity analysis, and human-approved TypeScript agent tasks. Discovery is read-only. An AI suggestion never authorizes a cloud change.

This revision restores the implemented features available at commit `673c20a8069c6c08d223440361a24e170b55bf83` alongside newer multi-cloud analysis, Kubernetes, agent execution and governance improvements. Findings, reviewed CLI/Terraform exports, GitOps, allocation, activity, printable reports and platform resource-access/publication controls are available again. The current database-recovery fixes and two-setting Docker Desktop developer setup remain. See the [restoration and compatibility guide](docs/FEATURE_RESTORATION_673C20A.md).

## Customer views

| View | Purpose |
| --- | --- |
| `/` | Deduplicated review opportunities, protection counts, scan trends, billing evidence and an hourly commitment ceiling when complete evidence exists |
| `/findings` | Provider/category/search filters, virtualized finding inventory, bulk CSV/JSON, evidence and five-pillar drawers, reviewed remediation exports |
| `/resources` | Inventory and findings merged into one resource assessment; service/provider/pillar filters, billing columns, scan deltas, CSV, AI review, decisions and agent handoff |
| `/workloads` | Application and environment roll-up of five-pillar resource evidence; ownership mapping and non-executable review steps |
| `/resources/report` | Printable resource assessment report from a completed live observation |
| `/services/[service]` | Service-specific analysis matrices (for example disks, compute, databases) |
| `/kubernetes` | API/Prometheus/OpenCost provenance, allocation slack, backing node billing and carefully gated consolidation models |
| `/optimization` | Optimization and retail evidence models tied to the selected scan |
| `/allocation` | Cost grouping, allocation/tag evidence, normalized billing imports and service analysis |
| `/outcomes` | Savings cases, investigations and outcome evidence |
| `/governance` | Risk and compliance workflows with human-approved change plans |
| `/agents` | Exact connector plans, verified human approval, expiring single-use permits and bounded execution evidence |
| `/automation` | Reviewed remediation, GitOps pull-request preparation and Terraform plan policy checks |
| `/activity` | Saved scan/AI history, delivery evidence and authorized delivery retry controls |
| `/claim` | First-time workspace onboarding with a platform-issued key |
| `/settings` | Four tabs: Cloud scopes & billing, Analysis rules, AI & data governance, Access & API keys |

The platform portal remains a separate operator application for customer, workspace, identity, plan and policy administration. Workspace Resource access and Rules tabs coexist. Its Knowledge page manages independently sourced publications in a separately configured knowledge database; privacy screening and two independent reviews precede publication. Automatic harvesting of client observations and training remain disabled.

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

### Azure scan fails: Azure CLI not found on path

`AzureCliCredential` means the scanner is using local **developer** authentication. The production image excludes Azure CLI unless explicitly enabled at build time. Installing or signing in to Azure CLI on Windows does not install it or establish a Linux-container sign-in. A successful `/api/v1/finops/imports` request confirms that API request succeeded; it does not verify Azure scan credentials.

For Docker Desktop, including Windows, edit the existing **root** `.env` and set these values while preserving the rest of the file:

```dotenv
CLOUDSAVER_CLOUD_IDENTITY=developer
CLOUDSAVER_INSTALL_AZURE_CLI=true
```

These are the only Azure developer setup flags required. The standard `compose.yaml` already provides a persistent CLI cache shared by the scanner and scan worker, writable by their non-root user. No override file, host Python or host Azure CLI is required. From the repository root, rebuild and start using ordinary Compose commands:

```powershell
# A container restart alone cannot install Azure CLI; rebuild the Python image.
docker compose up --build -d
```

The flags do not supply Azure credentials. If this cache has never been signed in, complete a one-time sign-in inside the scanner, replacing the placeholder with the Microsoft Entra tenant that owns your subscriptions:

```powershell
docker compose exec scanner-service az login --use-device-code --tenant "YOUR_ENTRA_TENANT_ID"
docker compose exec scanner-service az account list --query "[].{Subscription:id,Tenant:tenantId,Name:name}" --output table
```

Run each command only after the previous one succeeds. Complete the device-code sign-in in your browser; the scanner's user needs at least Reader access to the subscriptions selected for its workspace. Keep the browser/device sign-in code private. Then retry the scan in CloudSaver. Each additional Entra tenant must be signed in separately, and workspace tenant IDs must match the real owning Entra tenants.

If you use queued scans, also start or update the Celery scan worker so it uses the rebuilt image and shared CLI cache:

```powershell
docker compose up -d scan-worker
```

The cache is mounted only in the scanner and scan worker. The agent execution worker, platform and other services do not receive it. Existing optional host-cache overrides can replace these mounts; review a custom `compose.override.yaml` if it still binds a Windows Azure CLI directory. A previously copied `compose.azure-local.yaml` is no longer needed; omit its extra `-f` argument. Its cache volume name matches the standard stack, so an existing container sign-in is retained.

The volume contains developer credentials and survives container recreation. To sign out, use `docker compose exec scanner-service az logout`; both scanner and scan worker share that sign-in cache. Use developer authentication only for development. On Azure, configure an attached managed identity and the reviewed direct/federated access bindings described in [managed identity roles](docs/MANAGED_IDENTITY_ROLES.md). Managed-identity mode does not use this CLI cache. Setting `managed_identity` alone does not provide an identity on Docker Desktop.

### Migration fails: role "cloudsaver_app" does not exist

Read the actual migration error before retrying:

```powershell
docker compose --env-file .\.env logs --no-color --tail=120 migrate
```

If the log reports `psycopg.errors.UndefinedObject: role "cloudsaver_app" does not exist`, PostgreSQL is reachable but its application-role initialization did not finish. PostgreSQL only runs `/docker-entrypoint-initdb.d/` automatically when its data directory is empty; restarting a partially initialized volume does not rerun those scripts.

With the latest source, rebuild the Python service image and retry the migration. It creates a **missing** restricted application role from `CLOUDSAVER_DB_PASSWORD` and initializes the legacy scan store before applying schema grants. Existing role passwords and attributes are preserved. Unsafe existing role attributes stop the migration for administrator review.

```powershell
docker compose --env-file .\.env build migrate
docker compose --env-file .\.env run --rm migrate
# Continue only after the migration succeeds.
docker compose --env-file .\.env up -d
```

For an older image, when the log confirms that the role is missing, run its installed initialization script once before retrying:

```powershell
docker compose --env-file .\.env exec -T postgres sh /docker-entrypoint-initdb.d/00-init.sh
# Continue only if initialization succeeds.
docker compose --env-file .\.env run --rm migrate
docker compose --env-file .\.env up -d
```

These steps retain database records and volumes. Do **not** use `docker compose down -v` to repair this error. Keep the original credentials for populated databases. A password-authentication error is a different problem: restore the credentials that match the existing roles rather than rerunning initialization. Redact passwords and credential-bearing URLs before sharing logs.

### Platform migration fails: password authentication failed for identity_owner

`identity-migrate` uses `PLATFORM_DB_OWNER_PASSWORD` from **`platform/.env`**, separately from the CloudSaver database credentials in the root `.env`. The platform retains the PostgreSQL volume `cloudsaver_token-db-data`. Rebuilding a container or changing environment variables does not update passwords already stored in that volume. PostgreSQL can also report an authentication failure when the requested role was never created.

First restore the original `platform/.env` or its database passwords from your secret store if available. An upgrade from the older combined deployment can preserve its original settings with `platform/scripts/setup_platform.py --migrate-from ../.env`; that helper creates a new platform file and refuses to overwrite one that exists. Do not regenerate the key pepper, operator key or workspace keys during database recovery.

For a local deployment where you intentionally want the database to use the owner and app passwords in your **current** `platform/.env`, update the source from `main` while preserving your environment files, then run these commands from the repository root in PowerShell. Run them one at a time and continue only after each succeeds. This briefly stops platform access and explicitly changes the two database role passwords; other clients using the old passwords will need updating.

```powershell
# Install the updated, repeatable database initialization/recovery helper.
docker compose --env-file .\platform\.env -f .\platform\compose.yaml build platform-db
docker compose --env-file .\platform\.env -f .\platform\compose.yaml stop identity-service platform-portal

# Load the current environment into the database container; retain its volume.
docker compose --env-file .\platform\.env -f .\platform\compose.yaml up -d --wait --force-recreate platform-db

# Explicitly align stored owner/app passwords with the container environment.
docker compose --env-file .\platform\.env -f .\platform\compose.yaml exec -T platform-db sh /docker-entrypoint-initdb.d/00-identity.sh --reset-passwords

# Apply schema changes, then recreate the services with the current credentials.
docker compose --env-file .\platform\.env -f .\platform\compose.yaml run --rm identity-migrate
docker compose --env-file .\platform\.env -f .\platform\compose.yaml up -d --force-recreate identity-service platform-portal
docker compose --env-file .\platform\.env -f .\platform\compose.yaml ps
```

The helper creates missing roles/databases and preserves existing tables and records. Without `--reset-passwords`, it preserves existing passwords. It stops on unsafe role attributes or an unexpected database owner rather than silently changing them. Passwords are read inside the database container; do not paste them into terminal commands or share environment files. This does not change the PostgreSQL administrator password, identity key pepper or portal credentials.

If your database uses custom local administrator authentication, use your established DBA access procedure; do not weaken authentication to run this helper. Keep database backups and never use `down -v` as a password repair. If migration still fails, inspect:

```powershell
docker compose --env-file .\platform\.env -f .\platform\compose.yaml logs --no-color --tail=120 platform-db identity-migrate
```

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

## Local development prerequisites

- **Python 3.12** with `pip install -r requirements-dev.txt` (includes core and platform dependencies for local pytest).
- **Node.js 24.22.1 or newer** for `web-dashboard`, `agent-worker`, and `platform/portal`. Run `nvm use` from the repository root (see `.nvmrc`).
- **Docker** for disposable PostgreSQL/Redis integration tests (`scripts/test_postgres.py`) and the full Compose stack.

Quick unit checks without Docker:

```bash
make test
```

## Verify

```bash
python -m pip install -r requirements-dev.txt
# Full backend/platform suite with disposable PostgreSQL and Redis (requires Docker)
PYTHONPATH=platform python scripts/test_postgres.py tests platform/tests --tb=short
nvm use
npm --prefix agent-worker run typecheck
npm --prefix agent-worker test
npm --prefix web-dashboard run build
npm --prefix platform/portal run build
# Start the built dashboard, then run browser checks against its URL.
npm --prefix web-dashboard run test:e2e
python scripts/release_manifest.py --check
```

Verification results and deployment boundaries are recorded in the [lean implementation guide](docs/LEAN_CORE_IMPLEMENTATION.md). Live customer cloud permissions, metrics, reviewed rates and operational acceptance still require environment-specific validation. The documented upstream Azure Identity/MSAL advisory remains under review; the worker does not expose its affected interactive authorization-code flow.
