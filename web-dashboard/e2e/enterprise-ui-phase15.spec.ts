import {test, expect} from './test';
import {mockWorkspace, navigate} from './workspace-fixture';
import {CONTROL_PLANE_PLAN_REVISION_EVENT} from '../lib/control-plane-sync';
import {engineeringPlanId, mockEngineeringRoutes, openEngineeringWorkload} from './engineering-fixture';

test('engineering view surfaces sync notice after control-plane revision', async ({page}) => {
  await mockWorkspace(page);
  await mockEngineeringRoutes(page);
  await navigate(page, 'Workload assessments');
  await openEngineeringWorkload(page);
  await page.evaluate(
    ({eventName, planId}) => {
      window.dispatchEvent(new CustomEvent(eventName, {detail: {planId, at: Date.now()}}));
    },
    {eventName: CONTROL_PLANE_PLAN_REVISION_EVENT, planId: engineeringPlanId},
  );
  await expect(page.getByText(/Control-plane plan state changed in governance/i)).toBeVisible();
  await page.getByRole('button', {name: 'Refresh engineering records'}).click();
  await expect(page.getByText(/Control-plane plan state changed in governance/i)).toBeHidden();
});
