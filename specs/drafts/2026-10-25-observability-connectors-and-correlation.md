# Observability connectors: metrics, traces and correlation

- **Author:** CloudSaver engineering
- **Status:** Draft, awaiting review
- **Date:** Oct 25, 2026
- **Builds on:** Kubernetes Prometheus telemetry (`app/collectors/kubernetes.py`, `app/collectors/prometheus_auth.py`), live cloud metrics (`app/collectors/live_common.py`), billing sync worker (`app/billing_jobs.py`), resource costs (`FocusRepository.resource_costs`)

## Problem statement

CloudSaver only reads metrics from two places:

- Prometheus, and only for bound Kubernetes clusters. The operator configures the endpoints through environment variables, and you can't add or test one from the dashboard.
- Azure Monitor, CloudWatch and Google Cloud Monitoring, for a fixed list of resource types, capped at 25 resources per scan.

That leaves several gaps:

- You can't connect Prometheus for VMs, databases or applications outside Kubernetes, or any other metrics REST API.
- There are no traces. You can't see request rate, error rate or latency for a service before you act on a rightsizing finding.
- Nothing links metrics and traces to resources, findings or cost. You can't answer "what does this service cost per 1,000 requests?" or "is this oversized VM serving latency-sensitive traffic?"

## Proposed solution

Workspace admins can add read-only observability connectors in Settings, test them, and let a scheduled worker collect bounded summaries. CloudSaver then links those summaries to resources and costs.

| Connector | Source | What CloudSaver reads |
| --- | --- | --- |
| Prometheus | Any Prometheus-compatible HTTP API (`/api/v1/query_range`), including Azure, AWS and Google managed Prometheus through the existing auth readers | Per-series p50, p95, maximum and coverage for a reviewed query catalog, plus up to 20 custom PromQL queries per connector |
| REST metrics | Any HTTPS JSON API that returns time series | `GET` requests only. The response is mapped with a constrained JSON path to timestamp, value and resource label fields. |
| Traces | Grafana Tempo (`/api/search`, TraceQL metrics) and Jaeger (`/api/traces`, `/api/services`) query APIs | Per-service request rate, error rate, p50 and p95 latency, and the top 20 downstream dependencies. Span payloads aren't stored. |

Correlation then:

1. Maps series and services to inventory resources through explicit label mappings (for example `instance`, `azure_resource_id`, `service.name` to a workload).
2. Shows telemetry in a new **Telemetry** tab in the resource drawer and next to the related findings.
3. Computes **cost per 1,000 requests** where a resource has both complete billed cost and request volume for the same window.
4. Marks rightsizing findings `latency_sensitive` when linked traces show p95 latency or error rate above connector thresholds. The finding then needs explicit review instead of a ready-to-apply recommendation.

Every call is read-only. CloudSaver never writes to, alerts through or reconfigures an observability backend.

## Detailed design

### Data model

Migration `0025_observability_connectors`. All tables have forced row-level security, the standard `tenant_isolation` policy, and grants only to `cloudsaver_app`.

- **`observability_connectors`** (`SELECT, INSERT, UPDATE`):
  - Identity: `id`, `tenant_id`, `name`, `kind` (`prometheus`, `rest_metrics`, `tempo`, `jaeger`), `base_url`.
  - Auth: `auth_kind` (`none`, `bearer_env`, `basic_env`, `header_env`, `azure_managed`, `aws_sigv4`, `gcp_managed`) and `secret_ref`.
  - Collection: `queries` (JSON), `mappings` (JSON), `thresholds` (JSON), `schedule` (`hourly`, `daily`, `manual`).
  - Lifecycle: `enabled`, `version`, `created_by_hash`, `created_at`, `updated_at`.
- **`observability_snapshots`** (`SELECT, INSERT`, append-only): `id`, `tenant_id`, `connector_id`, `job_id`, `status`, `window_start`, `window_end`, `payload` (series summaries, trace aggregates, mapping coverage, warnings), `observed_at`.
- **`observability_jobs`**: same lease and fencing model as `billing_sync_jobs` (`state`, `lease_token`, `lease_until`, `idempotency_key`).

Secrets are never stored in the database. In this release, `secret_ref` names an environment variable matching `CLOUDSAVER_OBSERVABILITY_SECRET_[A-Z0-9_]{1,80}`, which the operator injects from their secrets manager. CloudSaver has no direct secrets manager client yet; see the open questions. The API returns only the reference name, never the value.

### Collection and safety

- **Worker:** a new `observability-worker` in the `scheduled` compose profile. It claims one connector at a time with a 10-minute lease, reads outside database locks, and commits through the fenced transaction pattern from `BillingJobs`.
- **Egress:**
  - HTTPS only, with no credentials, query string or fragment in `base_url`.
  - No redirects. Responses are limited to 4 MB, with a 5-second connect and 25-second read timeout.
  - The resolved address must not be private, loopback, link-local or metadata, unless `CLOUDSAVER_OBSERVABILITY_ALLOWED_HOSTS` explicitly allows that host.
- **Query bounds:**
  - Collection covers the last 7 days at a 5-minute step (hourly schedule) or the last 30 days at 1 hour (daily schedule).
  - Each connector can return up to 2,000 series per run.
  - Custom PromQL is capped at 2,000 characters and the result is checked against the series limit. REST paths are relative to `base_url`.
- **Failures:** a failed run stores a fixed error code (for example `OBSERVABILITY_SOURCE_UNAVAILABLE`). Provider response bodies are never stored.
- **Data minimization:** only aggregates are stored. Trace IDs, span attributes and label values outside the mapping allowlist are dropped.

### Correlation

- **Mappings** are explicit per connector, for example `{"resource_label": "azure_resource_id"}` or `{"service_to_workload": {"checkout": "payments/prod"}}`. Nothing is guessed from names.
- **Matching:** a series links to a resource only when the mapped label exactly matches an authorized inventory resource ID. Unmatched series are counted in `mapping_coverage`.
- **Cost per 1,000 requests** = billed cost from `FocusRepository.resource_costs` ÷ request count × 1,000, over the same complete UTC days. It's shown only when billing coverage is complete and request coverage is at least 95%. Otherwise it's `null`, with a reason.
- **Latency sensitivity:** if a finding's resource links to a service whose p95 latency or error rate exceeds the connector thresholds, the finding gets `latency_sensitive: true` and the rightsizing rules move to `needs_review`.

### API

All routes are served by the core API and proxied by the gateway.

| Method | Path | Purpose | Role |
| --- | --- | --- | --- |
| GET | `/api/v1/observability/connectors` | List connectors, without secret values | `TenantAdmin`, `BillingAdmin` (read) |
| POST | `/api/v1/observability/connectors` | Create a connector | `TenantAdmin` |
| PUT | `/api/v1/observability/connectors/{id}` | Update a connector (optimistic `version`) | `TenantAdmin` |
| POST | `/api/v1/observability/connectors/{id}/disable` | Disable a connector. Snapshots are kept. | `TenantAdmin` |
| POST | `/api/v1/observability/connectors/{id}/test` | One bounded probe query that returns reachability, auth result, sample series count and mapping coverage | `TenantAdmin` |
| POST | `/api/v1/observability/sync` | Queue a collection job (idempotency key) | `TenantAdmin` |
| GET | `/api/v1/observability/sync-jobs/{id}` | Poll a job | `TenantAdmin` |
| GET | `/api/v1/observability/summary` | Latest snapshot per connector, with coverage and warnings | Any workspace role |
| GET | `/api/v1/resources/{resource_key}/telemetry` | Linked series summaries, service trace aggregates, cost per 1,000 requests and latency sensitivity for one resource | Any workspace role, filtered by key scope |

All routes are added to `app/route_inventory.py`. Connector management is `full_scope`; reads are `scoped_read`.

### UI

- **Settings, new Integrations tab:**
  - Lists connectors with their status, last collection and mapping coverage.
  - **Add connector** opens a short form: type, name, URL, authentication, secret reference, mappings and schedule.
  - **Test connection** shows reachability, authentication and sample coverage before you save.
  - **Disable** and **Sync now** actions.
- **Resource drawer, new Telemetry tab:**
  - Metric summary cards (p95 CPU, memory, requests, errors, latency) with their sources.
  - A linked services table.
  - Cost per 1,000 requests, or the reason it's unavailable.
- **Findings:** a "Latency-sensitive" badge on affected rightsizing findings, with the reason.

All text follows the UX writing and data formatting standards (sentence case, `Oct 25, 2026`, `$1,200.00`, `95%`).

## Acceptance criteria

- [ ] A workspace admin can create, test, update and disable Prometheus, REST metrics, Tempo and Jaeger connectors from Settings. Secret values never appear in API responses, logs or snapshots.
- [ ] Connector URLs that are not HTTPS, resolve to private or metadata addresses (unless allowlisted), or redirect are rejected.
- [ ] The worker collects bounded summaries on schedule, fences commits with a lease, and stores one append-only snapshot per connector run. A failure stores only a fixed error code.
- [ ] Series link to resources only through explicit mappings and exact authorized resource IDs. Mapping coverage is reported.
- [ ] The resource drawer shows linked telemetry, and cost per 1,000 requests only when billing and request coverage are complete.
- [ ] Linked rightsizing findings over latency or error thresholds are marked latency-sensitive and need review.
- [ ] Viewers can read summaries but can't manage connectors. Scoped keys see only resources in scope.
- [ ] Tests cover URL validation, each connector parser, mapping, cost per request, fencing, authorization and the redaction of provider errors.
- [ ] Docs: a feature guide, environment variables in `.env.example` (names only), the permissions needed in each backend, and the README.

## Out of scope

- Running Prometheus, Grafana or an OpenTelemetry collector inside the CloudSaver stack.
- Datadog, New Relic and other vendor-specific APIs (possible later connector types).
- Logs (Loki, Elasticsearch) and push ingestion over OTLP.
- Alerting, dashboards, or any write to an observability backend.
- Linking deploys and change events to metric changes.
- Storing raw traces or full-resolution time series.

## Open questions

- Should Kubernetes cluster Prometheus bindings move into these connectors, or stay operator-managed?
- Should viewers see cost per 1,000 requests, or only billing admins (it exposes billed cost)?
- What retention should snapshots have (default proposal: 90 days, enforced by the data retention worker)?
- Which secrets manager should `secret_ref` support first beyond environment variables?

## Dependencies

- Migration `0025_observability_connectors` (after `0024_cloud_commitments`).
- Read-only credentials for each customer's observability backends.
