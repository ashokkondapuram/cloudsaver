# CloudSaver v0.7.0 verification report

Date: 2026-10-22 UTC. Repository: ashokkondapuram/project.

## Baseline and delivered behavior

Fetched remote main and incorporated commit 076c96f, which removes runtime demo
mode and expands the billing/operations dashboard. Resolved the dashboard merge
conflict while retaining both feature sets. Fixed stale test assumptions and
explicitly injected test-only scanner fixtures; verification never relies on
production synthetic scan paths or cloud credentials.

Added offline Terraform JSON guardrails, optional Infracost USD budget checks,
a standard-library CLI/composite Action, bounded policy API and dashboard panel.
Added owned live-scan GitOps preview and explicit GitHub App draft-PR adapter,
operator repository allowlists and durable tenant-scoped request history,
idempotency keys, bounded attempts and publisher leases. Packages are import-only
and isolated under .cloudsaver/reviews/. No existing infrastructure definition is
edited, no force-push is used and CloudSaver executes no Terraform or cloud action.

Historical synthetic snapshots remain stored unchanged, but reads mark their
origin, hide illustrative costs and prevent Bash/Terraform/GitOps export. They
cannot become live evidence merely through a compatibility mode label.

## Executed verification

- Python 3.12: `python scripts/test_postgres.py` — **272 passed**, no skips.
  The runner creates/removes its own disposable PostgreSQL 16/Redis 7 containers.
  One inherited Starlette/httpx TestClient deprecation warning remains.
- Database tests verify forced RLS on gitops_requests, foreign tenant reads,
  cross-tenant scan foreign keys, durable keys, active publisher exclusion and
  stale-token fencing. Upgrades preserve history from both earlier lineages,
  the v0.4.1 merge and v0.6 cloud-findings revision.
- SQLite tests verify request keys across restart, payload-key conflict, lease
  takeover, stale completion denial and foreign-tenant lookup denial.
- GitHub tests use real RS256 signatures and mocked HTTP: repository-scoped App
  token requests, numeric repository verification, atomic review commits, draft
  creation, lost-response reconciliation, wrong-repository denial, conflicting
  branches, redirect denial and preview-file hash verification on existing PRs.
  No live branch or PR was created by these tests.
- Policy tests exercise orphan versus declared/concrete attachment, nested Azure
  attributes, module-local references, conservative indexed-instance denial,
  deletion/replacement, required/unknown tags, USD budget/unknown pricing,
  inconsistent cost totals, duplicate keys, malformed/versioned/deep/oversized
  input, NaN/infinity rejection and sanitized output. CLI exit codes 0/1/2 pass.
- API tests verify Viewer reads/evaluation versus Admin publish restrictions,
  plan entitlement/owned scan checks, previews without I/O, idempotent publication,
  auditable uncertain outcomes, disabled publishing and bounded request bodies.
- Existing Azure/AWS/GCP/Kubernetes ingestion, identity, billing, credentials,
  quotas, worker lease/fencing, service routing and remediation tests pass.
- Frontend TypeScript and production build passed after merging the latest
  dashboard. Node 22 Docker build also checks types and builds successfully.
  Python image build passed with a strict runtime-source whitelist and non-root
  user. Consolidating runtime COPY avoids duplicated vfs layer storage.
- compileall, pip check and git diff --check passed.

- Running Compose stack: all eight long-running services healthy; migration
  completed successfully without replacing PostgreSQL/Redis volumes.
- Gateway and dashboard proxy smoke passed before and after restarting the
  scanner, gateway and dashboard: authentication, entitlements, history,
  GitOps target/history routes, invalid-plan redaction and route restrictions.
- Both retained historical synthetic snapshots read as legacy_synthetic with
  illustrative finding prices removed. The saved multi-cloud scan remained
  readable after restart. GitOps publishing stayed disabled with no targets.
  No live scan or external product action was triggered.

## Limits and acceptance still required

GitHub App installation/permission behavior, real Terraform plan corpora, target
provider versions and real Infracost reports need authorized external acceptance.
The App is operator-provisioned; native OAuth onboarding, GitLab/Bitbucket and
native OPA execution are not included. CI must pin reviewed checker code, protect
policy ownership and establish same-plan cost-report provenance. Source alone
cannot enforce merge checks.

Association checking is conservative and limited to documented resource/attribute
patterns; indexed/indirect/external bindings may need independent review. Optional
Infracost figures are reported USD estimates, not verified billing or savings.
Raw uploaded plans can contain secrets: they are processed transiently and are
not stored or echoed by CloudSaver. Repository CI may run on an explicitly
published draft PR; operators must exclude review folders from auto-apply jobs.

Ambiguous GitHub outcomes remain uncertain, with a maximum of four attempts.
Retry the same key after inspecting history; changed branch contents/base or
exhausted attempts require manual review. No distributed exactly-once delivery,
background replay, merge, deletion approval or destructive remediation is claimed.

Runtime is production-only (CLOUDSAVER_MODE=azure). Local verification uses health,
existing-history reads and invalid-input checks, with scheduled scans and alerts
disabled. No live cloud scan, payment, notification, ITSM ticket, remediation or
customer infrastructure PR was run. The final source publication to this user's
project repository is separate from testing the product's PR adapter.

Live Entra/Stripe/cloud acceptance, browser visual/accessibility QA, a production
restore drill, load/fault acceptance, GCP Catalog reconciliation and OpenCost
allocation remain pending. The inherited frontend dependency graph still has
9 advisories (6 high, 3 moderate); no unreviewed major upgrade was applied.
Prior evidence is retained in docs/TEST_REPORT_v0.6.0.md and earlier reports.
