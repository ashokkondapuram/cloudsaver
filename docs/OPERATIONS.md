# Database operations

These procedures are for an operator-controlled development installation. Test
upgrades and restores against a disposable copy before applying them to shared
data. No backup/restore drill or live Azure deployment is claimed by this release.

## Roles and upgrades

Keep runtime and schema-owner credentials separate. `cloudsaver_app` must be
NOSUPERUSER, NOBYPASSRLS, NOCREATEROLE and must neither own application tables nor
inherit the owner role. Never give its credentials to dashboard users. PostgreSQL
RLS enforces the transaction tenant context set by the authenticated server;
possession of the shared runtime database credential is not a user identity.

For an existing installation, take a complete backup first, stop scan writes and
review migrations 0001_domain and 0002_scan_findings. Set
`CLOUDSAVER_MIGRATION_URL` securely to the schema owner connection and run:

```bash
python -m alembic upgrade head
python -m alembic current
```

The `cloudsaver_app` role must already exist. Compose creates it only on a fresh
data volume, then runs a one-shot owner-credential `migrate` container before the
scanner starts. Changing `.env` never rotates passwords in an existing database.
For URLs assembled by Compose, both passwords must be URL-safe; the setup script
generates independent hexadecimal values. Review migrations before `make up` on
an existing installation, since Compose applies pending migrations automatically.

Migration 0002 retains old snapshot payloads and adds a nullable source-scan ID
to existing domain findings. It does not backfill or guess historical identities.
New ingestion always supplies the scan ID. Downgrading removes normalized scan
links; it preserves snapshots but should not be used as a substitute for a
reviewed rollback or restore plan.

## Complete backup

Configure an operator-only libpq service called `cloudsaver_backup` in a private
`pg_service.conf` and credentials in a mode-0600 `.pgpass` or an equivalent secret
manager. Use a dedicated backup identity with access to all tenant rows; the
runtime role cannot create a complete multi-tenant dump under forced RLS. A
backup account with BYPASSRLS must never be used by the application.

```bash
umask 077
pg_dump --dbname=service=cloudsaver_backup --format=custom --file=cloudsaver-backup.dump
pg_restore --list cloudsaver-backup.dump
```

Keep role definitions, credential recovery procedures and server configuration in
the operator's protected infrastructure inventory; a database dump does not
contain cluster-level roles. Encrypt backups, restrict access and configure
retention outside the application. A successful archive listing is not a restore
test.

## Restore drill

Create a new isolated PostgreSQL 16 database and the expected owner/runtime roles.
Configure a separate libpq service `cloudsaver_restore` pointing to that disposable
target with an authorized restore administrator. Never point it at an existing
customer database. Then:

```bash
pg_restore --dbname=service=cloudsaver_restore --exit-on-error --single-transaction cloudsaver-backup.dump
```

Verify Alembic revision, row counts as the backup/owner administrator, forced RLS,
role privileges and representative scan payloads. Through the runtime role, verify
two tenants cannot read or insert each other's records and absent context yields
no rows. Repeat application history reads after restart. Record archive checksum,
restore duration and results before considering the backup process accepted.

## Repeatable tests and stack smoke

```bash
python test_platform.py --postgres
python scripts/smoke_stack.py
# Restart local services without deleting the database volume, then reuse the ID:
docker compose restart scanner-service api-gateway web-dashboard
python scripts/smoke_stack.py --scan-id <id-printed-by-first-smoke>
```

The PostgreSQL runner creates a uniquely named disposable container with temporary
private credentials and removes it afterward. It never points at existing data.
The smoke script checks workspace authentication, configured providers, entitlements,
GitOps history and the dashboard proxy. It never triggers a cloud scan,
notification or remediation. The scan-id form verifies persistence after a
restart without creating another scan.

`docker compose down` retains history. `docker compose down --volumes` destroys
history; reserve it for confirmed disposable environments.

## Proxy-backed builds

Dockerfiles accept an optional BuildKit secret named `proxy_ca`. Supply the
environment's combined CA bundle to Python and Node dependency-install steps
through a local Compose build-secret override. Keep TLS verification enabled;
the CA is never copied into image layers. The repository does not include
session-specific certificate paths. Internal service hostnames are explicitly
excluded from HTTP proxies through Compose NO_PROXY settings.

## v0.4.1 migration convergence and scheduling

The merge revision 0004_merge_hardening joins 0002_scan_findings (GitHub v0.2)
and 0003_scan_jobs (Drive v0.4). Both upgrade paths are tested with retained
snapshot history. The merge adds a job ownership token and tenant-owned job/scan
link. Do not rename, delete or manually stamp prior applied revisions. Existing
Drive installations must review any pre-existing domain data before migration;
no automatic guessed backfill is performed.

Workers remain behind the scheduled Compose profile. Only operator-activated
subscriptions and persisted paid plans qualify. A transactional PostgreSQL
reservation limits Growth to daily and Enterprise to hourly scheduling, even if
two schedulers race. In v0.7.1 reservations commit delivery intent in the same
transaction; a separately enabled dispatcher publishes/reconciles it. Read
DELIVERY.md before activation. Automatic alerts remain opt-in.

## v0.6.0 cloud findings upgrade

Back up before upgrading. Revision 0005_cloud_findings creates a separate
normalized non-Azure finding table with forced RLS and a tenant-owned scan foreign
key. Existing Azure subscription foreign keys and histories remain intact.
Runtime startup rejects a missing/unprotected table or a table-owner/bypass role.
The integration runner tests upgrades from both previous branches and the v0.4.1
merge head. SQLite standalone scans remain supported with scope validation.

Provider credential and metric deployment is documented in CLOUD_SOURCES.md.
Workers/schedules remain Azure-only; automatic alerts remain disabled. Interactive
multi-cloud scans share the tenant Redis lease with the existing Azure worker.

```bash
python scripts/smoke_stack.py
# After service restart, use the returned ID without creating a new scan:
python scripts/smoke_stack.py --scan-id <saved-scan-id>
```

This checks existing data and routing only. It never calls cloud providers,
notification hooks, Stripe or remediation.

## v0.7.0 request history and upgrade

Migration 0006_gitops_requests adds forced-RLS GitOps history with tenant-owned
scan foreign keys, hashed request keys and fenced publisher leases. Back up first;
apply migrations with the schema owner before starting scanner-service. Retain
request history when designing retention: referenced scans cannot be deleted
while request/job/finding ownership links remain. No purge was run for this release.

Follow GITOPS.md to configure repository/App bindings. Publishing is disabled by
default. An uncertain result may already exist in GitHub; inspect history and
retry the same key. Never force-push or delete a branch to bypass a collision.
Historical synthetic records are projected with explicit provenance and unknown
prices; their original stored bytes are retained and they cannot be exported.

## v0.7.1 durable delivery upgrade

Apply 0007_delivery_outbox as the migration owner before restarting application
services. It adds forced-RLS delivery/audit/dispatcher tables, job ownership keys
and the queued notification state. Current histories are retained. Read DELIVERY.md
for the explicit global-webhook migration, pre-upgrade queued-job quarantine,
configuration, replay limits, pause/recovery and rollback restrictions.
