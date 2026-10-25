# Feature restoration from 673c20a

Reference: `673c20a8069c6c08d223440361a24e170b55bf83`, “client-managed users, onboarding keys and scope-limited access keys.” This is an additive restoration onto the current code, not a reset to that older source tree. Later security controls, data governance, collectors, resource evidence, Kubernetes analysis, typed agent execution and deployment fixes are retained.

## Restored workflows

| Capability | Where to use it | Boundary |
| --- | --- | --- |
| Finding inventory and drill-down | Inventory & findings, `/findings` | Current workspace/provider scope, virtualized filters, CSV/JSON and per-finding evidence |
| Per-finding five-pillar and AI review | Finding drawer, 360° assessment | Explicit sanitized context, evidence fingerprint, admin permission, processor policy and idempotency |
| Bulk reviewed CLI scripts | Finding selection or finding drawer | No server-side execution; live-state/protection checks and required managed snapshots remain in generated scripts |
| Terraform remediation exports | Finding review drawer | Plan entitlement, selected-resource ownership, import/review artifacts; no automatic apply |
| GitOps and plan policy | Automation & GitOps, `/automation` | Explicit configured GitHub App/target, reviewed content, authenticated administrator request; no automatic merge |
| Allocation and service analysis | `/allocation` | Saved observation evidence, exact billing amounts, missing prices remain unknown |
| Activity and delivery | `/activity` | Saved scans, saved AI assessment/usage, delivery evidence and explicit admin retries |
| Printable resource report | Resources → Print report, `/resources/report` | Completed live observation and the report's displayed resource count |
| Keyboard and command navigation | G then F, command search, Shift+R on selected findings | Current session/role and resource selection |
| Client-managed access | Claim account, Access & API keys, platform customer onboarding | Original users, onboarding keys, service accounts, delegated roles and scoped key lifecycle remain |
| Platform resource access | Workspace → Resource access | Operator-owned cloud identity bindings; independent Rules tab retained |
| Publication administration and metrics | Platform → Knowledge | Separate database/identity, synthetic/public documentation sources, privacy screening, distinct author/technical/privacy reviewers |

The API compatibility manifest at `tests/fixtures/restored_673c20a_routes.json` records the original core, edge and platform method/path contracts. Tests compare these contracts against actual OpenAPI routes while existing tests continue to verify newer routes. Historical wrapper module paths are retained for compatibility; the standard deployment continues to route tenant/settings, analytics and notification APIs through the consolidated core service. It does not start duplicate projectors or legacy service containers.

## Newer behavior retained

- Resource-level deduplication and exact USD resource/period billing joins, independent billed/effective/retail amounts and explicit evidence gaps.
- Live evidence, bounded multi-cloud readers, complete scope authorization, deterministic job selection and current worker revalidation.
- Kubernetes provenance and conservative physical/financial savings checks.
- Human-approved typed TypeScript agent plans, state-drift checks and single-use execution permits.
- Purpose/processor/retention/hold controls; API-key and service-account execution approval remains prohibited.
- Four consolidated settings tabs with rule controls, AI governance, delegated access, cloud scopes and billing.
- Missing application-role recovery, explicit platform password recovery, Windows setup without host Python and persistent developer Azure CLI cache in ordinary Compose.

Restoration does not make estimated costs verified savings, turn model prose into approval, install cloud permissions, or activate live integrations without credentials. Features only added after the reference commit and later deliberately removed, such as the separate manual optimization-case studio and scan-derived shared-knowledge harvesting, are not required to restore the reference commit's feature set.

## Knowledge storage and privacy

Production knowledge operations fail closed until `PLATFORM_KNOWLEDGE_DATABASE_URL` is configured in `platform/.env`. It must name a PostgreSQL database and runtime role distinct from identity storage. Never point it at the identity database or use `identity_app`, an owner, superuser or BYPASSRLS credentials. The identity service connects to this store for publication administration only. It does not copy scans, prompts, client identifiers or customer metrics into it, and inference does not consume it automatically.

Provision a separate database with a migration owner and a restricted `knowledge_app` login. Grant that login CONNECT only to the knowledge database. Make the database reachable over the platform database network, then apply the retained `k0001_publications` migration as its owner. The platform image now includes `knowledge_alembic.ini` and its migrations. Run this from a trusted migration environment with owner URLs supplied through its secret/environment mechanism:

```bash
# From platform/, with PLATFORM_KNOWLEDGE_MIGRATION_URL set to the knowledge owner
# and PLATFORM_IDENTITY_MIGRATION_URL identifying the separate identity database.
python -m alembic -c knowledge_alembic.ini upgrade head
```

Configure the runtime URL through the deployment's private environment file/secret store and recreate `identity-service`. Retain the existing identity key pepper, portal key, caller tokens and database credentials. Never put owner URLs in the customer console or commit them to Git. The dedicated PostgreSQL integration test provisions disposable roles/databases, applies the knowledge migration, writes an independently sourced publication and verifies no publication table/data is written to the operational database.

Historical publication rows in the old identity database remain archived; they are not automatically copied into the dedicated knowledge database. Re-review independently sourced content before importing it through publication administration.

Only independently authored synthetic patterns or approved public documentation may be submitted. Possible identifiers/secrets are rejected before persistence. Technical and privacy reviewers must be distinct from each other and the author; published content is immutable. Publication/freshness counts are measured; correctness/citation rates remain unavailable until evaluated. Regex checks alone do not establish anonymization, so independent privacy review remains required.

Use distinct Microsoft Entra identities with the corresponding reviewer roles for publication review. A shared local operator key cannot establish three independent people and cannot satisfy those review requirements.

## Upgrade and verification

Keep existing `.env` files and database volumes. No rollback, destructive migration or data wipe is required. Apply the current platform/core migrations using the existing schema-owner jobs, rebuild both application images and restart through their normal Compose files. Previously stored scan, rule, access, billing and audit records are retained.

For local Azure scans, set only `CLOUDSAVER_CLOUD_IDENTITY=developer` and `CLOUDSAVER_INSTALL_AZURE_CLI=true` in the root `.env`, then use `docker compose up --build -d`. No Azure-only override is needed. A cache without an Azure sign-in still needs one-time authentication.

Verification covers the original API manifest, restored remediation/GitOps and assessment tests, current backend/platform contracts against disposable PostgreSQL/Redis, separate knowledge storage/review safeguards, both Next.js builds, and browser workflows for restored and current screens. Browser fixtures intercept external APIs and do not assert that real Azure/GitHub/model integrations have been connected.

Verified results: **810 backend/platform tests passed**, **54 browser workflows passed**, and **both frontend production builds passed**. Both Compose configurations validate, including scoped GitOps credentials, isolated knowledge configuration and the standard developer CLI cache.
