import {type Page} from './test';
import {scanTime} from './workspace-fixture';

export const dataGovernanceAttemptId = '77777777-7777-4777-8777-777777777777';

export function dataGovernanceView() {
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
          azure_resource_id:
            '/subscriptions/synthetic/resourceGroups/rg/providers/Microsoft.CognitiveServices/accounts/company',
          purposes: ['assessment'],
          review_reference: 'DATA-REVIEW-42',
          review_expires_at: '2026-12-01T00:00:00Z',
        },
      ],
    },
    records: [
      {
        attempt_id: dataGovernanceAttemptId,
        purpose: 'assessment',
        expires_at: '2026-10-31T00:00:00Z',
        erased_at: null as string | null,
      },
    ],
    active_holds: [{attempt_id: dataGovernanceAttemptId, hold_until: '2026-11-15T00:00:00Z', review_reference: 'LEGAL-1'}],
    events: [
      {
        id: 'review-1',
        purpose: 'assessment',
        decision: 'blocked',
        reason: 'SECRET_DETECTED',
        created_at: scanTime,
        actor_reference: 'a'.repeat(64),
      },
    ],
    counts: {allowed: 12, blocked: 3, erased: 1},
  };
}

export async function mockDataGovernanceRoutes(page: Page) {
  await page.route('**/api/v1/ai/governance', route => route.fulfill({json: dataGovernanceView()}));
}
