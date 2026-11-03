import {test, expect} from './test';
import {mockWorkspace, navigate} from './workspace-fixture';
import {CONTROL_PLANE_PLAN_REVISION_EVENT} from '../lib/control-plane-sync';
import {mockControlPlanePlan, mockGovernanceRoutes} from './control-plane-fixture';
import {engineeringPlanId, mockEngineeringRoutes, openEngineeringWorkload} from './engineering-fixture';

test('governance tab clicks sync tab query in the URL', async ({page}) => {
  await mockWorkspace(page, {human: true});
  await mockGovernanceRoutes(page);
  await navigate(page, 'Risk & compliance');
  await page.getByRole('tab', {name: 'Findings', exact: true}).click();
  await expect(page).toHaveURL(/tab=findings/);
  await page.getByRole('tab', {name: 'Controls', exact: true}).click();
  await expect(page).toHaveURL(/tab=controls/);
  await mockControlPlanePlan(page, {
    planId: 'plan-focus',
    versionId: 'ver-focus',
    digest: 'd'.repeat(64),
    initialState: 'assessed',
    objective: 'Plan focus fixture',
  });
  await page.goto('/governance?tab=control-plane&plan=plan-focus');
  await expect(page.getByRole('tab', {name: 'Control-Plane Plans', exact: true})).toHaveAttribute('aria-selected', 'true');
  await page.getByRole('tab', {name: 'Approvals', exact: true}).click();
  await expect(page).toHaveURL(/tab=approvals/);
  await expect(page).not.toHaveURL(/plan=/);
});

test('engineering plans refetch when control-plane revision is signaled', async ({page}) => {
  let planState = 'assessed';
  let planFetchCount = 0;
  await mockWorkspace(page);
  await mockEngineeringRoutes(page, {
    planState: () => planState,
    onPlansRequest: () => {
      planFetchCount += 1;
    },
  });
  await navigate(page, 'Workload assessments');
  await openEngineeringWorkload(page);
  await expect(page.locator('.state-badge').filter({hasText: /assessed/i})).toBeVisible();
  planState = 'review_requested';
  await page.evaluate(
    ({eventName, planId}) => {
      window.dispatchEvent(new CustomEvent(eventName, {detail: {planId, at: Date.now()}}));
    },
    {eventName: CONTROL_PLANE_PLAN_REVISION_EVENT, planId: engineeringPlanId},
  );
  await expect(page.locator('.state-badge').filter({hasText: /review requested/i})).toBeVisible();
  expect(planFetchCount).toBeGreaterThanOrEqual(2);
});
