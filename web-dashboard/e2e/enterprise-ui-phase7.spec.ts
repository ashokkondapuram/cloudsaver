import {test, expect} from './test';
import {mockWorkspace, navigate, scanTime} from './workspace-fixture';
import {mockControlPlanePlan, mockGovernanceRoutes} from './control-plane-fixture';

const planId = 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee';
const versionId = 'ffffffff-ffff-4fff-8fff-ffffffffffff';

test('admin advances execution ladder through verified', async ({page}) => {
  await mockWorkspace(page, {human: true});
  await mockGovernanceRoutes(page);
  const {transitions} = await mockControlPlanePlan(page, {
    planId,
    versionId,
    digest: 'f'.repeat(64),
    initialState: 'approved',
    objective: 'Full execution tracking walkthrough',
  });
  await navigate(page, 'Risk & compliance');
  await page.getByRole('tab', {name: 'Control-Plane Plans', exact: true}).click();
  for (const label of ['Advance to queued', 'Advance to running', 'Advance to verification pending', 'Advance to verified']) {
    await page.getByRole('button', {name: label}).click();
  }
  await expect(page.getByText(/Verification completed for this plan version/i)).toBeVisible();
  await expect(page.locator('.plan-execution-stepper .plan-step.current')).toContainText('verified');
  await expect(page.locator('.plan-execution-stepper .plan-step.completed')).toHaveCount(3);
  expect(transitions).toEqual([
    {from_state: 'approved', to_state: 'queued'},
    {from_state: 'queued', to_state: 'running'},
    {from_state: 'running', to_state: 'verification_pending'},
    {from_state: 'verification_pending', to_state: 'verified'},
  ]);
});

test('data processor review expiry badge highlights renewals within 30 days', async ({page}) => {
  await mockWorkspace(page);
  await page.route('**/api/v1/ai/governance', route =>
    route.fulfill({
      json: {
        policy: {
          status: 'enforced',
          policy_revision: 2,
          environment_id: 'company-production',
          response_retention_days: 7,
          processors: [
            {
              target_id: 'expiring-review',
              deployment_name: 'review',
              endpoint_url: 'https://company.openai.azure.com',
              azure_resource_id: '/subscriptions/synthetic/resourceGroups/rg/providers/Microsoft.CognitiveServices/accounts/company',
              purposes: ['assessment'],
              review_reference: 'DATA-RENEW-1',
              review_expires_at: '2026-11-15T00:00:00Z',
            },
          ],
        },
        records: [],
        active_holds: [],
        events: [{id: 'e1', purpose: 'assessment', decision: 'allowed', reason: 'ok', created_at: scanTime, actor_reference: 'a'.repeat(64)}],
        counts: {allowed: 1, blocked: 0, erased: 0},
      },
    }),
  );
  await navigate(page, 'AI data governance');
  await expect(page.getByRole('cell').filter({hasText: 'Review in'})).toBeVisible();
  await expect(page.getByText('DATA-RENEW-1')).toBeVisible();
});
