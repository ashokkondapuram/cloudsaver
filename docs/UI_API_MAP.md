# Web dashboard → API map

Browser calls use `fetch('/api/v1' + path)` via `lib/api.ts` unless noted. Wire URLs prefix paths below with `/api/v1`.

Maintained from dashboard source; run `scripts/audit_workspace_api.py` for smoke checks against a live workspace.

## Global (`WorkspaceProvider`, `AppShell`)

| Surface | Method + path | Source |
|---------|---------------|--------|
| Session | GET `/me`, `/scans`, `/billing/entitlements` | `WorkspaceProvider.tsx` |
| New scan | POST `/scans/multi-cloud` | `WorkspaceProvider.tsx` |
| Reliability | GET `/operations/reliability` | `AppShell.tsx` |

## Pages

| Route | Key APIs | Source |
|-------|----------|--------|
| `/` | GET `/scans/{scanId}/resources?…` | `Overview.tsx`, `resource-pages.ts` |
| `/resources` | GET `/scans/{scanId}/resources`, GET `/ai-batches`, POST `/scans/{scanId}/ai-batches` | `ResourcesView.tsx`, `resources.ts` |
| `/resources/report` | GET `/scans/{scanId}/resources` (full) | `ResourcesView.tsx` |
| `/allocation` | GET `/finops/summary`, `/imports`, `/sync-status`; POST `/finops/sync`, `/imports` | `EnterpriseEvidence.tsx`, `V150Views.tsx` |
| `/automation` | GET/POST `/gitops/*`, POST `/policies/terraform/evaluate` | `GitOpsPanel.tsx`, `V150Views.tsx` |
| `/activity` | GET `/operations/reliability`, `/operations/deliveries*`; GET `/ai/assessments`, `/ai/usage` | `ReliabilityPanel.tsx`, `EnterpriseEvidence.tsx` |
| `/settings` | GET/PUT `/settings`, `/rules/*`, `/observability/*`, `/settings/ai`, `/ai/governance`, `/customer/*` | settings components |
| `/workloads` | GET `/outcomes/ownership`, `/engineering/*`, `/scans/{scanId}/resources` | `WorkloadsView.tsx`, `EngineeringView.tsx` |
| `/governance` | GET/POST `/governance/*`, `/control-plane/*` | `GovernanceWorkspace.tsx` |
| `/outcomes` | GET/POST `/outcomes/*` | `OutcomesWorkspace.tsx` |
| `/optimization` | GET `/optimization/scans/{scanId}/auto-scenarios` | `OptimizationEvidenceWorkspace.tsx` |
| `/agents` | GET/POST `/agents/*` | `AgentWorkspace.tsx` |
| `/kubernetes` | GET `/scans/{scanId}/kubernetes`; POST `…/patch-preview` | `KubernetesWorkspace.tsx` |
| `/services/[service]` | GET `/scans/{scanId}/analysis`, `/services/{service}?scan_id=` | `ServiceAnalysis.tsx`, `V150Views.tsx` |
| `/claim` | POST `/onboarding/claim` | `ClaimView.tsx` |

## Resource drawer tabs

| Tab | APIs | Source |
|-----|------|--------|
| Load | GET `/scans/{scanId}/resources/{resourceKey}` | `ResourceDrawer.tsx` |
| Costs | GET `/finops/azure-resource-costs`; POST `/finops/resource-cost` | `ResourceDrawer.tsx` |
| Costs / safety scenarios | POST `/control-plane/financial-scenarios`, `/control-plane/action-assessments` | `FinancialFiveStrip.tsx`, `ActionSafetyPanel.tsx` |
| AI | POST `/scans/{scanId}/resources/{resourceKey}/questions`; GET `/ai/targets` | `ResourceDrawer.tsx` |
| Decision | POST `/resources/{resourceKey}/decisions` | `ResourceDrawer.tsx` |
| History | GET `/resources/{resourceKey}/history` | `ResourceDrawer.tsx` |
| Evidence / rules / findings | Payload fields: `rule_matches`, `rule_conflicts`, `ai_context`, `findings` | same GET detail |

Detail response should include `assessment`, `findings`, `ai_context`, `rule_matches`, `rule_conflicts` (see `scripts/audit_workspace_api.py`).

## Route inventory

All scanner + gateway + agent gateway routes are classified in `app/route_inventory.py`. Internal agent routes (`/internal/v1/agent/*`) mount only on `services/agent_gateway.py`; see `tests/test_route_inventory.py`.
