# CloudSaver v0.11.0 verification report

Executed October 23, 2026 against the latest v0.10.0 GitHub baseline, commit `871abc291bb289f4c6de08a0a1748be803c59c67`. Requirements: the Drive optimization, service analysis and enterprise AI integration README linked in SOURCE_CONTEXT.md.

| Check | Result |
| --- | --- |
| Complete backend suite via `python scripts/test_postgres.py --tb=short` | **399 passed** with disposable PostgreSQL 16 / Redis 7; temporary containers cleaned up |
| Python dependency consistency (`python -m pip check`) | Passed |
| TypeScript and production build (`npx next build --webpack`) | Passed, all nine pages generated; webpack used for the managed host's build environment |
| Production browser workflows (`npm run test:e2e`) | **25 passed**, Chromium with intercepted test-only APIs |
| Standalone production deployment artifact | **2 assessment workflows passed**, including axe accessibility in the protected-resource workflow |
| Whitespace validation (`git diff --check`) | Passed |

## Verified core and inference behavior

- Missing, invalid, infinite, boolean and excessively large numeric inputs remain unknown. Real zero remains zero. Unknown billed costs and realizable savings remain null.
- The service matrix evaluates explicit saved controls and publishes required evidence fields, gaps and risk codes. Azure ARG retains known encryption enums and returned empty-plan/zone controls; AWS retains returned upgrade configuration without additional reads.
- Kubernetes utilization requires the actual complete collector summary. Partial counts, mismatched units, missing requests, malformed timestamps, wrong interval/method and old metric windows are not promoted to complete utilization evidence. Tests connect actual injected collector output to assessment.
- Observation freshness has explicit recent/stale/invalid/unknown states and a 24-hour review window. Stale evidence keeps risks and requires refresh. Policy version and evaluated-evidence digest support traceability without claiming independent verification.
- Summary review queues retain at most 50 findings, rank observed security exposures ahead of other risk and evidence gaps, and are stable regardless of input order. All summary findings are revalidated against current workspace scope; foreign scans remain inaccessible.
- Inference requires an exact resource selection, admin role, explicit acknowledgement and the preview evidence digest. Invalid/mismatched previews fail before budget or provider calls. The model cannot remove deterministic protections or approve infrastructure changes.
- Operator source-provider and context limits reject before paid attempts. Output ceilings are sent by all cloud adapters. Unapproved endpoints/identities and invalid limits are rejected.
- Advice rejects duplicate JSON properties, duplicate/wrong-pillar/fabricated citations, missing risk citations and risk downgrades. Missing/truncated/filtered/tool provider outcomes are rejected. Semantic prose claims remain unverified.
- Usage counters come from provider response metadata, separate from model text. Missing/invalid counters remain null; billed cost stays unavailable. Existing Redis concurrency, fencing, uncertain-outcome and tenant-isolation tests pass.
- Existing remediation Bash safety, PostgreSQL forced RLS, tenant registry, outbox/delivery faults, roles, cloud scope and integrations remain covered by the complete suite.

## Verified console behavior

All existing dark/light, 10,000-row inventory, filtering/export, comparison/focus, keyboard/mobile, plan review, delivery replay, viewer restrictions and late-response cancellation browser workflows pass. New checks verify priority drill-down, stale-evidence warnings, policy provenance, explicit preview digest submission and token usage. Tests use labeled fixtures and never call cloud inference or product mutation endpoints. The built standalone server was checked separately because `next start` warns for an `output: standalone` deployment.

## Activation and practical limits

AI remains opt-in and disabled by default. Existing API clients must fetch `/analysis/resource` and send its `assessment.evidence_digest` to `/ai-risk-evaluation`; missing digests return 422, changed previews return 409. See docs/ASSESSMENT_AI.md for exact target fields, thresholds, API and keyless activation.

No new database migration is required. The package does not deploy or rebuild the shared Compose stack. No live cloud scan, model invocation, remediation, payment, alert or product GitOps PR was executed. Cloud identities are not configured in this environment, so actual IAM/provider/model compatibility, staging acceptance and inference quality remain unverified.

Expanded optional checks do not imply that every live collector now collects those controls. Full dependency graphs, raw telemetry series, FOCUS reconciliation, durable inference audit/usage ledgers and monetary budgets remain roadmap work. The evidence digest is not a signature. Redis attempts/results retain the existing 24-hour lifetime, with no exactly-once guarantee after loss/expiry. Provider-reported tokens are not a billing ledger. No production/compliance certification, guaranteed savings, semantic truth guarantee or autonomous approval is claimed.

GitHub CI runs on publication; its final status is reported separately rather than modifying the packaged source report after publication. The local release manifest and ZIP contain matching source bytes, excluding local credentials, live databases, build caches and test outputs.
