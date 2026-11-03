import {test, expect} from './test';
import {mockWorkspace, navigate, scanId, subscriptionId, buildResourceItems, createFindings, tenantId} from './workspace-fixture';
import {mockControlPlanePlan, mockGovernanceRoutes} from './control-plane-fixture';

const wid = '44444444-4444-4444-8444-444444444444';
const pid = '66666666-6666-4666-8666-666666666666';
const deepPlanId = 'plan-deep-link-13';

test('governance deep link opens control-plane tab and highlights plan', async ({page}) => {
  await mockWorkspace(page, {human: true});
  await mockGovernanceRoutes(page);
  await mockControlPlanePlan(page, {
    planId: deepPlanId,
    versionId: 'ver-deep-13',
    digest: 'c'.repeat(64),
    initialState: 'review_requested',
    objective: 'Deep link highlight target',
  });
  await page.goto(`/governance?tab=control-plane&plan=${encodeURIComponent(deepPlanId)}`);
  await expect(page.getByRole('tab', {name: 'Control-Plane Plans', exact: true})).toHaveAttribute('aria-selected', 'true');
  await expect(page.getByText(/Focused plan from a shared link/i)).toBeVisible();
  const card = page.locator(`#control-plane-plan-${deepPlanId}`);
  await expect(card).toBeVisible();
  await expect(card).toHaveClass(/plan-card-highlight/);
  await expect(card.getByRole('heading', {name: /Deep link highlight target/i})).toBeVisible();
});

test('engineering plan links to governance with plan query', async ({page}) => {
  await mockWorkspace(page);
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
    if (path.endsWith(wid) && !path.includes('/members')) {
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
    if (path.endsWith('/members')) return route.fulfill({json: {items: [], next_cursor: null}});
    if (path.endsWith('/events')) return route.fulfill({json: {items: [], next_cursor: null}});
    if (path.endsWith('/plans')) {
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
                state: 'assessed',
                execution_enabled: false,
                context_changed: false,
                workload_id: wid,
                created_at: '2026-10-28T12:00:00Z',
                parameters: {
                  schema_version: 1,
                  objective: 'Resize archive VM disks',
                  action: 'azure.disk.review',
                  candidate_sku: null,
                  member_id: '88888888-8888-4888-8888-888888888888',
                  scan_id: scanId,
                  readiness: {
                    decision: 'ready_with_gaps',
                    evaluated_at: '2026-10-28T12:00:00Z',
                    checks: [{code: 'observation_freshness', status: 'pass', reason: 'Recent scan'}],
                  },
                },
              },
            },
          ],
          next_cursor: null,
        },
      });
    }
    return route.fulfill({status: 404, json: {detail: 'Unknown test route'}});
  });
  await navigate(page, 'Workload assessments');
  await page.getByRole('button', {name: 'Engineering plans', exact: true}).click();
  await page.getByRole('button', {name: 'Payments · nonproduction', exact: true}).click();
  const link = page.getByRole('link', {name: /Control-Plane Plans/i});
  await expect(link).toHaveAttribute('href', `/governance?tab=control-plane&plan=${encodeURIComponent(pid)}`);
});
