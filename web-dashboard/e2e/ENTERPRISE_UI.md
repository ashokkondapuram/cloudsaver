# Enterprise UI Playwright slice

Specs in this slice cover the enterprise control-plane, FinOps ladder, governance, and related dashboard surfaces introduced in phases 1–11 of the UI/UX program.

## Run locally

With the dashboard on `http://127.0.0.1:3000` (or set `CLOUDSAVER_DASHBOARD_URL`):

```bash
npm run test:enterprise-ui          # enterprise-ui project only
npx playwright test --project=dashboard   # remaining dashboard e2e
npm run test:e2e                    # both projects (full suite)
```

## Included files

| Pattern | Focus |
| --- | --- |
| `enterprise-ui-phase*.spec.ts` | Phase-scoped regressions (topology, ladder, lifecycle, Foundry, governance metrics, engineering↔control-plane links) |
| `control-plane-*.spec.ts` | Plans, human approval, action-safety firewall |
| `financial-scenario-absorption.spec.ts` | Five-measure strip + commitment-aware scenarios |
| `declared-workloads-if-match.spec.ts` | Engineering workload version fencing |
| `commitment-expiry-badges.spec.ts` | FinOps commitment expiry badges |

Shared fixtures: `control-plane-fixture.ts`, `workspace-fixture.ts`.

## CI

GitHub Actions `dashboard` job runs `npm run test:e2e`, which executes both Playwright projects (`enterprise-ui` then `dashboard`) against a production build on port 3099.
