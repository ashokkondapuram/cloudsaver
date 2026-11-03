import {test, expect, type Page} from './test';
import {mockWorkspace, navigate} from './workspace-fixture';

const planId = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
const versionId = 'dddddddd-dddd-4ddd-8ddd-dddddddddddd';
const digest = 'e'.repeat(64);

async function mockGovernance(page: Page) {
  await page.route('**/api/v1/governance/**', async route => {
    const path = new URL(route.request().url()).pathname.replace('/api/v1/governance', '');
    if (path === '/capabilities') {
      return route.fulfill({
        json: {roles: ['ComplianceReviewer'], subject_id: 'reviewer', human: true, manage_access: false, readable: true, automatic_execution: false},
      });
    }
    if (path === '/summary') {
      return route.fulfill({
        json: {
          open_material_risks: 0,
          overdue_findings: 0,
          expiring_exceptions: 0,
          unknown_assessments: 0,
          stale_evidence: 0,
          unassigned_resources: 0,
          assessment_results: {pass: 0, fail: 0, unknown: 0, not_applicable: 0},
          monitor: null,
          warning: 'TEST FIXTURE',
          compliance_score: null,
        },
      });
    }
    if (['/controls', '/directory', '/findings', '/risks', '/exceptions', '/access'].includes(path)) {
      return route.fulfill({json: path === '/controls' ? {policy: null} : {items: []}});
    }
    return route.fulfill({status: 404, json: {detail: 'Unknown test route'}});
  });
}

test('approved plan exposes execution tracking ladder and advance to queued', async ({page}) => {
  await mockWorkspace(page, {human: true});
  let state = 'approved';
  await mockGovernance(page);
  await page.route('**/api/v1/control-plane/plans*', route => {
    if (route.request().method() !== 'GET') return route.continue();
    return route.fulfill({
      json: {items: [{id: planId, objective: 'Post-approval execution tracking', created_at: '2026-10-01T12:00:00Z'}]},
    });
  });
  await page.route(`**/api/v1/control-plane/plans/${planId}/versions*`, route =>
    route.fulfill({
      json: {
        items: [{id: versionId, plan_id: planId, version: 1, state, targets: [], parameters: {}, identity_digest: digest}],
      },
    }),
  );
  await page.route(`**/api/v1/control-plane/plan-versions/${versionId}/transitions`, route => {
    const body = route.request().postDataJSON();
    state = body.to_state;
    return route.fulfill({json: {id: versionId, plan_id: planId, version: 1, state, identity_digest: digest}});
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
