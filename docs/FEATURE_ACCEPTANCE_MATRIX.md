# Feature completion and acceptance matrix

Status: local hardening and verification; not an assertion of 100% feature or production readiness. See [the verification record](AETHERGUARD_LOCAL_VERIFICATION.md) for exact results and limits.

The requested outcome is that every supported feature works. A unit test, build or passing browser fixture verifies a particular contract; it does not establish live provider permissions, financial truth, recovery, application quality or compliance. The approved environment for this work is local tests only, with no connected cloud sandbox.

Keep three completion levels separate:

1. Code and contract complete for the documented supported scope.
2. Locally verified using unit, database, build, browser and real local transport tests.
3. Accepted in the actual supported environment with authorized integrations and operational evidence.

Do not describe an area as fully complete if only level 2 is established. A feature that is explicitly a roadmap scaffold remains incomplete; a live integration that has not been exercised remains unverified. The existing root README and production launch gates remain authoritative.

## Supported application areas

| Area | Existing implementation / local evidence | Acceptance still needed |
| --- | --- | --- |
| Workspace identity, tenant keys and users | Core auth/scope tests and independent platform suites; shared keys remain distinct from verified human sessions. | Actual Entra issuer/audience/application roles, JWKS rollover, revocation and directory freshness in the deployed tenant. |
| Platform portal and subscription administration | Platform Python tests, portal financial unit tests, type checks and production build. | Actual operator login, secret configuration, customer onboarding and billing-provider reconciliation. |
| Inventory and multi-cloud scans | Collector, scan, job, scope, rule and PostgreSQL tests. Partial or missing evidence remains explicit. | Authorized Azure/AWS/GCP accounts; discovery completeness, pagination, IAM and source freshness for each sold service. |
| Resource exploration and ownership | Customer browser journeys and resource API tests; current explicit ownership and versioned decisions. | Customer mapping accuracy and representative large estates. |
| Workload assessments | Read-only grouping using authorized saved resources and explicit application/environment ownership; helper/browser tests. | Complete dependency discovery and persistent cross-resource improvement plans are separate roadmap work. |
| Service analysis | API and browser checks; incomplete response payloads produce an evidence error rather than a page crash. | Real service telemetry and provider coverage. |
| Five-pillar resource assessment | Versioned evidence, freshness, scope and missing-data tests. | Customer-specific operational requirements and control acceptance; an observed setting is not compliance certification. |
| Analysis-rule administration | Core/platform rule catalog, scope, override and preview tests. | Approved provider/service rule catalog, policy floors and customer acceptance. |
| Imported and synchronized billing | Durable jobs, corrections, accounting fixtures and PostgreSQL tests; GET does not perform ingestion. | Invoice/export reconciliation, credits, currencies, commitment eligibility and source completeness for each provider. |
| Commitment inventory | Provider-reader fixtures, bounded snapshots and scope tests. | Actual reservation/savings-plan/CUD permissions and accurate sharing/eligibility semantics. |
| Savings and anomaly investigations | Signed synthetic proof, outcome workflow and real local HTTP journeys. | Trusted attestor deployment, actual application outcomes, demand adjustments and finance acceptance. |
| Observability connectors | Read-only connector validation, bounded collection, mapping and API tests. | Actual Prometheus/Tempo/Jaeger/provider configuration, labels, windows and authorized source data. |
| AI assessment and data governance | Policy, processor, purpose, retention, budget, inference-state and browser tests. | Approved deployed models/processors, real quality evaluation, retention and customer data-use authorization. |
| Separate knowledge publication | Platform publication/privacy/reviewer tests and separate database configuration. | Operational separation, approved publication sources and measured evaluation. Client-data harvesting remains disabled. |
| GitOps review and plan policy | Offline policy and mocked-provider tests plus local BFF/gateway/core journeys. Resource lookup requires an owned observation and a workspace-granted repository. | Actual GitHub installation, repository-required checks, trusted plan provenance and deployment verification. |
| Agent worker | TypeScript checks/tests, lease/permit/approval and scoped adapter tests. | Approved sandbox execution and IAM for each supported operation. General VM resize, IP deletion and arbitrary shell/HTTP are not implicitly authorized. |
| Risk and compliance | Governance roles, signed evidence, exceptions, verification, closure and reopening; real local transport journey. | Qualified control/risk owners, authoritative source evidence, retention/legal policy and independent security acceptance. |
| Activity and delivery | Durable intent, broker, retry, fencing and reliability tests. | Actual opt-in destinations, alert delivery, responders and operational objectives. |
| Local deployment and upgrade | Disposable PostgreSQL role/bootstrap, migration, RLS, pooling, rollback and Compose contracts. | Managed secrets, TLS, HA, capacity, backups, measured restoration, incident response and production deployment acceptance. |

## AetherGuard P0 is a foundation, not a completed control plane

The feature branch adds eight database tables and domain helpers. Hardening makes its tested behavior safer:

- Mandatory missing evidence stays unknown; invalid and non-finite values are rejected.
- Approval identity includes SKU, exclusive-resource and HA-headroom semantics.
- Human/trusted-plan flags fail closed and cannot be supplied as truthy strings.
- Version creation is serialized using the existing tenant transaction lock.
- Changed idempotency-key payloads conflict.
- Check conclusions agree with their decision/trust evidence.
- Queue/running transitions require a current, unexpired exact-version approval.
- Newer plan versions cannot inherit an older version's authority.
- Runtime startup verifies forced RLS on every new table.
- Populated-history downgrades refuse and restore forced RLS.

These modules are not registered as control-plane API routes, durable orchestration or customer planning screens. They do not provide a complete topology collector, real commitment eligibility allocator, trusted GitHub check service, new destructive action adapter, automatic approval or verified financial outcome. Do not expose them by trusting request-supplied evidence or authority flags.

## Incomplete roadmap capabilities

The following remain implementation work, regardless of local unit-test status:

| Capability | Required work before it is a supported feature |
| --- | --- |
| Complete AetherGuard lifecycle | Reviewed action/evidence contracts, owned relationships, API/gateway/BFF wiring, coordinated plans, transactional audit/outbox, customer/operator UI and integration acceptance. |
| Full commitment-aware counterfactual allocation | Hourly eligibility and sharing semantics, current obligations, correction lineage, independent source coverage and finance reconciliation. Pure scenario inputs are not provider evidence. |
| Trusted pre-merge GitOps firewall | Authenticated webhook/job integration, trusted plan provenance, exact revision/approval binding, required-check enforcement and deployment-time rechecks. |
| Event-driven cloud discovery | Authenticated tenant-bound subscriptions, durable queues/checkpoints and bounded targeted rescan workers. Current subscribe methods remain explicitly unimplemented. |
| Automatic multi-IaC mapping and patching | Tenant-bound repository/state indexing and real AST changes; current lookup is operator-provided and the patch helper is an advisory placeholder. |
| GPU and model optimization | Real telemetry duration/coverage, quality/latency evaluation, source attribution, provider costs and approved actions. Current helpers do not establish production suitability. |
| Commitment purchase / Karpenter changes | Reviewed procurement/cluster semantics, exact approvals, supported typed operations and sandbox acceptance. Scenario/draft modules do not authorize writes. |
| Business unit economics | Owned business-volume ingestion, aligned accounting windows, allocation policy and reviewed attribution. The current endpoint is a manually supplied advisory calculation. |
| Interactive self-service consent | Reviewed provider-specific consent/callback/binding flows. Current supported onboarding remains operator-assisted through the platform portal. |

## Evidence and release requirements

Record the exact source SHA, commands, runtime versions and results in the accompanying hardening report. Do not sum overlapping runs as if they were distinct tests.

Before merging, regenerate the exact tracked-source release manifest and pass the required CI jobs. Before claiming production completion, attach environment-specific evidence to every applicable row above. There is no connected cloud sandbox in the current session, so level 3 cannot be established here.

The next product decision is the supported launch scope, including whether the roadmap capabilities are part of that launch. Missing features must remain explicit; disabling or relabeling a capability is not the same as implementing it.
