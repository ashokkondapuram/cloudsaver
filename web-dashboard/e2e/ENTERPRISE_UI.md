# Enterprise UI Playwright slice

Specs in this slice cover the enterprise control-plane, FinOps ladder, governance, and related dashboard surfaces introduced in phases 1–21 of the UI/UX program.

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
| `enterprise-ui-finops-surfaces.spec.ts` | Optimization topology, commitment ladder, agent drift, GitOps preview, observability sync |
| `enterprise-ui-governance-theme.spec.ts` | Data governance metrics and dark-theme control-plane surfaces |
| `enterprise-ui-governance-engineering.spec.ts` | Engineering↔governance cross-links, tab URL sync, sync notice, deep links |
| `enterprise-ui-control-plane-lifecycle.spec.ts` | Execution ladder, recovery, cancel/expired, review rollbacks, outbox aggregates |
| `enterprise-ui-foundry-probe.spec.ts` | AI Foundry connection probe failure and inference labeling |
| `control-plane-*.spec.ts` | Plans, human approval, action-safety firewall |
| `financial-scenario-absorption.spec.ts` | Five-measure strip + commitment-aware scenarios |
| `declared-workloads-if-match.spec.ts` | Engineering workload version fencing |
| `commitment-expiry-badges.spec.ts` | FinOps commitment expiry badges |

Shared fixtures: `control-plane-fixture.ts`, `engineering-fixture.ts`, `workspace-fixture.ts`.

## Deep links and live refresh

| Surface | Query parameters | Notes |
| --- | --- | --- |
| Governance | `tab=control-plane`, `plan=<cp_plan_id>` | Tab slugs mirror `lib/governance-tabs.ts`. Leaving Control-Plane Plans clears `plan`. |
| Workloads | `tab=engineering\|declared\|assessments`, `workload=<id>`, `plan=<cp_plan_id>` | `/workloads` without `tab` canonicalizes to `tab=assessments`. Engineering tab keeps workload/plan focus; declared tab keeps `workload` and drops `plan`; assessments clears deep-link params. |
| Share clipboard | Governance panel **Copy plan links** | Writes governance URL and, when linked, engineering and declared workload URLs (`engineering_workload_id` on plan list). Declared tab **Copy declared workload link** copies `tab=declared&workload=`. |

Cross-view refresh uses the browser event `cloudsaver:cp-plan-revision` (`lib/control-plane-sync.ts`):

- Control-plane transitions and approvals notify engineering to refetch plan state.
- Engineering workload/plan saves notify governance to refetch plan versions (including engineering outbox pending/published counts).

Plan version payloads may include `engineering_outbox_pending_count`, `engineering_outbox_published_count`, and `engineering_outbox_state` (latest row). Execution tracking in the UI remains audit-only; outbox rows do not trigger cloud mutations from the dashboard.

## CI

GitHub Actions `dashboard` job runs `npm run test:e2e`, which executes both Playwright projects (`enterprise-ui` then `dashboard`) against a production build on port 3099.
