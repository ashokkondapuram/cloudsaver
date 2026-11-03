import {test, expect} from './test';
import {mockWorkspace, navigate, scanTime} from './workspace-fixture';
import {mockControlPlanePlan, mockGovernanceRoutes} from './control-plane-fixture';

test.describe('Control-plane plan lifecycle', () => {
  test('approved plan exposes execution tracking ladder and advance to queued', async ({page}) => {
    await mockWorkspace(page, {human: true});
    await mockGovernanceRoutes(page);
    await mockControlPlanePlan(page, {
      planId: 'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
      versionId: 'dddddddd-dddd-4ddd-8ddd-dddddddddddd',
      digest: 'e'.repeat(64),
      initialState: 'approved',
      objective: 'Post-approval execution tracking',
    });
    await navigate(page, 'Risk & compliance');
    await page.getByRole('tab', {name: 'Control-Plane Plans', exact: true}).click();
    await expect(page.getByText('Execution tracking (no automatic cloud mutations)')).toBeVisible();
    await page.getByRole('button', {name: 'Advance to queued'}).click();
    await expect(page.getByText(/Execution states are recorded for audit/i)).toBeVisible();
    await expect(page.locator('.plan-execution-stepper .plan-step.current')).toContainText('queued');
  });

  test('admin advances execution ladder through verified', async ({page}) => {
    await mockWorkspace(page, {human: true});
    await mockGovernanceRoutes(page);
    const {transitions} = await mockControlPlanePlan(page, {
      planId: 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee',
      versionId: 'ffffffff-ffff-4fff-8fff-ffffffffffff',
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

  test('admin records failed execution and advances to reconciliation required', async ({page}) => {
    await mockWorkspace(page, {human: true});
    await mockGovernanceRoutes(page);
    const {transitions} = await mockControlPlanePlan(page, {
      planId: '11111111-1111-4111-8111-111111111112',
      versionId: '22222222-2222-4222-8222-222222222223',
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

  test('admin can cancel an assessed plan version without advancing review', async ({page}) => {
    await mockWorkspace(page, {human: true});
    await mockGovernanceRoutes(page);
    const {transitions} = await mockControlPlanePlan(page, {
      planId: '99999999-9999-4999-8999-999999999999',
      versionId: '88888888-8888-4888-8888-888888888888',
      digest: 'b'.repeat(64),
      initialState: 'assessed',
      objective: 'Cancel before independent review',
    });
    await navigate(page, 'Risk & compliance');
    await page.getByRole('tab', {name: 'Control-Plane Plans', exact: true}).click();
    await page.getByRole('button', {name: 'Cancel plan version'}).click();
    await expect(page.getByText(/plan version is cancelled/i)).toBeVisible();
    await expect(page.getByRole('button', {name: 'Advance to review requested'})).toHaveCount(0);
    expect(transitions).toEqual([{from_state: 'assessed', to_state: 'cancelled'}]);
  });

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
    await expect(page.getByText(/Worker outbox dispatch is not surfaced/i)).toBeVisible();
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
