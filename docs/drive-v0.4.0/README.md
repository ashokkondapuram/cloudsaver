# CloudSaver

Current release: **v0.2.0**. This includes Sprints A–C from the updated Drive README: verified Stripe billing webhooks, opt-in Celery scan workers and an explicit Azure Key Vault credential provider. See [SPRINTS_ABC.md](SPRINTS_ABC.md) for contracts and limits.

CloudSaver is an engineering MVP for reviewing potential Azure cloud waste. It turns the architecture and starter code supplied in Drive into a runnable application with a Next.js dashboard, five Python services, persistent scan history, tenant-scoped access and four Azure Resource Graph checks.

This release is a development foundation, not a completed commercial SaaS. The application never executes cloud changes. It can generate a reviewable, interactive deletion script for selected live unattached disks and unassociated public IPs; running that script is a separate, destructive operator action. Demo costs are illustrative; live findings have no savings figure until billing attribution is implemented. There is no runtime Gemini integration. Gemini continuation instructions below describe development collaboration only.

## Application architecture

| Component | Container port | Responsibility |
| --- | ---: | --- |
| Next.js dashboard | 3000 | React 19, TypeScript and Tailwind interface; same-origin API proxy |
| API gateway | 8000 | Workspace authentication, Redis request limit and service routing |
| Tenant service | 8001 | Authenticated workspace configuration |
| Scanner service | 8002 | Azure checks and tenant-scoped scan storage |
| Analytics service | 8003 | Category counts from the latest scan, without double-counting history |
| Notification service | 8004 | Explicitly requested summary delivery to an operator-configured webhook |
| PostgreSQL 16 | 5432 | Scan records with forced row-level security |
| Redis 7 | 6379 | Gateway rate-limit counters |

Only the dashboard and gateway are published by Compose, on loopback addresses. Internal service requests carry the caller's bearer key and each service authenticates it. This bootstrap authentication is not Entra ID sign-in. PostgreSQL connections use the restricted `cloudsaver_app` role; each storage operation sets its tenant context inside the transaction. The application must never use a PostgreSQL superuser or a role with `BYPASSRLS`.

The lightweight `app.main` application provides a standalone API and SQLite history. Its root page is an API welcome page, not a dashboard. Run the separate Next.js dashboard to use this backend locally. This path does not exercise the complete Compose stack.

## Quick local demo

Use Python 3.12 and Node.js 22. Run from this directory:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python scripts/run_demo.py
```

Keep the backend running. In another terminal, install Node.js 20 or newer, then run:

```bash
cd web-dashboard
npm ci
npm run dev
```

Open `http://127.0.0.1:3000` and paste the workspace access key printed by the backend launcher. The dashboard's same-origin proxy targets `http://127.0.0.1:8000` by default; `API_GATEWAY_URL` changes its server-side target. The launcher creates a fresh random key for each run and does not write it to disk. Scan history persists in `data/cloudsaver.sqlite3` by default. Demo fixtures are clearly marked and do not call Azure. Keep the printed key private.

For Windows, activate the environment with `.venv\Scripts\activate` before running the Python commands.

## Run the six-service stack

Install Docker Engine with the Compose plugin. For a fresh demo, run `python scripts/setup_compose.py` to create private local settings and print a workspace key. This refuses to overwrite an existing `.env`. Alternatively, copy `.env.example` to `.env` and set these values before starting:

- `DEMO_ACCESS_KEY`: a random key of at least 32 characters.
- `POSTGRES_PASSWORD`: a strong password for the database initialization owner.
- `CLOUDSAVER_DB_PASSWORD`: a different strong, URL-safe password for the restricted application role. A hexadecimal random string is suitable for inclusion in the connection URL.

Generate each value separately. For example:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Do not commit `.env` or share its contents. Then run:

```bash
docker compose up --build -d
docker compose ps
```

Open `http://127.0.0.1:3000` and enter `DEMO_ACCESS_KEY`. The gateway is available at `http://127.0.0.1:8000`. `make build`, `make up`, `make status`, `make logs` and `make down` wrap common Compose commands.

Database initialization creates the role and schema only for a new PostgreSQL data volume. Changing a password in `.env` does not rotate an existing database role. Apply deliberate migrations and password rotation for existing installations. `docker compose down` keeps the database volume; deleting that volume destroys saved history.

The release includes Compose wiring, but Docker startup and live PostgreSQL integration were not verified in this development environment. See `TEST_REPORT.md` for the checks actually performed.

## Configure live Azure scanning

Set `CLOUDSAVER_MODE=azure`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET` and `CLOUDSAVER_TENANTS`. Tenant and subscription IDs are operator-managed configuration, never taken from an arbitrary scan request. Each tenant supports 1–100 unique subscription IDs.

Compose passes Azure credentials only to the scanner service. Missing credentials fail a live scan; there is no fallback to demo data or another Azure identity.

`CLOUDSAVER_TENANTS` is a JSON array:

```json
[
  {
    "tenant_id": "11111111-1111-4111-8111-111111111111",
    "name": "Your organization",
    "subscription_ids": ["22222222-2222-4222-8222-222222222222"],
    "api_key_sha256": "replace_with_the_lowercase_sha256_digest_of_a_random_workspace_key"
  }
]
```

Replace the example IDs with actual authorized Azure IDs. Generate a random workspace key and configure its SHA-256 digest; give the original key only to authorized workspace users. Configuration rejects duplicate tenant IDs, duplicate key digests and malformed IDs. Raw workspace keys are not stored in server configuration.

The application registration needs an authorized service principal in each customer tenant and read access to the configured subscriptions. Set up and verify these permissions with the tenant administrator. Admin consent and RBAC onboarding remain future work. Environment credentials use an explicit client secret; the optional Key Vault provider also supports certificates held in memory. Never paste Azure secrets into chat or source files.

The checks cover unattached managed disks, unassociated public IPs, stopped/deallocated VMs and empty App Service plans. A finding is a review signal, not proof that deletion is safe or that a resource incurs a particular bill. Stopped VMs and their associated disks need separate review. Resource Graph results are paginated; a failed or incomplete audit does not save a partial successful scan.

The Azure path has not been tested against live subscriptions in this environment.

## API and storage

Workspace `/api/v1/` routes require `Authorization: Bearer <workspace-key>`. The public Stripe webhook instead requires a verified Stripe signature:

| Method | Route | Behavior |
| --- | --- | --- |
| GET | `/healthz` | Unauthenticated service liveness |
| GET | `/api/v1/me` | Current workspace and mode |
| GET | `/api/v1/scans?limit=50` | Workspace scan history; maximum limit 100 |
| POST | `/api/v1/scans` | Run a read-only scan and save its complete result |
| GET | `/api/v1/scans/{scan_id}` | Read a scan owned by the workspace |
| POST | `/api/v1/scans/{scan_id}/remediation` | Generate a selected-resource script from an owned completed live scan |
| GET | `/api/v1/analytics` | Latest-snapshot aggregation; service stack only |
| POST | `/api/v1/notifications/{scan_id}` | Explicit webhook send; service stack only |
| POST | `/api/v1/billing/webhook` | Stripe signature verification and tenant-scoped billing state; gateway/tenant service only |

Interactive scans run synchronously in a server thread pool. Standalone mode has a process-local guard; Compose enables a shared Redis lease across the API and scheduled workers. The lease is finite, and request cancellation does not stop an in-flight SDK operation; abnormal long requests need acceptance testing. A concurrent scan returns 409; scan failure returns 502 and saves no partial history. Interactive history stores completed scans. Scheduled jobs additionally retain queued/running/completed/failed states. Gateway limits are 120 requests per workspace per 60-second fixed window and fail closed when Redis is unavailable.

`CLOUDSAVER_DB` selects the standalone SQLite file. `CLOUDSAVER_DATABASE_URL` selects PostgreSQL instead. The Compose scanner uses PostgreSQL. Configure an application-role connection, never the initialization owner's credentials.

## Reviewable remediation scripts

`POST /api/v1/scans/{scan_id}/remediation` accepts a JSON body of the form `{"resource_ids":["<exact ARM resource ID from the scan>"]}`. It returns a shell script and suggested filename. Only completed live Azure scans and 1–50 unique, authorized disk or public-IP findings are eligible; demo scans and VM/App Service findings are rejected.

The application does not execute this script. Review the entire file and confirm retention requirements and independent backups before running it. The script requires Azure CLI and an interactive terminal, checks the active tenant and each subscription's tenant, requires typing each full ARM resource ID, and rechecks resource state immediately before deletion. Deletion permanently removes disk data or releases the public IP. State checks and deletion are not atomic; the script cannot eliminate a change between them. Do not treat script generation as automatic approval or as a guarantee of safe deletion.

## Database model and migration baseline

`database/models.py` defines organization, tenant, subscription, finding, billing-event and scan-job models. Alembic migrations 0001–0003 provide the schema. Interactive scans persist snapshots through `app/store.py`; the scheduled worker atomically commits normalized findings, a snapshot and job completion through `workers/storage.py`.

Run domain migrations as a deliberate schema-owner operation using `CLOUDSAVER_MIGRATION_URL`, separate from the runtime `CLOUDSAVER_DATABASE_URL`:

```bash
alembic upgrade head
```

Set the migration URL securely in the environment before running the command. The migration runner rejects `cloudsaver_app`; do not grant the runtime role migration privileges. Compose initializes the snapshot table through `database/init.sh` and `database/001_schema.sql`; that initialization is distinct from the domain Alembic migration. Live migration execution still needs verification against PostgreSQL.

## Optional notifications

Set `CLOUDSAVER_NOTIFICATION_WEBHOOK` to an operator-controlled HTTPS Slack or Teams webhook supported by `services/notification.py`. The notification endpoint first verifies scan ownership, then sends only an aggregate summary without resource names or subscription IDs. Webhook destinations cannot be provided by dashboard users. Scheduled-worker alerts require a separate explicit `CLOUDSAVER_AUTOMATED_ALERTS=true`; they run after scan commit and are not a durable notification outbox. An unset webhook returns a clear configuration error; repeated explicit sends are not deduplicated.

## Enable Sprints A–C locally

Build the core stack, then apply the domain migrations using the isolated owner operation:

```bash
docker compose up --build -d
docker compose --profile operations run --rm migrate
```

Only `migrate` receives the database owner connection. Runtime services use `cloudsaver_app`. The snapshot schema initializes separately for a fresh PostgreSQL volume.

Provision the trusted configured tenants and subscriptions before scheduling. This is an explicit operator action:

```bash
docker compose run --rm scanner-service python scripts/provision_tenants.py --activate
```

Without `--activate`, provisioned tenants stay pending and subscriptions inactive. For a specific existing organization or billing customer, use `--tenant-id`, `--organization-id` and `--stripe-customer-id`. The command refuses tenant reassignment and replacement of an existing customer binding. Run `python scripts/provision_tenants.py --help` for options.

For billing, configure `STRIPE_WEBHOOK_SECRET`, `CLOUDSAVER_STRIPE_CUSTOMERS` and `STRIPE_PRICE_TIERS` in `.env`, then recreate the tenant service. The customer mapping must exactly match the provisioned organization/customer relationship. `STRIPE_PRICE_TIERS` can be `{"price_your_growth_id":"GROWTH"}`. See `SPRINTS_ABC.md` for customer mapping format. The receive-only webhook does not create Checkout sessions or charges and does not yet enforce paid entitlements across all APIs. Use Stripe test-mode lifecycle events for external acceptance.

For scheduling, deliberately set `CLOUDSAVER_SCHEDULED_SCANS=true` in `.env` after reviewing the configured subscriptions, then start one scheduler and worker:

```bash
docker compose --profile scheduled up -d scan-worker scan-scheduler
```

The interval defaults to 3600 seconds, minimum 300. Both database activation and the trusted configuration allowlist must permit each subscription. Alerts stay off unless `CLOUDSAVER_AUTOMATED_ALERTS=true` is separately configured. No schedules or outbound alerts were enabled during development. Worker retries and total database attempts are bounded. A transactional dispatch outbox/reconciler is still needed for a crash between queuing a database row and publishing its broker message. Post-commit notifications also have a delivery gap; exactly-once delivery is not claimed.

For Key Vault, select `CLOUDSAVER_CREDENTIAL_PROVIDER=keyvault`, configure `AZURE_KEYVAULT_URL`, and grant the scanner/worker identity secret-read permission. Managed identity is the default; explicit `AZURE_KEYVAULT_AUTH=default` opts into the local Azure default credential chain. Secret names and tenant-matched JSON schemas are in `SPRINTS_ABC.md`. Certificate mode uses Python's `CertificateCredential` with in-memory PEM bytes. Failed vault access never falls back to environment credentials. Local Compose does not automatically provide an Azure managed identity; verify in an appropriate Azure environment or explicitly provision local credentials. Environment mode stays the default.

## Development and verification

The unit tests need no external credentials.

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

The dashboard's own `package.json` defines its frontend commands. See `TEST_REPORT.md` for the exact test and build evidence from this release. Mocked Azure tests verify scanner logic, not cloud permissions or real billing results. Live Azure, full Docker Compose and database RLS integration require an environment with those dependencies.

For a manually configured standalone server:

```bash
uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000
```

Use HTTPS and an appropriate ingress before any remote access. The included loopback development configuration is not a public hosting deployment.

## Continue development with Gemini

Share this source package and `TEST_REPORT.md` with Gemini. No Gemini review or external collaboration has been performed by this release. Use the following development brief:

> Continue CloudSaver from the existing source. Read README.md, ROADMAP.md and TEST_REPORT.md before editing. Preserve the Next.js 15 / React 19 dashboard, five-service Python architecture, workspace ownership checks and PostgreSQL forced RLS. Do not add a runtime Gemini integration. Treat demo savings as illustrative and live savings as unknown. First reproduce the documented checks, then validate Compose startup and tenant isolation against a real PostgreSQL instance. Report exact commands, results and unverified assumptions. Propose a bounded change, identify the files you will edit, and add behavior-based tests. Preserve the starter code documents in Drive. Keep release status in the project README and deliver executable code as a source package. Do not expose secrets.

Recommended next assignments are PostgreSQL/Redis/Stripe/Key Vault acceptance tests, a transactional scan-dispatch and notification outbox, then Entra sign-in/onboarding. Coordinate file ownership before simultaneous edits. Have a separate reviewer inspect tenant authorization and migration privileges before deploying to shared infrastructure. Return reviewed source and verification evidence to the same Drive project folder.

## Source and references

The starter code documents in Drive are retained as source material. The native project README receives a release-status and development-handoff update; the executable source is delivered as a separate package. The architecture is adapted into an executable development package, with unfinished commercial features tracked in `ROADMAP.md`.

- [Azure Resource Graph Python query options and pagination](https://learn.microsoft.com/en-us/python/api/azure-mgmt-resourcegraph/azure.mgmt.resourcegraph.models.queryrequestoptions?view=azure-python)
- [Azure Resource Graph data and paging guidance](https://learn.microsoft.com/en-us/azure/governance/resource-graph/concepts/work-with-data)
