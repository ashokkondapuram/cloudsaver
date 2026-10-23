# CloudSaver and Platform Portal: feature, rule, resource analysis, and AI knowledge improvements

**Document type:** Proposed implementation roadmap and functional specification.

**Source baseline:** `ashokkondapuram/cloudsaver` (project root), baseline commit `a59de5c` for the original billing companion; billing runtime notes in [Platform billing — operations and implementation boundaries](PLATFORM_BILLING.md) may reflect later revisions.

**Scope of this change:** This document only. It does not implement features, create databases, change existing rules, enable AI learning, run tests, or deploy services. All requirements below are **proposed** unless explicitly described as existing behavior.

The objective is a resource analysis product that explains its evidence, lets administrators control every published assessment rule by service and workspace, and improves its advisory knowledge without adding sensitive client data to a shared knowledge store. CloudSaver is the customer workspace; the Platform Portal is the operator control plane. They need consistent workflows and different access boundaries.

The companion [Platform billing — operations and implementation boundaries](PLATFORM_BILLING.md) covers commercial workflows and their current gaps. This document covers the remaining product improvements and their dependencies on billing, identity, and access.

## Contents

- [Current baseline and missing capabilities](#current-baseline-and-missing-capabilities)
- [Product principles and first delivery scope](#product-principles-and-first-delivery-scope)
- [CloudSaver UI and UX improvements](#cloudsaver-ui-and-ux-improvements)
- [Platform Portal UI and UX improvements](#platform-portal-ui-and-ux-improvements)
- [Shared interaction and accessibility requirements](#shared-interaction-and-accessibility-requirements)
- [Resource analysis improvements](#resource-analysis-improvements)
- [Rule catalog and administrative control](#rule-catalog-and-administrative-control)
- [Detailed initial resource rules](#detailed-initial-resource-rules)
- [AI assessment improvements](#ai-assessment-improvements)
- [Private analysis and shared knowledge boundaries](#private-analysis-and-shared-knowledge-boundaries)
- [Separate knowledge database](#separate-knowledge-database)
- [Knowledge acquisition and publication lifecycle](#knowledge-acquisition-and-publication-lifecycle)
- [Knowledge metrics and dashboards](#knowledge-metrics-and-dashboards)
- [Reliability, integrations, and operational requirements](#reliability-integrations-and-operational-requirements)
- [Delivery sequence and completion criteria](#delivery-sequence-and-completion-criteria)
- [Source references](#source-references)

## Current baseline and missing capabilities

Source files show the following existing foundations. Their existence is not a claim that every provider integration has been verified against a live environment.

| Area | Existing foundation | Improvement needed |
| --- | --- | --- |
| Azure inventory findings | Signals for unattached disks, unassociated public IPs, stopped VMs, empty App Service plans, unattached NICs, unassociated NSGs, and stopped/empty Application Gateways | Versioned service catalog, detailed evidence contracts, observation windows, explicit evaluation outcomes, and admin controls |
| Other cloud findings | AWS EBS, Elastic IP, and stopped RDS signals; GCP disk/address/Cloud SQL signals; Kubernetes CPU/memory request analysis | Publish the existing coverage accurately and bring each rule under the same administration model |
| Resource assessment | Findings grouped by resource; five-pillar deterministic checks, evidence gaps, fingerprints, and history | Inventory-wide analysis, dependency evidence, non-overlapping cost estimates, and outcome verification |
| AI advisory | Tenant-bound targets, allowlisted input, evidence citations, batch processing, follow-up questions, and constrained advisory responses | Calibrated confidence, approved knowledge retrieval, quality feedback, and privacy-safe knowledge publication |
| Customer resources UI | Resource table, filters, AI status, decisions, drawer, CSV, and printable reporting | Azure live scans persist `inventory`; Resource Explorer lists inventory-only rows; cross-scan trends remain roadmap |
| Operator workspace UI | Overview, cloud accounts, resource access, keys, usage, and activity | Identity admin API for workspace rule overrides; portal UI and diagnostics remain roadmap |
| Rules | CloudSaver scanner rules plus identity `analysis` catalog and workspace enablement | Effective rules endpoint drives scan filtering when identity is reachable |
| Shared AI knowledge | Resource-local inference and decision storage | Identity `knowledge` schema and publication admin API; retrieval at inference and metrics remain roadmap |
| Commercial enforcement | Billing records, approval queue, plan limits, and fallback entitlement checks | Resolve the subscription/workspace/entitlement gaps documented in the companion billing guide before representing paid feature activation as complete |

The current resource assessment is built from findings. A resource without a finding is not necessarily present in that assessment view. Therefore, an empty result must not be presented as proof that every resource was assessed or that the environment is healthy.

## Product principles and first delivery scope

1. **Evidence before conclusions.** Show what was collected, when, over which period, and what remains unknown.
2. **Resource inventory before a health score.** Count discovered, evaluated, excluded, unsupported, and inaccessible resources separately.
3. **Human-readable rules.** Use descriptive names and detailed explanations. This guide intentionally includes no rule codes, executable queries, or implementation snippets.
4. **Administration for every published rule.** Each supported service must expose all applicable published rules, including disabled and unavailable rules.
5. **Independent action safeguards.** A rule setting cannot disable authorization, retention protection, approval requirements, or fresh pre-action verification.
6. **AI advises from evidence.** It cannot approve changes, change policy, manufacture measurements, or treat missing evidence as a pass.
7. **Knowledge grows through reviewed publication.** More AI requests do not automatically mean more knowledge learned.
8. **No sensitive client data in shared knowledge.** Hashing or removing names alone is insufficient. Reject uncertain content rather than storing it.

The first detailed rule delivery covers four Azure resource types: managed disks, public IP addresses, virtual machines, and App Service plans. Each receives two fully specified rules. These are proposed additions or refinements, not assertions that the current collectors already obtain every required field.

Existing AWS, GCP, Kubernetes, and other Azure rules must remain visible in the catalog. Their detailed expansion follows the first four resource types; unsupported analysis must remain explicitly unavailable rather than appearing enabled and silently producing no results.

## CloudSaver UI and UX improvements

### Workspace home and onboarding

Make the landing page answer: what is connected, what was analyzed, what needs attention, and what can be done next.

- Persistent workspace identity, environment label, selected provider/service, and observation time.
- Setup checklist covering identity, cloud scopes, access verification, first inventory, telemetry, cost evidence, and active rules.
- Separate counts for connected scopes and scopes successfully read in the most recent run.
- Clear partial-coverage and stale-data banners with the affected scopes and a useful recovery action.
- KPI cards for verified billed cost, estimated opportunity, verified realized savings, resources with evidence gaps, and active review work. Unknown amounts display as unknown, not zero.
- A prioritized action list with owner, reason, evidence freshness, and next review date.
- No sample or fabricated production data when a service is unavailable. Demonstration data must have an explicit demonstration label and separate context.

### Resource Explorer

Use one canonical inventory row per resource, including resources without active findings.

| Element | Required behavior |
| --- | --- |
| Search and filters | Provider, service, resource type, scope, region, environment, owner, analysis state, severity, evidence coverage, and exception state |
| Filter persistence | URL-based saved views; changing workspaces clears incompatible selections and cached results |
| Service summary | Eligible resource count, applicable rules, enabled rules, evaluated count, and unavailable evidence |
| Table columns | Resource, service, scope, last observed, analysis coverage, risk, cost basis, opportunity, decision, and assignee |
| Bulk selection | Explicit page-only versus all-filtered selection with the exact affected count |
| Bulk actions | Assign owner, request review, apply a time-limited exception, or queue advisory analysis subject to permissions |
| Export | Same filters and authorization as the screen; selected currency, period, evidence freshness, and coverage included |
| Large results | Server-side paging/filtering and bounded export jobs; visible progress, cancellation, and expiry |

The resource drawer should have Overview, Evidence, Rules, Cost, Dependencies, AI Advice, History, and Decisions sections. Preserve the selected resource and filters when the drawer closes. Support a shareable resource page for investigations that need more space.

### Service analysis workspace

Provide a dedicated view per cloud service (for example storage, compute, networking) that complements Resource Explorer:

- Service-level coverage banner: discovered, in-scope, evaluated, excluded, unsupported, and failed-to-read counts with links to scope diagnostics.
- Rule matrix for that service: every published rule with enabled/disabled/unavailable state, last evaluation time, and outcome distribution (pass, risk, unknown, not applicable).
- Trend strip across completed scans for opportunity, verified savings, and evidence-gap counts; label each point with scan time and scope coverage.
- Comparison mode between two saved snapshots with explicit “observation change only” language when live state may differ.
- Entry points to deterministic assessment and AI advisory only when evidence digest and permissions allow; show why advisory is blocked when it is.

### Settings, plans, and access

- Plans tab: request plan changes, show pending approval, and surface billing state without implying Stripe checkout is available when it is not (see billing guide).
- Resource access tab: test access with clear pass/fail reasons tied to identity configuration.
- Activity and automation: correlate scans, assessments, and operator actions with request IDs where available.

## Platform Portal UI and UX improvements

### Operator home

- Fleet summary: customers, workspaces, billing state distribution, and workspaces with stale directory or failed access tests.
- Queues: plan-change approval (including `pending_payment` when Stripe is configured), and future rule-publication review queue.
- Links to billing customer views only for actions the runtime actually supports.

### Customer and workspace administration

- Customer billing tab: subscriptions, payments, entitlements, and `issuance_blocked` with actions that match backend capabilities.
- Workspace keys tab: respect issuance policy; explain blocked state with next steps.
- **Proposed:** Rule assignment panel per workspace—effective rules, inheritance from customer defaults, overrides, and read-only explanation of safeguards that cannot be turned off.
- **Proposed:** AI knowledge governance—publication queue, rejected candidates, and metrics without tenant-identifying content.

### Diagnostics

- Identity and proxy health for admin API paths; distinguish allowlisted routes from implemented handlers.
- Resource access test history per workspace.

## Shared interaction and accessibility requirements

- Sentence case labels; active voice; second person in customer-facing copy ([UX writing standards](ENVIRONMENT.md) apply across portal and dashboard).
- Loading, empty, partial-coverage, and error states must state what happened and what the user can do next.
- Keyboard navigation for tables, drawers, and bulk actions; visible focus; table semantics for screen readers.
- Do not use color alone for severity; pair with text and icons.
- Date and time: [data formatting standards](ENVIRONMENT.md)—`Mmm D, YYYY`, `H:MM AM/PM`, currency with two decimals when shown.
- Long-running exports and scans: non-blocking progress, cancel, and retention of partial failure detail.

## Resource analysis improvements

| Theme | Proposed behavior |
| --- | --- |
| Inventory union | Persist or project full resource inventory per scan, not only finding-backed rows |
| Evidence contract | Per rule: required fields, observation window, staleness threshold, and explicit unknown outcome |
| Cost | Separate observed retail estimate, billed amount (when ingested), and opportunity; never double-count across rules |
| Dependencies | Show unavailable dependency graph explicitly; no inferred edges in v1 of this roadmap |
| Outcomes | Pass, risk, unknown, excluded, unsupported—never collapse unknown into pass |
| Fingerprints | Stable resource identity across scans with breaking-change detection |
| Verification | Optional post-action re-scan or spot-check workflow with human sign-off |

Align deterministic assessment behavior with [Service architecture assessment and cloud AI advisory](ASSESSMENT_AI.md) for what already ships versus what remains roadmap.

## Rule catalog and administrative control

**Proposed** platform-level catalog (operator) and effective policy (customer workspace):

| Capability | Description |
| --- | --- |
| Published rule registry | Versioned metadata: service, resource type, descriptive name, pillar, evidence requirements, default severity |
| Enablement | Global default, customer override, workspace override; disabled rules remain visible |
| Unavailable rules | Shown with reason (missing collector evidence, plan limit, provider not connected) |
| Exceptions | Time-bounded, scoped, audited; cannot disable retention or approval safeguards |
| Audit | Who changed rule state, when, and effective scope |

CloudSaver continues to enforce tenant RLS and scan scope; portal changes rule publication and assignment, not scan credentials directly.

## Detailed initial resource rules

First delivery: four Azure resource types, two rules each. Names are descriptive only; implementation binds to internal rule identifiers separately.

### Managed disks

1. **Unattached managed disk** — Flag disks with no active VM attachment in the observation window. Evidence: attachment state, disk size, SKU, region, tags indicating retention intent. Outcome unknown if attachment state could not be read.
2. **Unattached disk with no recent snapshot** — For disks already flagged as unattached, check for a successful snapshot within the operator-defined retention window. Missing snapshot API access yields unknown, not pass.

### Public IP addresses

1. **Unassociated public IP** — Public IP with no associated NIC or load balancer front end in the observation window.
2. **Idle associated public IP** — Associated IP whose parent resource shows no meaningful ingress/egress signal when telemetry exists; unknown when metrics are unavailable.

### Virtual machines

1. **Stopped virtual machine** — VM in stopped/deallocated state beyond the grace window; exclude resources tagged with approved standby or DR intent per normalized tag policy.
2. **Oversized stopped or low-utilization VM** — When size and utilization evidence exists, highlight mismatch; unknown without utilization series.

### App Service plans

1. **Empty App Service plan** — Plan with no running apps or zero instances in the window.
2. **Underutilized plan SKU** — When app count and metric evidence exists, surface rightsizing opportunity; unknown without metrics.

Subsequent phases extend the same pattern to AWS, GCP, Kubernetes, and remaining Azure services already partially covered by collectors.

## AI assessment improvements

- **Confidence calibration** — Map model output to discrete confidence bands tied to evidence completeness, not model verbosity.
- **Retrieval** — Optional approved knowledge snippets at inference time; citations must reference publication IDs, not raw tenant stores.
- **Feedback** — Operator-reviewed thumbs-up/down on usefulness, separate from automatic learning.
- **Quality gates** — Reject advisories that cite checks not present in the deterministic assessment payload.
- **Batch** — Retain bounded batch with per-item failure isolation and shared attempt budget visibility.

Existing boundaries in [ASSESSMENT_AI.md](ASSESSMENT_AI.md) remain until superseded by implemented features.

## Private analysis and shared knowledge boundaries

| Data class | Where it lives | May enter shared knowledge |
| --- | --- | --- |
| Tenant scan payloads, names, tags | Tenant database | No |
| Deterministic assessment snapshots | Tenant database | Only anonymized, reviewed aggregates |
| AI advisories | Tenant store + optional cache | No verbatim text |
| Operator publication candidates | Staging queue | After review, stripped of identifiers |
| Global patterns | Shared knowledge DB | Yes, with publication record |

Reject publication when redaction confidence is low.

## Separate knowledge database

**Proposed** physical or logical database separate from tenant application data and platform directory/billing:

- Publication records, semantic keys, embedding references (if used), quality scores, and deprecation lifecycle.
- No foreign keys into tenant tables; link only opaque publication IDs used in retrieval.
- Migrations independent of CloudSaver `alembic` and platform `identity_migrations`.

## Knowledge acquisition and publication lifecycle

1. **Capture** — Candidate generated from operator-reviewed tenant outcomes or curated docs, not automatic from every inference.
2. **Redact** — Automated checks plus human review; reject on uncertainty.
3. **Publish** — Versioned entry available to retrieval layer.
4. **Deprecate** — Supersede or retire with reason; advisories must not cite deprecated IDs.
5. **Audit** — Actor, time, source class (never raw tenant dump).

## Knowledge metrics and dashboards

- Publications per month, acceptance/rejection rate, citation rate in advisories, deprecation count.
- Operator dashboard in portal; no tenant-identifying drill-down on shared metrics.
- Correlate with inference attempt volume only at aggregate fleet level.

## Reliability, integrations, and operational requirements

- Idempotent scan and export jobs; bounded retries; dead-letter with operator visibility.
- Feature flags for catalog rules, retrieval, and knowledge publication independent of billing provider mode.
- Billing-gated features must check entitlements and enforcement paths documented in [PLATFORM_BILLING.md](PLATFORM_BILLING.md).
- ITSM integrations (Jira, ServiceNow) remain outbound-only until authenticated sync is specified and implemented.
- Local development: loopback-only services per repository policy.

## Delivery sequence and completion criteria

| Phase | Focus | Completion criteria |
| --- | --- | --- |
| 0 | Documentation and catalog schema design | This roadmap approved; rule metadata model drafted |
| 1 | Inventory row + coverage denominators in CloudSaver UI | Explorer shows non-finding resources; coverage banner on service views |
| 2 | Rule registry + portal assignment (read-only effective view) | Operators see all rules and states; tenants see effective policy |
| 3 | First four Azure rule pairs | Evidence contracts met or marked unknown; admin enable/disable |
| 4 | AI retrieval from published knowledge only | No tenant text in shared DB; citation IDs in advisory UI |
| 5 | Knowledge DB + publication workflow | Review queue, metrics dashboard, deprecation path |

Commercial gating for paid analysis features depends on billing gap closure (subscription, workspace tier, entitlement projection, issuance enforcement).

## Source references

Runtime sources describe current behavior; this roadmap describes targets.

| Topic | Path |
| --- | --- |
| Deterministic assessment and AI (shipped boundaries) | [ASSESSMENT_AI.md](ASSESSMENT_AI.md) |
| v1.0 feature matrix | [V1_MASTER_GUIDE.md](V1_MASTER_GUIDE.md) |
| UI mapping | [UI_UX.md](UI_UX.md) |
| Cloud ingestion and scopes | [CLOUD_SOURCES.md](CLOUD_SOURCES.md) |
| Platform billing gaps and ops | [PLATFORM_BILLING.md](PLATFORM_BILLING.md) |
| Product roadmap (versions) | [ROADMAP.md](../ROADMAP.md) |
| CloudSaver settings and billing API | [`app/settings_api.py`](../app/settings_api.py) |
| Entitlements | [`app/entitlements.py`](../app/entitlements.py) |
| Web dashboard resources and settings | [`web-dashboard/`](../web-dashboard/) |
| Portal billing and workspaces | [`platform/portal/`](../platform/portal/) |
| Platform identity and access | [`platform/identity/`](../platform/identity/) |

Application behavior and deployment configuration remain those of the referenced source revision until implementation tasks close the gaps above.
