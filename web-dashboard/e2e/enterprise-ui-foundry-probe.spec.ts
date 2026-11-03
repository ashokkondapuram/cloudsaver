import {test, expect} from './test';
import {mockWorkspace} from './workspace-fixture';

const aiSettingsFixture = {
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
};

test.describe('AI Foundry connection probe', () => {
  test('surfaces failure category when metadata check fails', async ({page}) => {
    await mockWorkspace(page);
    await page.route('**/api/v1/settings/ai', route => route.fulfill({json: aiSettingsFixture}));
    await page.route('**/api/v1/settings/ai/test-connection', route =>
      route.fulfill({
        json: {
          status: 'failed',
          latency_ms: 12,
          failure_category: 'deployment_not_found',
          remediation_hint: 'Verify deployment name and endpoint URL.',
          stages: [{check: 'federated_identity', status: 'verified'}, {check: 'deployment_metadata', status: 'failed', reason: '404 from metadata read'}],
          inference_invoked: false,
        },
      }),
    );
    await page.goto('/settings?tab=ai');
    await page.getByRole('button', {name: 'Test Azure AI Foundry connection'}).click();
    await expect(page.locator('.foundry-probe-failure')).toContainText(/deployment not found/i);
  });

  test('labels metadata-only vs inference-invoked probes', async ({page}) => {
    await mockWorkspace(page);
    await page.route('**/api/v1/settings/ai', route => route.fulfill({json: aiSettingsFixture}));
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
});
