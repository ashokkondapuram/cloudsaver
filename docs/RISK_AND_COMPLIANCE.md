# CloudSaver 1.7.0 — accountable risk and control workflow

This release implements a narrow, complete governance workflow for one Azure storage control. Open **Risk & compliance** in the customer dashboard. Controls, findings, business risks, exceptions, source attestations and decision history are separate records. A technical pass, an accepted business risk and organizational compliance are different claims.

The [upgrade runbook](releases/1.7.0-UPGRADE.md) is authoritative for this release. Existing [enterprise launch gates](ENTERPRISE_READINESS_GAPS.md) remain open. This implementation is not a NIST assessment, compliance certification, penetration test or accepted enterprise production launch.

## Supported first control and evidence boundary

`AZ-STORAGE-PUBLIC-BLOB-ACCESS`: **Production customer-data storage must disallow public blob access at the Azure storage-account level.**

The live Azure inventory query now preserves `properties.allowBlobPublicAccess` as the dedicated boolean `evidence.allow_blob_public_access`. It uses the existing Resource Graph query; it adds no cloud write or extra provider call. Older observations that contain only a generic `publicly_accessible` field do not establish this control. Run a fresh inventory scan after upgrade.

| Result | Meaning |
| --- | --- |
| Fail | A fresh completed scan explicitly reports the account flag true, and a security analyst confirms production/customer-data applicability. |
| Pass | The same applicable account flag is explicitly false in a fresh completed scan. |
| Unknown | The flag, business context, current resource observation or source freshness is missing/invalid. Missing evidence is never filled with a pass. |
| Not applicable | The resource type is outside this control, or the analyst records a known nonproduction/non-customer-data scope with rationale. |

Configuration observations must be no more than 24 hours old. Before closure the application-access attestation must also be no more than one hour old and follow the implementation and post-change observation. The latest relevant saved scan is selected at the server: an older passing scan cannot hide a newer failing, missing or stale observation.

**Account permission is not proof that a container is publicly readable.** Disabling it does not establish that customer data was never exposed. Container ACLs, SAS/key exposure, private networking, actual data access and incident forensics are separate questions. No data-plane customer contents, credentials, IP lists, raw tags or arbitrary cloud configuration are copied into these control observations.

Assessment coverage includes explicitly assessed resources. Unassessed cloud-inventory coverage remains unknown; there is no single compliance score. The ownership metric covers these assessed records, not every resource in a customer account.

## Records and accountability

- **Control:** reviewed, immutable policy versions; accountable control owner; mandatory-obligation designation; residual-risk appetite; maximum exception duration; reviewed framework/version/reference/rationale mappings. No framework mappings are asserted by default.
- **Finding:** immutable original observation, current assessment, resource/tenant identity, human-confirmed application/environment/classification, technical owner, business owner, severity, UTC due date, treatment, change plan, approvals, provider-event evidence, independent verification and incident/exception links.
- **Business risk:** a separate risk statement, one or more related findings with the same business owner, inherent and residual likelihood/impact, treatment plan and review date. Closing a technical finding does not automatically retire its business risk.
- **Exception:** exact finding/resource and policy version, business justification, rejected alternatives, compensating controls and signed evidence, residual-risk snapshot, review trigger, start/review/expiry dates, separate security review and business authorization.

The pilot risk rubric is explicit: likelihood 1–5 × impact 1–5. Inherent scores ≥20 are critical, ≥12 high, ≥6 medium, otherwise low; scores ≥12 require material-risk authority. These are organizational review inputs, not measured probabilities. Triage defaults to a due **UTC date** within 1/7/30/90 calendar days for critical/high/medium/low respectively. It is not a measured 24-hour response SLA. The API can set an earlier date within the severity bound.

## Delegated access and separation of duties

Existing workspace/Entra roles are preserved. The new governance responsibilities are delegated separately in **Controls → Delegate governance responsibilities**. Workspace TenantAdmin does not silently inherit these decision powers.

| Governance role | Supported responsibility |
| --- | --- |
| ResourceOwner | Submit the treatment for findings where the immutable subject is the assigned technical owner; deliver signed evidence; request an exception or corrected-finding review. |
| SecurityAnalyst | Confirm applicability/context, create findings and business-risk assessments, triage, review compensation, approve verified closure and record incident handoffs. |
| ChangeApprover | Approve a specific plan proposed by a different person. This does not accept business risk or authorize an agent execution step. |
| BusinessRiskOwner | Review/retire its assigned business risks and authorize exceptions within an explicit maximum inherent score and exception duration. |
| ComplianceReviewer | Review control-policy versions and requirement mappings; independently verify implemented changes; approve verified closure. |
| Auditor | Read governance records and export labeled evidence/history; no mutation, approval or execution. Draft and historical decisions remain labeled, not presented as approved compliance. |
| AutomationIdentity | Deliver scoped signed collector evidence; never exercise human decision authority. |

A verified human TenantAdmin manages versioned delegations with an authority reference, active/revoked status and expiry (at most 90 days). Default business authority is at most inherent score 11 and seven exception days. Material risk requires an explicitly reviewed higher delegation; the software does not establish that an individual holds legally sufficient authority. Control ownership must reference a currently delegated ComplianceReviewer.

Use immutable provisioned user/service subject UUIDs, not emails, bearer tokens or keys. An alias helps identify the delegate. These necessary accountability identifiers remain tenant-scoped application data. A restricted provider/scope key cannot use these workspace-wide routes in the initial pilot (`full_scope` route policy).

**Human-only actions reject workspace keys and service accounts**, even if their subject has a governance delegation. Entra delegated sessions follow the existing production audience/issuer/scope/role/tenant policy. See the inherited production identity runbook; do not relabel a shared key as a human session to bypass approval. An API key can collect evidence only with an appropriate explicit principal delegation and collector signature.

For the reviewed remediation path, verifier must differ from proposer, implementer and change approver. The closing reviewer cannot be one of those execution participants. The risk acceptor must be the accountable business owner and differ from both the requester/technical owner and the security compensation reviewer. Delegation changes take effect server-side on the next decision; a stale UI cannot override them.

## Main remediation journey

1. A ComplianceReviewer publishes the control policy, owner and organization-specific scope/risk rationale. Mandatory designation defaults true. Once mandatory, an application policy revision cannot downgrade it to a discretionary exception.
2. A SecurityAnalyst selects an owned storage account from a completed scan and records application, environment, classification and named technical/business owners with rationale. Unknown context remains unknown. Repeated assessments deduplicate into the same resource/control finding while preserving assessment history.
3. The analyst creates a **separate business-risk record**, records inherent/residual risk and treatment plan, then triages the finding and deadline.
4. The assigned ResourceOwner drafts the exact target change, dependency checks, validation steps, rollback procedure and change reference. The target is fixed to the owned account with `allow_blob_public_access=false`. Human-readable plan steps are never executed as code.
5. A different ChangeApprover reviews a SHA-256-bound plan and current evidence. Approval expires after 24 hours. Revising the plan or changing an unimplemented policy/context invalidates approval. Revoked/expired change authority cannot approve an unused implementation.
6. Perform the separately approved infrastructure change through the organization's reviewed process. The outcome workflow itself has **no cloud-write connector**. Record implementation only after an authorized collector attests a successful provider event for the exact plan, following approval and within its validity. One event cannot implement two findings.
7. A ComplianceReviewer independently checks a fresh passing account observation plus signed health/legitimate-access results for the same plan and post-change scan. A technical pass by itself is insufficient.
8. Security/control review approves closure only while this independent verification and latest local configuration still support it. Closure records the narrow claim: configuration and legitimate access were verified, not that there was no previous exposure or that the organization is compliant.
9. Continuous monitoring reopens the finding on observed drift, unknown/stale evidence, expired verification, changed policy or invalid source evidence. A retired linked risk reopens when its finding drifts.

Completed authorized changes remain historical facts when their approver subsequently leaves. Historical delegation versions are retained for audit. Fresh independent verification is still required after evidence expires or policy/context review changes. A confirmed return of the prohibited configuration clears the active treatment and requires a new plan/approval cycle.

If a collector is revoked or its key changes, supported conclusions are withheld. A reviewed replacement collector can reattest **the same previously authorized event and event time**, then the owner records refreshed implementation evidence and obtains independent verification. This does not reexecute the change, broaden the target or substitute a different provider event. No uncertain cloud mutation is replayed.

## GitOps and agent links

Plan references can link an owned GitOps request from the same baseline scan and/or an agent task for the same owned resource. These are contextual links, not proof of a deployed fix. Verification continues to require the signed provider event and actual post-change checks.

Existing agent connectors do not gain a new public-access write capability in this release. Agent execution retains its separate verified-human approval, lease and per-step permit requirements. A governance approval never mints a worker permit, merges a pull request or authorizes arbitrary TypeScript/shell execution.

## Exceptions, corrected findings and incidents

Exception flow: **requested → independently reviewed → business-authorized → scheduled/active → expired, revoked or review required**.

- Only triaged discretionary failing controls can request acceptance. Mandatory obligations cannot be waived.
- The exact scope, current policy/risk versions, reviewed compensation evidence and role limits are rechecked at authorization.
- The inherent risk must fit the acceptor's explicit authority; residual score must fit control policy appetite. Duration must fit both policy and delegate limits, never more than 30 days.
- Start must be current/future, review before expiry, and risk-review coverage must extend through the exception. Only one accepted treatment owns a finding. A future approval is scheduled, not already active.
- Accepted risk remains a **failed control**. No exception turns a technical assessment into pass or certifies compliance.
- Expiry, changed risk/policy/scope, revoked authority or superseded/invalid compensation evidence reopens the finding. Renewal is a new request and review, not a silent extension. Review/expiry reminders are recorded in the dashboard; no email, Slack or incident-system message is sent.

False-positive/not-applicable requests preserve the original evidence and requester rationale. A different SecurityAnalyst needs fresh corrected evidence/context. **A newly passing configuration does not prove the original finding was false.** False-positive dismissal additionally requires a signed source correction explicitly refuting the frozen original scan/state digest. Unknown or failing evidence cannot be dismissed through an assertion alone. Not-applicable decisions remain that result, not pass.

Suspected compromise can be escalated with an incident-response reference. Normal remediation closure is blocked while incident escalation is active. A different analyst must record a linked incident-response clearance before normal treatment resumes. This is a local handoff record, not a complete SIEM, incident-response service or forensic conclusion.

## Signed evidence setup

Receipt ingestion is disabled by `CLOUDSAVER_GOVERNANCE_SOURCES=[]`. The software does not manufacture provider audit events, SLO results, compensation effectiveness or finance/legal authority. Deploy a reviewed attestor in the approved environment, with real access to its authoritative evidence sources.

Operator configuration example (substitute provisioned UUIDs):

```json
[{"tenant_id":"WORKSPACE_UUID","source_id":"security-attestor","providers":["azure"],"scope_ids":["SUBSCRIPTION_UUID"],"kinds":["implementation","verification","compensation","correction"],"key_env":"CLOUDSAVER_GOVERNANCE_KEY_PRIMARY"}]
```

Provide at least 32 random characters in `CLOUDSAVER_GOVERNANCE_KEY_PRIMARY` through the approved secret mechanism. In Compose, only **scanner-service (core)** and the dedicated **governance-monitor verifier** receive this secret. Browser, agent gateway, execution worker and other services do not. HMAC verification and signing use the same cryptographic secret: treat both verifier workloads as trusted secret holders. Custom key references require explicit secret mappings in both verifier deployments. The attestor separately holds its signing key; do not pass it through a user credential, plan, GitOps file, AI prompt or log.

`POST /api/v1/governance/evidence/receipts` requires a scoped delegated collection principal plus `X-Evidence-Signature`. HMAC-SHA256 covers UTF-8 Python-compatible `json.dumps(envelope, sort_keys=True, separators=(',', ':'), allow_nan=False)` bytes, including default ASCII escapes. Signature is lowercase hexadecimal. Envelope issuance must be no older than five minutes or more than 60 seconds ahead; source clocks must be synchronized. Underlying event/check times cannot be in the future.

Envelope: UUID `receipt_id`, UUID `tenant_id`, UUID `finding_id`, granted `source_id`, `kind`, offset-aware `issued_at`, and a strict structured `payload`. It is bound to the finding's tenant and provider scope through the operator grant. It is limited to 16 KB. Unknown fields, duplicate JSON keys, naive timestamps and untrusted booleans do not establish evidence. Retrying identical content/receipt ID is idempotent; conflicting content returns 409.

| Kind | Strict payload |
| --- | --- |
| implementation | Exact `plan_digest`, provider `event_id`, operation `disable_blob_public_access`, status `Succeeded`, offset-aware `occurred_at`. |
| verification | `plan_digest`, owned `scan_id`, exact assessment `state_digest`, `observed_at`, strict booleans `health_accepted` and `legitimate_access_accepted`, opaque `validation_reference`. |
| compensation | `observed_at`, `valid_until`, strict boolean `accepted`, opaque `evaluation_reference`, bounded `controls_summary`. Acceptance must cover the entire requested exception and be independently reviewed. |
| correction | Frozen `original_scan_id`, `original_state_digest`, `evaluated_at`, strict boolean `false_positive_supported`, opaque `refutation_reference`. A current passing account alone is not a historical refutation. |

Full contracts are in [governance_contracts.py](../app/governance_contracts.py). A collector can obtain the case, original state and exact plan digest through its delegated read path. Use opaque evidence/report references and policy summaries; never embed customer payloads, credentials or log bodies.

Accepted raw envelopes (strictly schema bounded), their normalized proof, signature, canonical fingerprint and source identity are retained for audit. Stored evidence is revalidated before reliance without treating its historical receipt as a new ingestion. New conflicting evidence supersedes earlier evidence for the plan. Removing a source grant, changing its key or tampering with its envelope/proof invalidates reliance; reviewed reattestation restores supported facts. Historical evidence is retained, not erased or rewritten.

HMAC establishes the authorized source and message binding, not the truth of the attestor's assertions. Authorized staging evidence and independent control-effectiveness review remain required before selling this capability as verified customer governance.

## Monitoring, exports and data governance

`governance-monitor` starts in development Compose and reassesses saved observations every 60 seconds. Outside Compose supervise `python -m workers.governance_monitor`. It makes no cloud, AI, notification or execution calls. Its tenant-scoped database updates share the existing transaction lock, and repeated unchanged checks do not append duplicate finding transitions. A heartbeat and counts are visible in the dashboard. This is not an accepted production monitoring SLA; alert routing and pager exercises remain launch gates.

`POST /api/v1/governance/monitor` allows an authorized human SecurityAnalyst to run the same saved-evidence assessment. GET reports and exports do not perform provider calls or change treatment state. If the worker is behind, the UI flags the saved-history boundary. Closure decisions always check current local evidence independently of the worker heartbeat.

`GET /api/v1/governance/findings/{id}/export` returns an authenticated tenant-scoped JSON package with original/current observations, pinned control versions and mappings, business context, risk, owners, plan, decisions, before/after evidence, exceptions, role-authority history and hash-linked audit events. It reports whether current verification is supported by the latest local observation and signed evidence separately from the recorded historical closure. A pending or expired case is not labeled approved compliance.

The runtime role cannot update/delete control revisions, grants, observations, receipts, event bindings or history. Exports verify event-chain continuity and provide SHA-256 content manifests. **A database owner can potentially rewrite an entire unkeyed chain and its manifest.** Retain a trusted package/hash anchor outside the mutable database under the organization's approved audit policy; these hashes are tamper evidence, not a digital signature, immutable storage service or legal attestation.

All new records stay in the configured core database and authenticated customer application responses. No AI inference, knowledge-base training, customer-payload collection or automatic external connector is introduced. Necessary user identifiers and bounded decision notes remain customer data. Include the new tables, verifier secrets and external audit anchors in backup/restore, retention, legal hold, erasure and offboarding review. No default append-only record period establishes a legally approved retention policy.

Pilot limits: 1,000 findings/record-view entries per workspace; 5,000 assessment rows per reporting view; up to 1,000 history/evidence entries per exported chain, 100 exceptions per finding export, 1,000 delegation revisions in the directory/audit view, and 1,000 candidate saved scans for latest-observation selection. Exceeding a complete-report bound raises an explicit error rather than quietly claiming complete coverage. Validate actual tenant scale and retention before expanding support.

## Acceptance and next scope

The first acceptance journey is implemented and regression-tested with synthetic data: observed issue → named owners/business risk → independent change approval → signed successful event → fresh passing configuration and legitimate-access evidence → independent verification → closure → drift reopening, with an explainable audit package. PostgreSQL RLS/append-only privileges and real HTTP dashboard/gateway/core paths are checked separately from intercepted UI fixtures.

This release does not certify a framework, populate a large control library, automatically infer customer data classification, investigate historical exposure, provide external incident response, implement a new cloud mutation connector, enforce a legally approved retention program, or establish production SLA/HA/recovery acceptance. Expand requirement mappings and controls only after the initial attestors, decisions and production-like acceptance evidence are trusted.

Design references: [NIST RMF](https://csrc.nist.gov/projects/risk-management/about-rmf), [SP 800-37 Rev. 2](https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-37r2.pdf), and [NIST CSF 2.0](https://nvlpubs.nist.gov/nistpubs/CSWP/NIST.CSWP.29.pdf). They inform the separation between implementation, assessment, risk authorization and monitoring; they are not evidence that CloudSaver satisfies those frameworks.
