# Enterprise UI / UX program (dashboard)

Living record of the incremental **Enterprise UI** workstream on the CloudSaver web dashboard (`web-dashboard/`). Each phase lands on `cursor/enterprise-ui-phaseN-083f`, merges to `main`, regenerates `RELEASE_MANIFEST.json`, and runs `npm run test:enterprise-ui` before merge.

**Operator docs:** Playwright slice details, deep links, and refresh behavior are maintained in [`web-dashboard/e2e/ENTERPRISE_UI.md`](../web-dashboard/e2e/ENTERPRISE_UI.md).

## Product invariants (unchanged across phases)

- Control-plane **execution tracking** and engineering **outbox aggregates** are **audit-only** in the dashboard. Transitions and displayed outbox counts do **not** invoke cloud provider APIs or dispatch workers from the UI.
- Human approval on plan versions requires a verified human session; scoped keys and automation identities cannot bind approvals.
- Engineering improvement plans share **`cp_plan_versions`** with governance Control-Plane Plans; cross-page refresh uses `cloudsaver:cp-plan-revision` with `source: engineering | governance`.
- FinOps “five-measure” and commitment surfaces remain evidence-bounded; synthetic savings are not invented in the UI.

## Key surfaces

| Surface | Route | Primary components |
| --- | --- | --- |
| Governance | `/governance` | `GovernanceWorkspace`, `ControlPlanePlansPanel` |
| Workloads | `/workloads` | `WorkloadsView`, `EngineeringView`, `DeclaredWorkloadsPanel` |
| Resources / FinOps | `/resources`, optimization, allocation | Resource drawer action-safety firewall, topology, commitment ladder |
| AI data governance | `/ai/governance` | Data governance metrics (dark theme) |

Shared libraries: `lib/governance-tabs.ts`, `lib/workloads-tabs.ts`, `lib/control-plane-sync.ts`, `lib/control-plane.ts`, `lib/plan-outbox.ts`.

## Phase log (1–25)

| Phase | Theme |
| --- | --- |
| 1–5 | Control-plane plans UI, execution ladder, human approval chrome, FinOps strip foundations |
| 6–11 | Foundry probe UX, governance dark theme, data governance metrics, plan lifecycle e2e |
| 12–15 | Engineering↔governance links, URL-synced tabs, revision events, engineering sync notice |
| 16 | Spec consolidation (`enterprise-ui*.spec.ts`), worker outbox copy on execution states |
| 17–18 | Bidirectional workload links, workloads tab URLs, plan workload names |
| 19–20 | Outbox fields on plan versions, aggregates, docs, bidirectional refresh |
| 21 | Declared workload deep links, workloads URL canonicalization, extended share links |
| 22 | Typed revision `source`, governance outbox live refresh + sync notice, `/governance` → `tab=risk` |
| 23 | Shared `governance-theme-fixture.ts`, theme spec uses control-plane fixtures |
| 24 | This program doc; engineering execution-state outbox coordination copy |
| 25 | Shared `lib/plan-outbox.ts`, expandable audit-only outbox readout on plan cards |

## Verification

```bash
cd web-dashboard
npm run test:enterprise-ui
```

CI (`.github/workflows/verify.yml` dashboard job) runs the full dashboard Playwright suite via `npm run test:e2e` unless the job is split per `ENTERPRISE_UI.md`.

## Backlog (not committed)

- Dedicated read/dispatch API for per-row `engineering_outbox` in the UI (today: version-level aggregates only).
- Optional CI step split (`test:enterprise-ui` then `--project=dashboard`) — requires GitHub token with `workflow` scope to change Actions YAML.
- Migrate rich `governance.spec.ts` mocks into shared fixtures without losing role-specific scenarios.
