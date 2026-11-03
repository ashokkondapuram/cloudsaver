import {test, expect} from './test';
import {mockWorkspace, navigate, scanId, createFindings, buildResourceItems, resourceDetail} from './workspace-fixture';

test('absorption proven drives commitment-aware scenario on the five-measure strip', async ({page}) => {
  const findings = createFindings(12);
  const row = buildResourceItems(findings).find(r => r.resource_name === 'archive-data-01')!;
  await mockWorkspace(page, {human: true});
  let posted: Record<string, unknown> | null = null;
  await page.route('**/api/v1/control-plane/financial-scenarios', route => {
    posted = route.request().postDataJSON();
    const absorbed = posted?.absorption_proven === true;
    return route.fulfill({
      status: 201,
      json: {
        id: 'scenario-fixture',
        status: 'computed',
        currency: 'USD',
        net_recurring_benefit: absorbed ? '25.00' : '0.00',
        result: {status: 'computed', net_recurring_benefit: absorbed ? '25.00' : '0.00'},
      },
    });
  });
  await page.route(`**/api/v1/scans/${scanId}/resources/${row.resource_key}`, route =>
    route.fulfill({
      json: {
        ...resourceDetail(scanId, findings, row.resource_key),
        costs: {
          billed_cost_usd: 100,
          effective_cost_usd: 80,
          retail_estimate_usd: 90,
          opportunity_usd: 25,
          verified_realized_savings_usd: null,
          explanation: 'fixture',
          currency: 'USD',
        },
        financial_overlaps: [],
      },
    }),
  );
  await navigate(page, 'Resources');
  await page.getByRole('button', {name: 'archive-data-01 disks'}).click();
  await page.getByRole('tab', {name: 'Costs', exact: true}).click();
  await expect(page.locator('.financial-five-strip')).toBeVisible();
  await page.getByRole('checkbox', {name: /Absorption proven/}).check();
  await page.getByRole('button', {name: 'Run commitment-aware scenario'}).click();
  await expect(page.locator('.financial-five-strip .highlight-avoidable')).toContainText('$25.00');
  expect(posted).not.toBeNull();
  const scenarioBody = posted as unknown as Record<string, unknown>;
  expect(scenarioBody.absorption_proven).toBe(true);
  expect(scenarioBody.uncommitted_if_absorbed).toBe('0.00');
});
