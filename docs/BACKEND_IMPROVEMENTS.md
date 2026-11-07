# CloudSaver backend improvements README

Source: ashokkondapuram/cloudsaver (main, inspected Nov 2026). This is a backend-only record of what the code actually does. UI copy, theme, and layout are out of scope. Published feature guides are dated around Oct 25, 2026 (39def45); the tree now also includes later migrations through core 0038_code_mode_runs and identity i0016_workspace_ui_themes. The 1.8.1 upgrade note still names heads 0033 and i0013. Treat those pins as the last tagged runbook, not the full tree.

Discovery stays read-only. An AI suggestion, a GitOps draft, a Bash review script, a Kubernetes patch preview, and an engineering plan never authorize a cloud change by themselves.

---

## Cross-cutting backend changes

These apply to every feature below.

| Change | What improved | Where |
| --- | --- | --- |
| Split process model | Core API (app.main, port 8002), authenticated edge (services/gateway.py, 8000), isolated agent gateway (services/agent_gateway.py, 8006), platform identity (internal only) | services/, platform/ |
| Forced tenant isolation | Transaction-local app.current_tenant_id, forced RLS, runtime role cloudsaver_app must not own tables or bypass RLS | app/enterprise_store.py, database/connection.py, migration 0009 onward |
| Scoped keys | Every /api/v1 route is classified. Restricted keys see only their providers and scopes. Unclassified routes fail closed | app/route_inventory.py, app/provider_access.py, app/data_scope.py |
| Fail closed on identity lag | Revoked keys 401, suspended workspace 403, identity outage 503, stale directory projection 503. Cache is disabled while the event poller is down | app/identity_client.py, app/auth.py |
| Money as decimals | FOCUS charges, commitment math, and outcomes reject floats, booleans, and scientific notation. Amounts are NUMERIC-style decimal strings | app/focus.py, app/commitment_arbitrage.py |
| Unknown stays unknown | Missing telemetry, price, dependency, or billing coverage is insufficient_evidence / null, never a zero or a pass | assessment, rules, pricing, Kubernetes |
| Async work is leased | Scan jobs, delivery, billing sync, AI batches, GitOps publish, and the platform outbox use idempotency keys, leases, and fences. Lost leases do not commit | workers/, migration 0033 |
| Three-tier route parity | Scanner, gateway, and dashboard BFF must match ROUTES. Contract items BC-01–BC-14 are marked done | docs/ENTERPRISE_BACKEND_PROGRAM.md |
| 1.8.0 reliability fixes | Foreign failed_scopes dropped for provider-restricted scans; drift batches over 100 events rejected with 422; outbox complete/fail is fenced; Redis skip releases the DB claim; non-finite JSON numbers rejected; overflowing telemetry integers do not crash evaluation; Azure ARM continuation hosts are validated | docs/BACKEND_RELIABILITY_GUIDE.md |

Plan limits come from the platform entitlement projection (0013_billing_projection). CloudSaver’s own Stripe checkout and webhook return 410. Stripe lives only in identity-service.

---

## 1. Overview (review queue, trends, commitment ceiling)

**Before:** a single scan total, mixed history, and a gross waste number that could be read as a reservation to buy.

**Backend improvement**

- One assessment per resource is built on read, not stored as a second source of truth (app/resource_assessment.py).
- Trends compare only completed scans with the same mode, provider set, and scope_fingerprint. Older scans without a fingerprint are shown alone and never diffed. Finding identity is provider + rule + resource id (Azure ids lowercased). Window is the latest 100 scans (app/trends.py).
- Opportunity totals take the largest alternative in an opportunity_group_id. An unknown alternative keeps the group unknown (app/pricing.py).
- The hourly commitment ceiling runs only when the saved scan already has commitment_evidence with source_verified and commitment_coverage_verified, aligned USD/hour series, and existing coverage. Cleanup is subtracted hour by hour; nearest-rank P10 over 30–90 days becomes calculate_clean_commitment_baseline. Otherwise the status is insufficient_evidence. purchase_authorized is always false (app/commitment_arbitrage.py).
- GET /api/v1/analytics is a latest-snapshot summary only. It never sums history.

**Not claimed:** the current scan pipeline does not write commitment_evidence, so a normal scan shows the ceiling as Unknown. “Resolved” does not prove deletion or savings.

---

## 2. Resources (one record, five pillars, decisions, export)

**Before:** findings listed separately from inventory, with no stable identity, no digest, and no separation of billed vs retail cost.

**Backend improvement**

- resource_key is SHA-256 of provider + resource id. Findings merge into one row; each check keeps its worst status. Inventory with no finding is inventory_only and uses the canonical observation, not a stripped fake row (app/resource_assessment.py).
- Five-pillar assessment uses saved evidence only. Missing checks are unknown, never a pass. Public databases, disabled encryption, admin ingress, and snapshot exposure are critical (app/assessment.py, app/assessment_policy.py, app/pillar_checks.py). Policy version is 2026-10-23.1.
- evidence_digest fingerprints sanitized evidence and ignores wall-clock time, so decisions and AI go stale when evidence changes (409 until refresh).
- Lifecycle compares the previous completed live scan with the same scope_fingerprint: new, persisting, regressed.
- FOCUS attach sums exact resource-level USD over 30 days ending at the scan date. Account totals are never spread across resources. commitment_locked when a Purchase exists or effective cost exceeds billed cost (app/focus.py).
- PostgreSQL stores full finding evidence on waste_findings (app/waste_finding_evidence.py). Scoped keys recompute coverage / coverage_manifest for the visible subset; partial and clean_baseline are not hard-coded optimism.
- Billable-first lists: cost_scope=billable is the default. GET /api/v1/resources/billable-catalog returns 36 metered families and explicitly free topology types (app/billable_resources.py). arm_detail filters list and export (collected, unsupported_type, resource_budget_exceeded, api_version_unresolved, fetch_failed).
- Decisions are append-only (accept / dismiss / defer) with a hashed actor, not a name. CSV formula cells (=, +, -, @) are neutralized.
- Only completed live scans are analyzable. Synthetic snapshots return 409.
- Protected findings add NO_DESTRUCTIVE_RECOMMENDATION. Observations older than 24 hours add REFRESH_OBSERVATION.

**Tables:** scan payload (scans), waste_findings, resource_decisions (migration 0010), focus_charges.

**Not claimed:** realizable_savings_usd, modeled_future_cost_usd, and verified_realized_savings_usd stay empty on the resource row. A decision does not change the cloud.

---

## 3. Workload assessments

**Backend improvement:** none on the server. /workloads is a browser join of GET /api/v1/outcomes/ownership and paged resource assessments. Membership is exact provider + scope + resource id. Names and tags are not used. Conflicting equal-version mappings stay unassigned. Every preview is executable: false, approval_granted: false, target_sku: null.

The ownership write that feeds this page is the outcomes feature (finops_ownership, versioned, basis: current_direct_resource_mapping).

---

## 4. Services

**Before:** one flat findings table.

**Backend improvement**

- GET /api/v1/services/{service} matches eight families by resource-type regex (disks, VMs, public IPs, App Service plans, databases, load balancers, object storage, AI endpoints). Unknown family is 404 at the gateway before the upstream call (app/v150_analysis.py).
- Each family returns at most 1,000 merged assessments with FOCUS billed USD attached at read time and the scan’s retail estimate kept separate.
- GET /api/v1/scans/{scan_id}/analysis summarizes by provider and category, dedupes retail with opportunity_totals, and caps the review queue at 50. full_inventory is always false because only resources with findings are included.
- POST .../analysis/resource returns the five-pillar result and the sanitized AI context for one finding without calling a model.

---

## 5. Kubernetes and containers

**Before:** optional Prometheus-only CPU/memory oversize checks with no inventory proof.

**Backend improvement**

- Two modes. With a tenant-bound entry in CLOUDSAVER_KUBERNETES_BINDINGS, federation reads the Kubernetes API, Prometheus, and optional OpenCost. Without a binding, metrics-only mode cannot claim cluster coverage (inventory_basis: metrics_visible_containers).
- API inventory pages 16 read-only kinds, 20,000 objects, identity and continuation checks. Pods, Nodes, or Namespaces failing fails the scan and saves nothing. Other kind failures become unavailable sources (app/collectors/kubernetes.py, app/collectors/federation.py).
- Prometheus: 12 range queries, 30 days, 5-minute step, backends prometheus_http, azure_amp, aws_amp_sigv4, gcp_gmp. Series must pass app/telemetry_contract.py. Gaps are not filled. Three consecutive failures open source_circuit_open_for_scan.
- Projection keeps an allowlisted inventory. Commands, env values, and Secret data are not stored (app/kubernetes_topology.py).
- OpenCost allocations stay basis: opencost_allocation_estimate. Idle and shared cost are not pushed onto workloads. Node billed cost is copied from the backing VM only when FOCUS coverage for that machine is complete (app/k8s_cost_reconciler.py).
- Ten rule contracts, version kubernetes-2026-10-24.1 (app/kubernetes_rules.py). Outcomes include insufficient_evidence for stale windows, workloads younger than 30 days, or missing fields. automatic_execution is false. Savings on the reliability rule is 0, otherwise null.
- Conflicting source digests mark resources source_conflict and clear cost attribution (app/collectors/provenance.py).
- Patch preview (POST .../kubernetes/patch-preview) returns 409 unless every replica independently passes the rule, the controller identity matches, desired replicas equal observed pods, the digest matches, and evaluate_slo_bounded_rightsizing is review_eligible. Response is a strategic merge patch plus kubectl dry-run commands. No cluster write.

**Saved-scan SLO packet:** when Prometheus CPU and throttling matrices are sufficient, `app/kubernetes_slo_evidence.py` attaches `slo_evidence` on each container (CPU series from the scan window; latency uses a decoupled low-latency proxy series until an optional latency query is wired). Patch preview still requires every replica to pass `evaluate_slo_bounded_rightsizing`. Cluster P95 is never summed from container percentiles; modeled node consolidation stays Unknown without node-pool evidence.

### 5b. Grafana / Mimir live rightsizing (advisory, separate route)

**Implemented** on main (not part of the scan ledger):

- API: GET/POST /api/v1/kubernetes/grafana/* (app/kubernetes_grafana_api.py); registered on gateway and route inventory.
- Connectors: kind grafana_mimir in observability_connectors (migration 0025); validated in app/collectors/observability.py; create via /api/v1/observability/connectors or kubernetes mirror routes.
- Query path: Grafana HTTP API → Mimir; tokens via CLOUDSAVER_OBSERVABILITY_SECRET_* on the scanner only (browser never holds tokens).
- Policy: grafana-k8s-rightsizing-v2 (app/collectors/grafana_k8s_policy.py, app/collectors/grafana_rightsizing.py): workload ownership from kube-state metrics, HPA/throttle/OOM safety blocks aligned with app/kubernetes_rules.py, P95×1.5 CPU and P99×1.35 memory gates, safety_blocks[], patch_eligible (advisory).
- app/observability_store.py excludes grafana_mimir from the generic sync worker; rightsizing is on-demand only.
- UI: Settings → Observability (Grafana Mimir); Kubernetes → Live rightsizing (Grafana). Spec: specs/drafts/2026-11-07-kubernetes-grafana-rightsizing.md.

**Not claimed:** no cluster write, no patch YAML apply, no substitute for saved-scan patch preview or federation evidence.

---

## 6. AI assessments and data governance

**Before:** optional direct SDK calls with Redis budgets and no durable outcome.

**Backend improvement**

- AI is off until all of these are true: CLOUDSAVER_AI_ENABLED, an operator target, a valid platform policy, a current processor approval, a plan that allows advisory, and a workspace setting. A missing policy is 503, not a permissive fallback (app/ai_platform_policy.py).
- Routing is same_cloud_only. Kubernetes sources are excluded. Bindings must match an approved target exactly (app/foundry.py).
- Context is allowlisted. Names, raw ids, tags, billed amounts, and free-text narratives are not sent. Secrets, emails, ARNs, and IPs are redacted. A 60-second processing grant is recorded in ai_data_events (app/data_governance.py).
- Adapters: Azure OpenAI / AI Foundry chat completions, Bedrock converse, Vertex generateContent. Temperature 0, JSON only. Tool calls and incomplete finishes are rejected (app/ai_advisory.py).
- Durable ledger: idempotent ai_inference_attempts (pending / completed / uncertain), hourly attempt budget, monthly token reservation, provider-reported usage. billed_cost_available is false. Uncertain attempts are not replayed (app/inference_ledger.py).
- Batches: 1–500 resources, one active batch per scan, Celery tick under a Redis lock. Evidence changes skip the item. Stuck items become uncertain after 15 minutes. Budget exhaustion pauses the batch (app/resource_batches.py).
- Follow-ups: 5 per resource per scan, current digest required.
- Connection test is metadata only, 3 per minute, and does not invoke a model (app/foundry_diagnostics.py).
- Retention 1–30 days (default 7). Legal holds expire within 30 days and block purge. Erase and hold require a human TenantAdmin, not a key (workers/data_retention.py).
- Every response sets advisory_only: true, automatic_execution: false, and semantic_claims_verified: false.

**Tables:** ai_inference_attempts, ai_inference_events (0009), batches (0010), diagnostics (0015), governance (0018).

---

## 7. Optimization evidence (topology, SLO, network, commitment)

**Backend improvement:** GET /api/v1/optimization/scans/{scan_id}/auto-scenarios extracts only fields already on the scan, capped at 1,000 items (app/v150_analysis.py).

- Topology edges must have both ends in the scan. inventory_complete and blast_radius_verified stay false.
- SLO burn rates are reported with change_authorized: false.
- Network bytes are reported with savings_usd: null.
- Commitment math is the same clean-before-commit path as Overview, and is dropped entirely when the scan was filtered for a scoped key.

The stronger engines exist and are tested but are not API routes: simulate_cascading_topology_savings, analyze_cross_az_and_nat_hairpin_waste, analyze_ephemeral_batch_waste (app/causal_topology_simulator.py), plus compute_clean_before_commit_plan and simulate_topology_blast_radius (app/nextgen_engines.py). evaluate_slo_bounded_rightsizing is wired as a gate for Kubernetes patches and multi-cloud rule materialization, not as a savings number on this page.

No collector currently writes commitment_evidence, verified_dependencies, slo_burn_rate, or the network fields, so a normal scan reports insufficient_evidence for all four engines.

---

## 8. Cost allocation and billing

**Before:** manual uploads and demo rates, and Stripe inside CloudSaver.

**Backend improvement**

- Strict FOCUS subset import: up to 5,000 records, decimal strings (15 integer / 8 fractional digits), charge categories Usage, Purchase, Tax, Credit, Adjustment. Same source_id with the same body is a cache hit; a different body is 409. Charge fingerprint is (BillingAccountId, x_ChargeId); a conflict rejects the whole import (app/focus.py).
- Scope check: sub-account must belong to the workspace and the key, and every ResourceId must belong to that account.
- Summary keeps currencies separate. ESR only when every row has list cost. Forecast only for a month-to-date window with every closed day complete. Z-score is a 30-day nonseasonal population score, flagged at 3, not a diagnosed anomaly.
- Automatic sync (POST /api/v1/finops/sync) returns 202. One active job, at most 8 scopes, 30-day window ending two days ago, UUID idempotency key. Worker holds a Postgres advisory lock, 10-minute per-scope lease, 6-hour job expiry. Provider reads happen outside the lock; commit re-checks lease, cancellation, and authorization (app/billing_jobs.py, workers/billing_sync.py).
- Readers: Azure Cost Management actual and amortized (resource grain); AWS Cost Explorer account grain, or Athena CUR 2.0 resource grain when configured; GCP BigQuery standard (project) or detailed (resource.global_name). Cap 20,000 rows. Errors are stored only as fixed codes, never provider text.
- Corrections are append-only deltas. Missing groups become unresolved_absent_groups, not zeros. Auto imports are complete: false.
- Commitment snapshots are best-effort and append-only (cloud_commitment_snapshots, migration 0024). A commitment read failure does not fail the cost import. Purchases, exchanges, and renewals are out of scope (app/collectors/commitments.py).
- Unit economics (GET /api/v1/finops/unit-economics/preview) is advisory decimal math. Zero prior cost or unchanged volume is 422, not an invented ratio (app/unit_economics.py).
- POST /api/v1/finops/saas-focus/import is on the BFF allowlist (BC-13) and lands in saas_focus_billing_records (migration 0030).

**Not claimed:** billing_reconciled is false. Completeness of a manual import is the operator’s declaration. AWS/GCP without detailed exports do not invent per-resource rows. The account breakdown is not chargeback.

---

## 9. Savings and investigations

**Before:** a single “estimated savings” figure with no proof chain.

**Backend improvement — three measures that are never substituted for each other** (app/outcome_store.py, app/outcome_evidence.py, migration 0022):

1. Estimated opportunity — largest USD retail estimate on the resource’s findings at case open.
2. Validated run-rate — demand-normalized recurring cost, only after signed audit, health, and billing receipts and a fresh post-change scan.
3. Reconciled financial benefit — billed cost over matched windows, only with provider reconciliation, credits, an invoice reference, and a local ledger digest match.

Verification stops at the first missing requirement (action must follow saved human approval, 30 closed days each side, demand ratio between 0.25 and 4, configuration digest match, and so on). Results may be negative.

Receipts are HMAC-SHA256 over canonical JSON, one collector grant, ± freshness window, body ≤ 16 KB. Re-posting the same receipt_id is idempotent. One provider event_id can fund one case. Overlapping claims for the same resource and currency are 409. Opening a case re-checks grants and the ledger; changed evidence marks the claim not current and drops it from the supported total.

Investigations (daily-same-weekday-median-v1 in app/outcome_anomalies.py): at least three of four prior same weekdays, threshold is the max of 5 currency units, 20% of the baseline, or 3× MAD. At most 200 candidates. Corrected billing reopens a resolved case or moves a case that no longer breaches to review_required. A planned exception (≤ 30 days, not in the past) only suppresses the workflow; charges stay visible.

Ownership mappings are versioned, direct, and have no shared-cost split. They are what workload assessments read.

Cases are capped at 1,000 per workspace. Create is idempotent on request_key.

---

## 10. Risk and compliance

**Backend improvement:** a separate governance role model, not workspace roles reused as approvers (app/governance_store.py, migration 0023).

- One implemented control: AZ-STORAGE-PUBLIC-BLOB-ACCESS on Azure storage accounts. Other providers are rejected. compliance_score is always null.
- Latest completed non-synthetic observation wins. An older scan id cannot hide newer evidence.
- Only production, customer-data accounts with an observed public-access flag produce pass/fail. Everything else is unknown.
- State machine with optimistic versions. Separation of duties is enforced in the store: approver ≠ proposer; verifier and closer ≠ proposer, approver, and implementer; exception approver is the business owner and differs from requester and reviewer; API keys cannot approve, verify, accept risk, or close.
- Hash-linked gov_events. Signed collector receipts (implementation, verification, compensation, correction). One provider event cannot implement two findings (gov_actions).
- governance-monitor reassesses saved observations about every 60 seconds, reopens on drift, expired approval, policy change, or revoked authority, and records automatic_execution=false and external_calls=0.
- Audit export is cloudsaver-governance-audit-v1 with per-section SHA-256. The chain still needs an external trust anchor.
- A later Merkle table tamper_evident_audit_chain exists from migration 0031 alongside resource_carbon_metrics (GreenOps). Those tables are tenant-isolated; they do not replace the governance hash chain or certify emissions.

Plan and agent links do not authorize execution. Those systems keep their own approvals.

---

## 11. Agent worker

**Before:** no bounded execution path; model output could be mistaken for an action.

**Backend improvement**

- Separate gateway and a TypeScript worker. Numeric ctx.call(index) only. No MCP, shell, arbitrary HTTP, or model-authored code (agent-worker/, app/agent_contract.py).
- Task create checks: execution enabled, scan completed and < 24 hours old, resource in scan, connector bound to workspace and scope, data-governance grant (app/agent_store.py, migration 0017).
- Planner sends only instruction, resource type, and connector metadata. Plan is 1–8 steps, at most one write, and that write must follow an inspection on the same connector. Generic http_json is blocked.
- program_hash covers task, resource, plan, rendered program, and connector bindings. Human approval (verified session, not an API key) binds that hash and an expiry. Any plan or connector change invalidates it.
- Step permits are single-use, in order, lease-fenced (120 seconds, heartbeat 20 seconds, 15-minute cap). Writes recheck the live digest (LIVE_STATE_CHANGED / LIVE_RESOURCE_STATE_DRIFTED). Worker HTTP: 45-second timeout, no redirects, 1 MB cap.
- Lost lease after a possible write becomes needs_reconciliation and is not retried. Tasks with attempted writes cannot be redrafted.
- Kill switch CLOUDSAVER_AGENT_ENABLED defaults off. 100 new tasks per workspace per rolling day.
- 1.8.1: catalog rule ids route to a workflow channel (app/agent_workflow_routing.py): FinOps autopilot resize, engineering review plan, Kubernetes patch, Bash review, Terraform import, or manual only. Expected-state guard runs before a step permit (BC-05).

Paired GitOps is a server-side step. The worker only relays the outcome.

---

## 12. Automation and GitOps (pre-merge firewall)

**Backend improvement**

- Bash export is review-only and Azure-only. It never shells out. Protected findings are refused. The script requires a typed resource id, re-reads live tags, and for disks requires a successful managed snapshot and a post-snapshot attachment check, with a 90-day retention instruction (app/remediation.py).
- Terraform export is import-only HCL. No delete, no apply, no guessed configuration. One provider alias per subscription (Azure) or per file (AWS/GCP). Kubernetes is rejected (app/remediation_terraform.py).
- Review packages are deterministic: UUIDv5 from scan, resources, repo, base branch, and Terraform hash. Files are imports.tf, README.md, manifest.json with automatic_deletion: false (app/gitops.py).
- Publish commits the intent first, then a 10-minute publisher lease. GitHub App token is installation-scoped to one repo, contents and pull_requests only. Pull requests are drafts with maintainer_can_modify: false. A branch with different content stops for manual review. Uncertain GitHub responses are not replayed as success. At most four attempts (app/gitops_store.py, migration 0006, forced RLS required at startup).
- POST /api/v1/policies/terraform/evaluate is the pre-merge firewall (app/plan_policy.py): plan format 1.0–1.2, 2 MB, duplicate keys and non-finite numbers rejected. Codes include DESTRUCTIVE_CHANGE, REQUIRED_TAGS, ORPHAN_RESOURCE, COST_BUDGET_EXCEEDED, COST_EVIDENCE_REQUIRED, and CLEAN_BASELINE_APPROVAL_REQUIRED for commitment or provisioned AI capacity changes.
- Agent sync publishes one approved tag/label/annotation merge as Terraform JSON. Journal agent_gitops_syncs records parity_verified: false (migrations 0020, 0028).
- Resource mapping is no longer env JSON only. Migration 0029 adds gitops_ast_*. Optional GitHub App indexing at branch SHA (app/gitops_terraform_ast_indexer.py, app/gitops_github_ast_indexer.py, app/gitops_crossplane_indexer.py). Lookup 404s the same way for foreign, unobserved, and ungranted resources. patch_preview for non-Terraform kinds still raises NotImplementedError and is not the public API.
- BC-14 exposes pull-request, pre-merge evaluate, AST sync, and index-repositories through the BFF.

Publishing stays off unless CLOUDSAVER_GITOPS_PUBLISH=true. CloudSaver never runs Terraform and never merges.

---

## 13. Activity and delivery

**Backend improvement:** transactional outbox instead of fire-and-forget webhooks (database/delivery.py, migration 0007, workers/dispatcher.py).

- Scan job and notification intent commit in the same transaction as the job.
- Dispatcher claims with FOR UPDATE SKIP LOCKED and a 60-second lease, reconciles published scan events against scan_jobs, and dead-letters at eight attempts.
- Backoff is bounded. 429 honors Retry-After (1–3600s). Other 4xx dead-letters. Target fingerprint change or revoked scope dead-letters. Manual replay is only for dead-letter notifications, fewer than three replays, and requires acknowledge_duplicate_risk.
- Destinations are operator config or saved workspace webhooks. Callers cannot pass a URL. Only Slack hook hosts and Teams / Power Platform webhook hosts are accepted. Response bodies are not read.
- API responses omit destination URL, payload, and lease token. Audit actors are principal:.
- “Acknowledged” means the webhook returned 2xx, not that a person read it.

Delivery, scheduled scans, and interactive jobs are off until their flags are set. PostgreSQL is required; otherwise reliability reports available: false.

---

## 14. Settings (scopes, rules, AI, plan)

**Backend improvement**

- WorkspaceSettings is strict (extra=forbid) and requires version. Stale writes return 409 (app/settings_api.py).
- Directory cutover makes workspace configuration read-only in CloudSaver; identity-service is the source of truth.
- Rule changes are previewed by re-evaluating the latest saved scan. No live cloud call. The new policy applies only to the next scan. Historical scans keep the policy they were evaluated with (app/effective_rules.py). Identity holds the published catalog (migrations i0010–i0014, including canonical rule ids).
- Access test is a short read-only probe, 3 per minute per workspace (app/access_probe.py).
- Schedule is manual, daily, or hourly, capped by the plan. Webhook URLs are write-only.
- Plan change is a request to identity (i0004, one pending request). CloudSaver does not charge the card.
- Identity overrides for Azure app client id or GCP service account are workspace settings, not a new consent flow. GET /api/v1/auth/consent-url still returns 501.

---

## 15. Onboarding and access

**Backend improvement**

- Platform issues the onboarding key. POST /api/v1/onboarding/claim exchanges it for an owner and a one-time personal key via identity POST /customer/v1/claim.
- Customer admin API is proxied, not reimplemented: invite, suspend (revokes keys), reactivate, ownership transfer, members, service accounts, key issue/revoke/rotate (0–168 hour overlap), audit, access-review CSV (app/onboarding_api.py).
- Key modes: local digest (all three roles, no provider restriction), identity verify (grant is authoritative), shadow (local wins, mismatches logged).
- Entra mode: RS256, v2.0 issuer, audience, access_as_user, and at least one of TenantAdmin, BillingAdmin, Viewer.
- Grant cache 0–30 seconds (default 15), evicted by long-poll GET /internal/v1/events.
- Offline license tokens (RS256, pinned public keys) carry expiry, roles, provider/scope, and plan limits and do not call the platform. Central revocation is not instant; lifetime and local trust updates are the contract (app/offline_license.py).
- Optional Keycloak path is a pilot (app/keycloak.py), not the default ./start.sh path.
- Actors in audit logs are stable hashes (app/principals.py).

Provider-scoped keys exist only when PLATFORM_PROVIDER_SCOPED_KEYS=true.

---

## 16. Scanning and analysis rules

**Backend improvement**

- perform_scan is all-or-nothing. Any scope failure, quota breach, or finding outside configured scopes saves nothing. Thread pool is at most 4 readers (app/multi_cloud.py).
- Caps: 100,000 findings and 100,000 resources; duplicate findings rejected.
- Credentials are keyless: Azure managed identity, AWS assume-role with workspace id as external id and caller-account check, GCP service-account impersonation, Kubernetes binding or named Prometheus token (app/cloud_identity.py).
- Effective rules come from identity. If the policy cannot be read, the scan is not saved.
- Azure Resource Graph detections (orphan disk, unassociated public IP, stopped VM, empty App Service plan, orphan NIC/NSG, idle Application Gateway) page 1,000 rows; an incomplete page set fails the scan (app/scanner.py).
- AWS: unattached EBS, unassociated EIP, idle RDS (app/scanner_aws.py). GCP: unattached disk, unassigned address, idle Cloud SQL with Monitoring evidence (app/scanner_gcp.py).
- Analysis rules (Azure 1.4.0) have bounded parameters (retention days, CPU percent, and so on). Multi-cloud materialization blocks savings findings when reliability evidence is missing or at risk (app/multicloud_rules.py).
- When live evidence is enabled, Azure Monitor / Activity Log, CloudWatch / CloudTrail, and GCP Cloud Asset / Monitoring / audit logs attach per source. Missing telemetry is insufficient_evidence. Azure ARM GET can set evidence.typed_configuration and evidence_schema_version: 3, and analysis_readiness names rules still waiting on telemetry (app/collectors/azure_arm_detail.py).
- Pricing: Azure Retail Prices only on an exact USD meter match. AWS/GCP use an operator catalog reviewed within 90 days, 730-hour month. Otherwise the estimate stays null (app/pricing.py).
- Interactive scans: POST /api/v1/scan-jobs returns 202, needs Postgres, delivery, and CLOUDSAVER_INTERACTIVE_JOBS. Idempotency key required. With the distributed lock, a second scan is 409 and async workers do not steal the lease (BC-07, app/scan_concurrency.py).
- Scheduler reserves the job and the delivery event together. Scope-authorization failures are not retried. Transient failures retry at most 3 times, backoff capped at 300 seconds.
- Canonical rule ids (migration 0034, identity i0014) keep historical and catalog ids aligned.
- Typed inventory tables (0035, 0036) and schema_capabilities on cloud status (BC-10) expose what the deployment can store. app/typed_resources/ is the read model; it does not replace the scan payload.
- Pillar rollup for a completed scan is also available at GET /api/v1/scans/{scan_id}/pillar-analysis (app/pillar_analysis_api.py).

Synchronous scans cannot be cancelled (POST .../cancel returns 409).

---

## 17. Platform portal and identity

**Backend improvement:** identity, billing, customers, keys, rule policy, AI policy, and knowledge are a separate product (platform/), reached only over the internal platform-link network. Cross-imports fail tests. Contract is platform/contracts/identity-v1.md.

- Service callers are named tokens (SHA-256 allowlist) limited to route families: verify, directory, admin.
- Operator auth is Entra or an operator key. The operator key is rejected in production. Non-GET admin calls need PlatformOperator, except knowledge review posts.
- Sessions are HTTP-only, SameSite=Strict, at most 8 hours. Revoking all keys and deleting a workspace require a sign-in within 15 minutes.
- Egress proxy allows CONNECT host:443 only to an exact public-host allowlist (≤ 20). It does not decrypt traffic (platform/egress/proxy.py).
- Billing evaluator runs every 60 seconds. Stripe webhooks are idempotent and handled in identity. CloudSaver only sees the projected plan (platform/identity/billing/).
- Knowledge publications live in a separate database. screen() rejects identifiers and secrets. Sources must be synthetic or public docs from Microsoft Learn, AWS, Google Cloud, or kubernetes.io. Publish needs two independent reviewers who are not the author; reviews expire in 90 days. Retrieval returns at most 5 items and is not a customer route. Client observations are not harvested for training.
- Identity migrations through i0016 add directory, billing, resource access, plan-change uniqueness, analysis knowledge, client access, cache event sequence, entitlement-change signals, analysis policy, AI Foundry policy, Kubernetes rules, multi-cloud catalog, canonical rule ids, CloudSaver integration settings, and workspace UI themes. UI themes are operator configuration, not a scan behavior.
- Portal forwards only allowlisted /admin/v1/* pairs and checks request origin.

---

## 18. Later backend features (in the tree, beyond the Oct 25 guides)

These are implemented modules, with the limits the code itself states.

**Engineering review plans**

/api/v1/engineering (app/engineering/, migration 0027). Workloads, members, and versioned plans are observation-bound. Capabilities hard-code execution_enabled: false, downtime_policy: zero_downtime, mode: review_only, and sandbox_verified: false. 1.8.1 defaults resize/restore actions and agent plans to resize_mode: zero_downtime. Plans share cp_plan_versions with the control plane. Azure-scoped in the response model.

**Control plane**

/api/v1/control-plane (app/control_plane/, migration 0026). Plan versions, action safety checks, and financial scenarios. HTTP is a thin mapper over those functions. Fields that would change the digest but have no columns (exclusive_targets, consumes_ha_headroom, skus) are rejected so a stored digest stays reproducible.

**FinOps autopilot**

/api/v1/finops/autopilot/playbooks, /resize-metrics, and POST /resize (202). Deterministic resize plans from playbooks (app/finops_resize_playbooks.py, app/finops_resize_metrics.py). auto_execute is a request flag on top of the agent gateway; it does not bypass agent approval, permits, or CLOUDSAVER_AGENT_ENABLED. Rule-to-action map includes Azure VM and App Service, AWS EC2/RDS, and GCP custom/Axion rightsizing.

**Drift ingress**

app/drift/: cloud-event webhook with a shared secret (public relative to workspace auth, not open), max 100 events or 422, fenced platform_outbox_intents (0033: lease_owner, lease_fence, lease_until). Workers refuse to start if the table exists without those columns. Redis contention releases the database claim. Subscription ensure (POST /api/v1/drift/cloud-events/subscriptions/ensure) is behind CLOUDSAVER_DRIFT_SUBSCRIPTION_WIRING. The in-memory buffer in app/collectors/event_stream.py is still a scaffold; durable dispatch is the outbox path.

**Code Mode**

Migration 0038, app/code_mode_*.py, workers/code-mode-bridge. Operator-reviewed JavaScript of the single shape function transform(input) { ... }. Python rejects import, fetch, eval, Function, require, globalThis. Runs are append-only. Off unless CLOUDSAVER_CODE_MODE_ENABLED=true. Human TenantAdmin must send acknowledge_sandbox: true. This is not the agent runCode path.

**Semantic embeddings**

Migration 0032, table semantic_resource_embeddings, optional pgvector vector(1536) HNSW index. Routes under /api/v1/semantic (app/drift/drift_ops_api.py, app/semantic_embeddings_pipeline.py, app/semantic_embeddings_store.py). Embeddings are a retrieval index, not an authorization or a savings proof.

**eBPF flow costs**

Migration 0030, table k8s_ebpf_flow_costs, collector app/collectors_ebpf_flow.py, and the ebpf-flow-exporter directory. Rows are tenant-scoped flow cost observations. They do not replace FOCUS node bills or OpenCost allocations.

**Observability connectors**

Migration 0025, /api/v1/observability (app/observability_api.py, workers/observability_sync.py). Connector configuration and sync state, separate from the Kubernetes scan ledger. Prometheus, REST metrics, Tempo, and Jaeger use the sync worker. Kind grafana_mimir is validated and stored here but excluded from sync; it powers §5b live rightsizing only.

---

## 19. Implemented math that is not a product feature yet

Tested, not production-wired (docs/features/v2-scaffolds.md):

| Module | What it does today | Gap |
| --- | --- | --- |
| app/scanner_ai_gpu.py | DCGM contract; trailing idle streak must meet min_idle_hours | No collector |
| app/autopilot_commitments.py | Ladder tranches apply step_pct to the ceiling; purchase_authorized: false | No purchase API |
| app/k8s_karpenter_sync.py | Returns a NodePool dict | Nothing is applied |
| app/ai_workload_optimizer.py | Decimal routing-savings estimate, advisory_only | No measured volume or quality gate |
| app/collectors/event_stream.py | Parses EventBridge, Event Grid, and Pub/Sub into a memory buffer | Not the durable ingress path |
| GET /api/v1/auth/consent-url | Always 501 | Operators add accounts in the portal |

The enforced closed-loop path is `app/outcome_store.py` and `app/outcome_evidence.py` (compare remediations to later FOCUS evidence and reopen on regression). Do not treat that workflow as a second billing system.

---

## Persistence map (core)

| Revision | Backend change |
| --- | --- |
| 0006 | GitOps requests, forced RLS |
| 0007 | Delivery outbox |
| 0009 | Inference ledger, FOCUS charges, forced RLS |
| 0010 | Resource decisions and AI batches |
| 0013 | Billing projection from the platform |
| 0015–0018 | AI diagnostics, data governance |
| 0017 | Agent tasks |
| 0020–0022 | Agent GitOps journal, billing jobs, financial outcomes |
| 0023–0024 | Governance, commitment snapshots |
| 0025–0027 | Observability, control plane, engineering workloads |
| 0028–0029 | Drift/GitOps outbox, AST index |
| 0030–0032 | SaaS FOCUS, eBPF flows, carbon metrics, Merkle audit chain, embeddings |
| 0033 | Fenced platform outbox leases |
| 0034–0036 | Canonical rule ids, resource-type catalog, typed tables |
| 0037 | Scan update/delete grants for the app role |
| 0038 | Code Mode runs |

Identity head in the tree is **i0016_workspace_ui_themes**.

---

## What this backend still does not claim

- No compliance certification, no invoice reconciliation, no realized-savings guarantee.
- No seasonal anomaly model. The daily investigation is a same-weekday median, and the billing Z-score is not seasonal.
- No interactive customer cloud-consent flow.
- No automatic commitment purchase, Karpenter apply, or cluster write.
- Sovereign Azure clouds are out of contract; ARM stays on the public profile with continuation-host checks.
- A 200 from a webhook is not proof a human acted. A model answer is not a control pass. A missing dependency edge is not proof there is no dependency.

**Representative regression entry points:** tests/test_high_impact_improvements.py, tests/test_resource_evidence_contracts.py, tests/test_enterprise_backend_contracts.py, tests/test_platform_outbox_lease.py, tests/test_finops_analysis_integrity.py, tests/test_engineering_zero_downtime.py, tests/test_agent_workflow_routing.py, tests/test_grafana_rightsizing.py, tests/test_grafana_k8s_policy.py, tests/test_kubernetes_slo_evidence.py, tests/test_backend_improvements_doc.py, and platform/tests/test_readme_improvements.py.
