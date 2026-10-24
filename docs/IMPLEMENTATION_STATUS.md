# README-driven engineering improvements

This implementation follows [the supplied engineering guide](https://docs.google.com/document/d/1oYrx3weFUJMQiB-e8JA-bJoC4uRd0OHUtnlT1er_zOQ) against Git baseline `6e0de85fe321aa51d97c8dfb734c3e9532e85a71`.

Development is isolated on branch `feat/readme-enterprise-improvements` in the fresh version checkout. This is an implementation increment, not completion of every phase in the comprehensive guide. No production deployment, live payment operation, cloud resource change, or customer data import was performed.

## Delivered

| Area | Result |
| --- | --- |
| Scope isolation | Inventory-only rows and saved rule evaluations are filtered alongside findings. Financial summaries are recomputed from authorized resources without double-counting alternatives. Strict write operations reject snapshots containing unauthorized inventory. Membership downgrades reduce existing key grants. |
| Delegated credentials | Issuing or rotating a key cannot expand the presenting administrator key's provider/scope envelope. Initial owner credentials align with their workspace administration membership. |
| Customer access UX | Dedicated `/settings/organization` and `/settings/access` destinations reuse the existing users/keys console. Newly issued secrets clear after two minutes or a credential/workspace change. The UI no longer claims an email was sent when no email delivery is configured. |
| Multi-cloud inventory | AWS volumes, addresses and RDS instances, GCP supported resources, and Kubernetes metric-visible containers carry inventory independently of findings. Unsupported or absent telemetry is not interpreted as a pass. |
| Eight Azure evidence contracts | Separate evaluations for disk retention/performance, unassociated/associated-idle IPs, stopped/low-use VMs, and empty/underutilized App Service plans. Freshness, state-history, protected-resource, metric coverage, and missing-memory checks are explicit. |
| Rule administration | Eight rules are registered through Platform migration `i0010_analysis_policy`. Overrides accept strictly typed, bounded parameters, update the workspace revision, and publish directory/cache invalidation. Existing parameter overrides survive a simple enable/disable toggle. |
| Customer rule UI | `/settings/rules` lists published provider/service rules, parameters and bounds. Changes require an observation-only preview before application. Scope-limited credentials cannot change workspace-wide policy. |
| Service analysis | `/services/disks`, `/services/public-ips`, `/services/virtual-machines`, and `/services/app-service-plans` expose coverage, outcome matrices, observation history and snapshot comparison. Comparison does not claim deletion or realized savings. |
| Scan consistency | Interactive and scheduled scans save effective policy, rule outcomes and coverage with the snapshot. Identity-managed scans fail closed if current policy cannot be obtained. |
| Financial overlap | Opportunity rollups use the maximum known alternative within an explicit workload group or the same resource. Unknown alternatives keep the complete total unknown. Resource assessments no longer add overlapping retail estimates. |
| Separate knowledge database | Optional dedicated PostgreSQL connection, credentials, migration history and tables. No operational-database fallback or automatic copying of legacy publications. |
| Knowledge privacy and review | Public/synthetic sources only; identifying/secret patterns are rejected before persistence. Technical and privacy reviewers must be different people and neither can be the author. Reviewers can inspect the complete article, source and author in the portal. Editing a draft clears its approvals. Published content is immutable. |
| Reviewer access boundaries | Dedicated knowledge reviewers can review knowledge without global operator permissions. They cannot use those roles to browse customer directory data or author commercial plans. |
| Inference retrieval | Optional taxonomy-only retrieval of current reviewed publications. No resource names, IDs, tags, telemetry or client prompts enter the retrieval request. Fabricated publication citations fail validation. Retrieval failure prevents a chargeable inference when the feature is enabled. |
| Knowledge metrics | Portal shows measured publication/review-state/freshness counts. Citation accuracy and correctness remain explicitly unmeasured. An inference request is not counted as learned knowledge. |
| Billing migration | Validated, atomic, idempotent importer pairs with the read-only legacy exporter. Exported events now carry explicit workspace ownership. Exact decimal strings and currency minor units are validated; missing commercial terms are not invented. |
| Billing lifecycle | A periodic evaluator updates derived billing state and publishes entitlement changes. Lapsed customers receive configured fallback entitlements; suspend policy blocks product operations while preserving security/billing administration. Stored commercial subscription plans remain intact. |

## Evidence contracts and current collection limits

The eight rules evaluate saved evidence. Current Azure Resource Graph collection adds available current state, creation time, plan tier and app count. It does **not** acquire a complete 30-day five-minute Azure Monitor window, complete attachment/state-transition history, every deployment slot, or verified workload dependencies.

Consequently, rules requiring those inputs return `insufficient_evidence` until the collector supplies the required contract. Resource creation time is never substituted for unattached duration. Missing guest memory prevents a full VM rightsizing assessment. A utilization review is not a compatible target recommendation or an infrastructure approval.

Kubernetes inventory covers containers visible in the configured Prometheus series. It does not enumerate all cluster objects. Other inventories cover the currently implemented service families, not every possible resource type in a cloud account.

Coverage counts are resource sets and can overlap across different rule outcomes. Disabled/unavailable/unknown rules are not passes. Failed collectors abort the snapshot instead of silently resolving old findings.

Financial grouping is conservative. Parent workload groups must come from verified relationships; names/tags are not used to infer topology. More advanced combinations of independently compatible recommendations still need an explicit compatibility model.

## Enable the optional knowledge service

1. Provision a separate PostgreSQL database, such as `cloudsaver_knowledge`. Do not use the identity database or a schema within it.
2. Create a separate schema-owner identity and the unprivileged runtime role `knowledge_app`. Grant the runtime role connection access to this database. Do not grant superuser, RLS bypass, database creation or role-management privileges.
3. Configure `PLATFORM_KNOWLEDGE_MIGRATION_URL` with the knowledge-owner DSN and `PLATFORM_KNOWLEDGE_DATABASE_URL` with the runtime DSN through secret storage.
4. From `platform/`, run `python -m alembic -c knowledge_alembic.ini upgrade head` as the knowledge schema owner. The identity database retains its independent migration command: `python -m alembic -c identity_alembic.ini upgrade head`.
5. Assign `KnowledgeReviewer` and `PrivacyReviewer` as separate operator identity capabilities. Reviewers need not receive `PlatformOperator`; a PlatformOperator creates candidates and publishes only after both reviews.
6. Create independently authored synthetic or approved public-documentation guidance. Only approved official HTTPS documentation sources are accepted for source URLs.
7. Enable `CLOUDSAVER_KNOWLEDGE_ENABLED=true` on scanner/AI workers only after the separate database is migrated and the internal retrieval route is reachable. It defaults to false.

Knowledge service credentials must differ from identity service credentials. Runtime connections using the same database name or runtime username are rejected. The initial knowledge migration has no foreign keys or database links to client, identity or billing tables.

Automated identifier detection is a rejection aid, not proof that arbitrary text is anonymous. Independent privacy review remains mandatory. Client-derived contributions, fine-tuning, raw client feedback ingestion, and client-derived embeddings are not enabled.

Legacy publications in the identity database are not migrated automatically: they require eligibility review before any safe content is recreated in the separate store. Existing unreviewed records cannot become inference sources through a fallback.

Published guidance is excluded from retrieval when its approvals are older than 90 days. Retrieval is bounded to five entries from the first 1,000 current candidates; the response states those limits. Metrics have a 10,000-record cap and expose truncation. This increment does not claim an exhaustive semantic/vector search engine.

## Billing import

Run the existing exporter under its documented read-only source permissions. Keep the exported identifiers and the operator terms file outside Git.

From `platform/`, the importer entry point is:

`python -m identity.billing.importer --input /secure/billing-export.json --terms /secure/billing-terms.json`

The terms object is keyed by workspace UUID. Each imported provider subscription requires an explicit amount **string**, currency, interval, current-period start/end, and optional grace days. Amounts are converted using explicit minor-unit precision; supported currencies currently include USD, CAD, EUR, GBP, INR, AUD, JPY and KWD. Floats, exponent notation, non-finite numbers, duplicate JSON fields and excess precision are rejected.

Old exports whose events lack a workspace identifier must be regenerated; the importer does not guess event ownership. Conflicting customer references or subscriptions cause the whole transaction to roll back. Repeating unchanged inputs creates no duplicate subscription/provider events.

The billing evaluator does not charge cards, extend service dates based on a payment ledger entry, create invoices, or infer settlement. It follows the stored subscription period and grace policy. Key revocation and user/security administration remain available during billing suspension.

## Remaining guide requirements

The following work is still required before claiming full completion of the supplied blueprint:

- Live Azure Monitor/history/dependency collectors for all eight rule contracts, source-specific telemetry permissions, and broader provider/service evidence coverage.
- Delegated time-limited scoped rule exceptions, policy rollout approvals, and richer saved service views.
- Verified parent-workload opportunity grouping and more complex compatibility modeling.
- Structured private AI feedback storage/UI, automated safe public-source ingestion, semantic/vector indexing, immutable multi-article releases, and independently labeled quality/calibration benchmarks.
- Customer Entra/OIDC authorization-code + PKCE sessions, immutable issuer/subject enrollment, workspace switching, capability-level key subsetting, and fresh step-up verification.
- Invite/expiry notifications, transactional delivery and external SIEM integration.
- Live end-to-end validation of Stripe collection/settlement, cloud access and model-provider behavior. Existing Stripe tests exercise local SDK signatures, conservative transitions and the Platform boundary; they do not prove remote billing readiness.

No customer data is used for shared model training or automatic knowledge contribution in this increment.

## Verification

Completed verification:

| Check | Result |
| --- | --- |
| `PYTHONPATH=platform python scripts/test_postgres.py tests platform/tests --tb=short` | **631 passed** with real disposable PostgreSQL 16 and Redis 7, including forced RLS, migrations/rollback, dedicated knowledge database and rule-parameter persistence. |
| Dashboard `npm run test:e2e` against Chromium | **32 passed**, covering access, accessibility, resource tables, assessments, financial workflows and new rule controls. |
| Dashboard `npm run test:e2e -- e2e/rules-services.spec.ts` against the final production build | **2 passed**, verifying preview-before-apply and read-only viewers after the last dashboard change. |
| Dashboard `npm run build -- --webpack` | Production build and TypeScript validation passed. |
| Platform portal `npm run build -- --webpack` | Production build and TypeScript validation passed, including full knowledge article review. |
| `git diff --check` | Passed. |

Tests use synthetic inputs. Browser tests intercept backend requests with explicit fixtures; they do not validate remote Azure, Entra, Stripe or model-provider behavior. The backend suite reports one upstream Starlette/httpx deprecation warning.

The environment's Node version is 24.19.0. The repository requests Node >=24.22.1; production should use that supported version. Successful local builds do not substitute for validation in the pinned production image.
