import {test, expect} from './test';
import {mockWorkspace, navigate, scanId, subscriptionId} from './workspace-fixture';

test('optimization workspace shows topology split view and latency sensitivity banner', async ({page}) => {
  await mockWorkspace(page);
  await page.route('**/api/v1/optimization/scans/' + scanId + '/auto-scenarios', route =>
    route.fulfill({
      json: {
        warning: 'No synthetic savings are generated.',
        automatic_execution: false,
        purchase_authorized: false,
        engines: {
          topology: {
            status: 'observed',
            items: [
              {
                resource_id: `/subscriptions/${subscriptionId}/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/app`,
                dependencies: [
                  {
                    from_resource_id: `/subscriptions/${subscriptionId}/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/app`,
                    to_resource_id: `/subscriptions/${subscriptionId}/resourceGroups/rg/providers/Microsoft.Sql/servers/db`,
                    relationship: 'depends_on',
                    verification_state: 'verified',
                  },
                ],
              },
            ],
          },
          slo: {
            status: 'observed',
            items: [
              {
                resource_id: `/subscriptions/${subscriptionId}/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/app`,
                cpu_latency_pearson: 0.82,
                blocked_by_latency_sensitivity: true,
              },
            ],
          },
        },
      },
    }),
  );
  await navigate(page, 'Optimization evidence');
  await expect(page.locator('.slo-correlation-banner.blocked-latency')).toContainText('BLOCKED_BY_LATENCY_SENSITIVITY');
  await expect(page.locator('.topology-split-view')).toBeVisible();
  await expect(page.getByText('1 edges')).toBeVisible();
});

test('cost allocation exposes commitment ladder preview with purchase disabled', async ({page}) => {
  await mockWorkspace(page);
  await page.route('**/api/v1/finops/commitment-ladder/preview*', route =>
    route.fulfill({
      json: {
        status: 'computed',
        purchase_authorized: false,
        baseline: {recommended_new_commitment_hr: '7'},
        steps: [
          {quarter: 1, step_pct: '25', recommended_new_commitment_hr: '1.75', purchase_authorized: false, status: 'scenario', ladder_note: 'Q1 tranche'},
          {quarter: 2, step_pct: '50', recommended_new_commitment_hr: '3.50', purchase_authorized: false, status: 'scenario', ladder_note: 'Q2 tranche'},
          {quarter: 3, step_pct: '75', recommended_new_commitment_hr: '5.25', purchase_authorized: false, status: 'scenario', ladder_note: 'Q3 tranche'},
        ],
      },
    }),
  );
  await navigate(page, 'Cost allocation');
  await page.getByRole('button', {name: 'Preview ladder'}).click();
  await expect(page.getByText('purchase_authorized: false')).toBeVisible();
  await expect(page.locator('.commitment-ladder-grid')).toContainText('1.75');
});

test('agent workspace surfaces drift abort banner when permit_status is ABORTED_STATE_DRIFT', async ({page}) => {
  const id = '88888888-8888-4888-8888-888888888888';
  const resourceId = `/subscriptions/${subscriptionId}/resourceGroups/rg/providers/Microsoft.Compute/disks/d1`;
  await mockWorkspace(page, {human: true});
  await page.route('**/api/v1/agents/catalog', route => route.fulfill({json: {enabled: true, connectors: []}}));
  await page.route('**/api/v1/agents/tasks', route =>
    route.fulfill({
      json: {
        items: [
          {
            id,
            resource_id: resourceId,
            state: 'needs_reconciliation',
            version: 2,
            created_at: '2026-10-22T15:30:00Z',
            payload: {intent: 'Drift blocked task', permit_status: 'ABORTED_STATE_DRIFT', plan: {summary: 'Blocked', steps: []}, steps: []},
            events: [],
          },
        ],
      },
    }),
  );
  await page.route('**/api/v1/agents/tasks/' + id, route =>
    route.fulfill({
      json: {
        id,
        resource_id: resourceId,
        state: 'needs_reconciliation',
        version: 2,
        payload: {intent: 'Drift blocked task', permit_status: 'ABORTED_STATE_DRIFT', plan: {summary: 'Blocked', steps: []}, steps: []},
        events: [],
      },
    }),
  );
  await navigate(page, 'Agent workspace');
  await page.getByRole('button', {name: /Drift blocked task/}).click();
  await expect(page.locator('.drift-abort-banner')).toContainText('ABORTED_STATE_DRIFT');
});

test('gitops package preview loads AST HCL mapping for selected resource', async ({page}) => {
  await mockWorkspace(page);
  const resourceId = `/subscriptions/${subscriptionId}/resourceGroups/platform/providers/Microsoft.Compute/disks/archive-data-01`;
  await page.route('**/api/v1/gitops/resource-mapping*', route =>
    route.fulfill({
      json: {
        cloud_resource_id: resourceId,
        repository: 'example/infrastructure',
        file_path: 'modules/compute/main.tf',
        iac_kind: 'terraform',
        start_line: 12,
        end_line: 28,
        indexed_commit_sha: 'abc123def456',
        address: 'azurerm_linux_virtual_machine.vm1',
      },
    }),
  );
  await navigate(page, 'Automation');
  await page.getByRole('checkbox', {name: /archive-data-01/}).check();
  await page.getByRole('button', {name: 'Preview review package', exact: true}).click();
  await expect(page.locator('.hcl-diff-container')).toContainText('modules/compute/main.tf');
  await expect(page.locator('.hcl-diff-pre')).toContainText('vm1');
});

test('observability sync now polls job status until completion', async ({page}) => {
  await mockWorkspace(page);
  let polls = 0;
  const connector = {
    id: '55555555-5555-4555-8555-555555555555',
    name: 'Fixture Prometheus',
    kind: 'prometheus',
    base_url: 'https://prometheus.example.com',
    auth_kind: 'none',
    secret_ref: null,
    header_name: null,
    aws_account_id: null,
    gcp_project_id: null,
    queries: [],
    services: [],
    schedule: 'hourly',
    trace_window_hours: 1,
    mappings: {},
    thresholds: {latency_p95_ms: 500, error_rate_pct: 1},
    enabled: true,
    version: 1,
    updated_at: '2026-10-01T12:00:00Z',
  };
  await page.route('**/api/v1/observability/connectors', route => route.fulfill({json: {items: [connector]}}));
  await page.route('**/api/v1/observability/summary', route => route.fulfill({json: {items: [{id: connector.id, status: 'completed', observed_at: '2026-10-01T12:00:00Z'}]}}));
  await page.route('**/api/v1/observability/sync', route =>
    route.fulfill({status: 202, json: {status: 'queued', job_id: '77777777-7777-4777-8777-777777777777'}}),
  );
  await page.route('**/api/v1/observability/sync-jobs/77777777-7777-4777-8777-777777777777', route => {
    polls++;
    return route.fulfill({json: {status: polls >= 2 ? 'completed' : 'running'}});
  });
  await navigate(page, 'Settings');
  await page.getByRole('tab', {name: 'Integrations', exact: true}).click();
  await page.getByRole('button', {name: 'Sync now'}).click();
  await expect(page.getByText(/Observability sync completed/i)).toBeVisible({timeout: 20000});
  expect(polls).toBeGreaterThanOrEqual(2);
});
