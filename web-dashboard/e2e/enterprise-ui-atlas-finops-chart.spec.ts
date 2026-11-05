import {test, expect} from './test';
import {mockWorkspace, navigate, subscriptionId} from './workspace-fixture';

test('cost allocation renders AnalyticsChart from finops daily series', async ({page}) => {
  await mockWorkspace(page);
  await page.route('**/api/v1/finops/summary*', route =>
    route.fulfill({
      json: {
        currency: 'USD',
        records: 42,
        billed_cost: '22.50',
        effective_cost: '20.00',
        list_cost: null,
        effective_savings_rate_pct: null,
        excluded_overlapping_records: 0,
        warning: 'TEST FIXTURE: Billing evidence for chart pilot.',
        daily: [
          {date: '2026-10-01', billed_cost: '10.00', complete: true},
          {date: '2026-10-02', billed_cost: '12.50', complete: true},
        ],
        forecast: null,
        anomaly: null,
        providers: [],
      },
    }),
  );
  await page.addInitScript(() => {
    document.documentElement.dataset.uiPreset = 'atlas';
  });
  await navigate(page, 'Cost allocation');
  const chart = page.locator('.analytics-chart');
  await expect(chart).toBeVisible();
  await expect(chart.getByRole('heading', {name: 'Daily billed cost trend'})).toBeVisible();
  await expect(chart.locator('.analytics-chart-table table')).toBeVisible();
  await expect(chart.locator('tbody tr')).toHaveCount(2);
});
