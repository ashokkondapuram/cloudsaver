import {type Page} from './test';
import {buildResourceItems, createFindings, scanId, subscriptionId, tenantId} from './workspace-fixture';

export const engineeringWorkloadId = '44444444-4444-4444-8444-444444444444';
export const engineeringPlanId = '66666666-6666-4666-8666-666666666666';

type PlanStateSource = string | (() => string);

export type MockEngineeringRoutesOptions = {
  workloadId?: string;
  planId?: string;
  planState?: PlanStateSource;
  objective?: string;
  readinessDecision?: string;
  onPlansRequest?: () => void;
};

export async function mockEngineeringRoutes(page: Page, options: MockEngineeringRoutesOptions = {}) {
  const wid = options.workloadId ?? engineeringWorkloadId;
  const pid = options.planId ?? engineeringPlanId;
  const objective = options.objective ?? 'Review disk retention';
  const readinessDecision = options.readinessDecision ?? 'evidence_required';
  const memberId = buildResourceItems(createFindings())[0].resource_key;
  const planStateSource = options.planState ?? 'assessed';
  const resolvePlanState = () => (typeof planStateSource === 'function' ? planStateSource() : planStateSource);

  await page.route('**/api/v1/outcomes/ownership', route => route.fulfill({json: {items: []}}));
  await page.route('**/api/v1/engineering/**', async route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/capabilities')) {
      return route.fulfill({
        json: {
          stage: 'local_review',
          scopes: [{scope_id: subscriptionId}],
          actions: [{id: 'azure.disk.review', mode: 'review_only'}],
          acceptance_required: [],
        },
      });
    }
    if (path === '/api/v1/engineering/workloads') {
      return route.fulfill({
        json: {
          items: [
            {
              id: wid,
              tenant_id: tenantId,
              name: 'Payments',
              environment: 'nonproduction',
              owner: 'Platform owner',
              team: 'Engineering',
              scope_id: subscriptionId,
              provider: 'azure',
              version: 1,
              requirements: {},
            },
          ],
          next_cursor: null,
        },
      });
    }
    if (path.endsWith('/members')) return route.fulfill({json: {items: [], next_cursor: null}});
    if (path.endsWith('/events')) return route.fulfill({json: {items: [], next_cursor: null}});
    if (path.endsWith('/plans')) {
      options.onPlansRequest?.();
      return route.fulfill({
        json: {
          items: [
            {
              id: pid,
              latest: {
                id: '77777777-7777-4777-8777-777777777777',
                plan_id: pid,
                version: 2,
                identity_digest: 'a'.repeat(64),
                state: resolvePlanState(),
                execution_enabled: false,
                context_changed: false,
                workload_id: wid,
                created_at: '2026-10-28T12:00:00Z',
                parameters: {
                  schema_version: 1,
                  objective,
                  action: 'azure.disk.review',
                  candidate_sku: null,
                  workload_version: 1,
                  member_id: memberId,
                  scan_id: scanId,
                  resource_key: memberId,
                  readiness: {
                    decision: readinessDecision,
                    evaluated_at: '2026-10-28T12:00:00Z',
                    checks: [{code: 'ATTACHMENT_HISTORY', status: 'unknown', reason: 'fixture'}],
                  },
                },
              },
            },
          ],
          next_cursor: null,
        },
      });
    }
    if (path === `/api/v1/engineering/workloads/${wid}`) {
      return route.fulfill({
        json: {
          id: wid,
          tenant_id: tenantId,
          name: 'Payments',
          environment: 'nonproduction',
          owner: 'Platform owner',
          team: 'Engineering',
          scope_id: subscriptionId,
          provider: 'azure',
          version: 1,
          requirements: {},
        },
      });
    }
    return route.fulfill({status: 404, json: {detail: 'Unknown test route'}});
  });
}

export async function openEngineeringWorkload(page: Page, workloadLabel = 'Payments · nonproduction') {
  await page.getByRole('button', {name: 'Engineering plans', exact: true}).click();
  await page.getByRole('button', {name: workloadLabel, exact: true}).click();
}
