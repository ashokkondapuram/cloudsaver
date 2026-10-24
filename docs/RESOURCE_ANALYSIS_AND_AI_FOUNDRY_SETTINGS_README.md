# Source snapshot

Source: https://docs.google.com/document/d/19Ttsj8kI2HpvO7OsrXF8DzE6dB3NuBSQfVqcWFnkiHU

CloudSaver & Platform Portal: Comprehensive Code, Resource Analysis & Multi-Cloud AI Foundry Improvement Guide

Document type: Actionable engineering specification and code-improvement blueprint.
Source baseline: https://github.com/ashokkondapuram/project, commit 6e0de85fe321aa51d97c8dfb734c3e9532e85a71.
Scope: Concrete code, API, database, and UI/UX improvements across the FastAPI backend (app/, services/), the Platform Identity & Control Plane (platform/identity/, platform/portal/), and the Customer Web Dashboard (web-dashboard/), with deep focus on Resource Analysis and Multi-Cloud AI Foundry Configuration Settings (Azure AI Foundry, AWS Bedrock, GCP Vertex AI).

Contents

Baseline Audit & Current Implementation State (6e0de85)

Deep-Dive Improvement A: Multi-Cloud Resource Analysis, Evidence Contracts & Service Workspaces

2.1 Canonical Inventory Union & Seven-Counter Scan Coverage Manifest

2.2 Eight-State Rule Evaluation Outcome Taxonomy & Freshness Contracts

2.3 High-Resolution Time-Series Evidence Engine (5-Minute Aggregates)

2.4 Typed Dependency Graph & Operational Protection Intent

2.5 Non-Overlapping Cost Attribution & Mutually Exclusive Opportunity Groups

2.6 Detailed Specification of the Eight Initial Azure Rules & Multi-Cloud Rule Matrix

2.7 Resource Explorer, Dedicated Service Workspaces & Customer Rule Settings UI

Deep-Dive Improvement B: Multi-Cloud AI Foundry Configuration & Governance Settings

3.1 Architectural Ownership: Platform Guardrails vs. Workspace Self-Service Settings

3.2 Provider-Specific Configuration Contracts (Azure AI Foundry, AWS Bedrock, GCP Vertex AI)

3.3 Source-Provider Affinity, Token Budgets & Privacy Consent Controls

3.4 Backend Settings API (app/settings_api.py) & Non-Destructive Connection Diagnostics

3.5 Frontend AIFoundryConfigurationEditor (WorkspaceSettings.tsx) & Pre-Inference Disclosure

3.6 Shared Knowledge Retrieval at Inference, Confidence Calibration & Citation Quality Gates

Priority 3: End-to-End Customer Access & Delegated Key Administration UI (/api/v1/customer/*)

Priority 4: Commercial Platform Billing Completion & Lapsed-Account Enforcement

Priority 5: Enterprise Entra/OIDC Sign-In, Capability Envelopes & Step-Up Authentication

Phased Implementation Sequence, Migrations & Verification Matrix

1. Baseline Audit & Current Implementation State (6e0de85)

Inspecting commit 6e0de85 across app/, services/, platform/identity/, web-dashboard/, and platform/portal/ establishes what is already wired versus where high-impact code improvements are required:

Subsystem

Shipped in Commit 6e0de85

Remaining Code & Architecture Gaps to Close

Resource Analysis & Rule Catalog

Azure live scans persist inventory rows; five-pillar deterministic checks, evidence gaps, content fingerprints; platform/identity/analysis/admin.py; app/effective_rules.py driving scan filtering; operator RulesTab.tsx in platform/portal/.

Non-Azure collectors (AWS, GCP, Kubernetes) emit only finding-backed rows; missing explicit 7-counter scan coverage manifests, 5-minute time-series interval validation ($\ge 95%$ coverage), typed dependency edges, mutually exclusive cost opportunity groups, dedicated Service Analysis Workspaces, and a customer-facing Analysis Rules delegation UI.

Multi-Cloud AI Foundry Settings & Knowledge

Opt-in keyless Azure OpenAI, AWS Bedrock Converse, and GCP Vertex adapters; SQL-backed attempt reservation & token ledger (0009_enterprise_evidence); KnowledgeView.tsx in platform/portal/.

Missing self-service AI Foundry configuration UI & API in WorkspaceSettings.tsx / app/settings_api.py: workspace admins can edit resource-access identity (ResourceAccessIdentityEditor), but cannot configure or test per-provider AI Foundry endpoints, deployments, Bedrock guardrail IDs, Vertex locations, source-provider affinity (same_cloud_only), or token budgets from Settings. Inference also does not yet retrieve published knowledge entries or calibrate discrete confidence bands.

Customer-Managed Access & Keys

i0007_client_access migration; app/onboarding_api.py (customer_access_router with 18 routes wired into app/main.py and services/gateway.py); /claim page; ResourceAccessIdentityEditor in WorkspaceSettings.tsx.

Zero dedicated frontend UI for the 18 /api/v1/customer/* routes: customer owners/admins cannot yet invite/suspend users, transfer ownership, manage workspace memberships, create service accounts, issue/rotate/revoke delegated keys, or export customer audit CSVs from the dashboard.

Platform Commercial Billing

i0002_billing through i0005_plan_change_pending_unique; CloudSaver 0013_billing_projection; Stripe Checkout creation on plan approval; POST/PATCH /admin/v1/plans.

platform/identity/billing/importer.py is absent; missing Portal UI for authoring/retiring plans; no overrides accepted during initial POST /admin/v1/subscriptions; DB partial-unique index race on plan requests returns 500 instead of 409 Conflict; no automated time-based evaluator for past-due/lapsed account downgrades.

Authentication & Authorization

Peppered HMAC key verification returning scope_restrictions, subject_type, subject_id, membership_version, and customer_roles.

Customer sign-in relies on personal keys with email-derived identity rather than primary Entra/OIDC human sessions (idp_issuer + immutable idp_subject); missing fine-grained capability arrays (users.invite, keys.issue, etc.) and step-up authentication.

2. Deep-Dive Improvement A: Multi-Cloud Resource Analysis, Evidence Contracts & Service Workspaces

2.1 Canonical Inventory Union & Seven-Counter Scan Coverage Manifest

An empty findings table must never be presented as proof that every resource was assessed or that an environment is healthy. Separate resource discovery from finding detection across all providers (app/scanner.py, app/scanner_aws.py, services/scanner.py):

Full Inventory Union Persistence:

Upgrade AWS, GCP, and Kubernetes collectors to persist canonical inventory rows for every discovered resource in scope—matching the existing Azure live scan behavior—so Resource Explorer always shows one canonical row per resource regardless of whether a finding was triggered.

Each persisted resource observation records: resource_id, provider, service, resource_type, scope_id (subscription/account/project/cluster), region, configuration_snapshot, dependency_refs, protection_signals, observed_at, collector_version, and evidence_schema_version.

Seven-Counter Scan Coverage Manifest:

Every scan snapshot must persist a structured coverage_manifest per provider and service:

discovered_count: Total resources returned by provider APIs across authorized scopes.

in_scope_count: Resources matching active workspace scope and environment filters.

evaluated_count: Resources where rule evidence contracts were completely satisfied (condition_detected or condition_not_detected).

insufficient_evidence_count: Resources where required metrics, attachment histories, or snapshot APIs were unreadable (unknown—never counted as pass).

excluded_count: Resources bypassed by an active, time-bounded scoped exception or explicit DR/retention protection intent.

unsupported_count: Discovered resource types or SKUs that do not yet have an applicable rule in the catalog.

failed_scopes: Explicit array of scopes ({scope_id, provider, error_category, message}) that failed to read. Partial or failed scope runs are never merged into a clean baseline to silently mark prior findings as resolved.

2.2 Eight-State Rule Evaluation Outcome Taxonomy & Freshness Contracts

Replace binary finding generation in app/scanner.py and app/effective_rules.py with an explicit eight-state per-rule evaluation record for every eligible resource:

Outcome State

Counts Toward Evaluated Coverage?

Meaning & UI Treatment

condition_detected

Yes

All required evidence collected and fresh; waste, sizing, or risk condition verified.

condition_not_detected

Yes

All required evidence collected and fresh; resource verified healthy against rule thresholds.

insufficient_evidence

No

Missing metric series, unreadable snapshot/backup API, or observation window shorter than required.

not_applicable

No

Resource SKU, ephemeral state, or architecture variant is outside the rule's applicability contract.

disabled_by_policy

No

Rule is turned off by platform default, customer policy, or workspace override.

excluded_by_exception

No

Resource matches an active, non-expired scoped exception (reason, owner, expires_at).

unsupported_by_collector

No

Rule exists in catalog, but the current collector version does not yet gather its required inputs.

evaluation_failed

No

Collector or rule evaluator encountered a runtime/provider error; surfaces diagnostic link.

Freshness Enforcement: Configuration evidence must be $< 24\text{h}$ old for advisory assessment. Before generating any destructive script, Terraform removed block, or GitOps PR, require a fresh authoritative state and dependency re-read.

2.3 High-Resolution Time-Series Evidence Engine (5-Minute Aggregates)

Upgrade utilization collectors (Azure Monitor, AWS CloudWatch, GCP Cloud Monitoring, Prometheus) to enforce strict time-series completeness before emitting rightsizing or idle-traffic findings:

# app/telemetry_contract.py

from dataclasses import dataclass

from datetime import datetime

@dataclass(frozen=True)

class TimeSeriesEvidenceContract:

    metric_name: str

    aggregation: str                  # 'P95', 'P99', 'MAX', 'SUM' (never substitute AVG for peak checks)

    interval_minutes: int = 5         # 5-minute source aggregates

    window_days: int = 30             # 30-day observation window ending within 24h

    min_resource_age_days: int = 30   # Resource must exist for >= 30 days

    min_coverage_ratio: float = 0.95  # >= 95% valid intervals (e.g., >= 8,208 of 8,640 points)

    max_gap_minutes: int = 60         # No unexplained telemetry gap > 1 hour

@dataclass(frozen=True)

class TimeSeriesEvaluationResult:

    contract: TimeSeriesEvidenceContract

    expected_samples: int

    valid_samples: int

    max_observed_gap_minutes: int

    window_start: datetime

    window_end: datetime

    observed_value: float | None

    is_sufficient: bool

    gap_reason: str | None            # Explicit reason when is_sufficient is False (never fill missing with 0.0)

2.4 Typed Dependency Graph & Operational Protection Intent

Extend resource ingestion to persist typed dependency edges and explicit protection holds:

Typed Relationships: vm_to_disk, nic_to_ip, ip_to_load_balancer_or_nat_or_appgw, app_service_to_plan, resource_to_backup_vault_or_asr, and resource_to_management_lock. Each edge records verification_state: verified, inferred, stale, or unavailable.

Protection Intent Signals: Evaluate resource locks (CanNotDelete, ReadOnly), backup/replication enrollment, and normalized tags (Role=DR-Standby, Role=Witness, Retention=Permanent, MigrationWindow=Active). Protected resources still undergo full rule evaluation so operators see their cost and posture, but destructive actions are hard-blocked at both the API and script-generation layers.

2.5 Non-Overlapping Cost Attribution & Mutually Exclusive Opportunity Groups

In app/pricing.py and services/analytics.py, separate financial columns and prevent double-counting:

Five Distinct Financial Fields:

billed_cost_usd: Actual ingested FOCUS/invoice cost for the resource over the period (or null if billing is not ingested).

retail_estimate_usd: Modeled current run-rate using region, exact SKU, tier, provisioned capacity/IOPS, pricing date, and currency (never apply a flat generic per-GB rate across disk tiers or a single rate across Basic/Standard/dynamic IPs).

modeled_future_cost_usd: Projected cost of the target SKU or snapshot retention overhead after the change.

opportunity_usd: Estimated monthly savings for this specific recommendation (null when cost inputs are unknown).

verified_realized_savings_usd: Calculated only after an approved change is verified completed across a post-action observation window, accounting for new snapshot/transfer/replacement charges.

Mutually Exclusive Opportunity Groups (opportunity_group_id):

Assign overlapping findings on connected resources (e.g., retiring a stopped VM and deleting or tier-downsizing its attached OS/data disks and public IP) to the same opportunity_group_id (workload:{parent_vm_id}).

Workspace and service KPI totals sum the maximum mutually compatible opportunity per group and display a clear overlap badge in the drawer ("Overlaps financially with VM retirement recommendation on vm-prod-01").

2.6 Detailed Specification of the Eight Initial Azure Rules & Multi-Cloud Rule Matrix

Register all published rules in platform/identity/analysis/ and app/effective_rules.py with versioned metadata, required evidence contracts, delegated parameter bounds, and change safeguards:

Provider & Service

Rule Identifier & Plain-Language Name

Evidence Prerequisites & Window

Trigger Condition, Cost Basis & Safeguards

Azure Managed Disks

1. AZURE_DISK_UNATTACHED_RETENTION

Retained unattached managed disk review

SKU, size GB, redundancy, region, diskState, attachment transition event/history ($\ge 14\text{d}$), locks, backup/ASR refs, DR tags. Creation date is never treated as detachment date.

diskState == 'Unattached' continuously for $\ge 14\text{d}$ (delegated bound $7\text{–}90\text{d}$). Excludes ephemeral disks. Deducts 30-day safety snapshot cost from gross disk rate; requires fresh state re-read + snapshot before delete.

Azure Managed Disks

2. AZURE_DISK_PROVISIONED_PERFORMANCE

Disk snapshot recency & provisioned tier review

For unattached disks: snapshot recency in retention window. For attached Premium/Ultra/SSD v2 disks: 30-day 5-min IOPS & MBps series ($\ge 95%$ coverage).

Flags unattached disks with no recent snapshot (insufficient_evidence if snapshot API unreadable) or over-provisioned Premium/Ultra disks whose P99 IOPS/throughput fits a lower SKU tier.

Azure Public IPs

3. AZURE_PUBLIC_IP_UNASSOCIATED

Unassociated public IP address review

SKU (Basic/Standard), allocation (Static/Dynamic), ipConfiguration, natGateway, LB frontend refs, DNS/allowlist tags over $7\text{d}$.

Unassociated Static/Standard IP accruing hourly charges. Requires operator confirmation that no external partner firewall or DNS record depends on the static address.

Azure Public IPs

4. AZURE_PUBLIC_IP_ASSOCIATED_IDLE

Idle associated public IP traffic review

Parent association + 30-day 5-min Azure Monitor byte/packet ingress & egress counters ($\ge 95%$ valid intervals).

Associated IP whose parent resource shows zero meaningful ingress/egress across $30\text{d}$. Returns insufficient_evidence when Azure Monitor metrics are unavailable.

Azure Virtual Machines

5. AZURE_VM_STOPPED_RESIDUAL_COST

Stopped virtual machine residual cost review

powerState (stopped vs. deallocated), state transition timestamp ($\ge 14\text{d}$), attached disk SKUs, reservation coverage, standby/DR/witness tags.

Distinguishes OS-stopped VMs (still billed for compute) from deallocated VMs (billed for attached disks/IPs). Groups disk/IP charges into one opportunity_group_id.

Azure Virtual Machines

6. AZURE_VM_RIGHTSIZING_UTILIZATION

Oversized or low-utilization virtual machine review

30-day 5-min CPU, memory, disk IOPS, and network series ($\ge 95%$ coverage, age $\ge 30\text{d}$), burstable credit balance, target SKU compatibility.

Sustained P95 CPU $< 10%$ and P95 memory/IOPS comfortably within smaller SKU without credit exhaustion. Returns insufficient_evidence if memory telemetry is missing unless CPU-only override is explicitly enabled.

Azure App Service Plans

7. AZURE_ASP_EMPTY_PAID_PLAN

Empty paid App Service plan review

SKU tier (Basic, Standard, PremiumV2/V3, Isolated), numberOfSites, deployment slots, worker count, VNet/ASE stamp refs over $7\text{d}$.

Paid plan (tier not in ('Free', 'Shared')) with numberOfSites == 0 and zero deployment slots across the window.

Azure App Service Plans

8. AZURE_ASP_UNDERUTILIZED_SKU

Underutilized App Service plan SKU & instance review

Hosted app count, instance count, autoscale rules, and 30-day 5-min CpuPercentage & MemoryPercentage series ($\ge 95%$ coverage).

Multi-instance or PremiumV3 plan with P95 CPU $< 15%$ and P95 memory $< 30%$ while preserving min_instances >= 2 zone-redundancy floor for production plans.

Existing Multi-Cloud Rules

Azure NIC/NSG/AppGW; AWS EBS/EIP/RDS; GCP Disk/IP/Cloud SQL; K8s CPU/Mem P95

Registered in the same versioned catalog with explicit provider billing semantics (e.g., NIC/NSG carry $0 direct charge; AppGW checks all backend pools; Cloud SQL requires 336h zero connections; K8s requires 14d hourly Prometheus samples).

Exposed under identical administrative enable/disable, exception, and coverage denominator rules.

2.7 Resource Explorer, Dedicated Service Workspaces & Customer Rule Settings UI (web-dashboard/)

Resource Explorer (web-dashboard/components/resources/):

Displays one canonical row per inventory resource (including resources with 0 active findings), URL-persisted filter views, explicit page-only vs. all-filtered bulk selection, and an 8-section slide-over drawer (Overview, Evidence, Rules, Cost, Dependencies, AI Advice, History, Decisions).

Supports six distinct decision states (reviewed, accepted_for_investigation, scheduled, rejected, deferred, verified_completed) and automatically reopens a decision if materially changed evidence invalidates its basis.

Dedicated Service Analysis Workspaces (web-dashboard/app/services/[service]/page.tsx):

Dedicated views for Disks, Public IPs, Virtual Machines, and App Service Plans featuring the 7-counter Coverage Banner, the service's Published Rule Matrix, a Cross-Scan Trend Strip, and Snapshot Comparison Mode.

Customer Rule Administration (web-dashboard/components/rules/CustomerRuleSettings.tsx):

Displays the provider $\to$ service $\to$ resource type $\to$ rule tree, inherited platform/customer defaults, delegated enable/disable toggles, bounded threshold sliders, time-limited scoped exceptions, and a Before / After Impact Preview modal (POST /api/v1/rules/preview).

3. Deep-Dive Improvement B: Multi-Cloud AI Foundry Configuration & Governance Settings

3.1 Architectural Ownership: Platform Guardrails vs. Workspace Self-Service Settings

Following the architectural boundary established in commit 6e0de85 (where per-workspace cloud resource-access identities moved to CloudSaver's WorkspaceSettings.tsx via PUT /api/v1/settings, while platform-wide defaults remain in platform/portal/):

+---------------------------------------------------------------------------------------------------+

|                   Platform Portal Operator Control Plane (platform/portal/)                       |

|  - Global AI Policy: Allowed providers, approved model catalog, region allowlists,                |

|    maximum token/attempt ceilings, emergency provider kill-switch, and Shared Knowledge DB        |

+---------------------------------------------------------------------------------------------------+

                                                 |

                                                 | Enforces policy bounds & plan entitlements

                                                 v

+---------------------------------------------------------------------------------------------------+

|               CloudSaver Workspace AI Foundry Settings (web-dashboard/ & app/settings_api.py)     |

|  - Workspace Admin configures tenant-bound AI Foundry endpoints, deployments & keyless auth:      |

|    1. Azure AI Foundry (Hub/Project Endpoint, Deployment, API Version, Managed Identity Client ID)|

|    2. AWS Bedrock (Region, Model/Inference Profile ARN, Guardrail ID/Version, Federated Role ARN) |

|    3. GCP Vertex AI (Project ID, Location, Gemini Model ID, Workload Identity Service Account)    |

|  - Source-Provider Affinity ('same_cloud_only' vs 'workspace_default') & Token Budget Caps        |

|  - Non-destructive 'Test AI Connection & RBAC' diagnostic runner                                  |

+---------------------------------------------------------------------------------------------------+

3.2 Provider-Specific Configuration Contracts (Azure AI Foundry, AWS Bedrock, GCP Vertex AI)

Extend the versioned workspace settings schema in app/settings_api.py and PostgreSQL tenant settings storage to include a strongly typed ai_foundry configuration block. All authentication is keyless (reusing the workspace's federated Managed Identity / Workload Identity bindings—no raw API keys stored in application tables):

Provider

Settings Schema Fields (settings.ai_foundry.providers.<provider>)

Keyless Identity & Security Validation Rules

Azure AI Foundry

(Azure OpenAI / AI Services)

- enabled: bool

- endpoint_url: https://<hub-or-resource>.openai.azure.com or https://<project>.services.ai.azure.com

- deployment_name: e.g., gpt-4o, o3-mini

- api_version: e.g., 2024-10-21

- region: Azure region (eastus2, swedencentral, etc.)

- deployment_sku: 'Standard_PAYG' | 'Provisioned_PTU'

- auth_binding: 'workspace_managed_identity' | 'custom_client_id'

- managed_identity_client_id: optional UUID override

- ai_search_knowledge_endpoint: optional HTTPS URI for private RAG

Rejects non-HTTPS or non-Azure endpoints (.openai.azure.com or .services.ai.azure.com required). Acquires Entra bearer token for https://cognitiveservices.azure.com/.default using DefaultAzureCredential / federated azure_client_id. Enforces Zero Data Retention (ZDR) / abuse-monitoring opt-out headers metadata disclosure.

AWS Bedrock

(Converse API & Guardrails)

- enabled: bool

- region: AWS region (us-east-1, us-west-2, eu-central-1)

- model_id: Model ID or Cross-Region Inference Profile ARN (e.g., us.anthropic.claude-3-5-sonnet-20241022-v2:0, amazon.nova-pro-v1:0)

- guardrail_id: optional Bedrock Guardrail identifier

- guardrail_version: optional version ('1', '2', never 'DRAFT' in prod)

- role_arn: IAM Role ARN assumed via STS AssumeRoleWithWebIdentity

- external_id: workspace-bound STS condition

- vpc_endpoint_url: optional PrivateLink vpce-... URI

Validates ARN/model syntax against platform allowlist. Uses keyless federated token exchange (AssumeRoleWithWebIdentity) with least-privilege bedrock:InvokeModel and bedrock:ApplyGuardrail permissions. Never accepts static AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY in workspace settings.

GCP Vertex AI

(Gemini Enterprise)

- enabled: bool

- project_id: GCP project slug

- location: Vertex region (us-central1, europe-west4, etc.)

- model_id: e.g., gemini-1.5-pro-002, gemini-1.5-flash-002

- service_account_email: Federated GCP service account email

- workload_identity_pool_provider: full WIF provider resource name

- vpc_sc_enforced: bool (VPC Service Controls boundary indicator)

Exchanges workspace identity token via GCP Security Token Service (STS) for a short-lived OAuth 2.0 token scoped to https://www.googleapis.com/auth/cloud-platform (roles/aiplatform.user). Enforces response_mime_type="application/json" with strict response schema validation.

3.3 Source-Provider Affinity, Token Budgets & Privacy Consent Controls

Include workspace-level governance policies inside settings.ai_foundry.policy:

Source-Provider Routing Policy (routing_mode):

same_cloud_only (Recommended Enterprise Default): Azure resource evidence is evaluated strictly by Azure AI Foundry; AWS resource evidence strictly by AWS Bedrock; GCP/GKE resource evidence strictly by GCP Vertex AI. If the matching cloud's AI provider is not configured, AI advisory for that resource is blocked with a clear configuration link rather than sending cross-cloud telemetry.

workspace_default_provider: Routes all eligible assessments to the workspace's designated primary_provider (azure | aws | gcp), provided the platform operator policy permits cross-provider inference.

Per-Target Context, Output & Attempt Budgets:

max_input_tokens_per_request: Bounded up to platform ceiling (default 4,000, max 16,000).

max_output_tokens_per_request: Bounded up to platform ceiling (default 1,200, max 4,096).

hourly_attempt_budget: Maximum accepted inference attempts per hour for the workspace (enforced by the durable SQL attempt ledger in migration 0009_enterprise_evidence).

monthly_token_limit: Optional hard token cap (input + output tokens combined) that automatically pauses new inferences when reached.

Independent Consent & Knowledge Sharing Toggles:

advisory_enabled: Master opt-in switch (defaults to false; requires explicit acknowledgement of model target, destination region, and unverified advisory status).

allow_anonymized_knowledge_candidates: Separate opt-in toggle (defaults to false). Enabling advisory_enabled never implies consent to contribute patterns to the shared knowledge review queue.

3.4 Backend Settings API (app/settings_api.py) & Non-Destructive Connection Diagnostics

Extend app/settings_api.py and services/scanner.py:

# app/settings_api.py — Proposed Endpoints & Validation Contract

# 1. GET /api/v1/settings

#    Returns current versioned settings including `identity` and `ai_foundry` blocks,

#    effective platform bounds, and current 30-day token/attempt ledger usage.

# 2. PUT /api/v1/settings

#    Requires TenantAdmin role + matching optimistic concurrency `version`.

#    Enforced closed (HTTP 409/403) during directory cutover mode or when plan

#    entitlement `can_use_ai_advisory` is False.

#    Validates endpoint URLs, model allowlists, region allowlists, and token bounds

#    against platform policy, then emits an append-only `ai_settings_updated` audit event.

# 3. POST /api/v1/settings/ai/test-connection

#    Non-destructive diagnostic probe for a selected provider ('azure' | 'aws' | 'gcp').

Actionable Diagnostic Categories (POST /api/v1/settings/ai/test-connection): Instead of a generic "Connection failed" error, the diagnostic probe executes a zero-data readiness check (validating federated token acquisition, IAM/RBAC role assignment, model deployment existence, and Bedrock Guardrail status) and returns a structured result:

status: 'passed' | 'failed'

failure_category: 'identity_federation_failed' | 'missing_model_rbac' | 'deployment_or_model_not_found' | 'guardrail_not_found' | 'quota_or_ptu_exhausted' | 'network_or_privatelink_blocked' | null

remediation_hint: Provider-specific fix (e.g., "Grant role Cognitive Services OpenAI User to managed identity client ID ... on Azure AI Foundry resource ..." or "Add bedrock:InvokeModel permission for arn:aws:bedrock:us-east-1::foundation-model/... to IAM role arn:aws:iam::...").

Records the test result in the workspace's access diagnostic history.

3.5 Frontend AIFoundryConfigurationEditor (WorkspaceSettings.tsx) & Pre-Inference Disclosure

In web-dashboard/components/settings/WorkspaceSettings.tsx, add AIFoundryConfigurationEditor.tsx directly below ResourceAccessIdentityEditor:

Provider Configuration Cards (Azure AI Foundry, AWS Bedrock, GCP Vertex AI):

Provider-accurate labels and field validators (e.g., Azure shows Foundry Endpoint URL, Deployment Name, API Version, and links to the workspace's Azure Client ID; AWS shows Region, Bedrock Model / Inference Profile ID, Guardrail ID & Version, and Federated IAM Role ARN; GCP shows Project ID, Vertex Location, Gemini Model ID, and Workload Identity Service Account).

Per-provider Test AI Connection button displaying real-time pass/fail badges, latency (ms), verified token/RBAC status, and actionable remediation copy on failure.

Routing, Budget & Consent Panel:

Radio selector for same_cloud_only vs. workspace_default_provider.

Sliders/inputs for hourly attempt budget and monthly token cap, paired with a live progress bar showing current 30-day usage from the durable ledger (attempts_last_30d, known_input_tokens, known_output_tokens, unmetered_attempts).

Separate checkboxes for Enable Opt-In AI Advisory and Allow Anonymized Pattern Candidates for Operator Review.

Pre-Inference Transparency Banner in Resource Drawer (AI Advice Tab):

Before an operator clicks Request AI Assessment, display the exact resolved target (Provider, Model Deployment, Destination Region, Source-Provider Policy, Allowed Evidence Fields, Published Knowledge Retrieval Status, and Remaining Hourly Attempt Quota).

Require assessment.evidence_digest to match the current previewed resource snapshot (returning 409 Conflict if stale).

3.6 Shared Knowledge Retrieval at Inference, Confidence Calibration & Citation Quality Gates

Connect the configured AI Foundry adapter to the governed knowledge store (platform/identity/knowledge/):

Separate Knowledge Database (KNOWLEDGE_DATABASE_URL): Store approved, anonymized guidance patterns with zero foreign keys to tenant tables.

Inference-Time Retrieval: Inject published patterns matching (provider, service, rule_id, pillar) into the system prompt context.

Deterministic Quality Gate: Reject any model response that cites a check_id not present in the deterministic assessment payload, cites an unknown/deprecated publication_id, fabricates a dollar figure when cost is unknown, or recommends modifying a protected resource.

Discrete Confidence Calibration: Display HIGH, MEDIUM, LOW, or INSUFFICIENT_EVIDENCE based strictly on the resource's deterministic evidence completeness rather than model prose.

4. Priority 3: End-to-End Customer Access & Delegated Key Administration UI (/api/v1/customer/*)

Wire all 18 customer_access_router endpoints in app/onboarding_api.py to dedicated screens under web-dashboard/components/customer-access/:

CustomerUsersDirectory.tsx: GET /api/v1/customer/users, POST .../invite (enforcing the 20/day limit), POST .../{user_id}/suspend, and POST .../{user_id}/reactivate.

OwnershipTransferModal.tsx: POST /api/v1/customer/ownership/transfer (atomic transfer of CustomerOwner with reason and membership_version bump).

WorkspaceMembershipsTable.tsx: GET/PUT/DELETE /api/v1/customer/workspaces/{tenant_id}/members/{user_id} with strict delegation envelope checks.

ServiceAccountsManager.tsx: GET/POST/PATCH/DELETE /api/v1/customer/service-accounts (up to 25 non-human integration principals).

DelegatedKeysManager.tsx & ScopeRestrictionsBuilder.tsx: GET/POST /api/v1/customer/workspaces/{tenant_id}/keys and rotate/revoke, binding keys to subject_user_id or service_account_id with subscription/account/project/cluster scope restrictions enforced server-side in narrow().

CustomerAuditLogView.tsx: GET /api/v1/customer/audit (before-cursor pagination) and GET /api/v1/customer/audit/export.csv.

5. Priority 4: Commercial Platform Billing Completion & Lapsed-Account Enforcement

Close the operational billing gaps documented in PLATFORM_BILLING.md:

Implement platform/identity/billing/importer.py: Validated, atomic billing importer pairing with scripts/export_billing.py (exact Decimal validation, duplicate source replay stability, conflict rejection).

Subscription Overrides on Creation: Allow POST /admin/v1/subscriptions to persist entitlement overrides (can_use_ai_advisory, max_subscriptions, max_active_keys_per_workspace, can_export_terraform, retention_days) immediately on creation and project them via app/directory_projector.py.

Plan-Change Race Handling (409 Conflict): Catch i0005_plan_change_pending_unique integrity errors in platform/identity/service.py and return HTTP 409 Conflict.

Automated Time-Based Lapsed-Account Evaluator: Background evaluator transitioning expired unpaid subscriptions (active $\to$ past_due $\to$ suspended), setting issuance_blocked = true, and emitting cache invalidation events.

Portal Plan Catalog Authoring UI: Wire POST/PATCH/retire /admin/v1/plans to platform/portal/components/billing/PlanCatalogAdmin.tsx.

6. Priority 5: Enterprise Entra/OIDC Sign-In, Capability Envelopes & Step-Up Authentication

Primary Entra / OIDC Human Sessions: Bind human users in directory.users by immutable (idp_issuer, idp_subject) and support Authorization Code + PKCE sign-in in web-dashboard/.

Fine-Grained Capability Arrays: Return explicit capabilities (scans.run, resources.read, rules.override, exceptions.manage, ai.configure, ai.invoke, iac.export, users.invite, keys.issue, keys.revoke, audit.export) in /internal/v1/keys/verify.

Step-Up Authentication: Require fresh re-authentication (max_age=300) before ownership_transfer, workspace-wide revoke-all, or disabling AI source-provider affinity restrictions.

7. Phased Implementation Sequence, Migrations & Verification Matrix

7.1 Ordered Delivery Sequence

Phase

Target Modules

Key Deliverables & Completion Criteria

Phase 1: Multi-Cloud Resource Analysis & Eight Azure Rules

app/scanner*.py, app/telemetry_contract.py, app/pricing.py, web-dashboard/app/services/*

Full inventory union persisted across AWS/GCP/K8s/Azure; 7-counter coverage manifest; 8-state evaluation outcomes; 5-min time-series coverage checks ($\ge 95%$); mutually exclusive opportunity_group_id; Service Analysis workspaces & customer rule override preview.

Phase 2: Multi-Cloud AI Foundry Settings & Diagnostics

app/settings_api.py, app/ai_gateway.py, web-dashboard/components/settings/AIFoundryConfigurationEditor.tsx

Versioned ai_foundry settings block for Azure AI Foundry, AWS Bedrock (with Guardrails), and GCP Vertex AI; keyless federated auth validation; same_cloud_only routing enforcement; POST /api/v1/settings/ai/test-connection diagnostics; pre-inference transparency banner.

Phase 3: Separate Knowledge DB, Retrieval & Confidence Calibration

platform/identity/knowledge/, app/ai_gateway.py, platform/portal/components/knowledge/*

Isolated knowledge_db migrations; dual-reviewer redaction gate; inference-time retrieval with mandatory publication_id + check_id citation verification; discrete confidence bands (HIGH/MEDIUM/LOW/INSUFFICIENT_EVIDENCE) and private feedback chips.

Phase 4: Customer Access UI (/api/v1/customer/*)

web-dashboard/components/customer-access/*, app/auth.py

All 18 /api/v1/customer/* endpoints wired to customer admin screens; server-side scope_restrictions enforced in narrow().

Phase 5: Commercial Billing Importer & Lapsed Evaluator

platform/identity/billing/importer.py, evaluator.py, platform/portal/components/billing/*

Billing importer/exporter round-trip; initial subscription overrides; HTTP 409 race mapping; automated lapsed-account evaluator and Portal Plan Catalog UI.

Phase 6: Entra/OIDC Sessions, Capabilities & Step-Up Auth

platform/identity/, app/auth.py, web-dashboard/

Human sign-in bound to (idp_issuer, idp_subject); capability subsetting enforced on keys; step-up auth on sensitive mutations.

7.2 Verification Commands

Every phase must pass all backend, database, audit, and frontend build gates before merge:

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
