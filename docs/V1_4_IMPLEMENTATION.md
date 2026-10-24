# CloudSaver v1.4.0 initial implementation and operator guide

> The subsequent lean revision removes the standalone optimization APIs/screens and knowledge retrieval described here. Use [the current lean guide](LEAN_CORE_IMPLEMENTATION.md) and the root README for active routes, deployment and verification. This document retains the initial v1.4 design history.

This upgrade implements the v1.4 coding-agent specification against the actual `f11ccf0` source tree. It adds the 36-family resource catalog, read-only live evidence adapters, deterministic multi-cloud reviews, concrete five-pillar checks, hourly commitment and observed-topology planning, typed multi-cloud execution, and expanded data governance. The default deployment does not acquire new cloud permissions or activate additional discovery automatically.

The specification names several files and tables that do not exist in this baseline. The implementation uses `app/ai_advisory.py` for native inference; `app/causal_topology_simulator.py`, `app/nextgen_engines.py` and `/api/v1/optimization/*` for planning; `ai_data_events` and `ai_data_holds` for governance; and saved scan JSON for resource assessments. It does not create competing stores with invented names.

## Upgrade order

1. Review the new cloud reader and execution permissions below. Keep execution disabled during migration and retain the existing backups and retention policy.
2. Upgrade the platform identity database to **`i0013_multicloud_analysis_catalog`**, whose real parent is `i0012_kubernetes_rules`. The specification's proposed `i0011` is already occupied by AI Foundry policy. The new migration preserves existing rule identities, overrides and forced RLS. The previous Kubernetes v1 fixture stays unchanged; the v2 catalog retains all eight original rules and adds StatefulSet and DaemonSet reviews.
3. Upgrade the CloudSaver database to **`0019_multicloud_governance_and_pillars`**, parent `0018_ai_data_governance`. It adds coarse provider/scope audit metadata, preservation release fields and normalized opportunity-group/SLO columns. Assessment content remains in its existing saved scan store. Both version tables are widened to accommodate the new revision identifiers.
4. Deploy upgraded identity, scanner, API gateway, agent gateway, workers, dashboard and portal. New AI services refuse startup without migration 0019. The scan storage adapter can still read/write older snapshots during controlled migration tooling; this is not permission to run new governance APIs against the old schema.
5. Review the effective rules in **Settings → Analysis rules** and the platform workspace rule editor. Each rule can be independently enabled/disabled. Published parameter bounds are validated in both preview and save; a disabled rule does not remove historical findings or bypass mandatory safety checks.
6. Explicitly activate live evidence and configure reviewed processors/connectors only after their owning identities are ready. Use background scan jobs for expanded inventory/telemetry; a large synchronous scan can exceed normal request timeouts.

Application Compose uses `cloudsaver-python:1.4.0`; the independent worker uses `cloudsaver-agent-worker:1.1.0`. The platform runs in its separate deployment project. No live environment was deployed as part of development.

```bash
# Upgrade the platform in its own project using its schema-owner migration job first.
docker compose build
docker compose run --rm migrate
docker compose up -d

# Build/start the worker only after reviewing connector grants and identity bindings.
docker compose build agent-worker
docker compose --profile agentic up -d agent-worker
```

## Live evidence and discovery

```dotenv
CLOUDSAVER_LIVE_EVIDENCE_ENABLED=true
CLOUDSAVER_LIVE_EVIDENCE_MAX_RESOURCES=25
```

Activation defaults to `false`. The resource budget accepts 1–100 resources per source/scan, default 25. It bounds expensive 30-day metric and audit enrichment; discovered resources beyond the budget explicitly retain unknown telemetry. It is not a claim that all discovered resources were evaluated. Plan deployment-specific quotas, scan frequency and database capacity before raising it. Raw five-minute series increase saved snapshot size substantially.

Every accepted metric window has 30 days of five-minute points, at least 95% coverage, no unexplained gap over one hour, finite nonnegative observations and no duplicate timestamps. Missing data is never zero-filled. Legacy complete 14-day hourly assessment evidence remains accepted where its existing contract applies. Percentages, byte counts, IOPS and currency cannot be substituted for one another.

| Provider | Inventory and evidence | Permissions / behavior |
| --- | --- | --- |
| Azure | Existing full scoped ARG inventory; Azure Monitor, Activity Log, resource/RG locks, managed snapshots, App Service sites/slots, Recovery Services backup and ASR read planes | Existing customer federation/managed identity reader. Add the relevant Monitor/Activity Log and Recovery Services read permissions. A failed evidence plane stays unknown; a successful ARG query is not proof that every evidence API was authorized. |
| AWS | Existing EBS/EIP/RDS; expanded EC2, NAT, ELBv2, Aurora, DynamoDB, ElastiCache, Lambda/ECS, S3 and SageMaker/Bedrock inventory; resource-bound CloudWatch, CloudTrail and snapshot reads | Reader role must authorize all activated inventory APIs, `cloudwatch:GetMetricData`, `cloudtrail:LookupEvents` and snapshot descriptions. Caller account is verified with STS. One mandatory inventory failure aborts the snapshot; optional evidence failure does not become a clean result. |
| GCP | Existing disks/addresses/SQL; Cloud Asset resource discovery for GCE, forwarding rules/NAT routers, AlloyDB, reservations, Cloud Run/Memorystore and Vertex; Monitoring, Audit Log and snapshot readers | Workload identity with scoped Asset, Monitoring, Logging and Compute read permissions. Log search uses Google's read-only `entries:list` POST endpoint. Returned project, location and resource identities are fenced. |
| Kubernetes | Existing API/Prometheus/OpenCost federation, plus Jobs and controller-specific projections | Extend reader RBAC to `batch/jobs`. Core denied inventory still aborts; secondary denied APIs retain explicit gaps. No Secret contents, environment values or arbitrary pod commands are added to inventory. |

The live adapters collect the API fields they can establish, and rules require their own exact evidence. Some provider metrics depend on guest agents, metric dimensions, tier or service-specific configuration. Unsupported metrics, ambiguous dimensional series, unavailable memory capacity, missing price meters, unverified target SKUs, SLOs and dependency completeness remain unknown. The catalog does not promise a finding for every resource or a successful production integration without those prerequisites.

State history requires an authoritative state-changing event that agrees with the current observation and a complete query. **No event is not proof of ninety days in one state.** Creation timestamps do not establish unattached or stopped duration. In particular, address association and disk attachment operations may be logged against a parent VM; incomplete resource-level audit history therefore cannot establish a continuous idle interval. These cases remain unknown rather than applying the specification's unsafe no-event fallback.

## Rules and five-pillar assessment

`app/resource_catalog.py` and its independently packaged platform mirror describe exactly Azure 10, AWS 10, GCP 8 and Kubernetes 8 resource families. Several families include related resource types and multiple reviews. Existing point-in-time findings remain review signals; the expanded evidence rules do not promote them to verified waste solely because a resource is stopped.

New detected conditions become ordinary saved findings under their frozen policy. Missing inputs produce `insufficient_evidence`; disabled rules produce `disabled_by_policy`; malformed contracts produce `evaluation_failed`. No rule grants execution authority. Regional quantities, prices, discount eligibility, snapshot cost and compatibility must be established before financial attribution. Example rates in the source specification are not installed as universal live prices.

The five pillars now include snapshot age, explicit production HA intent, database backup retention, replication lag, throttling/OOM/burst/queue/SLO signals, explicit exposure, encryption/required customer keys, transport/model controls, audited transitions, locks and freshness. Absent control evidence remains unknown. A stale observation adds a refresh requirement and operations risk; it does not fabricate a new independently observed security incident. AI context includes allowlisted measured facts and observed checks, with bounded legacy gap checks; it excludes raw metric series and inventory identifiers.

Capacity reduction requires fresh SLO burn at most 1.0, CPU-to-latency correlation at most 0.60 and applicable saturation checks. Low average CPU alone is insufficient. Target compatibility is separate evidence. The existing full-series SLO simulator remains available; one scalar supplied by a client does not replace its time-series validation.

StatefulSet memory reviews use a 1.50× P99 buffer. StatefulSet projection records volume-template, disruption-budget and topology-spread evidence. DaemonSet slack is summed across actually observed containers/nodes with stable requests and complete CPU/throttling evidence; it is not multiplied twice. Job/CronJob reviews distinguish observed completed retention and repeated backoff failures. Container allocation slack remains separate from realizable node savings, and no automatic pod eviction/volume shrinking was added.

Verified VM/disk/IP relationships now form review groups for Azure, AWS and GCP. Kubernetes retains its observed node-pool groups. Portfolio totals take the maximum compatible alternative per group rather than adding every finding. Unknown alternatives keep the complete total unknown. A relationship inferred from a tag or name cannot create a verified group.

## Planning workflows

The dashboard's **Optimization studio** adds **Hourly portfolio** and **Blast-radius review**. It also retains the original causal, SLO, network, commitment and signed-savings workflows.

### Hourly clean-before-commit portfolio

`POST /api/v1/optimization/scans/{scan_id}/portfolio` requires BillingAdmin or TenantAdmin and an owned, nonempty scan of at most 1,000 resources. The server derives resource ownership, disposition, opportunity groups and detected conditions from that scan. Request bodies cannot supply authoritative assessment results or foreign resource IDs.

The JSON body contains `hourly_usage_series`, `cleanup_profiles` keyed by saved resource assessment key, and `commitment_terms`. Each profile has:

```json
{
  "unit": "USD/hour",
  "currency": "USD",
  "window_start": "2026-09-24T00:00:00Z",
  "window_end": "2026-10-24T00:00:00Z",
  "points": [
    {"at": "2026-09-24T01:00:00Z", "value": "10.0000"}
  ]
}
```

The abbreviated example shows one point; actual input must contain all 720 aligned hours, with nonnegative decimal strings and matching windows. Duplicate, missing and mixed-currency/unit points are rejected. The browser accepts a reviewed JSON file under 1 MB and sends it only after an explicit evaluation action.

Each commitment term has `term_years` (1 or 3), `discount_percent` (decimal string strictly between 0 and 100), `existing_commitment_hr` (decimal string) and `review_reference` (bounded internal ticket reference). Each hour's cleanup deductions are deduplicated by provider, scope and opportunity group. Waste cannot exceed observed spend in that hour. The clean floor uses nearest-rank P15 after cleanup; existing coverage is deducted before sizing additional commitment.

Incomplete resource reviews, unverified commitment disposition and missing cleanup profiles block a clean floor. Kubernetes allocation-only profiles are excluded from physical node savings. Output contains modeled annual clean-plus-commit savings and modeled avoided over-commitment cost, while verified physical savings remain null and `purchase_authorized` remains false. This is historical scenario math, not a forecast guarantee or proof cleanup has happened. Risk adjustment requires independently reviewed demand and terms; no synthetic risk premium is invented.

### Observed blast radius

`POST /api/v1/optimization/scans/{scan_id}/blast-radius` accepts only `resource_id` and `action` (`retirement` or `consolidation`). It reads the authorized saved graph, traverses observed edges and checks fresh topology, verified graph completeness, protection, and complete zero request/healthy-target windows. Unknown graph coverage and any active traffic block retirement review. Even `review_eligible` returns `change_approved=false`; the engine does not delete anything.

## Multi-cloud worker connectors

The deterministic TypeScript compiler still emits only numeric `ctx.call(index)` statements. There is no MCP server, arbitrary model source, shell, dynamic dependency installation or generic HTTP action execution. The gateway and worker independently validate operation/argument shapes, scope, inspection order and at most one write. Approval hash schema 3 binds the expanded connector definitions and governance contract; existing approvals must be reviewed again.

| Kind | Operations | Execution prerequisites |
| --- | --- | --- |
| `azure_arm` | `resource.inspect`, `tags.merge`, `snapshot.create` | Existing Azure managed/workload identity; exact subscription/resource. Snapshot-capable inspection reads disk identity/state. Destination must be absent; async creation remains uncertain until readback verifies the copied source. |
| `aws_sdk` | `resource.inspect`, `tags.merge`, `ebs.snapshot.create` | Exact account, region and role ARN; keyless projected `AWS_WEB_IDENTITY_TOKEN_FILE`. Static access-key environment credentials are rejected. STS verifies the actual account. Typed EC2 volume/instance and RDS-instance inspection/tagging only. |
| `gcp_rest` | `resource.inspect`, `labels.merge`, `disk.snapshot.create` | Exact project and impersonated service account. ADC source must be a supported keyless federation or compute identity; static JWT/user-refresh clients are rejected. Compute disk/instance and SQL-instance label operations use live fingerprints/settings versions. |
| `k8s_api` | `workload.inspect`, `annotations.merge` | Operator-fixed HTTPS API origin, exact cluster and namespaced workload identity, dedicated service-account token reference. UID/resourceVersion preconditions; only `cloudsaver.io/recommended-*` annotations. |

Metadata writes contain 1–10 explicit string values with bounded provider-valid keys; secret-shaped data is refused before provider calls. A write requires inspection of the same connector/resource in that approved task. Live drift blocks mutation. Provider writes have no automatic retries; lost or ambiguous acknowledgements require reconciliation.

Snapshots take only `snapshot_name_prefix` and `retention_days` from 7 to 90. AWS CreateSnapshot inherits encryption, so an unencrypted/non-KMS source is refused rather than falsely claiming an encrypted snapshot. Snapshot names and retention tags are deterministic/bounded. **Retention tags do not schedule provider deletion**; lifecycle enforcement belongs to a separately reviewed backup process. Pending snapshot creation is uncertain, not success. No disk/VM delete, stop, resize, arbitrary Kubernetes patch or commitment purchase operation is exposed.

Example non-secret grants (replace every placeholder; use identical gateway/worker catalogs):

```json
[
  {"id":"aws-tags","tenant_id":"<workspace UUID>","provider":"aws","scope_id":"123456789012","kind":"aws_sdk","operations":["resource.inspect","tags.merge","ebs.snapshot.create"],"region":"us-east-1","role_arn":"arn:aws:iam::123456789012:role/ReviewedExecutor"},
  {"id":"gcp-labels","tenant_id":"<workspace UUID>","provider":"gcp","scope_id":"example-project","kind":"gcp_rest","operations":["resource.inspect","labels.merge","disk.snapshot.create"],"service_account":"execution-worker@example-project.iam.gserviceaccount.com"},
  {"id":"cluster-review","tenant_id":"<workspace UUID>","provider":"kubernetes","scope_id":"cluster-a","kind":"k8s_api","operations":["workload.inspect","annotations.merge"],"endpoint":"https://cluster.example.internal","token_env":"CLOUDSAVER_AGENT_K8S_TOKEN_PRIMARY"}
]
```

Bind federation files, ADC configuration, projected tokens and Kubernetes execution token values through private deployment mounts/secrets. Default Compose does not mount host credentials or invent federation setup. Keep discovery and execution identities separate. AWS executor rights are limited to account identity, supported descriptions/tags and snapshot creation; GCP rights are limited to supported reads/labels/snapshots and service-account impersonation; Kubernetes rights are namespaced get/patch for the supported objects. Cloud RBAC must enforce the reviewed resource boundary as well as application grants.

## Multi-cloud data governance

The owning logical environment must still match `CLOUDSAVER_DATA_ENVIRONMENT_ID`. Azure registrations retain their existing format and owning-directory check. AWS and GCP approvals use exact provider-specific fields; they do not enable cross-cloud inference or training. Existing workspace consent, plan entitlements, model/region policy and budgets still apply. Empty/mismatched/expired registrations block model invocation before credentials are requested.

AWS processor fields: `provider=aws`, `workspace_id`, `target_id`, `aws_account_id`, `aws_region`, `aws_role_arn`, `model_id`, `guardrail_id`, numeric published `guardrail_version`, `purposes`, `review_reference`, `review_expires_at`, `provider_controls_reviewed=true`. The role account must match registration and the model target; DRAFT guardrails are refused.

GCP processor fields: `provider=gcp`, `workspace_id`, `target_id`, `gcp_project_id`, `gcp_location`, `gcp_service_account`, `model_id` (approved Gemini model), `vpc_sc_enforced=true`, and the same review/purpose fields. Exact project, region, impersonated identity and model must match the target. The VPC-SC flag records the owner's verified review; CloudSaver does not independently prove perimeter enforcement, provider retention, training behavior or processing location.

Training, cross-tenant learning and generic HTTP action transfer remain prohibited. No client observation is automatically contributed to the separate reviewed public/synthetic knowledge database. Pattern filtering is not proof of anonymization; sensitive business free text must not be entered as task instructions or model questions.

`GET /api/v1/ai/governance` now filters event rows, counts, retention records and holds by the principal's provider/scope **before** ordering and limiting. Unlabelled legacy records are hidden from restricted keys rather than guessed into a scope. Processor destination registrations are omitted from restricted views. Full-workspace privacy mutations retain their existing role checks.

`POST /api/v1/ai/governance/holds/{hold_id}/release` requires a full-workspace human TenantAdmin session, a non-identifying `release_reason` and bounded `review_ticket`. Delegated keys and service accounts cannot release preservation. The database runtime role cannot directly update hold rows. A narrow tenant-bound owner function performs a one-time release and appends immutable metadata audit evidence. Release does not reset TTL or restore content; expired content becomes eligible for normal erasure. Provider/backup copies remain under their separate lifecycle.

Existing 0018 retention windows are unchanged by 0019. The old seven-day historical review grace is not restarted. Downgrade refuses to silently reinstate released holds; erased content still prevents rollback to the old required-response schema. Use forward fixes rather than restoring deleted content or rewriting audit evidence.

## Verification and integration boundaries

Tests use synthetic provider responses, disposable PostgreSQL/Redis and browser API fixtures. They exercise actual restricted SQL privileges and the real TypeScript executor with mocked cloud transports. Live cloud permissions, metric availability, SLO inputs, deployment-specific quotas, full provider pricing and backup lifecycle must be validated by the environment owner. A catalog entry is an evaluation contract, not a claim that every service always supplies complete evidence.

No production deployment, customer-data transfer, provider mutation or commitment purchase was performed while implementing this upgrade.

Release verification completed on 2026-10-24:

| Gate | Result |
| --- | --- |
| Backend and platform suite, including PostgreSQL migrations and restricted runtime privileges | 833 passed; one upstream Starlette/httpx deprecation warning |
| Dashboard browser workflows, including accessibility and the new planning/governance screens | 60 passed |
| Dashboard and platform portal production builds | Both passed, including TypeScript checks |
| Worker TypeScript check and host test suite | Passed; 19 tests |
| Worker production Docker build with pinned Node 24.22.1 | Passed |
| Worker tests inside that image, without networking and with a read-only filesystem, non-root user and 256 MB memory limit | 17 passed; two additional snapshot test cases subsequently passed in the host suite |

These checks validate synthetic integrations and application safety boundaries. They do not certify a production cloud account or resolve the upstream dependency advisory below.

### Upstream dependency advisory

The locked `@azure/identity` 4.14.0 dependency uses `@azure/msal-node` 6.0.1. npm audit reports two high-severity entries through [GHSA-xcx6-jx8p-x3h5](https://github.com/advisories/GHSA-xcx6-jx8p-x3h5), affecting MSAL authorization-code parameter disclosure. The worker exposes only managed identity and workload identity, with no authorization-code/browser sign-in flow. At implementation time the official Identity package still requires MSAL 6; MSAL 7.1.1 is available outside that supported dependency range. Track the supported SDK fix and reassess before adding any interactive credential flow. The dependency audit is not clean; no unsupported major-version override is installed.
