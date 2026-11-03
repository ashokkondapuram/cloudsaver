import {test, expect} from './test';
import {mockWorkspace, navigate} from './workspace-fixture';
import {mockControlPlanePlan, mockGovernanceRoutes} from './control-plane-fixture';

const planId = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
const versionId = 'dddddddd-dddd-4ddd-8ddd-dddddddddddd';
const digest = 'e'.repeat(64);

test('approved plan exposes execution tracking ladder and advance to queued', async ({page}) => {
  await mockWorkspace(page, {human: true});
  await mockGovernanceRoutes(page);
  await mockControlPlanePlan(page, {
    planId,
    versionId,
    digest,
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

test('foundry probe surfaces failure category when metadata check fails', async ({page}) => {
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
