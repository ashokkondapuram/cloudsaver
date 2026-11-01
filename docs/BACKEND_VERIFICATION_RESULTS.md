# Backend verification results and release blockers

Baseline: main `6920bf9` (1.8.0). Scope: backend only. This pass performed tests and failure probes, preserving the prior request for a fixing guide. Application code is unchanged in the original audit pass. This report supersedes any implication that source inspection alone demonstrated reliability.

See remediation commits on `main` after this import for blocker fixes (pgvector image, outbox lease expiry, legacy reclaim, drift event identity, ingress atomicity).

## Verdict

**Blockers 1–5 addressed in source** (pgvector image, lease expiry on complete, legacy reclaim, event identity, ingress atomicity). Re-run disposable PostgreSQL suites and full release gates before a production-ready claim.

## Executed checks

| Check | Result | Interpretation |
|---|---|---|
| `python -m pytest -q tests` at repository root | 1,067 passed; 101 skipped; 1 warning | General backend regression baseline passes; skipped integrations are not validated |
| `PYTHONPATH=..:. python -m pytest -q tests` from `platform/` | 106 passed; 9 skipped; 1 warning | Platform/identity regression baseline passes with both source roots configured |
| Ruff `--select F821,F823` over app/services/workers/database/platform identity | Passed | No undefined-name/local-binding errors under these selected rules; not a full security/static audit |
| Disposable PostgreSQL/Redis runner with PostgreSQL, control-plane and provider retry suites | 16 passed; 75 setup errors | Migration failure prevents database suites establishing RLS, persistence or concurrency guarantees |
| Isolated clean PostgreSQL migration diagnostic | Failed | `vector` extension is unavailable |
| Expired lease completion probe, SQLite | Failed invariant | Expired owner can complete before another worker reclaims |
| Legacy null-expiry lease recovery probe, SQLite | Failed invariant | Old leased rows with null expiry remain unclaimable |
| Distinct no-ID event identity probe | Failed invariant | Same resource/operation with distinct timestamps hashes to the same key |
| Ingress valid-event then invalid-event probe | Failed invariant | HTTP 422 is returned after one intent has already committed |

## Blockers and remediation status

| # | Issue | Remediation |
|---|---|---|
| 1 | pgvector missing from Postgres image / test runner | `database/Dockerfile` and `scripts/test_postgres.py` use `pgvector/pgvector:pg16` |
| 2 | Expired lease completion | `complete`/`fail`/`release_to_pending` require active `lease_until` |
| 3 | Legacy null `lease_until` | `_reclaim_expired` requeues `leased` rows with null or past expiry |
| 4 | Event identity collision | `drift_idempotency_key` includes `event_timestamp_utc` |
| 5 | Ingress partial commit | Validate full batch, then `enqueue_batch` in one transaction per tenant |

Regression tests: `tests/test_platform_outbox_lease.py`, `tests/test_drift_event_pipeline.py`, `tests/test_drift_ingress_and_ast_db.py`.
