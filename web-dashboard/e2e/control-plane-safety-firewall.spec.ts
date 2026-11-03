import {test, expect} from './test';
import {mockWorkspace, navigate} from './workspace-fixture';

test('resource drawer exposes action-safety firewall and five-measure financial strip', async ({page}) => {
  await mockWorkspace(page);
  await page.route('**/api/v1/scans/*/resources/*', async route => {
    if (route.request().method() !== 'GET') return route.continue();
    return route.fulfill({
      json: {
        scan_id: 'scan-1',
        assessment: {
          resource_key: 'abc',
          resource_id: '/subscriptions/x/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1',
          resource_name: 'vm-protected',
          resource_type: 'Microsoft.Compute/virtualMachines',
          provider: 'azure',
          disposition: 'protected',
          review_priority: 'critical',
          protected_reasons: ['DR_STANDBY'],
          pillars: [{pillar: 'reliability', status: 'risk', checks: []}],
          evidence_coverage: {observed: 2, total: 5},
          observation: {status: 'recent', observed_at: '2026-10-01T12:00:00Z', max_age_hours: 24},
          guardrails: [],
          evidence_digest: 'digest',
          policy_version: '1',
          scope_id: 'sub',
          resource_group: 'rg',
        },
        findings: [],
        costs: {
          billed_cost_usd: 100,
          effective_cost_usd: 80,
          retail_estimate_usd: 90,
          opportunity_usd: 25,
          verified_realized_savings_usd: null,
          explanation: 'fixture',
          currency: 'USD',
        },
        ai: {status: 'not_run'},
        followups: [],
        followups_remaining: 5,
      },
    });
  });
  await page.route('**/api/v1/control-plane/action-assessments', async route => {
    return route.fulfill({
      status: 201,
      json: {
        id: 'assess-1',
        action_id: 'resource:/subscriptions/x/.../vm1',
        rule_version: '0.1',
        findings: {'AG-DR-01': 'fail', 'AG-COST-01': 'unknown'},
        decision: 'blocked',
        evidence_digest: 'e'.repeat(64),
        policy_digest: 'p'.repeat(64),
        created_at: '2026-10-01T12:00:00Z',
      },
    });
  });
  await navigate(page, 'Resources');
  await page.getByRole('button', {name: /vm-protected/i}).click();
  await expect(page.locator('.financial-five-strip')).toBeVisible();
  await expect(page.getByText('30-day billed cost')).toBeVisible();
  await page.getByRole('tab', {name: 'Action safety'}).click();
  await page.getByRole('button', {name: 'Evaluate action safety'}).click();
  await expect(page.getByText('blocked')).toBeVisible();
  await expect(page.getByText('AG-DR-01')).toBeVisible();
});
