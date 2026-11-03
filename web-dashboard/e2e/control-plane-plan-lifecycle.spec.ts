import {test, expect} from './test';
import {mockWorkspace, navigate} from './workspace-fixture';
import {mockControlPlanePlan, mockGovernanceRoutes} from './control-plane-fixture';

const planId = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const versionId = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
const digest = 'c'.repeat(64);

test('human approver advances plan lifecycle and records bound approval', async ({page}) => {
  await mockWorkspace(page, {human: true});
  await mockGovernanceRoutes(page);
  const {transitions, approvals} = await mockControlPlanePlan(page, {
    planId,
    versionId,
    digest,
    initialState: 'assessed',
    objective: 'Rightsize with independent approval',
    targets: ['/subscriptions/x/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1'],
  });
  await navigate(page, 'Risk & compliance');
  await page.getByRole('tab', {name: 'Control-Plane Plans', exact: true}).click();
  await page.getByRole('button', {name: 'Advance to review requested'}).click();
  await page.getByRole('checkbox', {name: /I reviewed the exact targets/i}).check();
  await page.getByRole('button', {name: 'Record human approval'}).click();
  await expect(page.getByText(/plan version is approved/i)).toBeVisible();
  expect(transitions).toEqual([
    {from_state: 'assessed', to_state: 'review_requested'},
    {from_state: 'review_requested', to_state: 'approved'},
  ]);
  expect(approvals[0]).toMatchObject({identity_digest: digest});
  await expect(page.locator('.plan-step.completed')).toHaveCount(4);
  await expect(page.locator('.plan-step.current')).toContainText('approved');
});

test('foundry connection probe renders ordered metadata stages', async ({page}) => {
  await mockWorkspace(page);
  await page.route('**/api/v1/settings/ai', route =>
    route.fulfill({
      json: {
        version: 1,
        editable: true,
        plan_allowed: true,
        directory_mode: 'tenant',
        ai_foundry: {
          providers: {azure: {enabled: false, target_id: 'review'}, aws: {enabled: false, target_id: null}, gcp: {enabled: false, target_id: null}},
          policy: {
            advisory_enabled: false,
            routing_mode: 'same_cloud_only',
            max_input_tokens_per_request: 4000,
            max_output_tokens_per_request: 2000,
            hourly_attempt_budget: 10,
            monthly_token_limit: null,
          },
        },
        catalog: [
          {
            provider: 'azure',
            target_id: 'review',
            model: 'gpt-4o',
            fields: {endpoint_url: 'https://example.openai.azure.com', deployment_name: 'review'},
            auth: 'managed_identity',
            privacy_attestation: 'TEST FIXTURE',
          },
        ],
        platform_policy: {
          version: 1,
          policy: {enabled: true, disabled_providers: [], max_input_tokens_per_request: 8000, max_output_tokens_per_request: 4000, hourly_attempt_ceiling: 20, monthly_token_ceiling: 1000000},
        },
        usage: null,
        diagnostics: [],
        message: 'TEST FIXTURE',
        knowledge_retrieval: 'disabled',
      },
    }),
  );
  await page.route('**/api/v1/settings/ai/test-connection', route =>
    route.fulfill({
      json: {
        status: 'inconclusive',
        latency_ms: 4,
        failure_category: null,
        remediation_hint: 'Metadata reads do not prove inference permissions.',
        stages: [
          {check: 'federated_identity', status: 'verified'},
          {check: 'deployment_metadata', status: 'verified'},
          {check: 'model_invocation_permissions_and_quota', status: 'not_tested'},
        ],
        inference_invoked: false,
      },
    }),
  );
  await page.goto('/settings?tab=ai');
  await page.getByRole('button', {name: 'Test Azure AI Foundry connection'}).click();
  await expect(page.locator('.foundry-probe-stages')).toBeVisible();
  await expect(page.locator('.foundry-probe-stage')).toHaveCount(3);
  await expect(page.getByText('Model invocation permissions and quota')).toBeVisible();
});
