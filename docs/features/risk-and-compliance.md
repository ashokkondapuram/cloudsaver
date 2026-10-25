# Risk and compliance

Risk and compliance is an accountable workflow that takes an observed Azure storage account from a technical control assessment to a reviewed treatment, independent verification and an exportable audit package. It supports one reviewed control, `AZ-STORAGE-PUBLIC-BLOB-ACCESS` ("Production customer-data storage must disallow public blob access"). Every decision is a local, hash-linked application record made by a named person with a delegated, time-limited governance role. Nothing in this workflow changes your cloud resources, contacts an external system or sends evidence to an AI model, and a closed finding never certifies organizational compliance.

Last reviewed against the code on Oct 25, 2026.

## Where to find it

- **Route:** `/governance` ([web-dashboard/app/governance/page.tsx](../../web-dashboard/app/governance/page.tsx) renders [GovernanceWorkspace.tsx](../../web-dashboard/components/governance/GovernanceWorkspace.tsx)).
- **Navigation label:** **Risk & compliance**, in the **ACT & GOVERN** group of the sidebar ([AppShell.tsx](../../web-dashboard/components/AppShell.tsx)).
- **Who can see it:** Every signed-in user sees the navigation entry. The page loads `GET /governance/capabilities` first:
  - If you have no active governance delegation and are not a `TenantAdmin`, you see **Governance access required** and nothing else.
  - If you hold at least one active governance role, or you are a `TenantAdmin`, you can read findings, risks, exceptions, controls and audit packages.
  - Forms and buttons appear only for the roles allowed to use them (see [Permissions](#permissions)).

The page has seven tabs: **Risk register**, **Findings**, **Controls**, **Exceptions**, **Approvals**, **Evidence** and **Audit exports**. Summary cards across the top show open material risks, overdue findings, expiring exceptions, unknown assessments, unassigned assessed resources and stale evidence.

## What you can do

### Set up governance (TenantAdmin)

1. Open **Controls** and expand **Delegate governance responsibilities**.
2. Enter a user or service ID (UUID), an alias, a governance role, an expiry (at most 90 days ahead), a maximum inherent score and maximum exception days within the delegate's authority, and a reviewed authority reference.
3. Select **Save delegated authority**. Each save creates a new immutable grant version. To revoke, clear **Delegation active** and save again.

Workspace administration does not grant risk acceptance or change approval. You must delegate those roles explicitly.

### Publish the control policy (ComplianceReviewer)

1. In **Controls**, expand **Review a new control-policy version**.
2. Choose the accountable control owner (who must hold an active `ComplianceReviewer` delegation), state whether the policy is a mandatory obligation, set the maximum accepted residual score (1–25) and the maximum exception days (1–30), and write the rationale.
3. Optionally add framework mappings as a JSON array of `framework`, `version`, `reference` and `rationale` records.
4. Select **Publish reviewed policy version**.

A mandatory obligation cannot be downgraded to discretionary by a later version. A new policy version invalidates existing verifications and, where nothing has been implemented, existing plans and approvals.

### Assess a storage account (SecurityAnalyst)

1. Select a completed scan in the workspace, then open **Findings** and expand **Assess an observed storage account**.
2. Choose an Azure storage account from the scan, then record the application, environment, data classification, technical owner (`ResourceOwner`), business risk owner (`BusinessRiskOwner`) and a business-context confirmation.
3. Select **Evaluate technical control**.

The result is `pass`, `fail`, `unknown` or `not_applicable`. A `fail` or `unknown` result creates an accountable finding in the `triage` state.

### Link a business risk and triage (SecurityAnalyst)

1. In **Risk register**, expand **Assess a business risk**, choose an unlinked finding and record the risk statement, treatment plan, inherent and residual likelihood and impact (1–5 each) and a review date within 90 days.
2. Open the finding and select **Validate triage and deadline**. Triage sets a due date from the severity policy.

### Remediate and close a finding

| Step | Who | Action in the finding drawer |
| --- | --- | --- |
| Propose | Technical owner (`ResourceOwner`) | Draft the exact change plan (change reference, steps, dependency checks, validation steps, rollback plan, optional GitOps request ID and agent task ID), then **Submit change plan**. |
| Approve | A different `ChangeApprover` | Confirm you reviewed the plan, then **Approve bound change plan**. Approval lasts 24 hours. |
| Implement | Technical owner | Choose a signed `implementation` receipt, then **Record signed implementation**. |
| Verify | `ComplianceReviewer` who did not propose, approve or implement | Choose a signed `verification` receipt, then **Independently verify the fix**. |
| Close | `SecurityAnalyst` or `ComplianceReviewer` who did not propose, approve or implement | **Approve verified closure**. |

You apply the fix yourself, outside CloudSaver, and a configured collector submits the signed receipts. Every decision requires a note of at least 10 characters.

### Request a time-limited exception

1. The technical owner opens **Exceptions** and expands **Request a time-limited exception**. Only triaged or reopened findings under a discretionary policy qualify.
2. Provide the justification, rejected alternatives, compensating controls, remediation plan, review trigger, a signed `compensation` receipt ID, and start, end and review times (UTC).
3. A separate `SecurityAnalyst` selects **Review compensating controls**.
4. The accountable `BusinessRiskOwner` selects **Authorize time-limited risk**. The finding moves to `accepted_risk`, or `exception_scheduled` if the start time is in the future. The underlying control stays failed.
5. A `SecurityAnalyst` or `BusinessRiskOwner` can reject or revoke an exception.

### Other workflows

- **Dismissal review:** The technical owner requests a false-positive or not-applicable review. A different `SecurityAnalyst` dismisses only with fresh evidence that matches the classification; a false positive also needs a signed `correction` receipt that refutes the original observation.
- **Incident handoff:** A `SecurityAnalyst` can escalate a finding to incident response with a reference. A different analyst records clearance, which reopens the finding for normal treatment.
- **Risk review and retirement:** The accountable `BusinessRiskOwner` can record a risk review (which sets the next review 30 days out) or retire a risk once all linked findings are closed or dismissed with fresh evidence.
- **Reassess:** A `SecurityAnalyst` can select **Reassess saved observations** to run the monitor on demand.
- **Export:** Select **Download audit package** in **Audit exports** or in a finding drawer.

## How it works

1. **Observation selection.** For each finding, [app/governance_api.py](../../app/governance_api.py) (`latest_observation`) picks the latest completed, non-synthetic, visible scan that contains the resource or covers its scope. If you pass an older scan ID, the request fails so that an older passing scan cannot hide newer evidence.
2. **Evaluation.** [app/governance_evidence.py](../../app/governance_evidence.py) (`evaluate`) reads the `allow_blob_public_access` flag from the saved observation and combines it with the human-reviewed context. Only production, customer-data storage accounts with an observed flag produce `pass` or `fail`. Observations older than 24 hours, incomplete scans and legacy synthetic scans produce `unknown`. Each result carries a state digest of configuration, context and control version.
3. **State machine.** [app/governance_store.py](../../app/governance_store.py) (`Governance`) enforces roles, separation of duties, optimistic versioning and transitions. Finding states include `triage`, `triaged`, `proposed`, `approved`, `implemented`, `verified`, `closed`, `reopened`, `dismissal_review`, `dismissed`, `accepted_risk`, `exception_scheduled` and `incident_escalated`.
4. **Signed evidence.** Collectors post envelopes to `/evidence/receipts` with an `X-Evidence-Signature` header. [governance_evidence.py](../../app/governance_evidence.py) (`receipt`) checks the tenant and finding binding, issuance freshness (60 seconds in the past to 5 minutes ahead), the collector grant and an HMAC-SHA256 signature over the canonical JSON. Payloads are validated against the `Implementation`, `Verification`, `Compensation` or `Correction` models in [app/governance_contracts.py](../../app/governance_contracts.py).
5. **Audit history.** Every change appends an event whose hash covers the previous event hash, and history reads re-verify the chain.
6. **Continuous monitoring.** The `governance-monitor` Compose service runs [workers/governance_monitor.py](../../workers/governance_monitor.py) about every 60 seconds. For each workspace it reassesses saved observations, reopens findings on drift, expired approvals, changed policy or revoked authority, and expires or flags exceptions. It records a status with `external_calls=0`, `external_notifications_sent=0` and `automatic_execution=False`.
7. **Gateway.** [services/governance_routes.py](../../services/governance_routes.py) registers fixed forwarding routes on the API gateway ([services/gateway.py](../../services/gateway.py)) to the scanner service, forwarding `X-Evidence-Signature` for receipts.

## API reference

All paths are served by the scanner service router (`/api/v1/governance`) and forwarded unchanged by the API gateway. Every route requires an authenticated workspace credential; gateway calls are also rate-limited per workspace. "Reader" means any active governance role or `TenantAdmin`. "Human" means a verified user session, not an API key or service account.

| Method | Path | Purpose | Required role/scope |
| --- | --- | --- | --- |
| GET | `/api/v1/governance/capabilities` | Your governance roles, human status and whether you can manage access | Any authenticated caller |
| GET | `/api/v1/governance/access` | Latest delegation per subject and role | Human `TenantAdmin` |
| PUT | `/api/v1/governance/access` | Create a new delegation version | Human `TenantAdmin` |
| GET | `/api/v1/governance/directory` | Active delegates and their roles | Reader |
| GET | `/api/v1/governance/controls` | Current control policy and supported control key | Reader |
| POST | `/api/v1/governance/controls` | Publish a new control-policy version | Human `ComplianceReviewer` |
| POST | `/api/v1/governance/assessments` | Evaluate a storage account from an owned scan | Human `SecurityAnalyst`; resource must be in your authorized scope |
| GET | `/api/v1/governance/summary` | Dashboard counts, assessment results and monitor status | Reader |
| GET | `/api/v1/governance/findings` | List visible findings | Reader |
| GET | `/api/v1/governance/findings/{finding_id}` | Finding detail, event history, receipts and freshness | Reader |
| POST | `/api/v1/governance/findings/{finding_id}/actions` | Apply an action (`triage`, `propose`, `approve`, `implement`, `verify`, `close`, `request_dismissal`, `dismiss`, `incident`, `resume`, `note`) | Human; role depends on the action (see [Permissions](#permissions)) |
| GET | `/api/v1/governance/findings/{finding_id}/export` | Download the audit package as JSON | Reader |
| GET | `/api/v1/governance/risks` | List business risks | Reader |
| POST | `/api/v1/governance/risks` | Create a business risk linked to findings | Human `SecurityAnalyst` |
| POST | `/api/v1/governance/risks/{risk_id}/actions` | `review` or `retire` a risk | Human `BusinessRiskOwner` who owns the risk |
| GET | `/api/v1/governance/exceptions` | List exceptions | Reader |
| POST | `/api/v1/governance/exceptions` | Request an exception | Human `ResourceOwner` who is the technical owner |
| POST | `/api/v1/governance/exceptions/{exception_id}/actions` | `review`, `approve`, `reject` or `revoke` an exception | Human; `SecurityAnalyst` reviews, `BusinessRiskOwner` approves, either can reject or revoke |
| POST | `/api/v1/governance/evidence/receipts` | Submit a signed collector receipt | `AutomationIdentity`, `ResourceOwner`, `SecurityAnalyst` or `ComplianceReviewer` (human session not required); valid `X-Evidence-Signature` |
| POST | `/api/v1/governance/monitor` | Reassess saved observations now | Human `SecurityAnalyst` |

Errors map consistently: 403 for missing authority, 404 for records outside your workspace or scope, 409 for state or version conflicts, and 422 for invalid fields.

## Data and evidence

Records live in ten tenant-scoped tables defined in [app/governance_schema.py](../../app/governance_schema.py) for development SQLite; production uses the reviewed forced row-level-security migration [migrations/versions/0023_risk_governance.py](../../migrations/versions/0023_risk_governance.py).

| Table | Contents | Mutability |
| --- | --- | --- |
| `gov_controls` | Control-policy versions | Append-only |
| `gov_grants` | Delegation versions | Append-only |
| `gov_findings` | One finding per tenant, provider, scope, resource and control | Versioned updates |
| `gov_risks` | Business risks | Versioned updates |
| `gov_exceptions` | Exception requests and decisions | Versioned updates |
| `gov_assessments` | Every technical assessment | Append-only |
| `gov_receipts` | Signed collector envelopes, signatures and normalized proof | Append-only |
| `gov_actions` | Provider event keys, so one event cannot implement two findings | Append-only |
| `gov_events` | Hash-linked decision history | Append-only |
| `gov_monitor` | Latest monitor status per tenant | Upserted |

The audit package (`format: cloudsaver-governance-audit-v1`) contains the finding and its history, all assessments, all receipts with envelopes and signatures, the linked risk and its history, exceptions with history, control history, and the delegation history of every actor involved. It includes a SHA-256 manifest per section, `currently_fresh` and `current_verification_supported` flags, and a warning that hash links need an independently retained trusted anchor.

Scores are likelihood times impact (1–25). A risk is material when its inherent score is 12 or more. Linked findings get a severity of critical (20 or more), high (12 or more), medium (6 or more) or low, with triage deadlines of 1, 7, 30 or 90 days respectively.

## Permissions

Governance roles are defined in [app/governance_contracts.py](../../app/governance_contracts.py) and are separate from workspace roles.

| Role | Can do |
| --- | --- |
| `TenantAdmin` (workspace role) | Read governance records; manage delegations (human session only). Cannot make governance decisions without a delegated role. |
| `ResourceOwner` | Propose plans, record implementation, request exceptions and dismissal reviews, but only for findings where you are the named technical owner. |
| `SecurityAnalyst` | Assess resources, create risks, triage, dismiss, escalate and clear incidents, review exceptions, close verified findings, run the monitor. |
| `ChangeApprover` | Approve a proposed plan you did not propose. |
| `BusinessRiskOwner` | Review and retire risks you own within your `maximum_score`; authorize exceptions within your `maximum_exception_days` and the policy risk appetite. |
| `ComplianceReviewer` | Publish control policies; independently verify fixes; close verified findings. |
| `AutomationIdentity` | Submit signed evidence receipts only. |

Separation-of-duties rules enforced by the store:

- The approver must differ from the proposer.
- The verifier and the closer must differ from the proposer, approver and implementer.
- An exception reviewer must differ from the requester and the business owner, and the approver must be the accountable business owner and differ from the requester, reviewer and technical owner.
- Dismissal and incident clearance must be recorded by a different analyst than the one who requested or escalated.
- API keys and service accounts can submit evidence but cannot approve, verify, accept risk or close findings.

## Configuration

| Variable | Purpose | Default |
| --- | --- | --- |
| `CLOUDSAVER_GOVERNANCE_SOURCES` | JSON array of collector grants. Each entry has exactly `tenant_id`, `source_id`, `providers` (must be `["azure"]`), `scope_ids` (1–100), `kinds` (any of `implementation`, `verification`, `compensation`, `correction`) and `key_env`. At most 100 entries. | `[]` (no collectors) |
| `CLOUDSAVER_GOVERNANCE_KEY_*` | Per-collector HMAC signing secret named by `key_env` (for example `CLOUDSAVER_GOVERNANCE_KEY_PRIMARY` in [compose.yaml](../../compose.yaml)). Must be at least 32 characters. Store it in a secrets manager. | Unset |

The `governance-monitor` service uses the standard database and tenant settings loaded by `Settings.load()` in [app/config.py](../../app/config.py).

## Guardrails and limitations

- **One control.** Only `AZ-STORAGE-PUBLIC-BLOB-ACCESS` on Azure `microsoft.storage/storageaccounts` is supported. Other providers are rejected.
- **No compliance claim.** The summary always returns `compliance_score: null`. An account-level flag does not prove a container is public or that data was exposed.
- **Freshness windows.** Assessments are fresh for 24 hours. Change approvals expire after 24 hours. Verification receipts must be observed within one hour of verifying, and closure must happen within 24 hours of verification.
- **Bounded data.** Each workspace is limited to 1,000 findings, 1,000 history events per record, and 5,000 assessments for reporting. Receipts over 16,000 bytes are rejected.
- **Exceptions never waive mandatory obligations**, and they require compensating evidence valid for the full exception window. A renewal is a new request.
- **Plan links do not authorize execution.** A linked GitOps request must belong to the finding's baseline scan, and a linked agent task must bind the same resource. Those systems keep their own approvals.
- **Reminders are dashboard-only.** The monitor records review reminders but sends no external notifications.
- **Monitoring lag.** The dashboard warns when the last monitor check is more than two minutes old.

## Tests

- [tests/test_governance_workflows.py](../../tests/test_governance_workflows.py) — end-to-end governance lifecycle, separation of duties and evidence rules.
- [tests/test_scoped_governance_outcomes.py](../../tests/test_scoped_governance_outcomes.py) — scope-restricted visibility for governance records.
- [tests/test_compose.py](../../tests/test_compose.py) — Compose wiring, including the `governance-monitor` service.
- [tests/governance_http_fixture.py](../../tests/governance_http_fixture.py) — shared HTTP fixture for governance tests.
- [web-dashboard/e2e/governance.spec.ts](../../web-dashboard/e2e/governance.spec.ts) — browser coverage of the Risk & compliance workspace.

## Related docs

- [Risk and compliance workflow](../RISK_AND_COMPLIANCE.md)
- [Financial outcomes](../FINANCIAL_OUTCOMES.md)
- [GitOps and pre-merge guardrails](../GITOPS.md)
- [Agentic worker](../AGENTIC_WORKER.md)
- [AI data governance](../AI_DATA_GOVERNANCE.md)
- [Environment variables](../ENVIRONMENT.md)
