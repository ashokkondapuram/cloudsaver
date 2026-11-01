# Drift streaming & GitOps production enablement

Use this sequence once per environment. All HTTPS endpoints must be reachable from public cloud control planes (EventBridge, Event Grid, Pub/Sub push).

## 1. Core secrets and URL

| Variable | Value |
|----------|--------|
| `CLOUDSAVER_DRIFT_INGEST_URL` | Public gateway URL, e.g. `https://<gateway>/api/v1/drift/cloud-events/ingest` |
| `CLOUDSAVER_DRIFT_WEBHOOK_SECRET` | ≥32 random bytes; sent as header `X-CloudSaver-Drift-Webhook-Secret` (AWS/Azure) or Pub/Sub push attribute `webhook_secret` (GCP) |
| `CLOUDSAVER_DRIFT_SUBSCRIPTION_WIRING` | `true` on the scanner/core service that exposes the admin API |
| `CLOUDSAVER_PLATFORM_OUTBOX_DISPATCH` | `true` so Celery dispatches `DRIFT_INSPECT_RESOURCE` intents |
| `CLOUDSAVER_DRIFT_LIVE_READERS` | `true` for live ARM/EC2/GCP reads during drift inspect |

AWS-only: `CLOUDSAVER_DRIFT_EVENTBRIDGE_ROLE_ARN` (role trusted by EventBridge to invoke the API destination).

Apply Postgres migrations through **0032** before semantic pgvector backfill.

## 2. Wire cloud subscriptions (per workspace)

As tenant admin:

```http
POST /api/v1/drift/cloud-events/subscriptions/ensure
Authorization: Bearer <workspace token>
```

Requires workspace bindings: `aws_accounts`, `subscription_ids`, and/or `gcp_projects`.

Verify Event Grid validation: Azure sends `SubscriptionValidationEvent`; ingress returns `validation.validationResponse`.

GCP: note `sink_writer_identity` in the API response; grant **Pub/Sub Publisher** on topic `cloudsaver-drift-audit` to that service account if logs do not arrive.

## 3. GitOps AST index (per repository target)

| Variable | Purpose |
|----------|---------|
| `CLOUDSAVER_GITOPS_AST_INDEX_FROM_GITHUB` | `true` |
| `CLOUDSAVER_GITHUB_APP_*` + `CLOUDSAVER_GITOPS_TARGETS` | App credentials and targets |

```http
POST /api/v1/gitops/ast/index-repositories
```

Repeat after major IaC refactors or when remediation returns `REPO_DRIFT_REINDEX_REQUIRED`.

Optional env JSON mappings: `POST /api/v1/gitops/ast/sync`.

## 4. FinOps autopilot (optional)

| Variable | Purpose |
|----------|---------|
| `CLOUDSAVER_FINOPS_AUTOPILOT` | Enable resize API |
| `CLOUDSAVER_AGENT_ENABLED` | Worker execution |
| `CLOUDSAVER_FINOPS_AUTOPILOT_AUTO_APPROVE` | Only with `auto_execute: true` on requests |
| `CLOUDSAVER_AGENT_CONNECTORS` | Include `compute.resize` on cloud connectors |

## 5. Smoke test

1. Mutate a tagged test VM/disk in cloud.
2. Confirm `POST /api/v1/drift/cloud-events/ingest` returns `accepted: 1` (or subscription delivers automatically).
3. Confirm outbox worker completes drift inspect (platform dashboard / logs).
4. If `sync_iac` resize used, confirm GitHub draft PR updates Terraform SKU in the indexed file block.

## 6. Publish application commits

From your workstation with GitHub credentials:

```bash
git push -u origin main
```

Cloud agent VMs cannot push without configured credentials.
