import {test, expect, type Page} from './test';
import {mockWorkspace, navigate, scanTime} from './workspace-fixture';

const attempt = '77777777-7777-4777-8777-777777777777';

function governanceView() {
  return {
    policy: {
      status: 'enforced',
      policy_revision: 4,
      environment_id: 'company-production',
      response_retention_days: 7,
      processors: [
        {
          target_id: 'approved-review',
          deployment_name: 'company-review',
          endpoint_url: 'https://company.openai.azure.com',
          azure_resource_id: '/subscriptions/synthetic/resourceGroups/rg/providers/Microsoft.CognitiveServices/accounts/company',
          purposes: ['assessment'],
          review_reference: 'DATA-REVIEW-42',
          review_expires_at: '2026-12-01T00:00:00Z',
        },
      ],
    },
    records: [{attempt_id: attempt, purpose: 'assessment', expires_at: '2026-10-31T00:00:00Z', erased_at: null as string | null}],
    active_holds: [{attempt_id: attempt, hold_until: '2026-11-15T00:00:00Z', review_reference: 'LEGAL-1'}],
    events: [{id: 'review-1', purpose: 'assessment', decision: 'blocked', reason: 'SECRET_DETECTED', created_at: scanTime, actor_reference: 'a'.repeat(64)}],
    counts: {allowed: 12, blocked: 3, erased: 1},
  };
}

async function mockDataGovernance(page: Page) {
  await page.route('**/api/v1/ai/governance', route => route.fulfill({json: governanceView()}));
}

test('data governance workspace surfaces decision summary metrics in default dark theme', async ({page}) => {
  await mockWorkspace(page);
  await mockDataGovernance(page);
  await navigate(page, 'AI data governance');
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  const metrics = page.locator('.data-governance-metrics');
  await expect(metrics).toBeVisible();
  await expect(metrics.getByText('12', {exact: true})).toBeVisible();
  await expect(metrics.getByText('3', {exact: true})).toBeVisible();
  await expect(metrics.getByText('Active legal holds').locator('..').getByText('1', {exact: true})).toBeVisible();
});

test('control-plane plan cards inherit dark governance surface tokens', async ({page}) => {
  await mockWorkspace(page, {human: true});
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
  await page.route('**/api/v1/control-plane/plans*', route =>
    route.fulfill({
      json: {items: [{id: 'plan-dark', objective: 'Dark theme plan card', created_at: '2026-10-01T12:00:00Z'}]},
    }),
  );
  await page.route('**/api/v1/control-plane/plans/plan-dark/versions*', route =>
    route.fulfill({
      json: {
        items: [
          {
            id: 'ver-dark',
            plan_id: 'plan-dark',
            version: 1,
            state: 'approved',
            targets: [],
            parameters: {},
            identity_digest: 'd'.repeat(64),
          },
        ],
      },
    }),
  );
  await navigate(page, 'Risk & compliance');
  await page.getByRole('tab', {name: 'Control-Plane Plans', exact: true}).click();
  const card = page.locator('.gov-risk').filter({hasText: 'Dark theme plan card'});
  await expect(card).toBeVisible();
  await expect(card.locator('.plan-step.completed')).toHaveCount(4);
  await expect(page.getByText(/plan version is approved/i)).toBeVisible();
});
