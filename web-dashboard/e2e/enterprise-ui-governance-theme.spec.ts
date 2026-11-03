import {test, expect} from './test';
import {mockWorkspace, navigate} from './workspace-fixture';
import {mockControlPlanePlan, mockGovernanceRoutes} from './control-plane-fixture';
import {mockDataGovernanceRoutes} from './governance-theme-fixture';

test('data governance workspace surfaces decision summary metrics in default dark theme', async ({page}) => {
  await mockWorkspace(page);
  await mockDataGovernanceRoutes(page);
  await navigate(page, 'AI data governance');
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  const metrics = page.locator('.data-governance-metrics');
  await expect(metrics).toBeVisible();
  await expect(metrics.getByText('12', {exact: true})).toBeVisible();
  await expect(metrics.getByText('3', {exact: true})).toBeVisible();
  await expect(metrics.getByText('Active legal holds').locator('..').getByText('1', {exact: true})).toBeVisible();
});

test('control-plane plan cards inherit dark governance surface tokens', async ({page}) => {
  await mockWorkspace(page, {human: true});
  await mockGovernanceRoutes(page);
  await mockControlPlanePlan(page, {
    planId: 'plan-dark',
    versionId: 'ver-dark',
    digest: 'd'.repeat(64),
    initialState: 'approved',
    objective: 'Dark theme plan card',
  });
  await navigate(page, 'Risk & compliance');
  await page.getByRole('tab', {name: 'Control-Plane Plans', exact: true}).click();
  const card = page.locator('.gov-risk').filter({hasText: 'Dark theme plan card'});
  await expect(card).toBeVisible();
  await expect(card.locator('.plan-step.completed')).toHaveCount(4);
  await expect(page.getByText(/plan version is approved/i)).toBeVisible();
});
