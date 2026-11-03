import {type Page} from './test';

export async function mockGovernanceRoutes(page: Page) {
  await page.route('**/api/v1/governance/**', async route => {
    const path = new URL(route.request().url()).pathname.replace('/api/v1/governance', '');
    if (path === '/capabilities') {
      return route.fulfill({
        json: {
          roles: ['ComplianceReviewer'],
          subject_id: 'reviewer',
          human: true,
          manage_access: false,
          readable: true,
          automatic_execution: false,
        },
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
    if (path === '/controls') return route.fulfill({json: {policy: null}});
    if (path === '/directory') return route.fulfill({json: {items: []}});
    if (['/findings', '/risks', '/exceptions', '/access'].includes(path)) return route.fulfill({json: {items: []}});
    return route.fulfill({status: 404, json: {detail: 'Unknown test route'}});
  });
}

export type MockControlPlanePlanOptions = {
  planId: string;
  versionId: string;
  digest: string;
  initialState: string;
  objective?: string;
  targets?: string[];
  engineeringWorkloadId?: string | null;
  engineeringWorkloadName?: string | null;
  engineeringOutboxState?: 'pending' | 'published' | null;
  engineeringOutboxPendingCount?: number | (() => number);
  engineeringOutboxPublishedCount?: number | (() => number);
  engineeringOutboxItems?: Array<{
    event_id: string;
    kind: string;
    state: 'pending' | 'published';
    created_at: string;
  }>;
};

export async function mockControlPlanePlan(page: Page, options: MockControlPlanePlanOptions) {
  let state = options.initialState;
  const transitions: unknown[] = [];
  const approvals: unknown[] = [];
  const objective = options.objective ?? 'Control-plane plan fixture';
  const targets = options.targets ?? [];

  await page.route('**/api/v1/control-plane/plans*', route => {
    if (route.request().method() !== 'GET') return route.continue();
    return route.fulfill({
      json: {
        items: [
          {
            id: options.planId,
            objective,
            created_at: '2026-10-01T12:00:00Z',
            engineering_workload_id: options.engineeringWorkloadId ?? null,
            engineering_workload_name: options.engineeringWorkloadName ?? null,
          },
        ],
      },
    });
  });
  const resolveCount = (value: number | (() => number) | undefined) =>
    typeof value === 'function' ? value() : (value ?? 0);

  await page.route(`**/api/v1/control-plane/plans/${options.planId}/versions*`, route =>
    route.fulfill({
      json: {
        items: [
          {
            id: options.versionId,
            plan_id: options.planId,
            version: 1,
            state,
            targets,
            parameters: {},
            identity_digest: options.digest,
            engineering_outbox_state: options.engineeringOutboxState ?? null,
            engineering_outbox_pending_count: resolveCount(options.engineeringOutboxPendingCount),
            engineering_outbox_published_count: resolveCount(options.engineeringOutboxPublishedCount),
          },
        ],
      },
    }),
  );
  await page.route(`**/api/v1/control-plane/plan-versions/${options.versionId}/engineering-outbox*`, route =>
    route.fulfill({
      json: {
        items: options.engineeringOutboxItems ?? [],
      },
    }),
  );
  await page.route(`**/api/v1/control-plane/plan-versions/${options.versionId}/transitions`, route => {
    const body = route.request().postDataJSON();
    transitions.push(body);
    state = body.to_state;
    return route.fulfill({
      json: {id: options.versionId, plan_id: options.planId, version: 1, state, identity_digest: options.digest},
    });
  });
  await page.route(`**/api/v1/control-plane/plan-versions/${options.versionId}/approvals`, route => {
    approvals.push(route.request().postDataJSON());
    return route.fulfill({status: 201, json: {id: 'approval-fixture'}});
  });

  return {transitions, approvals};
}
