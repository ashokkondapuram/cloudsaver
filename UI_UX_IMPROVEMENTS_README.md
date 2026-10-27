# CloudSaver UI/UX Improvements — Review README

Status: proposed design and implementation backlog. Documentation only.

Implementation update: the subsequent build request is tracked in [UI/UX implementation and local verification](docs/UI_UX_IMPLEMENTATION.md). That record distinguishes delivered improvements from the remaining roadmap below.

Prepared: 2026-10-27. Reviewed source baseline: `19856e4` in `ashokkondapuram/cloudsaver`.

This document proposes improvements to the customer console and the separate platform portal. It does not replace the root README, assert that the proposals are implemented, or authorize deployment. No application changes, builds, tests, cloud calls, or publishing are part of this documentation change.

## 1. Purpose and intended outcome

Make CloudSaver easier to understand and operate throughout this journey:

**Connect → Understand evidence → Prioritize → Assign → Review → Approve → Implement → Verify → Monitor.**

The interface should answer five questions on every operational screen:

1. Which customer, workspace, cloud scope, workload, and observation am I viewing?
2. What is known, missing, stale, or inferred?
3. What needs attention, and who owns it?
4. What can I do with my current permissions?
5. How will I know whether the action succeeded and delivered a useful outcome?

Visual polish should support these questions. It must not hide incomplete evidence, introduce invented financial results, or imply that an AI recommendation authorizes a change.

## 2. Current implementation and reuse boundaries

The following classification comes from source and existing verification documents. Existing verification describes its recorded baseline; it is not a new test run for `19856e4`.

| Area | Current foundation | Proposed improvement |
| --- | --- | --- |
| Customer navigation | Routes for resources, workloads, services, Kubernetes, finance, outcomes, governance, agents, automation, activity, and settings. | Organize navigation around tasks and make cross-workflow context consistent. |
| Resource explorer | Filters, five-pillar evidence, detail drawer, decisions, exports, and bounded resource loading. | Improve evidence comparison, ownership visibility, table configuration, and contextual next steps. |
| Rule management | Customer provider/service filters, parameter bounds, versioned preview/apply; platform workspace rule controls. | Add a consistent rule detail experience, effective-policy explanation, and safer operator review. |
| Financial evidence | Allocation, billing jobs, commitment evidence, outcomes, and per-resource Azure cost fetch. | Explain source windows, job progress, financial uncertainty, and reconciliation consistently. |
| Approval and execution | Existing governance, GitOps, agent plans, permits, and human approval foundations. | Present one navigable evidence trail while preserving separate approval authorities. |
| Platform portal | Customer/workspace administration, keys, plans, billing, activity, security, knowledge, and policies. | Improve customer-to-workspace navigation, impact previews, recovery guidance, and review queues. |
| Request reliability | Session invalidation, cancellation, stale-response guards, and uncertain-write handling have local verification records. | Preserve these controls and extend the same states to new experiences. |
| Full coordinated control plane | Domain/storage foundations exist; the acceptance matrix identifies missing API/UI/orchestration work. | Keep unsupported functionality visibly planned until its complete lifecycle is delivered. |

Inspect current source before implementation. Do not treat older feature guides as authoritative when they disagree with current routes, contracts, or migrations.

Source references:

- [Current product README](README.md)
- [Feature acceptance matrix](docs/FEATURE_ACCEPTANCE_MATRIX.md)
- [Previous UI/request reliability verification](docs/DETAIL_RELIABILITY_VERIFICATION.md)
- [Historical UI design guide](docs/UI_UX.md)
- [Customer navigation](web-dashboard/components/AppShell.tsx)
- [Platform navigation](platform/portal/components/AppShell.tsx)
- [Customer rule settings](web-dashboard/components/rules/CustomerRuleSettings.tsx)
- [Platform workspace rules](platform/portal/components/workspaces/RulesTab.tsx)

## 3. Information architecture

Reuse existing routes. The grouping below is a presentation proposal, not a request to rename every route or create duplicate pages.

| Customer navigation group | Existing destinations | Primary question |
| --- | --- | --- |
| Understand | Overview, Workloads, Resources, Services, Kubernetes | What exists, what supports it, and what evidence is available? |
| Improve | Optimization evidence, Savings & investigations | Which improvements deserve action, and what changed? |
| Finance | Cost allocation and its billing/commitment views | Where did spend occur, and what is financially supported? |
| Govern & execute | Risk & compliance, Automation & GitOps, Agent worker | Who approved which exact change, and what happened? |
| Operate | Activity & delivery | Which jobs, deliveries, or verifications need attention? |
| Administer | Settings | Which scopes, rules, identities, and data policies apply? |

Keep customer and operator applications distinct. Switching to the platform portal requires its own authorized session; customer access must not imply operator access.

For the portal, retain Directory, Billing, Oversight, and Platform groupings. Provide contextual links between customer detail, its workspaces, relevant billing records, and filtered activity. Do not combine data from unrelated customers into a detail screen.

### Global context

- Always show active workspace and role. Show customer and environment in operator detail flows.
- Distinguish selected cloud scope, selected resource scan, and selected billing period; they are independent contexts.
- Display source timestamps and timezone labels. Relative labels such as “2 hours ago” must expose the exact timestamp.
- Preserve safe view preferences, such as density and visible columns. Clear resource selections when workspace, credential, scan, or authorized scope changes.
- Deep links must be authorized on every read. Keep credentials and sensitive identifiers out of shareable URL parameters and browser analytics.
- Search results should identify their source and scope. If search covers only the selected snapshot, say so; do not imply an enterprise-wide search index.

## 4. Visual system and interaction standards

Reuse current typography, theme support, shared components, icons, tables, dialogs, and status patterns. Reconcile customer and portal tokens where practical without implying identical identities or permissions.

| Element | Requirement |
| --- | --- |
| Page heading | One clear title, short purpose, current context, and one primary task when appropriate. |
| Cards | Show a decision-relevant metric with units, period, scope, coverage, and evidence link. Avoid decorative counters without a supported meaning. |
| Statuses | Use text plus icon/color. Distinguish warning, failure, unknown, unavailable, stale, accepted risk, and success. |
| Tables | Named columns, keyboard access, useful defaults, visible sort/filter state, explicit pagination, and a clear selected-row count. |
| Drawers | Summarize first; reveal source details progressively. Preserve comparison context but load fresh resource-specific state on reopening. |
| Forms | Persistent labels, inline field errors, required-field explanations, unsaved-change protection, and an explicit final action. |
| Feedback | Persistent inline feedback for blocked or uncertain operations; transient toasts only for supplementary confirmation. |
| Financial values | Currency and period are mandatory. Unknown is not zero. Do not aggregate currencies without a documented conversion policy. |
| Responsive layouts | Reflow headings, actions, filters, and summaries; allow horizontal scrolling inside wide tables rather than across the full page. |

Target WCAG 2.2 AA for supported journeys. Validate keyboard navigation, visible and unobscured focus, dialog focus return, screen-reader names, live status announcements, contrast, reduced motion, and zoom/reflow. Prefer 44-pixel touch controls; meet applicable minimum target-size requirements where compact controls are necessary. Automated accessibility checks supplement manual review.

## 5. Customer console improvements

### 5.1 Overview: make the next useful action obvious

Divide the overview into three compact sections:

- **Evidence health:** connected scopes, last successful inventory, last billing evidence, source errors, and missing ownership.
- **Attention queue:** unassigned material findings, investigations awaiting acknowledgment, pending human approvals, overdue verification, and expiring exceptions.
- **Outcomes:** estimated opportunity, validated run-rate reduction, and reconciled benefit as separate measures with coverage and period.

Each card opens a filtered existing view. Use “Not measured” when a metric is unavailable; never display synthetic values as customer results. Allow role-appropriate emphasis without inventing new roles or changing server authorization.

Acceptance: a new viewer can identify the active workspace, most recent evidence, largest evidence gap, and permitted next step without opening an unrelated settings screen.

### 5.2 Onboarding and connection recovery

Provide an evidence-backed checklist: authorized identity, workspace assignment, cloud scope configuration, inventory access check, first completed scan, billing configuration, and ownership review. Steps must reflect actual server state, not simply button clicks.

Separate discovery permission, billing permission, and execution permission. A successful inventory check must not mark billing or mutation readiness as complete.

Offer specific recovery guidance for expired sessions, unavailable connectors, missing tenant assignment, insufficient provider permissions, and delayed billing. For developer Azure CLI issues, distinguish an unrecognized cache from a missing login and a provider authorization failure. Never request token/cache contents in UI support instructions or promise that a Windows-encrypted cache works in a Linux container.

Current supported onboarding remains operator-assisted where self-service consent is unimplemented. Label that boundary and avoid a dead-end consent button.

### 5.3 Resource explorer and assessment detail

Default columns: resource, provider/service, workload/owner, highest assessment priority, evidence coverage, observation age, and a clearly labeled cost measure. Offer column selection and comfortable/compact density.

Requirements:

- Inventory-only resources remain discoverable even when they have no findings.
- Explain whether counts describe the complete selected snapshot or filtered rows.
- Show applied filters as removable chips; provide a clear reset and distinguish “no matches” from “no inventory.”
- Preserve the current supported loading bound: source pages of at most 1,000, maximum 10,000 resources per scan, and 50 displayed matching rows per table page. Broader estates require a separately designed server-side query contract, not silent truncation or an arbitrary client limit increase.
- Name exports by their actual scope: complete selected snapshot, filtered inventory, or selected resources. Show count, currency/window where relevant, and safe CSV handling.
- Label resource identity and evidence windows before displaying assessment conclusions.
- Show five-pillar evidence coverage separately from risk severity. Full coverage is not a safety certificate.
- Place unknown/stale checks near the recommendation they constrain.
- Show dependencies as observed, declared, or inferred; missing relationships do not establish safe deletion.

Organize detail into Summary, Evidence & rules, Costs, Dependencies, Decisions, and History using existing detail data. Keep actions tied to the exact selected resource. Financial refresh, AI assessment, approval, and provider execution must remain distinct actions.

### 5.4 Workloads and services

Present workload membership, owner, environment, mapping method, shared-resource attribution, and evidence coverage before any aggregate priority.

Offer a list/table experience first; introduce a topology view only when authorized relationship evidence exists. Show unresolved or ambiguous mappings explicitly. A cloud subscription is an authorization scope, not automatically an application.

Service views should explain supported resource types, required evidence, unavailable metrics, and how recommendations differ by service. Provide a direct path back to the selected resource and its rule evidence.

### 5.5 Financial outcomes and investigations

Use a shared financial context panel: source, currency, billing period, collection time, completeness, and reconciliation state.

Keep these measures separate everywhere:

| Measure | Display requirement |
| --- | --- |
| Estimated opportunity | Assumptions, eligible resources, overlap/conflict groups, and uncertainty. |
| Validated run-rate reduction | Implementation date, supported recurring-cost evidence, and technical acceptance. |
| Reconciled financial benefit | Actual financial evidence, adjustments, attribution rationale, and finance decision. |

Billing reads must remain read-only. Explicit sync actions should expose an existing durable job reference/status where supported. Per-resource Azure cost fetch is a separate current action; do not label it a durable background job until its contract supports that behavior.

During provider throttling, show the last confirmed checkpoint, safe retry state, and next-attempt time only when returned by the backend. Do not invent a countdown or encourage repeat submissions. Cancel/resume controls require actual backend support.

Investigations should show detection window, baseline, contributions, owner, notes, possible change correlations, and resolution. Label correlation separately from proven cause. Delayed billing cannot support a real-time-alert claim.

### 5.6 Plans, approvals, agents, and verification

Link existing records into a navigable journey without flattening their independent states:

**Finding → reviewed plan → exact approval → implementation evidence → technical verification → application acceptance → financial reconciliation.**

The approval screen must show exact targets, parameter changes, plan version, expiry, policy constraints, maintenance window if applicable, prechecks, disruption, recovery limits, and unresolved evidence.

Display why approval is blocked. API keys and automation identities must not gain verified-human approval authority through UI changes. Changed state, expired authority, or a new plan version requires review under the existing server policy.

Execution shows per-step status and supported recovery actions. An ambiguous provider write must say “Outcome uncertain — reconciliation required”; no automatic replay or generic “Try again” mutation button.

Verification presents execution, technical, application, external-security, and financial results independently. Closing a dialog or receiving a successful API response does not close a finding. Accepted risk remains a failed control with an exception, not a pass.

## 6. Rules administration: customer and platform

Build on existing catalogs and versioned policy contracts. Do not add a second rule engine.

### Catalog and rule detail

Provide provider, service/resource type, pillar, state, availability, and search filters. For each rule show:

- Stable ID, version, name, purpose, supported targets, and applicability.
- Required evidence, freshness/sample requirements, missing-data behavior, and evaluation explanation.
- Effective state and its source: platform policy, workspace override, or mandatory restriction.
- Delegated thresholds with units, bounds, defaults, and rationale.
- Potential operational effects, treatment options, and verification requirements.
- Historical evaluations with the original rule/policy versions.

Unavailable, retired, disabled, unknown, and not applicable are different states. A published catalog entry is not evidence that a rule evaluated successfully.

### Change review

Proposed workflow: select workspace/provider/service → edit allowed rules → review draft diff → preview supported impact → confirm → display committed version and audit reference.

Platform controls must not silently disable mandatory protections. A request to administer every rule means visibility and explicit policy decisions; it does not imply that every safety rule is overridable.

For bulk edits, show exact affected rules and workspaces, exclude unauthorized/unavailable entries explicitly, and use a bounded server contract before enabling the control. Do not simulate a successful bulk save with unrelated per-row writes.

On version conflict, preserve a non-sensitive draft in memory, reload current policy, show differences, and require a fresh preview. Never silently overwrite another administrator's changes. Existing historical scans retain their original evaluation policy.

Acceptance: an administrator can explain why a rule is effective, which thresholds are editable, what will change next scan, and which historical observations will remain unchanged. A scope-limited or read-only user cannot apply workspace-wide changes.

## 7. Platform portal improvements

| Area | Proposed experience | Required boundary |
| --- | --- | --- |
| Customer directory | Searchable customer list, clear customer status, workspace count, and direct detail navigation. | Counts must be authorized and source-backed; missing counts remain unknown. |
| Workspace detail | Consistent Overview, Cloud accounts, Resource access, Rules, Keys, Usage, and relevant billing links. | Show customer/workspace context before every write. |
| Keys and access | Effective role/scope summary, expiry, usage, rotate/revoke explanation, and one-time secret reveal. | Never show stored secrets, put keys in URLs, or imply a copy can be recovered later. |
| Plans and billing | Current entitlement, pending changes, effective dates, provider state, and an impact comparison. | A plan edit does not prove a completed provider charge, refund, or entitlement projection. |
| Security and activity | Filtered events, safe error codes, request references, step-up context, and links to affected records. | No raw credentials, customer payload dumps, or unauthorized cross-customer joins. |
| Knowledge | Publication source, privacy screening, review history, expiry, lifecycle, and separate storage status. | Retain existing source restrictions and independent reviews; customer observations must not become training material. |

Auditors should have a coherent read-only journey. Knowledge/privacy reviewer navigation must reflect the exact server-granted routes rather than exposing unrelated administration controls. Disabled actions should explain the missing authority without revealing foreign records.

For sensitive writes, present the actual customer, workspace, effective change, required step-up, and expected impact. If the result is uncertain, retain the draft in the current authorized session, show an activity/status lookup, and prevent automatic duplicate submission.

## 8. AI experience and knowledge governance

Before an AI action, disclose the configured processor, approved purpose, data categories, retention policy, and applicable budget limits using existing policy data. Display “Unavailable” when policy or processor configuration is missing.

Separate deterministic rule results, AI advice, owner statements, execution evidence, and independent verification. AI text must not appear as a passed check or automatically accepted treatment.

Show knowledge metrics only when supported by measured records: publication counts, current reviews, freshness, and evaluation results with methodology/window. “Items published” is not “knowledge learned,” and a separate database alone does not establish privacy compliance.

No automatic ingestion of client evidence into shared knowledge or model training. Any future publication pipeline requires explicit approved source/purpose contracts and privacy review; this UI proposal does not authorize it.

## 9. Shared state and recovery contract

| State | Required user experience |
| --- | --- |
| Initial loading | Stable layout, meaningful loading label, no invented zero totals. |
| Empty source | Explain what has not been collected and offer an authorized setup/scan action. |
| Empty filtered result | Show active filters and a reset action. |
| Partial or stale evidence | Identify affected source/window and limit conclusions. Preserve a previous result only with an explicit stale label and the same authorized context. |
| Session ended | Clear protected cached data and selections; require reauthentication. A 403 alone must not end a valid session. |
| Permission denied | Explain permitted recovery without leaking whether a foreign record exists. |
| Read failure | Show safe error and request reference; retry the read without replaying a mutation. |
| Unknown job status | Show last confirmed state and a read-only status check; do not assume no job exists. |
| Policy conflict | Preserve the permitted in-memory draft, show newer state, and require review. |
| Mutation uncertain | Explain possible completion, link activity/reconciliation, and block automatic resubmission. |
| Backend capability unavailable | Mark planned/unsupported functionality explicitly; do not show a success-capable control. |

Cancel stale reads on context changes and ignore late responses. Do not let old pagination responses overwrite a newer filter. Sensitive drafts must clear on logout, tenant change, or loss of access.

## 10. Optional Sites review prototype

If a Sites prototype is requested later, use a separate project with clearly labeled synthetic data. Prioritize the Overview → Resources → Rule detail → Plan review → Outcomes journey, followed by customer/workspace operator administration.

The prototype must label simulated actions, contain no customer keys or imported client observations, and make no cloud/provider mutations. It is a design review artifact, not proof of authentication, tenant isolation, financial correctness, or production readiness. Registering or publishing a Site is outside this README-only request.

## 11. Delivery backlog and dependencies

| Priority | Increment | Dependency | Reviewable outcome |
| --- | --- | --- | --- |
| P0 | Consistent evidence/status language and authorization-aware actions | Existing response contracts and permission policy | Supported states documented on every affected screen; unknown evidence never looks successful. |
| P1 | Context header, navigation grouping, evidence-health overview | Authorized scope/freshness data | Clear current workspace, observation, billing period, and next task. |
| P1 | Resource explorer/detail refinements | Existing bounded inventory and assessment APIs | Inventory-only resources, clear coverage, scoped exports, and safe detail comparison. |
| P1 | Rule detail and reviewed workspace changes | Catalog metadata, policy provenance, versioned preview/apply | Explainable effective policy and conflict-safe edits. |
| P1 | Financial job visibility and evidence windows | Durable job/status contracts and source completeness metadata | Safe sync recovery and distinct estimated/validated/reconciled measures. |
| P1 | Portal customer/workspace and sensitive-write flows | Existing operator roles, activity, and step-up | Clear impact, correct authorization, and uncertain-write recovery. |
| P2 | Connected plans, approvals, verification, and outcome navigation | Complete owned relationships and API/gateway/browser contracts | One complete supported vertical slice with independent outcomes. |
| P2 | Server-side large-estate exploration | Designed bounded query, export, and consistency contracts | Representative tenant-scale acceptance beyond current client limits. |
| P2 | Rich topology and business unit economics views | Verified relationships, allocation and business-volume evidence | Useful visualizations with visible uncertainty and explainable attribution. |

Assign an individual owner and a linked implementation issue before scheduling each increment. These are product delivery priorities, not claims that the current UI contains a particular security defect. Do not invent a calendar estimate without team capacity and dependency review.

## 12. Future acceptance plan — not executed here

Review one complete synthetic journey before broad visual expansion:

1. An authorized user opens a workspace with fresh inventory and delayed billing.
2. They find an inventory-only resource, inspect five-pillar unknowns, and identify its owner.
3. An administrator previews a delegated rule change; a concurrent policy update forces a fresh review.
4. An owner prepares a supported exact action; a separate authorized human reviews it.
5. Execution records success or uncertainty without automatic replay.
6. Independent evidence supports technical acceptance; finance remains awaiting reconciliation when billing is incomplete.
7. A fresh confirmed recurrence reopens the finding without authorizing a new change.
8. An operator traces the same workspace's permitted administration and audit context without crossing customer boundaries.

Future verification should include accessible keyboard/screen-reader journeys, responsive layouts, real browser-to-gateway-to-core contracts, negative role/scope cases, stale-response races, duplicate submissions, timeout recovery, invalid response handling, safe exports, and representative inventory size. Use only approved local fixtures until an authorized sandbox is connected.

Record exact release SHA and evidence for each implemented increment. Existing builds and intercepted browser fixtures do not establish live provider acceptance or compliance certification.

## 13. Review checklist

- [ ] Supported pages and planned capabilities are clearly distinguished.
- [ ] Existing routes, identity, evidence, jobs, approval, and audit infrastructure are reused.
- [ ] Customer and platform operator journeys remain separate and authorized.
- [ ] Every metric has scope, units, period, and missing-data behavior.
- [ ] Estimated opportunity, validated reduction, and reconciled benefit remain distinct.
- [ ] Rule changes respect platform restrictions and exact policy versions.
- [ ] AI advice cannot approve changes, accept risk, or silently publish customer knowledge.
- [ ] Uncertain writes and incomplete evidence have usable recovery paths.
- [ ] Accessibility and representative user review have named owners.
- [ ] Future acceptance evidence is recorded without claiming tests were run for this document.

Review decision: pending. Approving this design backlog is not approval to execute a cloud change or publish a Site.
