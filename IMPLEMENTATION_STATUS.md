# CloudSaver v1.0.0 implementation status

The v1.0.0 milestone adds durable SQL AI attempt/history/usage evidence, finance-authorized normalized billing imports and analytics, corresponding console workflows and four-reader bounded discovery. See [the eight-area master-guide mapping](docs/V1_MASTER_GUIDE.md).

The preceding core milestone adds versioned service checks, freshness and evidence fingerprints, a bounded review queue, snapshot-wide scope validation and stricter enterprise AI governance. See [assessment controls](docs/ASSESSMENT_AI.md).

The previous UI milestone builds on v0.9.0 (`b61f1b7cdca47e68568f3434dca8a5918ae2bd30`): dark/light themes, counted resource facets, quick views, sizing, comparison drawers, evidence radar and telemetry facts. See [the UI source mapping](docs/UI_UX.md).

The analysis and AI foundation was built on upstream v0.8.0 (`6d6a37c645d84e277bdbeefc93f75e902a5b7297`) and the newly populated Drive optimization, service analysis and AI integration README.

| Area | Implemented boundary |
| --- | --- |
| Resource assessment | Five evidence-led pillars per saved finding, explicit risk/observed/unknown checks, exact selection and current-scope validation |
| Service analysis | Provider/category finding counts, protected/risk counts, known retail portions and unknown price counts; not a complete inventory |
| Protection | Normalized DR/witness/retention tags and returned deletion-protection evidence; server blocks protected destructive scripts |
| Disk artifact safety | Human confirmation, mandatory successful managed snapshot, post-snapshot attachment check, live tag rechecks, 90-day retention instruction; no script execution |
| AI integration | Optional tenant-bound Azure OpenAI, Bedrock Converse and Vertex Google-model adapters, keyless identity, fixed instruction, allowlisted context and strict advisory schema |
| AI governance | Operator context/output ceilings and allowed source providers; pillar-specific citations and risk floors; terminal-response checks and provider-reported token usage, without billed-cost assertions |
| AI coordination | Default API uses durable SQL attempt reservation, database-hour budget, permanent per-key fences, cached success and protected terminal outcomes; no automatic uncertain replay. Legacy direct-SDK Redis coordinator remains separate |
| Billing evidence | Finance-only immutable normalized imports, exact monetary strings, atomic deduplication, currency isolation, declared coverage, conditional ESR and provisional projections; not full FOCUS conformance or provider reconciliation |
| Dashboard | 640px resource drawer with 360° assessment, exact context preview, explicit external-processing acknowledgement, admin-only inference and escaped model text |
| Tenant foundation | Existing PostgreSQL forced RLS, runtime registry, operator-owned identity settings, versioned workspace settings and scoped cloud collection retained |
| Existing operations | Durable jobs/delivery, manual retry controls, plan guardrails and import-only GitOps review retained |

Read [assessment and AI details](docs/ASSESSMENT_AI.md), [keyless onboarding](docs/CLOUD_SOURCES.md), and [executed checks](TEST_REPORT.md).

The API does not expose model-generated actions or code. A model cannot remove protection or approve an infrastructure change. Existing saved evidence is not rewritten to invent missing facts. Legacy synthetic snapshots cannot enter resource analysis or AI review.

Remaining work includes native billing connectors, resource-level billing linkage and reconciliation, seasonally evaluated anomalies, complete resource/dependency telemetry, organization hierarchy, broader policies, reconciled AI monetary budgets/usage accounting and authorized live staging acceptance. No compliance certification, live savings, zero hallucinations, production throughput or end-to-end cloud acceptance is claimed.
