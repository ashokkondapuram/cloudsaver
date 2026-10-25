import {test, expect} from '@playwright/test';
import {mockWorkspace, navigate, scanId, subscriptionId, scanTime} from './workspace-fixture';
import {foundryView} from './foundry-fixture';

test('AI configuration needs explicit opt-in without enabling knowledge sharing', async ({page}) => {
  await mockWorkspace(page);
  const view = foundryView();
  const writes: {ai_foundry: typeof view.ai_foundry; version: number; acknowledge_external_processing: boolean}[] = [];
  await page.route('**/api/v1/settings/ai', async route => {
    if (route.request().method() === 'PUT') {
      const body = route.request().postDataJSON(); writes.push(body);
      view.ai_foundry = body.ai_foundry; view.version++;
      return route.fulfill({json: {version: view.version, ai_foundry: view.ai_foundry}});
    }
    return route.fulfill({json: view});
  });
  await page.goto('/settings?tab=ai');
  await expect(page.getByRole('heading', {name: 'AI Foundry configuration'})).toBeVisible();
  await page.getByLabel('Azure AI Foundry binding', {exact: true}).selectOption('review');
  const azure = page.locator('article').filter({has: page.getByRole('heading', {name: 'Azure AI Foundry', exact: true})});
  await azure.getByRole('checkbox', {name: 'Enable this provider'}).check();
  await page.getByRole('checkbox', {name: 'Enable opt-in AI advisory'}).check();
  await expect(page.getByRole('button', {name: 'Save AI configuration'})).toBeDisabled();
  await page.getByRole('checkbox', {name: /I acknowledge the selected provider/}).check();
  await page.getByRole('button', {name: 'Save AI configuration'}).click();
  await expect.poll(() => writes.length).toBe(1);
  expect(writes[0].version).toBe(1);
  expect(writes[0].acknowledge_external_processing).toBe(true);
  expect(writes[0].ai_foundry.policy.advisory_enabled).toBe(true);
  expect(writes[0].ai_foundry.policy).not.toHaveProperty('allow_anonymized_knowledge_candidates');
  expect(JSON.stringify(writes[0])).not.toContain('api_key');
  await expect(page.getByRole('checkbox', {name: /I acknowledge the selected provider/})).not.toBeChecked();
});

test('metadata diagnostics do not display invocation RBAC as verified', async ({page}) => {
  await mockWorkspace(page);
  const view = foundryView();
  view.ai_foundry.providers.azure = {...view.ai_foundry.providers.azure, ...view.catalog[0].fields, target_id: 'review'};
  await page.route('**/api/v1/settings/ai', route => route.fulfill({json: view}));
  await page.route('**/api/v1/settings/ai/test-connection', route => route.fulfill({json: {
    status: 'inconclusive', latency_ms: 3, failure_category: null, remediation_hint: 'Metadata reads do not prove inference permissions.',
    stages: [{check: 'federated_identity', status: 'verified'}, {check: 'model_invocation_permissions_and_quota', status: 'not_tested'}], inference_invoked: false}}));
  await page.goto('/settings?tab=ai');
  await page.getByRole('button', {name: 'Test Azure AI Foundry connection'}).click();
  await expect(page.getByRole('status').filter({hasText: 'inference permission unverified'})).toBeVisible();
  await expect(page.getByText('model invocation permissions and quota: not tested')).toBeVisible();
  await expect(page.getByRole('checkbox', {name: 'Enable opt-in AI advisory'})).not.toBeChecked();
});

test('viewer AI settings have no mutation or connection-check controls', async ({page}) => {
  await mockWorkspace(page, {role: 'Viewer'});
  await page.route('**/api/v1/settings/ai', route => route.fulfill({json: foundryView(false)}));
  await page.goto('/settings?tab=ai');
  await expect(page.getByLabel('Azure AI Foundry binding', {exact: true})).toBeDisabled();
  await expect(page.getByRole('button', {name: 'Save AI configuration'})).toHaveCount(0);
  await expect(page.getByRole('button', {name: /Test.*connection/})).toHaveCount(0);
});

test('resource drawer separates evidence, rules, dependencies and unknown financial fields', async ({page}) => {
  await mockWorkspace(page);
  const key = 'a'.repeat(64);
  const pillars = Object.fromEntries(['cost', 'reliability', 'performance', 'security', 'operations'].map(pillar => [pillar, 'unknown']));
  const row = {resource_key: key, provider: 'azure', resource_id: '/subscriptions/' + subscriptionId + '/disks/fixture', resource_name: 'fixture-disk',
    resource_type: 'Microsoft.Compute/disks', resource_group: 'fixture', scope_id: subscriptionId, service_category: 'storage',
    finding_count: 0, rule_ids: [], review_priority: 'evidence_required', disposition: 'inventory_only', protected_reasons: [],
    risk_level: 'unknown', risk_check_codes: [], evidence_gap_codes: [], evidence_coverage: {observed: 0, total: 0}, retail_estimate_usd: null,
    evidence_digest: 'b'.repeat(64), pillars, ai: {status: 'not_run', risk_level: null, summary: null, actions: [], assessment_id: null, created_at: null, reason: null}, decision: null};
  const detail = {scan_id: scanId, assessment: {...row, pillars: Object.keys(pillars).map(pillar => ({pillar, status: 'unknown', checks: []})),
    guardrails: [], policy_version: 'fixture', observation: {status: 'recent', observed_at: scanTime, max_age_hours: 24}},
    findings: [], ai_context: {}, ai: row.ai, ai_result: null, decision: null, followups: [], followups_remaining: 5,
    observation: {observed_at: scanTime, collector_version: 'fixture', evidence_schema_version: '2', configuration_snapshot: {}, dependency_refs: []},
    rule_evaluations: [{rule_id: 'AZURE_DISK_UNATTACHED_RETENTION', rule_version: 'fixture', outcome: 'insufficient_evidence', reason: 'Retention history is missing.'}],
    costs: {billed_cost_usd: null, retail_estimate_usd: null, modeled_future_cost_usd: null, opportunity_usd: null, verified_realized_savings_usd: null,
      explanation: 'No attributable cost evidence is available.'}, financial_overlaps: []};
  await page.route('**/api/v1/scans/*/resources**', route => route.fulfill({json: new URL(route.request().url()).pathname.endsWith('/' + key) ? detail : {
    scan_id: scanId, observed_at: scanTime, total: 1, items: [row], summary: {total: 1, ai_status: {not_run: 1}, ai_risk: {}, decision: {none: 1}, review_priority: {evidence_required: 1}}}}));
  await page.route('**/api/v1/ai-batches?*', route => route.fulfill({json: {items: []}}));
  await navigate(page, 'Resources');
  await page.getByRole('button', {name: 'View analysis for fixture-disk'}).click();
  const drawer = page.getByRole('dialog', {name: 'Resource details'});
  await expect(drawer.getByRole('tab')).toHaveCount(9);
  await drawer.getByRole('tab', {name: 'Cost', exact: true}).click();
  await expect(drawer.getByText('Unknown', {exact: true})).toHaveCount(6);
  await drawer.getByRole('tab', {name: 'Rules', exact: true}).click();
  await expect(drawer.getByText('Retention history is missing.')).toBeVisible();
  await drawer.getByRole('tab', {name: 'Dependencies', exact: true}).click();
  await expect(drawer.getByText(/No typed dependency evidence is available/)).toBeVisible();
});
