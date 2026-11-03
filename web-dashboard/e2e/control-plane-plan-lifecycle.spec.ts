import {test, expect, type Page} from './test';
import {mockWorkspace, navigate} from './workspace-fixture';

const planId = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const versionId = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
const digest = 'c'.repeat(64);

async function mockGovernance(page: Page) {
  await page.route('**/api/v1/governance/**', async route => {
    const path = new URL(route.request().url()).pathname.replace('/api/v1/governance', '');
    let response: unknown;
    if (path === '/capabilities') {
      response = {
        roles: ['ComplianceReviewer'],
        subject_id: 'reviewer',
        human: true,
        manage_access: false,
        readable: true,
        automatic_execution: false,
      };
    } else if (path === '/controls') response = {policy: null};
    else if (path === '/directory') response = {items: []};
    else if (['/findings', '/risks', '/exceptions', '/access'].includes(path)) response = {items: []};
    else if (path === '/summary') {
      response = {
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
      };
    } else return route.fulfill({status: 404, json: {detail: 'Unknown test route'}});
    await route.fulfill({json: response});
  });
}

test('human approver advances plan lifecycle and records bound approval', async ({page}) => {
  await mockWorkspace(page, {human: true});
  let state = 'assessed';
  const transitions: unknown[] = [];
  const approvals: unknown[] = [];
  await mockGovernance(page);
  await page.route('**/api/v1/control-plane/plans*', route => {
    if (route.request().method() !== 'GET') return route.continue();
    return route.fulfill({
      json: {items: [{id: planId, objective: 'Rightsize with independent approval', created_at: '2026-10-01T12:00:00Z'}]},
    });
  });
  await page.route(`**/api/v1/control-plane/plans/${planId}/versions*`, route =>
    route.fulfill({
      json: {
        items: [
          {
            id: versionId,
            plan_id: planId,
            version: 1,
            state,
            targets: ['/subscriptions/x/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1'],
            parameters: {},
            identity_digest: digest,
          },
        ],
      },
    }),
  );
  await page.route(`**/api/v1/control-plane/plan-versions/${versionId}/transitions`, route => {
    const body = route.request().postDataJSON();
    transitions.push(body);
    state = body.to_state;
    return route.fulfill({json: {id: versionId, plan_id: planId, version: 1, state, identity_digest: digest}});
  });
  await page.route(`**/api/v1/control-plane/plan-versions/${versionId}/approvals`, route => {
    approvals.push(route.request().postDataJSON());
    state = 'approved';
    return route.fulfill({status: 201, json: {id: 'approval-fixture'}});
  });
  await navigate(page, 'Risk & compliance');
  await page.getByRole('tab', {name: 'Control-Plane Plans', exact: true}).click();
  await page.getByRole('button', {name: 'Advance to review requested'}).click();
  await page.getByRole('checkbox', {name: /I reviewed the exact targets/i}).check();
  await page.getByRole('button', {name: 'Record human approval'}).click();
  expect(transitions).toEqual([{from_state: 'assessed', to_state: 'review_requested'}]);
  expect(approvals[0]).toMatchObject({identity_digest: digest});
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
