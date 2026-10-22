# CloudSaver v0.7.0 status

This release follows the advanced roadmap found in Drive's root (v0.6.0–v1.0.0).
The v0.5.0 package was reviewed and selected features were ported into the
verified GitHub code. Its PostgreSQL stubs, permissive schema changes and AWS
live-to-demo fallbacks were excluded. TEST_REPORT.md records executed evidence.

| Area | Implemented | Remaining work / acceptance |
| --- | --- | --- |
| Azure | Seven ARG review checks; complete pagination; unknown unsupported prices | Authorized Azure acceptance, wider billing attribution |
| AWS | EBS/EIP/stopped-RDS ingestion, named profiles, STS account check, pagination | Real AWS IAM acceptance, pricing, other partitions |
| GCP | Zonal/regional disks, regional external IPv4, evidence-gated dev/staging SQL review | GCP API/IAM/Monitoring acceptance, global addresses, Billing Catalog |
| Kubernetes | Native Prometheus CPU/memory review, complete 14-day sampled P95/headroom evidence | Live cluster acceptance, OpenCost allocation, namespace/DaemonSet audits |
| Exports | Owned live Azure/AWS/GCP import-only Terraform, regional disk support, scope/plan checks; Azure Bash | Terraform/provider acceptance; no AWS/GCP deletion scripts or Kubernetes mutation |
| Trends | Durable history, matching scope/mode, identity-based observation deltas, unknown costs | Larger history pagination, billing series and realized savings evidence |
| Database | Atomic normalized Azure/cloud findings and snapshots, restricted role, forced RLS, migration upgrades | Production restore drill and independent review |
| Identity | Strict signed Entra delegated tokens and explicit roles | Live Entra acceptance, browser PKCE/consent, membership onboarding |
| Billing | Trusted SDK Checkout and durable verified webhooks, persisted entitlements | Stripe test-mode acceptance, portal/upgrades, invoice UX |
| Scheduling | Existing opt-in Azure Celery worker, Redis heartbeat, durable fencing/cadence | Publish outbox, replay/failover, multi-cloud scheduling and interactive jobs |
| Notifications | Existing explicit aggregate webhook path; automatic alerts disabled | Reliable delivery outbox, audited ITSM integration/provider acceptance |
| Dashboard | Provider selection/filtering, evidence, trend chart, exports and roles | Browser accessibility/visual QA, interactive sign-in, inherited dependency advisories |
| Plan policies | Offline CLI/Action and bounded API, supported attachment checks, deletion/tag policies, optional Infracost budget | Real Terraform/Infracost corpus acceptance, more module/instance relationships, native OPA integration and CI provenance |
| GitOps | GitHub App repository allowlist, import-only draft PRs, deterministic packages, durable idempotency/leases/history | Live App acceptance, native OAuth onboarding, GitLab/Bitbucket, destructive approval workflows |
| Later roadmap | Advanced roadmap and limits recorded | AI anomalies, tags/showback, autonomous approvals, deployment/compliance |

The Drive v0.5.0 guide describes scheduler/ITSM behavior beyond what its source
wires into the service stack. Those claims are not inherited as verified features.
This release does not report synthetic dispatches, cancellation, production
readiness, SOC 2 certification or Gemini review.

Interactive scans are synchronous; completed scans cannot be cancelled. There is
no reliable automatic alert-delivery guarantee. All live AWS/GCP/Kubernetes dollar
and net savings estimates remain unknown. A resource no longer observed is not
proof of remediation. See docs/CLOUD_SOURCES.md for exact scope/telemetry rules.

Latest GitHub commit 076c96f was merged before release. Its production-only mode
and dashboard operations are retained. Legacy synthetic history is read with
explicit provenance and no illustrative dollar estimates; exports/publishing are
blocked. No live PR or infrastructure change was created during verification.
