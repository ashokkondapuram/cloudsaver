import {test, expect} from './test';
import {mockWorkspace, navigate} from './workspace-fixture';
import {mockControlPlanePlan, mockGovernanceRoutes} from './control-plane-fixture';

const planId = '11111111-1111-4111-8111-111111111112';
const versionId = '22222222-2222-4222-8222-222222222223';

test('admin records failed execution and advances to reconciliation required', async ({page}) => {
  await mockWorkspace(page, {human: true});
  await mockGovernanceRoutes(page);
  const {transitions} = await mockControlPlanePlan(page, {
    planId,
    versionId,
    digest: 'a'.repeat(64),
    initialState: 'running',
    objective: 'Execution failure recovery path',
  });
  await navigate(page, 'Risk & compliance');
  await page.getByRole('tab', {name: 'Control-Plane Plans', exact: true}).click();
  await page.getByRole('button', {name: 'Record failed outcome'}).click();
  await expect(page.locator('.plan-step.plan-step-failed')).toContainText('running');
  await page.getByRole('button', {name: 'Advance to reconciliation required'}).click();
  await expect(page.locator('.plan-step.plan-step-warning')).toContainText('verification pending');
  await expect(page.getByText(/no further execution transitions apply/i)).toBeVisible();
  expect(transitions).toEqual([
    {from_state: 'running', to_state: 'failed'},
    {from_state: 'failed', to_state: 'reconciliation_required'},
  ]);
});
