import {test, expect} from './test';
import {buildResourceItems, createFindings, mockWorkspace, navigate, scanId, scanTime} from './workspace-fixture';

test('resources explorer passes arm_detail to the scan inventory API', async ({page}) => {
  await mockWorkspace(page);
  const items = buildResourceItems(createFindings(12));
  let armDetailQuery = '';
  await page.route(`**/api/v1/scans/${scanId}/resources**`, async route => {
    if (route.request().method() !== 'GET') {
      await route.fallback();
      return;
    }
    armDetailQuery = new URL(route.request().url()).searchParams.get('arm_detail') || '';
    await route.fulfill({
      json: {
        scan_id: scanId,
        observed_at: scanTime,
        total: items.length,
        items,
        summary: {total: items.length, ai_status: {not_run: items.length}, ai_risk: {none: items.length}, decision: {none: items.length}, review_priority: {high: items.length}},
      },
    });
  });
  await navigate(page, 'Resources');
  await expect(page.locator('.resource-table')).toBeVisible();
  const quickView = page.getByRole('group', {name: 'Evidence quick views'});
  await quickView.getByRole('button', {name: 'ARM detail collected'}).click();
  await expect.poll(() => armDetailQuery).toBe('collected');
  await expect(page).toHaveURL(/arm_detail=collected/);
  await quickView.getByRole('button', {name: 'ARM detail collected'}).click();
  await expect.poll(() => armDetailQuery).toBe('');
  await expect(page).not.toHaveURL(/arm_detail=/);
});

test('resources explorer loads arm_detail filter from the URL', async ({page}) => {
  await mockWorkspace(page);
  const items = buildResourceItems(createFindings(8)).map((row, index) => ({...row, arm_detail: index % 2 === 0 ? 'collected' as const : null}));
  let armDetailQuery = '';
  await page.route(`**/api/v1/scans/${scanId}/resources**`, async route => {
    if (route.request().method() !== 'GET') {
      await route.fallback();
      return;
    }
    armDetailQuery = new URL(route.request().url()).searchParams.get('arm_detail') || '';
    await route.fulfill({
      json: {
        scan_id: scanId,
        observed_at: scanTime,
        total: items.length,
        items,
        summary: {total: items.length, ai_status: {not_run: items.length}, ai_risk: {none: items.length}, decision: {none: items.length}, review_priority: {high: items.length}},
      },
    });
  });
  await page.goto('/resources?arm_detail=collected');
  await expect(page.locator('.resource-table')).toBeVisible();
  await expect.poll(() => armDetailQuery).toBe('collected');
  await expect(page.getByRole('group', {name: 'Evidence quick views'}).getByRole('button', {name: 'ARM detail collected'})).toHaveAttribute('aria-pressed', 'true');
});
