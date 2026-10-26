import {test, expect} from './test';
import {mockWorkspace, navigate} from './workspace-fixture';

const rule = {id: 'AZURE_DISK_UNATTACHED_RETENTION', name: 'Retained unattached disk review',
  provider: 'azure', resource_type: 'microsoft.compute/disks', description: 'History is required.',
  enabled: true, status: 'published', parameters: {minimum_days: 14}, unavailable_reason: null,
  allowed_override_bounds: {minimum_days: {minimum: 7, maximum: 90}}};

test('rule changes require a saved-observation preview before applying', async ({page}) => {
  await mockWorkspace(page);
  const requests: {method: string; body: unknown}[] = [];
  let current = {...rule};
  await page.route('**/api/v1/rules/**', async route => {
    const request = route.request(), method = request.method();
    if (method !== 'GET') requests.push({method, body: request.postDataJSON()});
    if (request.url().endsWith('/preview')) return route.fulfill({json: {version: 1, scan_id: 'saved', resources_changed: 1, message: 'Saved observation only.'}});
    if (method === 'PUT') current = {...current, enabled: false};
    return route.fulfill({json: {version: method === 'PUT' ? 2 : 1, items: [current]}});
  });
  await navigate(page, 'Analysis rules');
  await page.getByRole('checkbox', {name: 'Enable Retained unattached disk review'}).uncheck();
  await page.getByRole('button', {name: 'Preview 1 rule changes'}).click();
  const dialog = page.getByRole('dialog', {name: 'Review rule policy changes'});
  await expect(dialog).toContainText('1 resources change');
  expect(requests.map(r => r.method)).toEqual(['POST']);
  await dialog.getByRole('button', {name: 'Apply changes'}).click();
  await expect(dialog).not.toBeVisible();
  expect(requests.map(r => r.method)).toEqual(['POST', 'PUT']);
  await expect(page.getByRole('checkbox', {name: 'Enable Retained unattached disk review'})).not.toBeChecked();
});

test('viewers can inspect rules without receiving mutation controls', async ({page}) => {
  await mockWorkspace(page, {role: 'Viewer'});
  await page.route('**/api/v1/rules/effective', route => route.fulfill({json: {version: 1, items: [rule]}}));
  await navigate(page, 'Analysis rules');
  await expect(page.getByRole('checkbox', {name: 'Enable Retained unattached disk review'})).toBeDisabled();
  await expect(page.getByRole('button', {name: /Preview.*rule changes/})).toHaveCount(0);
});
