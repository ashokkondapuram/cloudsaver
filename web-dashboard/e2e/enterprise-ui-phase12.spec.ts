import {test, expect} from './test';
import {mockWorkspace, navigate, scanId, subscriptionId, buildResourceItems, createFindings, tenantId} from './workspace-fixture';
import {mockControlPlanePlan, mockGovernanceRoutes} from './control-plane-fixture';

const wid = '44444444-4444-4444-8444-444444444444';
const pid = '66666666-6666-4666-8666-666666666666';
const item = buildResourceItems(createFindings())[0];

test('engineering improvement plan surfaces linked control-plane state', async ({page}) => {
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
                  objective: 'Review disk retention',
                  action: 'azure.disk.review',
                  candidate_sku: null,
                  workload_version: 1,
                  member_id: item.resource_key,
                  scan_id: scanId,
                  resource_key: item.resource_key,
                  readiness: {
                    decision: 'evidence_required',
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
    return route.fulfill({status: 404, json: {detail: 'Unknown test route'}});
  });
  await navigate(page, 'Workload assessments');
  await page.getByRole('button', {name: 'Engineering plans', exact: true}).click();
  await page.getByRole('button', {name: 'Payments · nonproduction', exact: true}).click();
  await expect(page.locator('.state-badge').filter({hasText: /assessed/i})).toBeVisible();
  await expect(page.getByRole('link', {name: /Control-Plane Plans/i})).toBeVisible();
});

test('control-plane plan cards show lifecycle state badge', async ({page}) => {
  await mockWorkspace(page, {human: true});
  await mockGovernanceRoutes(page);
  await mockControlPlanePlan(page, {
    planId: 'plan-badge',
    versionId: 'ver-badge',
    digest: 'b'.repeat(64),
    initialState: 'queued',
    objective: 'State badge visibility',
  });
  await navigate(page, 'Risk & compliance');
  await page.getByRole('tab', {name: 'Control-Plane Plans', exact: true}).click();
  await expect(page.locator('.plan-state-badge')).toContainText('queued');
});
