import {test, expect} from './test';
import {mockWorkspace, navigate, tenantId, subscriptionId} from './workspace-fixture';

const workloadId = '44444444-4444-4444-8444-444444444444';

test('declared workloads tab surfaces version for If-Match fencing', async ({page}) => {
  await mockWorkspace(page);
  await page.route('**/api/v1/outcomes/ownership', route =>
    route.fulfill({json: {items: [], basis: 'current_direct_resource_mapping'}}),
  );
  await page.route('**/api/v1/engineering/workloads*', route => {
    if (route.request().method() !== 'GET') return route.continue();
    return route.fulfill({
      json: {
        items: [
          {
            id: workloadId,
            tenant_id: tenantId,
            name: 'Payments',
            environment: 'production',
            owner: 'Platform owner',
            team: 'Engineering',
            scope_id: subscriptionId,
            provider: 'azure',
            version: 3,
            requirements: {slo_reference: 'SLO-42', recovery_reference: 'DR-9'},
          },
        ],
        next_cursor: null,
      },
    });
  });
  await navigate(page, 'Workload assessments');
  await page.getByRole('button', {name: 'Declared workloads', exact: true}).click();
  await expect(page.getByRole('columnheader', {name: 'Version (If-Match)'})).toBeVisible();
  await expect(page.getByText('Payments')).toBeVisible();
  await expect(page.locator('code', {hasText: 'v3'})).toBeVisible();
});
