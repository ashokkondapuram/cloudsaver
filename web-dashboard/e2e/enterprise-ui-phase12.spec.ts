import {test, expect} from './test';
import {mockWorkspace, navigate} from './workspace-fixture';
import {mockControlPlanePlan, mockGovernanceRoutes} from './control-plane-fixture';
import {mockEngineeringRoutes, openEngineeringWorkload} from './engineering-fixture';

test('engineering improvement plan surfaces linked control-plane state', async ({page}) => {
  await mockWorkspace(page);
  await mockEngineeringRoutes(page);
  await navigate(page, 'Workload assessments');
  await openEngineeringWorkload(page);
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
