import {test, expect} from './test';
import {mockWorkspace, navigate} from './workspace-fixture';
import {mockControlPlanePlan, mockGovernanceRoutes} from './control-plane-fixture';

test('admin returns assessed plan to evidence required', async ({page}) => {
  await mockWorkspace(page, {human: true});
  await mockGovernanceRoutes(page);
  const {transitions} = await mockControlPlanePlan(page, {
    planId: '33333333-3333-4333-8333-333333333334',
    versionId: '44444444-4444-4444-8444-444444444445',
    digest: 'f'.repeat(64),
    initialState: 'assessed',
    objective: 'Rollback evidence gate',
  });
  await navigate(page, 'Risk & compliance');
  await page.getByRole('tab', {name: 'Control-Plane Plans', exact: true}).click();
  await page.getByRole('button', {name: 'Return to evidence required'}).click();
  await expect(page.locator('.plan-step.current')).toContainText('evidence required');
  expect(transitions).toEqual([{from_state: 'assessed', to_state: 'evidence_required'}]);
});
