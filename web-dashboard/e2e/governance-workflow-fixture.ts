import {type Page} from './test';
import {mockWorkspace, navigate, scanId, scanTime, subscriptionId} from './workspace-fixture';

export const governanceFindingId = '77777777-7777-4777-8777-777777777777';
export const governanceRiskId = '88888888-8888-4888-8888-888888888888';
export const governanceExceptionId = '99999999-9999-4999-8999-999999999999';
export const governanceOwnerId = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
export const governanceBusinessOwnerId = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
export const governanceResourceId = `/subscriptions/${subscriptionId}/resourceGroups/qa/providers/Microsoft.Storage/storageAccounts/customer`;

export type GovernanceWorkflowSetupOptions = {
  roles?: string[];
  human?: boolean;
  state?: string;
};

/** Role-rich governance mocks used by dashboard (non-enterprise-ui) workflow specs. */
export async function setupGovernanceWorkflow(page: Page, options: GovernanceWorkflowSetupOptions = {}) {
  await mockWorkspace(page, {role: 'Viewer', human: options.human ?? true});
  const mutations: {path: string; body: unknown}[] = [];
  const context = {
    application: 'payments',
    environment: 'production',
    classification: 'customer_data',
    technical_owner: governanceOwnerId,
    business_owner: governanceBusinessOwnerId,
    rationale: 'Application owner reviewed the production customer-data classification.',
  };
  const policy = {
    id: 'server-read-only-policy-id',
    control_key: 'AZ-STORAGE-PUBLIC-BLOB-ACCESS',
    version: 1,
    owner: 'verifier',
    mandatory_obligation: false,
    risk_appetite: 6,
    maximum_exception_days: 7,
    rationale: 'TEST FIXTURE: reviewed discretionary organizational policy.',
    mappings: [] as unknown[],
  };
  const assessment = {
    result: 'fail',
    reason: 'ACCOUNT_PERMITS_PUBLIC_BLOB_ACCESS',
    state_digest: 'a'.repeat(64),
    scan_id: scanId,
    observed_at: scanTime,
    configuration: {allow_blob_public_access: true},
    limitation: 'Account permission is not proof that a container is public or that customer data was accessed.',
  };
  let finding: Record<string, unknown> = {
    id: governanceFindingId,
    state: options.state || 'proposed',
    version: 3,
    created_at: scanTime,
    updated_at: scanTime,
    payload: {
      resource_name: 'customer',
      resource_id: governanceResourceId,
      provider: 'azure',
      scope_id: subscriptionId,
      context,
      control: policy,
      original_assessment: assessment,
      assessment,
      risk_id: governanceRiskId,
      severity: 'critical',
      due_date: '2026-10-26',
      plan: {
        digest: 'b'.repeat(64),
        change_reference: 'CHG-42',
        steps: ['Disable account public blob access for the exact storage account.'],
        dependency_checks: ['Confirm authenticated application dependency access.'],
        validation_steps: ['Re-read configuration and test legitimate authenticated application access.'],
        rollback_plan: 'Any rollback requires a separately reviewed and approved change.',
        desired_configuration: {allow_blob_public_access: false},
      },
      approval: null,
      implementation: null,
      verification: null,
    },
    events: [],
    evidence: [],
    assessment_fresh: true,
  };
  let exception: Record<string, unknown> = {
    id: governanceExceptionId,
    state: 'reviewed',
    version: 2,
    payload: {
      finding_id: governanceFindingId,
      risk_id: governanceRiskId,
      justification: 'Migration requires a reviewed short transition window.',
      rejected_alternatives: 'Immediate shutdown was rejected after continuity review.',
      compensating_controls: 'Reviewed network filtering and monitored access.',
      remediation_plan: 'Complete migration, then disable public access.',
      start: '2026-10-25T00:00:00Z',
      end: '2026-10-27T00:00:00Z',
      review_at: '2026-10-26T00:00:00Z',
      review_trigger: 'Review on any network or application change.',
      requested_by: governanceOwnerId,
      review: {subject_id: 'security', note: 'Reviewed compensation.'},
      approval: null,
    },
  };
  await page.route(`**/api/v1/scans/${scanId}/resources?**`, route =>
    route.fulfill({
      json: {
        items: [
          {
            resource_id: governanceResourceId,
            resource_name: 'customer',
            resource_type: 'Microsoft.Storage/storageAccounts',
            provider: 'azure',
          },
        ],
      },
    }),
  );
  await page.route('**/api/v1/governance/**', async route => {
    const req = route.request();
    const path = new URL(req.url()).pathname.replace('/api/v1/governance', '');
    const body = req.method() === 'GET' ? null : req.postDataJSON();
    if (body) mutations.push({path, body});
    let response: unknown;
    if (path === '/capabilities') {
      response = {
        roles: options.roles || ['Auditor'],
        subject_id: options.roles?.includes('ResourceOwner')
          ? governanceOwnerId
          : options.roles?.includes('BusinessRiskOwner')
            ? governanceBusinessOwnerId
            : 'reviewer',
        human: options.human ?? true,
        manage_access: false,
        readable: true,
        automatic_execution: false,
      };
    } else if (path === '/controls') response = {policy};
    else if (path === '/directory') {
      response = {
        items: [
          {subject_id: governanceOwnerId, alias: 'platform-owner', roles: ['ResourceOwner']},
          {subject_id: governanceBusinessOwnerId, alias: 'business-owner', roles: ['BusinessRiskOwner']},
          {subject_id: 'verifier', alias: 'control-owner', roles: ['ComplianceReviewer']},
        ],
      };
    } else if (path === '/findings') response = {items: [finding]};
    else if (path === '/risks') {
      response = {
        items: [
          {
            id: governanceRiskId,
            state: 'active',
            version: 1,
            payload: {
              statement: 'Potential disclosure of customer data through public storage configuration.',
              treatment_plan: 'Apply the reviewed private-access configuration and verify legitimate access.',
              business_owner: governanceBusinessOwnerId,
              finding_ids: [governanceFindingId],
              inherent_score: 20,
              residual_score: 4,
              material: true,
              review_date: '2026-11-20',
            },
          },
        ],
      };
    } else if (path === '/exceptions') response = {items: [exception]};
    else if (path === '/summary') {
      response = {
        open_material_risks: 1,
        overdue_findings: 0,
        expiring_exceptions: 1,
        unknown_assessments: 1,
        stale_evidence: 0,
        unassigned_resources: 0,
        assessment_results: {pass: 0, fail: 1, unknown: 1, not_applicable: 0},
        monitor: {checked_at: scanTime, findings_checked: 1, changed: 0},
        warning: 'Technical assessments are not organizational compliance.',
        compliance_score: null,
      };
    } else if (path === `/findings/${governanceFindingId}`) response = finding;
    else if (path === `/findings/${governanceFindingId}/actions`) {
      finding = {
        ...finding,
        state: (body as {action: string}).action === 'approve' ? 'approved' : finding.state,
        version: (finding.version as number) + 1,
      };
      response = finding;
    } else if (path === '/assessments') {
      finding = {
        ...finding,
        state: 'triage',
        version: 1,
        payload: {...(finding.payload as Record<string, unknown>), risk_id: null, plan: null},
      };
      response = {assessment, finding};
    } else if (path === `/exceptions/${governanceExceptionId}/actions`) {
      exception = {
        ...exception,
        state: 'approved',
        version: 3,
        payload: {
          ...(exception.payload as Record<string, unknown>),
          approval: {subject_id: governanceBusinessOwnerId, authority_reference: 'RISK-AUTH-42'},
        },
      };
      response = exception;
    } else if (path === `/findings/${governanceFindingId}/export`) {
      response = {
        format: 'cloudsaver-governance-audit-v1',
        technical_only: true,
        content: {finding},
        manifest: {finding: 'c'.repeat(64)},
      };
    } else if (path === '/monitor') {
      response = {
        checked_at: scanTime,
        findings_checked: 1,
        changed: 0,
        external_notifications_sent: 0,
        automatic_execution: false,
      };
    } else throw new Error('Unmocked governance path ' + path);
    await route.fulfill({json: response});
  });
  await navigate(page, 'Risk & compliance');
  return mutations;
}
