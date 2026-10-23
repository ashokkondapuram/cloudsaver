# CloudSaver v0.9.0 verification report

Date: October 23, 2026 (UTC). Baseline: upstream v0.8.0 commit `6d6a37c645d84e277bdbeefc93f75e902a5b7297`. Source requirements and implementation boundaries are recorded in [SOURCE_CONTEXT.md](SOURCE_CONTEXT.md) and [the assessment/AI guide](docs/ASSESSMENT_AI.md).

## Executed checks

| Check | Result |
| --- | --- |
| Baseline disposable PostgreSQL 16 / Redis 7 suite before development | 305 passed |
| Final backend suite via `python scripts/test_postgres.py --tb=short` | 352 passed; one inherited Starlette/httpx deprecation warning |
| Gateway regression after adding the new forwarding/Retry-After test | 14 passed, including 13 cases also present in the backend suite; 353 distinct backend cases covered across these runs |
| Python dependency consistency (`pip check`) | No broken requirements |
| Dashboard `npm run typecheck` | Passed |
| Host production `next build --webpack` | Passed; nine generated pages, fixed same-origin API proxy |
| Dependency audit (`npm audit --audit-level=moderate`) | Zero known vulnerabilities reported |
| Production browser workflows, system Chromium | 17 passed against a freshly started production server; exit status 0 |
| Container builds, Python services and standalone dashboard | Passed, including the normal Turbopack production build |
| `git diff --check` | Passed |

## Behaviors exercised

- Unknown/invalid/negative/nonfinite prices remain unknown; a real zero remains zero. Retail estimates do not become billed spend or realizable savings. Provider/category aggregation retains unknown-price counts and does not mutate saved scans.
- All five pillars are represented. Explicit false flags and zero-day backup retention remain risks; absent encryption, backup, dependency and telemetry evidence is not a pass. Complete Kubernetes 14-day sampled P95 evidence is distinguished from incomplete windows.
- Case/punctuation-normalized recovery, witness and retention tags and explicit deletion protection preserve protected disposition and block destructive artifact generation.
- Generated Bash was executed only against a local fake CLI in a PTY. Failed snapshots and live protected tags aborted deletion; the unprotected successful-snapshot case reached only the fake delete command. Tests also verify post-snapshot rechecks and retention instructions. No real cloud resource was read, snapshotted or deleted by these artifact tests.
- Analysis selects exact resource + rule from an owned live scan. Foreign scans are hidden; legacy data and changed cloud scopes are rejected. Entra viewers can read assessment but cannot invoke models. Real PostgreSQL runtime RLS still bounds reads and preserves stored evidence.
- Azure, Bedrock and Vertex request formation was verified with injected credentials/clients/transports. Approved endpoints, fixed identity bindings, tenant external ID, explicit Vertex scope, no model tools, bounded output, no inference retries and sanitized failures were checked. No live model inference occurred.
- Context excludes names, raw IDs, tags, emails, endpoints and scan free text. Strict model validation rejects extra approval/code properties, missing/duplicate pillars, unsupported risk classifications and fabricated evidence references. Schema validation does not certify the truth of model prose.
- Real Redis concurrent submissions produced one provider invocation, cached success, fingerprint conflicts, tenant isolation, hourly attempt exhaustion, uncertain-attempt suppression and TTL bounds. Replaced fences cannot be overwritten by stale completion. Coordination failure blocks inference.
- Browser tests verify the new assessment, protection banner, sanitized-context preview, acknowledgement and role gates, same-key resubmission and cancellation of late AI results when changing findings. Existing navigation, code review, selection shortcuts, plan upload, GitOps acknowledgement, scan dialog, mobile views and 10,000-row virtualization still pass. Automated accessibility checks cover the assessment dialog and existing major views. These checks do not replace manual assistive-technology acceptance.

## Deployment and external acceptance limits

The multi-service Compose restart was blocked by automatic approval review because it could mutate shared containers, databases and volumes during verification. It was not retried or bypassed. New images were built, but the running shared stack was not upgraded by this release and no fresh full-stack smoke result is claimed. Existing volumes and customer-like local data were preserved.

AI remains disabled by default. Authorized cloud/IAM/model staging acceptance, region/retention review, live Azure snapshot/restore drills, provider quotas, billing reconciliation, load/failover acceptance and manual accessibility testing remain outstanding. The Redis inference fence is a 24-hour attempt coordinator, not an immutable audit or permanent exactly-once guarantee. The 90-day snapshot tag is not an enforced lifecycle policy. No live scan, inference, notification, payment, product PR or infrastructure remediation was triggered during these checks.

GitHub Actions will independently run the repository gates after publication. This source package records local checks; use the linked repository workflow for the subsequent CI result.
