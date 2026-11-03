import {test, expect} from './test';
import {mockWorkspace, navigate} from './workspace-fixture';
import {mockControlPlanePlan, mockGovernanceRoutes} from './control-plane-fixture';

test('admin marks queued plan version expired', async ({page}) => {
  await mockWorkspace(page, {human: true});
  await mockGovernanceRoutes(page);
  const {transitions} = await mockControlPlanePlan(page, {
    planId: '77777777-7777-4777-8777-777777777777',
    versionId: '66666666-6666-4666-8666-666666666666',
    digest: 'd'.repeat(64),
    initialState: 'queued',
    objective: 'Expire after queue without run',
  });
  await navigate(page, 'Risk & compliance');
  await page.getByRole('tab', {name: 'Control-Plane Plans', exact: true}).click();
  await page.getByRole('button', {name: 'Mark expired'}).click();
  await expect(page.getByText(/plan version is expired/i)).toBeVisible();
  await expect(page.getByRole('button', {name: 'Advance to running'})).toHaveCount(0);
  expect(transitions).toEqual([{from_state: 'queued', to_state: 'expired'}]);
});

test('admin returns review requested plan to assessed before approval', async ({page}) => {
  await mockWorkspace(page, {human: true});
  await mockGovernanceRoutes(page);
  const {transitions} = await mockControlPlanePlan(page, {
    planId: '55555555-5555-4555-8555-555555555555',
    versionId: '44444444-4444-4444-8444-444444444444',
    digest: 'e'.repeat(64),
    initialState: 'review_requested',
    objective: 'Rollback review gate',
  });
  await navigate(page, 'Risk & compliance');
  await page.getByRole('tab', {name: 'Control-Plane Plans', exact: true}).click();
  await page.getByRole('button', {name: 'Return to assessed'}).click();
  await expect(page.locator('.plan-step.current')).toContainText('assessed');
  expect(transitions).toEqual([{from_state: 'review_requested', to_state: 'assessed'}]);
});

test('control-plane plans link to declared workloads view', async ({page}) => {
  await mockWorkspace(page, {human: true});
  await mockGovernanceRoutes(page);
  await page.route('**/api/v1/outcomes/ownership', route => route.fulfill({json: {items: []}}));
  await page.route('**/api/v1/engineering/workloads*', route => route.fulfill({json: {items: [], next_cursor: null}}));
  await mockControlPlanePlan(page, {
    planId: 'plan-link',
    versionId: 'ver-link',
    digest: 'a'.repeat(64),
    initialState: 'draft',
    objective: 'Cross-link fixture',
  });
  await navigate(page, 'Risk & compliance');
  await page.getByRole('tab', {name: 'Control-Plane Plans', exact: true}).click();
  await page.getByRole('link', {name: 'declared engineering workloads'}).click();
  await expect(page).toHaveURL(/\/workloads/);
});
