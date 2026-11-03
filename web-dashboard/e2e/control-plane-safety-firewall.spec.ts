import {test, expect} from './test';
import {mockWorkspace, navigate, scanId, createFindings, buildResourceItems, resourceDetail} from './workspace-fixture';

test('resource drawer exposes action-safety firewall and five-measure financial strip', async ({page}) => {
  const findings = createFindings(12);
  const row = buildResourceItems(findings).find(r => r.resource_name === 'archive-data-01')!;
  await mockWorkspace(page, {human: true});
  await page.route(`**/api/v1/scans/${scanId}/resources/${row.resource_key}`, route =>
    route.fulfill({
      json: {
        ...resourceDetail(scanId, findings, row.resource_key),
        assessment: {
          ...resourceDetail(scanId, findings, row.resource_key).assessment,
          resource_name: 'vm-protected',
          disposition: 'protected',
          protected_reasons: ['DR_STANDBY'],
        },
        costs: {
          billed_cost_usd: 100,
          effective_cost_usd: 80,
          retail_estimate_usd: 90,
          opportunity_usd: 25,
          verified_realized_savings_usd: null,
          explanation: 'fixture',
          currency: 'USD',
        },
        financial_overlaps: [],
      },
    }),
  );
  await page.route('**/api/v1/control-plane/action-assessments', route =>
    route.fulfill({
      status: 201,
      json: {
        id: 'assess-1',
        action_id: `resource:${row.resource_id}`,
        rule_version: '0.1',
        findings: {'AG-DR-01': 'fail', 'AG-COST-01': 'unknown'},
        decision: 'blocked',
        evidence_digest: 'e'.repeat(64),
        policy_digest: 'p'.repeat(64),
        created_at: '2026-10-01T12:00:00Z',
      },
    }),
  );
  await navigate(page, 'Resources');
  await page.getByRole('button', {name: 'archive-data-01 disks'}).click();
  await expect(page.locator('.financial-five-strip')).toBeVisible();
  await expect(page.getByText('30-day billed cost')).toBeVisible();
  await page.getByRole('tab', {name: 'Action safety'}).click();
  await page.getByRole('button', {name: 'Evaluate action safety'}).click();
  await expect(page.getByText('blocked')).toBeVisible();
  await expect(page.getByText('AG-DR-01')).toBeVisible();
});
