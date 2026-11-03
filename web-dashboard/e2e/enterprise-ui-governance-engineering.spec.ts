import {test, expect} from './test';
import {mockWorkspace, navigate} from './workspace-fixture';
import {CONTROL_PLANE_PLAN_REVISION_EVENT} from '../lib/control-plane-sync';
import {mockControlPlanePlan, mockGovernanceRoutes} from './control-plane-fixture';
import {
  engineeringPlanId,
  engineeringWorkloadId,
  mockEngineeringRoutes,
  openEngineeringWorkload,
} from './engineering-fixture';

const deepPlanId = 'plan-deep-link-13';

test.describe('Engineering ↔ governance cross-links', () => {
  test('engineering improvement plan surfaces linked control-plane state', async ({page}) => {
    await mockWorkspace(page);
    await mockEngineeringRoutes(page);
    await navigate(page, 'Workload assessments');
    await openEngineeringWorkload(page);
    await expect(page.locator('.state-badge').filter({hasText: /assessed/i})).toBeVisible();
    await expect(page.getByRole('link', {name: /Control-Plane Plans/i})).toBeVisible();
  });

  test('engineering plan links to governance with plan query', async ({page}) => {
    await mockWorkspace(page);
    await mockEngineeringRoutes(page, {readinessDecision: 'ready_with_gaps', objective: 'Resize archive VM disks'});
    await navigate(page, 'Workload assessments');
    await openEngineeringWorkload(page);
    const link = page.getByRole('link', {name: /Control-Plane Plans/i});
    await expect(link).toHaveAttribute('href', `/governance?tab=control-plane&plan=${encodeURIComponent(engineeringPlanId)}`);
  });

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
  });

  test('control-plane plan links to engineering workload when link metadata is present', async ({page}) => {
    await mockWorkspace(page, {human: true});
    await mockGovernanceRoutes(page);
    await mockEngineeringRoutes(page);
    await mockControlPlanePlan(page, {
      planId: engineeringPlanId,
      versionId: '77777777-7777-4777-8777-777777777777',
      digest: 'a'.repeat(64),
      initialState: 'assessed',
      objective: 'Review disk retention',
      engineeringWorkloadId: engineeringWorkloadId,
      engineeringWorkloadName: 'Payments',
    });
    await navigate(page, 'Risk & compliance');
    await page.getByRole('tab', {name: 'Control-Plane Plans', exact: true}).click();
    await page.getByRole('link', {name: /Open linked engineering workload \(Payments\)/i}).click();
    await expect(page).toHaveURL(/tab=engineering/);
    await expect(page.getByRole('button', {name: 'Engineering plans', exact: true})).toHaveAttribute('aria-pressed', 'true');
    await expect(page.locator(`#engineering-plan-${engineeringPlanId}`)).toHaveClass(/plan-card-highlight/);
  });
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
  await page.getByRole('button', {name: 'Dismiss', exact: true}).click();
  await expect(page.getByText(/Control-plane plan state changed in governance/i)).toBeHidden();
});

test('workloads tab clicks sync tab query and clears engineering deep-link params', async ({page}) => {
  await mockWorkspace(page);
  await mockEngineeringRoutes(page);
  await navigate(page, 'Workload assessments');
  await page.getByRole('button', {name: 'Declared workloads', exact: true}).click();
  await expect(page).toHaveURL(/tab=declared/);
  await page.getByRole('button', {name: 'Engineering plans', exact: true}).click();
  await expect(page).toHaveURL(/tab=engineering/);
  await page.goto(
    `/workloads?tab=engineering&workload=${encodeURIComponent(engineeringWorkloadId)}&plan=${encodeURIComponent(engineeringPlanId)}`,
  );
  await page.getByRole('button', {name: 'Saved assessments', exact: true}).click();
  await expect(page).toHaveURL(/tab=assessments/);
  await expect(page).not.toHaveURL(/plan=/);
  await expect(page).not.toHaveURL(/workload=/);
});
