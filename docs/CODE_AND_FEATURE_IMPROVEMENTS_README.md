# Source: https://docs.google.com/document/d/1oYrx3weFUJMQiB-e8JA-bJoC4uRd0OHUtnlT1er_zOQ

# Revision: AHj4eMSaExbG94PZvYEE-Z8uMEKj4xy1iKCP4u4KDw4iS_7NZTvwg0ex-uoziaRm1aoT76xekG7i0O3RFaJkeNkhAoaGF2jVbczOU5mRNfM

CloudSaver & Platform Portal: Comprehensive Code & Feature Improvement Guide

Document type: Actionable engineering specification and code-improvement blueprint.
Source baseline: https://github.com/ashokkondapuram/project, commit 6e0de85fe321aa51d97c8dfb734c3e9532e85a71.
Scope: Concrete code, API, database, and UI/UX improvements across the FastAPI backend (app/, services/), the Platform Identity & Control Plane (platform/identity/, platform/portal/), and the Customer Web Dashboard (web-dashboard/).

Contents

Baseline Audit & Current Implementation State (6e0de85)

Priority 1: End-to-End Customer Access & Delegated Key Administration UI (/api/v1/customer/*)

Priority 2: Canonical Inventory Union, Service Analysis Workspaces & Eight Initial Azure Rules

Priority 3: AI Knowledge Retrieval at Inference, Confidence Calibration & Privacy-Safe Governance

Priority 4: Commercial Platform Billing Completion & Lapsed-Account Enforcement

Priority 5: Enterprise Entra/OIDC Sign-In, Capability Envelopes & Step-Up Authentication

Phased Implementation Sequence, Migrations & Verification Matrix

1. Baseline Audit & Current Implementation State (6e0de85)

Inspecting commit 6e0de85 across app/, services/, platform/identity/, web-dashboard/, and platform/portal/ establishes what is already wired versus where high-impact code improvements are needed:

Subsystem

Shipped in Commit 6e0de85

Remaining Code & Architecture Gaps to Close

Customer-Managed Access & Keys

i0007_client_access migration; app/onboarding_api.py (customer_access_router with 18 routes wired into app/main.py and services/gateway.py); /claim page; basic ResourceAccessIdentityEditor in WorkspaceSettings.tsx.

Zero dedicated frontend UI for the 18 /api/v1/customer/* routes: customer owners/admins cannot yet invite/suspend users, transfer ownership, manage workspace memberships, create service accounts, issue/rotate/revoke delegated keys, or export customer audit CSVs from a full management screen.

Rule Catalog & Effective Rules

platform/identity/analysis/admin.py; app/effective_rules.py driving scan filtering; operator RulesTab.tsx in platform/portal/components/workspaces/RulesTab.tsx.

Customer-facing Analysis Rules delegation screen in web-dashboard/ (threshold overrides within delegated bounds, time-limited scoped exceptions, before/after impact preview); full 8-rule Azure specification with 5-minute time-series contracts.

Resource Explorer & Service Views

Azure live scans persist inventory rows; Resource Explorer displays inventory-only rows alongside findings.

Non-Azure collectors (AWS, GCP, Kubernetes) still only emit finding-backed rows; missing dedicated Service Analysis Workspaces (coverage denominator banners, per-service rule outcome matrices, cross-scan trend strips, snapshot diff mode) and mutually exclusive cost opportunity groups.

AI Advisory & Shared Knowledge

platform/identity/knowledge/admin.py with cursor pagination; KnowledgeView.tsx in platform/portal/; durable tenant-scoped AI attempt ledger (0009_enterprise_evidence).

Inference-time knowledge retrieval is not wired: AI assessments do not yet query published knowledge entries or cite opaque publication IDs; missing discrete confidence calibration, deterministic citation quality gates, structured tenant feedback capture, and a physically/logically separated knowledge database with redaction gates.

Platform Commercial Billing

i0002_billing through i0005_plan_change_pending_unique; CloudSaver 0013_billing_projection; Stripe Checkout creation on plan approval and webhook forwarding; POST/PATCH /admin/v1/plans.

platform/identity/billing/importer.py is absent (only scripts/export_billing.py exists); missing Portal UI for authoring/retiring plans; no overrides accepted during initial POST /admin/v1/subscriptions; DB partial-unique index race on plan requests returns 500 instead of 409 Conflict; no automated time-based evaluator for past-due/lapsed account downgrades.

Authentication & Authorization

Peppered HMAC key verification returning scope_restrictions, subject_type, subject_id, membership_version, and customer_roles.

Customer sign-in relies on personal keys with email-derived identity rather than primary Entra/OIDC human sessions (idp_issuer + immutable idp_subject); missing fine-grained capability arrays (users.invite, keys.issue, etc.), step-up authentication for destructive admin actions, and invite/expiry notifications.

2. Priority 1: End-to-End Customer Access & Delegated Key Administration UI (/api/v1/customer/*)

2.1 Problem Statement

In app/onboarding_api.py, customer_access_router exposes 18 customer-facing administration endpoints proxied through services/gateway.py and app/main.py under /api/v1/customer/*. While unit tests (tests/test_onboarding_api.py) verify the backend handlers, FEATURE_IMPROVEMENTS.md notes that no dedicated screen in web-dashboard/ exercises these 18 routes end-to-end.

2.2 Target Frontend & BFF Architecture

Build a comprehensive Customer Access & Credentials module under web-dashboard/components/customer-access/ and surface it in WorkspaceSettings.tsx (for workspace-scoped actions) and a dedicated /settings/organization route (for customer-wide administration by CustomerOwner and CustomerAdmin).

web-dashboard/

├── app/

│   ├── claim/page.tsx                        # Existing bootstrap key claim flow (enhance with step-by-step guidance)

│   └── settings/

│       └── access/page.tsx                   # Dedicated Customer & Workspace Access Console

└── components/

    └── customer-access/

        ├── CustomerUsersDirectory.tsx        # List, invite (20/day limit), suspend, reactivate users

        ├── OwnershipTransferModal.tsx        # Atomic CustomerOwner transfer with confirmation & reason

        ├── WorkspaceMembershipsTable.tsx     # Assign/remove users per workspace, set roles & scope restrictions

        ├── ServiceAccountsManager.tsx        # Create/manage up to 25 non-human service accounts

        ├── DelegatedKeysManager.tsx          # Issue, rotate (with overlap window), and revoke personal/SA keys

        ├── ScopeRestrictionsBuilder.tsx      # Subscription / AWS account / GCP project / cluster selector

        └── CustomerAuditLogView.tsx          # Before-cursor paginated audit stream + one-click CSV export

2.3 Complete 18-Route Wiring Specification

Frontend Component

HTTP Method & Gateway Route (/api/v1/customer/*)

Required Request / State Handling

ClaimLandingPage

POST /api/v1/onboarding/claim

Consumes single-use bootstrap key (24h default / 72h max TTL), enrolls first CustomerOwner, immediately invalidates bootstrap key, and transitions to personal credential setup.

CustomerUsersDirectory

GET /api/v1/customer/users

POST /api/v1/customer/users/invite

POST /api/v1/customer/users/{user_id}/suspend

POST /api/v1/customer/users/{user_id}/reactivate

Displays user status (active, invited, suspended), email verification state, and daily invite quota remaining (20 - invites_today). Suspending a user immediately surfaces a banner explaining that all personal keys bound to that subject_id are rejected by /internal/v1/keys/verify.

OwnershipTransferModal

POST /api/v1/customer/ownership/transfer

Restricted to current CustomerOwner. Requires target active user_id, explicit confirmation text, and audit reason; demotes caller to CustomerAdmin and bumps membership_version.

WorkspaceMembershipsTable

GET /api/v1/customer/workspaces/{tenant_id}/members

PUT /api/v1/customer/workspaces/{tenant_id}/members/{user_id}

DELETE /api/v1/customer/workspaces/{tenant_id}/members/{user_id}

Enforces optimistic concurrency via membership_version. Restricts assignable roles and provider/scope envelopes strictly to the caller's own delegation envelope (403 on escalation attempt).

ServiceAccountsManager

GET /api/v1/customer/service-accounts

POST /api/v1/customer/service-accounts

PATCH /api/v1/customer/service-accounts/{sa_id}

DELETE /api/v1/customer/service-accounts/{sa_id}

Manages non-human principals (capped at 25 per customer) for CI/CD and scheduled jobs. Displays active key count per service account and prevents service accounts from inviting human users.

DelegatedKeysManager

GET /api/v1/customer/workspaces/{tenant_id}/keys

POST /api/v1/customer/workspaces/{tenant_id}/keys

POST /api/v1/customer/workspaces/{tenant_id}/keys/{key_id}/rotate

POST /api/v1/customer/workspaces/{tenant_id}/keys/{key_id}/revoke

Supports issuing keys bound to subject_user_id or service_account_id with mandatory expires_at, provider grants (all_providers or allowed_providers), and scope_restrictions. Displays plaintext secret once in a copyable modal with auto-clear timer. Respects issuance_blocked when commercial billing requires an active subscription.

CustomerAuditLogView

GET /api/v1/customer/audit

GET /api/v1/customer/audit/export.csv

Uses before timestamp cursor pagination appropriate for append-only event streams (bootstrap_issued, customer_claimed, user_invited, membership_changed, key_issued, key_rotated, key_revoked, ownership_transferred).

2.4 Backend Hardening for Scope Restrictions (app/auth.py & platform/identity/)

Server-Side Scope Enforcement (narrow()): Ensure every read and mutating handler in app/ and services/scanner.py intersects the requested subscription, AWS account, GCP project, or Kubernetes cluster against grant.scope_restrictions returned by /internal/v1/keys/verify.

Cache Eviction on Membership/Key Mutation: Whenever membership_version or key status changes in platform/identity/customer/admin.py, emit an invalidation event so CloudSaver's verify cache immediately evicts stale grants rather than waiting for TTL expiry.

3. Priority 2: Canonical Inventory Union, Service Analysis Workspaces & Eight Initial Azure Rules

3.1 Full Multi-Cloud Inventory Persistence & Coverage Denominators

Currently, Azure live scans persist inventory rows so Resource Explorer can show resources without active findings, while other collectors only emit finding-backed rows.

Unified Inventory Collector Contract (app/scanner.py, app/scanner_aws.py, services/scanner.py):

Extend AWS, GCP, and Kubernetes collectors to persist canonical inventory records alongside findings in a single atomic transaction per scan run.

Record a Scan Coverage Manifest on every scan snapshot containing separate, explicit counts:

discovered_count: Total resources returned by provider APIs within authorized scopes.

in_scope_count: Resources matching active workspace scope filters.

evaluated_count: Resources where rule evidence contracts were fully met (condition_detected or condition_not_detected).

insufficient_evidence_count: Resources where required telemetry, tags, or snapshot APIs were unreadable (unknown outcome—never collapsed into pass).

excluded_count: Resources bypassed by an active, time-bounded scoped exception or protected DR/retention intent tag.

unsupported_count: Resource types or SKUs present in inventory but not yet covered by an active rule.

failed_scopes: Explicit list of subscriptions/accounts/regions that failed to read, preventing partial scans from silently resolving prior findings.

3.2 Dedicated Service Analysis Workspaces (web-dashboard/)

Add a Service Analysis navigation view (web-dashboard/app/services/[service]/page.tsx) providing specialized workspaces for Managed Disks, Public IP Addresses, Virtual Machines, and App Service Plans:

Service Coverage Banner: Displays the 6 coverage denominators above with direct links to scope access diagnostics when failed_scopes > 0 or insufficient_evidence_count > 0.

Published Rule Matrix: Lists every rule for that service from app/effective_rules.py (enabled, disabled_by_policy, blocked_by_access, blocked_by_plan, unavailable) with last evaluation timestamp and outcome distribution (risk, pass, unknown, excluded, not_applicable).

Cross-Scan Trend Strip: Tracks opportunity amount, verified realized savings, and evidence-gap counts across completed historical scans, labeling each data point with its exact scan timestamp and scope coverage percentage.

Snapshot Comparison Mode: Side-by-side diff between any two saved scan snapshots (new, persisting, changed, resolved_with_evidence, no_longer_observed, out_of_scope) with explicit "Observation change only" copy.

3.3 Mutually Exclusive Cost Opportunity Grouping (app/pricing.py & services/analytics.py)

Prevent financial double-counting across overlapping rules:

Introduce opportunity_group_id (keyed by parent workload/instance topology, e.g., vm:{resource_id}).

When a Virtual Machine is flagged for retirement/rightsizing and its attached Managed Disks or Public IPs have separate recommendations, group them into a single mutually exclusive opportunity set.

Rollup KPIs (total_monthly_opportunity_usd) sum the maximum mutually compatible opportunity per group rather than summing overlapping raw findings, while keeping billed_cost, retail_estimate, modeled_future_cost, and verified_realized_savings in distinct columns.

3.4 Code Specification for the Eight Initial Azure Rules (app/scanner.py & platform/identity/analysis/)

Register and enforce the eight foundational Azure rules in the versioned rule catalog with strict evidence contracts:

Service

Rule Identifier & Descriptive Name

Required Evidence Contract & Observation Window

Trigger Logic & Mandatory Safeguards

Managed Disks

1. AZURE_DISK_UNATTACHED_RETENTION

Retained unattached managed disk review

SKU, size GB, redundancy, region, diskState, attachment transition history (14d continuous window), locks, backup/ASR references, DR/retention tags. Creation time alone is rejected as detachment time.

diskState == 'Unattached' for $\ge 14\text{d}$ (configurable $7\text{–}90\text{d}$). Excludes ephemeral disks and DR-tagged volumes. Requires fresh state re-read and managed snapshot before deletion.

Managed Disks

2. AZURE_DISK_PROVISIONED_PERFORMANCE

Unattached disk snapshot & tier/performance review

For unattached or Premium/Ultra disks: snapshot recency within operator retention window, plus 30-day 5-minute IOPS/throughput series ($\ge 95%$ valid sample coverage, max gap $\le 1\text{h}$).

Flags unattached disks lacking a recent snapshot (unknown if snapshot API unreadable) or attached Premium SSDs/Ultra Disks where P99 IOPS/MBps sits well within a lower tier's baseline.

Public IPs

3. AZURE_PUBLIC_IP_UNASSOCIATED

Unassociated public IP address review

SKU (Basic/Standard), allocation method (Static/Dynamic), ipConfiguration, natGateway, load balancer frontend references, DNS/whitelist tags over a 7-day window.

ipConfiguration == null and natGateway == null. Distinguishes billable Static/Standard IPs from non-billed dynamic addresses; warns on third-party allowlist impact before release.

Public IPs

4. AZURE_PUBLIC_IP_ASSOCIATED_IDLE

Idle associated public IP traffic review

Parent resource association + 30-day Azure Monitor byte/packet ingress & egress counters ($\ge 95%$ valid intervals).

Associated IP where parent NIC/LB/gateway records zero or near-zero ingress/egress across 30 days. Returns insufficient_evidence (never pass) when Azure Monitor metrics are not authorized.

Virtual Machines

5. AZURE_VM_STOPPED_RESIDUAL_COST

Stopped virtual machine residual cost review

powerState (stopped vs. deallocated), state transition timestamp ($\ge 14\text{d}$ grace window), attached OS/data disk SKUs, reserved instance coverage, standby/DR/witness tags.

Highlights PowerState/stopped (still incurring full compute charges) immediately as high priority, and PowerState/deallocated VMs accumulating attached Premium SSD & static IP charges.

Virtual Machines

6. AZURE_VM_RIGHTSIZING_UTILIZATION

Oversized or low-utilization virtual machine review

30-day 5-minute CPU, memory (when guest/ insights telemetry exists), disk IOPS, and network bandwidth series ($\ge 95%$ coverage, resource age $\ge 30\text{d}$), burst credit balance.

P95 CPU $< 10%$ and memory/IOPS within target smaller SKU limits without burst credit depletion. Suppresses downsizing if memory telemetry is absent unless operator explicitly permits CPU-only review.

App Service Plans

7. AZURE_ASP_EMPTY_PAID_PLAN

Empty paid App Service plan review

SKU tier (Basic, Standard, PremiumV2/V3, Isolated), numberOfSites, deployment slots, worker count, VNet integration, stamp reservations over a 7-day window.

Paid plan (tier != 'Free' && tier != 'Shared') with numberOfSites == 0 and zero active deployment slots.

App Service Plans

8. AZURE_ASP_UNDERUTILIZED_SKU

Underutilized App Service plan SKU & instance review

Hosted app count, instance count, auto-scale rules, and 30-day 5-minute CpuPercentage and MemoryPercentage series ($\ge 95%$ valid intervals).

Multi-instance or PremiumV3 plan with sustained P95 CPU $< 15%$ and P95 memory $< 30%$ above minimum HA replica floor (min_instances >= 2 preserved for production).

3.5 Customer-Delegated Rule Administration Screen (web-dashboard/)

Add an Analysis Rules view in web-dashboard/components/rules/CustomerRuleSettings.tsx:

Renders the provider $\to$ service $\to$ resource type $\to$ rule tree fetched from /api/v1/rules/effective.

Allows CustomerAdmin / workspace rule administrators to toggle delegated rules, adjust numeric parameters within platform-defined allowed_override_bounds, and create time-bounded scoped exceptions (reason, scope, owner, expires_at, optional external_ticket_ref).

Includes a Before / After Impact Preview modal (POST /api/v1/rules/preview) showing how many resources and findings in the latest scan snapshot would change state before committing the policy revision.

4. Priority 3: AI Knowledge Retrieval at Inference, Confidence Calibration & Privacy-Safe Governance

4.1 Separate Knowledge Database & Strict Privacy Boundary (platform/identity/knowledge/)

To guarantee that sensitive client data (resource names, subscription IDs, tags, raw telemetry, or verbatim AI advisories) can never leak across tenants:

+--------------------------------------------------------------------------------------------------+

|                        Tenant-Private Operational Database (CloudSaver DB)                       |

|  - Resource names, ARNs, tags, raw telemetry, deterministic assessments, private AI advisories   |

|  - Structured operator feedback (incorrect_fact, missing_context, useful_explanation, etc.)      |

+--------------------------------------------------------------------------------------------------+

                                                 |

                                                 | 1. Operator flags anonymized pattern candidate

                                                 v

+--------------------------------------------------------------------------------------------------+

|                    Redaction & Privacy Gate (platform/identity/knowledge/)                       |

|  - Automated regex/NER scrubber strips UUIDs, ARNs, IPs, hostnames, emails, cost-center codes    |

|  - Dual-control sign-off: KnowledgeReviewer (technical accuracy) + PrivacyReviewer (zero PII)    |

|  - Low redaction confidence -> Automatic Rejection (never stored in shared tables)               |

+--------------------------------------------------------------------------------------------------+

                                                 |

                                                 | 2. Approved immutable publication (pub_id)

                                                 v

+--------------------------------------------------------------------------------------------------+

|                     Separate Shared Knowledge Database (knowledge_db)                            |

|  - Zero foreign keys to tenant tables; stores only opaque publication_id, version, service_type, |

|    rule_id, pillar, vetted guidance pattern, applicability preconditions, and quality metrics    |

+--------------------------------------------------------------------------------------------------+

                                                 |

                                                 | 3. Read-only retrieval at inference time

                                                 v

+--------------------------------------------------------------------------------------------------+

|                         CloudSaver AI Assessment Engine (app/ai_gateway.py)                      |

|  - Injects matching published patterns by (provider, service, rule_id, pillar)                   |

|  - Requires model output to cite exact publication_id + deterministic check_id                   |

+--------------------------------------------------------------------------------------------------+

Database Separation (platform/knowledge_migrations/): Move knowledge tables into a dedicated database connection (KNOWLEDGE_DATABASE_URL) or strictly isolated schema with zero foreign keys to directory, billing, or CloudSaver tenant tables.

4.2 Inference-Time Retrieval & Deterministic Quality Gates (app/)

Upgrade the CloudSaver AI advisory pipeline:

Approved Knowledge Retrieval: Before invoking Azure OpenAI, AWS Bedrock Converse, or GCP Vertex AI, query the published knowledge store for active (status == 'published') entries matching the target resource's (provider, resource_type, triggered_rule_ids, pillar).

Strict Citation Enforcement: The post-inference validator must verify that every claim in the returned JSON cites:

A valid deterministic check_id or evidence_field present in the input assessment.evidence_digest payload, and/or

An opaque publication_id supplied in the retrieved knowledge context.

Any advisory citing non-existent checks, inventing dollar savings when cost is unknown, or recommending action when a protection lock is active is rejected at the quality gate and recorded as a validation failure without exposing unverified text to the user.

Evidence-Calibrated Confidence Bands: Replace arbitrary numerical AI scores with discrete confidence bands derived deterministically from evidence completeness:

HIGH: All required configuration, 30-day time-series (coverage $\ge 95%$), dependency, and billed/retail pricing evidence are present and fresh ($< 24\text{h}$).

MEDIUM: Configuration and state history are complete, but secondary metrics or amortized billing fields are partial.

LOW: Point-in-time state is known, but historical observation window is shorter than policy default.

INSUFFICIENT_EVIDENCE: Critical required fields are unknown or stale; AI advisory explains what evidence is missing and how to grant collector access rather than guessing a recommendation.

4.3 Structured Feedback & Portal Knowledge Metrics (web-dashboard/ & platform/portal/)

Customer Feedback Controls: In the Resource Explorer drawer (AI Advice tab), add structured feedback chips (incorrect_fact, missing_context, useful_explanation, unsupported_recommendation, already_addressed) stored in the tenant-private database.

Portal Knowledge Governance Enhancements (platform/portal/components/knowledge/KnowledgeView.tsx):

Expand KnowledgeView.tsx into tabbed sub-views: Overview & Metrics (publications per month, acceptance/rejection rate, citation rate across fleet inferences, deprecation count), Candidate Queue (showing redacted candidate patterns and dual-reviewer sign-off controls for KnowledgeReviewer and PrivacyReviewer), Published Catalog, and Deprecation History.

5. Priority 4: Commercial Platform Billing Completion & Lapsed-Account Enforcement

5.1 Close Documented Runtime Gaps in PLATFORM_BILLING.md

Implement platform/identity/billing/importer.py:

Pair with the existing scripts/export_billing.py helper to provide a validated, idempotent billing importer.

Validate schema versions, customer/workspace references, exact Decimal monetary strings (rejecting floats, NaN, exponents, and over-precision values), subscription uniqueness constraints, and provider event idempotency in a single atomic transaction.

Subscription Overrides on Creation (platform/identity/billing/admin.py):

Update POST /admin/v1/subscriptions to accept and validate an optional overrides block (max_subscriptions, max_active_keys_per_workspace, can_export_terraform, can_use_ai_advisory, retention_days) at creation time so operators do not have to issue a separate PATCH call immediately after creation.

Ensure app/directory_projector.py projects the complete effective plan block (base catalog + subscription overrides) into CloudSaver's local projection table (0013_billing_projection).

Map Plan-Change Race Conditions to HTTP 409 Conflict (platform/identity/service.py):

Wrap inserts into billing.plan_change_requests so that if two concurrent requests hit the partial unique index (i0005_plan_change_pending_unique), the database IntegrityError is caught and translated into a clean HTTP 409 Conflict ("A pending plan change request already exists for this workspace") rather than a 500 error.

Automated Time-Based Lapsed-Account Evaluator (platform/identity/billing/evaluator.py):

Build a periodic background task / lifespan worker that evaluates subscriptions whose current_period_end or grace_period_ends_at has passed without a settled payment:

Transitions stored customer billing_state from active $\to$ past_due $\to$ suspended / downgraded.

Sets issuance_blocked = true when require_subscription_for_keys is enabled, automatically preventing new key issuance or rotation.

Emits billing_state_changed and entitlements_changed cache invalidation events so CloudSaver immediately enforces fallback tier restrictions.

Portal Plan Catalog Authoring UI (platform/portal/components/billing/PlanCatalogAdmin.tsx):

Wire the existing POST /admin/v1/plans, PATCH /admin/v1/plans/{code}, and POST /admin/v1/plans/{code}/retire identity endpoints to a dedicated Plan Catalog management screen in platform/portal/, including Stripe external_price_refs.stripe mapping and explicit confirmation when seed prices are null (custom contract pricing).

6. Priority 5: Enterprise Entra/OIDC Sign-In, Capability Envelopes & Step-Up Authentication

6.1 Primary Entra / OIDC Human Sign-In (platform/identity/ & web-dashboard/)

Replace email-derived personal key sign-in for human users with first-class OIDC / Microsoft Entra ID authentication:

Bind each directory.users row by (idp_issuer, idp_subject) rather than mutable email strings.

Add OIDC authorization code + PKCE sign-in flow to web-dashboard/ and /api/v1/me/memberships so authenticated users can switch across all workspaces where they hold an active membership without pasting raw bearer keys into the browser.

Retain personal and service-account bearer keys strictly for CLI, CI/CD, and headless API automation.

6.2 Fine-Grained Capability Arrays (platform/identity/domain.py & app/auth.py)

Extend workspace roles (TenantAdmin, BillingAdmin, Viewer) and customer roles (CustomerOwner, CustomerAdmin, CustomerAuditor) into explicit capability sets returned in /internal/v1/keys/verify:

Capabilities: scans.run, resources.read, rules.override, exceptions.manage, ai.invoke, iac.export, billing.read, billing.request_change, users.invite, memberships.manage, keys.issue, keys.revoke, service_accounts.manage, audit.export.

A delegated personal or service-account key can hold a strict subset of the issuer's capabilities (e.g., a CI/CD key with only scans.run and iac.export).

6.3 Step-Up Authentication & Lifecycle Notifications

Step-Up Verification: Require fresh OIDC re-authentication (max_age=300) or OTP challenge before executing ownership_transfer, workspace-wide revoke-all, or bulk key issuance.

Notification & SIEM Dispatch (services/notification.py): Dispatch transactional alerts when an admin is invited, a key is nearing expiration (7 days and 24 hours prior), or CustomerOwner is transferred, and support HMAC-signed webhook delivery of customer audit events to external SIEM collectors.

7. Phased Implementation Sequence, Migrations & Verification Matrix

7.1 Ordered Delivery Phases

Phase

Target Modules

Key Deliverables & Completion Criteria

Phase 1: Customer Access UI & Scope Enforcement

web-dashboard/components/customer-access/*, app/auth.py, tests/test_onboarding_api.py

All 18 /api/v1/customer/* routes wired to web-dashboard screens; server-side scope_restrictions enforced in narrow(); Playwright E2E tests pass for claim, invite, membership edit, SA creation, key issue/rotate/revoke, and CSV export.

Phase 2: Multi-Cloud Inventory Union & Service Workspaces

app/scanner*.py, services/analytics.py, web-dashboard/app/services/*

AWS, GCP, and K8s scans persist canonical inventory rows and coverage manifests; mutually exclusive opportunity_group_id prevents VM+Disk double counting; Service Analysis pages and customer rule override previews pass tests.

Phase 3: Eight Foundational Azure Rules & Time-Series Contracts

app/scanner.py, platform/identity/analysis/, tests/test_expanded_rules.py

All 8 Azure rules implemented with 5-minute time-series coverage checks ($\ge 95%$ intervals), attachment transition history, and explicit unknown outcomes when telemetry is missing.

Phase 4: Separate Knowledge DB & AI Retrieval Pipeline

platform/identity/knowledge/, app/ai_gateway.py, platform/portal/components/knowledge/*

Dedicated knowledge_db migration applied; redaction + dual-reviewer gate enforced; inference retrieves published patterns and enforces publication_id + check_id citations; discrete confidence bands and feedback chips verified.

Phase 5: Commercial Billing Importer & Lapsed Evaluator

platform/identity/billing/importer.py, evaluator.py, platform/portal/components/billing/*

Billing importer/exporter round-trip verified; POST /admin/v1/subscriptions accepts initial overrides; i0005 race returns HTTP 409; automated lapsed-account evaluator and Portal Plan Catalog CRUD UI pass integration tests.

Phase 6: Entra/OIDC Sessions, Capabilities & Step-Up Auth

platform/identity/, app/auth.py, web-dashboard/

Human sign-in bound to (idp_issuer, idp_subject); capability subsetting enforced on keys; step-up auth required on ownership transfer and revoke-all.

7.2 Verification Commands

Every phase must maintain 100% pass rates across the repository's verification gates before merge:

# 1. Backend & disposable PostgreSQL 16 + Redis 7 integration suite

python scripts/test_postgres.py --tb=short

# 2. Platform Identity, Billing, Analysis, Knowledge & Audit coverage suite

pytest platform/tests/ tests/test_onboarding_api.py tests/test_effective_rules.py

# 3. Structural audit-event coverage gate (every mutating method on *Ops emits self._event)

pytest platform/tests/test_audit_coverage.py

# 4. Frontend production build & TypeScript verification (Customer Dashboard & Platform Portal)

cd web-dashboard && npm run typecheck && npx next build --webpack

cd ../platform/portal && npm run typecheck && npx next build --webpack

# 5. Formatting & whitespace hygiene

git diff --check
