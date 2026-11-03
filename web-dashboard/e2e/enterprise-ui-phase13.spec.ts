import {test, expect} from './test';
import {mockWorkspace, navigate} from './workspace-fixture';
import {mockControlPlanePlan, mockGovernanceRoutes} from './control-plane-fixture';
import {engineeringPlanId, mockEngineeringRoutes, openEngineeringWorkload} from './engineering-fixture';

const deepPlanId = 'plan-deep-link-13';

test('governance deep link opens control-plane tab and highlights plan', async ({page}) => {
  await mockWorkspace(page, {human: true});
  await mockGovernanceRoutes(page);
  await mockControlPlanePlan(page, {
    planId: deepPlanId,
    versionId: 'ver-deep-13',
    digest: 'c'.repeat(64),
    initialState: 'review_requested',
    objective: 'Deep link highlight target',
  });
  await page.goto(`/governance?tab=control-plane&plan=${encodeURIComponent(deepPlanId)}`);
  await expect(page.getByRole('tab', {name: 'Control-Plane Plans', exact: true})).toHaveAttribute('aria-selected', 'true');
  await expect(page.getByText(/Focused plan from a shared link/i)).toBeVisible();
  const card = page.locator(`#control-plane-plan-${deepPlanId}`);
  await expect(card).toBeVisible();
  await expect(card).toHaveClass(/plan-card-highlight/);
  await expect(card.getByRole('heading', {name: /Deep link highlight target/i})).toBeVisible();
});

test('engineering plan links to governance with plan query', async ({page}) => {
  await mockWorkspace(page);
  await mockEngineeringRoutes(page, {readinessDecision: 'ready_with_gaps', objective: 'Resize archive VM disks'});
  await navigate(page, 'Workload assessments');
  await openEngineeringWorkload(page);
  const link = page.getByRole('link', {name: /Control-Plane Plans/i});
  await expect(link).toHaveAttribute('href', `/governance?tab=control-plane&plan=${encodeURIComponent(engineeringPlanId)}`);
});
