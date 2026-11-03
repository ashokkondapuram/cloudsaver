import {test, expect, type Page} from './test';
import {mockWorkspace, navigate} from './workspace-fixture';
import {mockControlPlanePlan, mockGovernanceRoutes} from './control-plane-fixture';

async function mockPlans(page: Page) {
  await mockGovernanceRoutes(page);
  await mockControlPlanePlan(page, {
    planId: 'plan-1',
    versionId: 'ver-1',
    digest: 'f'.repeat(64),
    initialState: 'draft',
    objective: 'Resize batch pool after SLO review',
  });
}

test('scoped workspace key disables human approval in chrome and control-plane plans', async ({page}) => {
  await mockWorkspace(page);
  await mockPlans(page);
  await expect(page.getByText('Read/scoped key — human approval disabled')).toBeVisible();
  await navigate(page, 'Risk & compliance');
  await page.getByRole('tab', {name: 'Control-Plane Plans', exact: true}).click();
  await expect(page.getByText(/Read\/scoped workspace key — human approval disabled/)).toBeVisible();
});

test('verified human session clears control-plane approval warning', async ({page}) => {
  await mockWorkspace(page, {human: true});
  await mockPlans(page);
  await expect(page.getByText('Verified human session')).toBeVisible();
  await navigate(page, 'Risk & compliance');
  await page.getByRole('tab', {name: 'Control-Plane Plans', exact: true}).click();
  await expect(page.getByText(/human approval disabled/i)).toHaveCount(0);
  await expect(page.getByRole('heading', {name: 'Resize batch pool after SLO review'})).toBeVisible();
});
