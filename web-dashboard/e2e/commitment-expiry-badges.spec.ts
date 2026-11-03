import {test, expect} from './test';
import {mockWorkspace, navigate, subscriptionId} from './workspace-fixture';

test('commitments table shows expiry threshold badges from end dates', async ({page}) => {
  await mockWorkspace(page);
  const end = new Date(Date.now() + 15 * 86400000).toISOString();
  await page.route('**/api/v1/finops/commitments', route =>
    route.fulfill({
      json: {
        items: [
          {
            provider: 'azure',
            scope_id: subscriptionId,
            commitment_id: 'res-1',
            kind: 'reservation',
            name: 'Batch VM reservation',
            status: 'active',
            end,
            utilization_percent: '72',
            commitment_amount: '1200',
            currency: 'USD',
            unused_amount: '3',
          },
        ],
        scopes: [{provider: 'azure', scope_id: subscriptionId, status: 'completed', warnings: []}],
        summary: {
          active: 1,
          total: 1,
          expiring_90_days: 1,
          average_utilization_percent: '72.0',
          unused_commitment_cost: {USD: '3.0'},
        },
      },
    }),
  );
  await navigate(page, 'Cost allocation');
  await expect(page.getByText('Batch VM reservation')).toBeVisible();
  await expect(page.locator('.state-badge.expiry-30')).toContainText('30-day expiry');
});
