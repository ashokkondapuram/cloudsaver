import {test, expect} from './test';
import {mockWorkspace, navigate} from './workspace-fixture';
import {mockControlPlanePlan, mockGovernanceRoutes} from './control-plane-fixture';

const planId = '99999999-9999-4999-8999-999999999999';
const versionId = '88888888-8888-4888-8888-888888888888';

test('admin can cancel an assessed plan version without advancing review', async ({page}) => {
  await mockWorkspace(page, {human: true});
  await mockGovernanceRoutes(page);
  const {transitions} = await mockControlPlanePlan(page, {
    planId,
    versionId,
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

test('foundry probe labels metadata-only vs inference-invoked probes', async ({page}) => {
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
        status: 'verified',
        latency_ms: 8,
        failure_category: null,
        remediation_hint: 'Probe invoked a minimal inference call.',
        stages: [{check: 'federated_identity', status: 'verified'}, {check: 'model_invocation_permissions_and_quota', status: 'verified'}],
        inference_invoked: true,
      },
    }),
  );
  await page.goto('/settings?tab=ai');
  await page.getByRole('button', {name: 'Test Azure AI Foundry connection'}).click();
  await expect(page.getByText('Inference invoked during probe')).toBeVisible();
});
