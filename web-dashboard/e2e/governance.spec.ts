import {test, expect} from './test';
import AxeBuilder from '@axe-core/playwright';
import {
  governanceBusinessOwnerId,
  governanceFindingId,
  governanceOwnerId,
  governanceResourceId,
  setupGovernanceWorkflow,
} from './governance-workflow-fixture';

test('auditor mobile dashboard preserves uncertainty and seven accessible workflow views', async ({page}) => {
  await page.setViewportSize({width: 390, height: 844});
  const mutations = await setupGovernanceWorkflow(page);
  await expect(page.getByRole('heading', {name: 'Risk & compliance', exact: true})).toBeVisible();
  const tabs = page.getByRole('tablist', {name: 'Risk and compliance workflows'});
  await expect(tabs.getByRole('tab')).toHaveCount(8);
  await tabs.getByRole('tab', {name: 'Risk register', exact: true}).focus();
  await page.keyboard.press('End');
  await expect(tabs.getByRole('tab', {name: 'Audit exports', exact: true})).toBeFocused();
  const download = page.waitForEvent('download');
  await page.getByRole('button', {name: 'Download audit package', exact: true}).click();
  expect((await download).suggestedFilename()).toBe(`cloudsaver-governance-${governanceFindingId}.json`);
  await tabs.getByRole('tab', {name: 'Evidence', exact: true}).click();
  await expect(page.getByText(/Configuration evidence cannot determine historical data exposure/)).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  const audit = await new AxeBuilder({page}).include('main').withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze();
  expect(audit.violations).toEqual([]);
  expect(mutations).toEqual([]);
});

test('a change approver explicitly reviews the exact plan and cannot close a proposed issue', async ({page}) => {
  const mutations = await setupGovernanceWorkflow(page, {roles: ['ChangeApprover']});
  await page.getByRole('tab', {name: 'Approvals', exact: true}).click();
  await page.getByRole('button', {name: 'Review finding', exact: true}).click();
  const drawer = page.getByRole('dialog', {name: 'Governance finding review'});
  await expect(drawer.getByRole('heading', {name: 'Exact reviewed change plan'})).toBeVisible();
  await expect(drawer.getByRole('button', {name: 'Approve verified closure'})).toHaveCount(0);
  const approve = drawer.getByRole('button', {name: 'Approve bound change plan', exact: true});
  await expect(approve).toBeDisabled();
  await drawer.getByLabel('Decision / investigation note', {exact: true}).fill('Reviewed the exact target, dependencies and rollback.');
  await drawer.getByLabel('I reviewed the exact resource, target configuration, dependencies, validation and rollback.').check();
  await approve.click();
  await expect(drawer.getByText('Approved · revision 4', {exact: true})).toBeVisible();
  expect((mutations[0].body as {action: string}).action).toBe('approve');
  expect((mutations[0].body as {version: number}).version).toBe(3);
  const audit = await new AxeBuilder({page}).include('dialog[open]').withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze();
  expect(audit.violations).toEqual([]);
});

test('security analyst confirms classification and named owners before creating an issue', async ({page}) => {
  const mutations = await setupGovernanceWorkflow(page, {roles: ['SecurityAnalyst']});
  await page.getByRole('tab', {name: 'Findings', exact: true}).click();
  await page.getByText('Assess an observed storage account', {exact: true}).click();
  await page.getByRole('combobox', {name: 'Storage account from selected scan', exact: true}).selectOption(governanceResourceId);
  await page.getByLabel('Application', {exact: true}).fill('payments');
  await page.getByRole('combobox', {name: 'Environment', exact: true}).selectOption('production');
  await page.getByRole('combobox', {name: 'Data classification', exact: true}).selectOption('customer_data');
  await page.getByRole('combobox', {name: 'Technical owner', exact: true}).selectOption(governanceOwnerId);
  await page.getByRole('combobox', {name: 'Business risk owner', exact: true}).selectOption(governanceBusinessOwnerId);
  await page.getByLabel('Business-context confirmation', {exact: true}).fill('Application owner confirmed the customer-data context.');
  await page.getByRole('button', {name: 'Evaluate technical control', exact: true}).click();
  await expect(page.getByRole('dialog', {name: 'Governance finding review'})).toBeVisible();
  expect((mutations[0].body as {context: {technical_owner: string}}).context.technical_owner).toBe(governanceOwnerId);
  expect((mutations[0].body as {context: {classification: string}}).context.classification).toBe('customer_data');
  expect(mutations[0].body as Record<string, unknown>).not.toHaveProperty('compliant');
});

test('accepted-risk decision remains separate from failed technical control', async ({page}) => {
  const mutations = await setupGovernanceWorkflow(page, {roles: ['BusinessRiskOwner']});
  await page.getByRole('tab', {name: 'Exceptions', exact: true}).click();
  await page.getByLabel('Exception decision note', {exact: true}).fill('Authorized within documented senior risk delegation.');
  await page.getByRole('button', {name: 'Authorize time-limited risk', exact: true}).click();
  await expect(page.getByText(/Accepted by business-owner/)).toBeVisible();
  expect((mutations[0].body as {action: string}).action).toBe('approve');
  await page.getByRole('tab', {name: 'Evidence', exact: true}).click();
  await expect(page.locator('.gov-assessment-counts .gov-fail')).toHaveText('Fail');
});

test('keys and automation cannot exercise human approval controls', async ({page}) => {
  const mutations = await setupGovernanceWorkflow(page, {roles: ['ChangeApprover'], human: false});
  await page.getByRole('tab', {name: 'Approvals', exact: true}).click();
  await page.getByRole('button', {name: 'Review finding', exact: true}).click();
  const drawer = page.getByRole('dialog', {name: 'Governance finding review'});
  await expect(drawer.getByRole('button', {name: 'Approve bound change plan', exact: true})).toBeDisabled();
  expect(mutations).toEqual([]);
});

test('control policy revision submits reviewed inputs without read-only server metadata', async ({page}) => {
  const mutations = await setupGovernanceWorkflow(page, {roles: ['ComplianceReviewer']});
  await page.getByRole('tab', {name: 'Controls', exact: true}).click();
  await page.getByText('Review a new control-policy version', {exact: true}).click();
  await page.getByRole('textbox', {name: 'Policy applicability and risk-appetite rationale', exact: true}).fill(
    'The compliance reviewer confirmed this organizational policy revision.',
  );
  await page.getByRole('button', {name: 'Publish reviewed policy version', exact: true}).click();
  await expect(page.getByText(/New immutable control policy reviewed/)).toBeVisible();
  const submitted = mutations.find(m => m.path === '/controls')!;
  expect(submitted.body as Record<string, unknown>).not.toHaveProperty('id');
  expect(submitted.body as Record<string, unknown>).not.toHaveProperty('control_key');
  expect((submitted.body as {version: number}).version).toBe(1);
});
