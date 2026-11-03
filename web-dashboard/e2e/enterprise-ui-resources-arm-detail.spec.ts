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
  await page.getByRole('button', {name: 'ARM detail collected'}).click();
  await expect.poll(() => armDetailQuery).toBe('collected');
  await page.getByRole('button', {name: 'ARM detail collected'}).click();
  await expect.poll(() => armDetailQuery).toBe('');
});
