import {test, expect, type Page} from './test';
import {mockWorkspace, navigate} from './workspace-fixture';

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
    } else if (path === '/controls') {
      response = {policy: null};
    } else if (path === '/directory') {
      response = {items: []};
    } else if (path === '/findings' || path === '/risks' || path === '/exceptions' || path === '/access') {
      response = {items: []};
    } else if (path === '/summary') {
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
    } else {
      return route.fulfill({status: 404, json: {detail: 'Unknown test route'}});
    }
    await route.fulfill({json: response});
  });
  await page.route('**/api/v1/control-plane/plans*', route =>
    route.fulfill({
      json: {
        items: [
          {
            id: 'plan-1',
            objective: 'Resize batch pool after SLO review',
            created_at: '2026-10-01T12:00:00Z',
          },
        ],
      },
    }),
  );
  await page.route('**/api/v1/control-plane/plans/plan-1/versions*', route =>
    route.fulfill({
      json: {
        items: [
          {
            id: 'ver-1',
            plan_id: 'plan-1',
            version: 1,
            state: 'draft',
            identity_digest: 'f'.repeat(64),
            created_at: '2026-10-01T12:00:00Z',
          },
        ],
      },
    }),
  );
}

test('scoped workspace key disables human approval in chrome and control-plane plans', async ({page}) => {
  await mockWorkspace(page);
  await mockGovernance(page);
  await expect(page.getByText('Read/scoped key — human approval disabled')).toBeVisible();
  await navigate(page, 'Risk & compliance');
  await page.getByRole('tab', {name: 'Control-Plane Plans', exact: true}).click();
  await expect(page.getByText(/Read\/scoped workspace key — human approval disabled/)).toBeVisible();
});

test('verified human session clears control-plane approval warning', async ({page}) => {
  await mockWorkspace(page, {human: true});
  await mockGovernance(page);
  await expect(page.getByText('Verified human session')).toBeVisible();
  await navigate(page, 'Risk & compliance');
  await page.getByRole('tab', {name: 'Control-Plane Plans', exact: true}).click();
  await expect(page.getByText(/human approval disabled/i)).toHaveCount(0);
  await expect(page.getByRole('heading', {name: 'Resize batch pool after SLO review'})).toBeVisible();
});
