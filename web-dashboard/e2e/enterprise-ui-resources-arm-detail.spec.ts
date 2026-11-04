import {test, expect} from './test';
import {buildResourceItems, createFindings, mockWorkspace, navigate, scanId, scanTime} from './workspace-fixture';

test('resources explorer filters ARM detail client-side without refetching inventory', async ({page}) => {
  await mockWorkspace(page);
  const items = buildResourceItems(createFindings(12)).map((row, index) => ({
    ...row,
    arm_detail: index % 3 === 0 ? ('collected' as const) : null,
  }));
  let resourceGets = 0;
  await page.route(`**/api/v1/scans/${scanId}/resources**`, async route => {
    if (route.request().method() !== 'GET') {
      await route.fallback();
      return;
    }
    resourceGets++;
    const url = new URL(route.request().url());
    expect(url.searchParams.get('arm_detail')).toBeNull();
    const offset = Number(url.searchParams.get('offset') || 0);
    const limit = Number(url.searchParams.get('limit') || items.length);
    await route.fulfill({
      json: {
        scan_id: scanId,
        observed_at: scanTime,
        total: items.length,
        items: items.slice(offset, offset + limit),
        summary: {total: items.length, ai_status: {not_run: items.length}, ai_risk: {none: items.length}, decision: {none: items.length}, review_priority: {high: items.length}},
      },
    });
  });
  await navigate(page, 'Resources');
  await expect(page.locator('.resource-table')).toBeVisible();
  const initialGets = resourceGets;
  const quickView = page.getByRole('group', {name: 'Evidence quick views'});
  await quickView.getByRole('button', {name: 'ARM detail'}).click();
  await expect(page).toHaveURL(/arm_detail=collected/);
  await expect(page.locator('.resource-table tbody tr')).toHaveCount(items.filter(row => row.arm_detail === 'collected').length);
  expect(resourceGets).toBe(initialGets);
  await quickView.getByRole('button', {name: 'ARM detail'}).click();
  await expect(page).not.toHaveURL(/arm_detail=/);
  await expect(page.locator('.resource-table tbody tr')).toHaveCount(items.length);
});

test('resources explorer loads arm_detail filter from the URL', async ({page}) => {
  await mockWorkspace(page);
  const items = buildResourceItems(createFindings(8)).map((row, index) => ({...row, arm_detail: index % 2 === 0 ? 'collected' as const : null}));
  await page.route(`**/api/v1/scans/${scanId}/resources**`, async route => {
    if (route.request().method() !== 'GET') {
      await route.fallback();
      return;
    }
    const url = new URL(route.request().url());
    expect(url.searchParams.get('arm_detail')).toBeNull();
    const offset = Number(url.searchParams.get('offset') || 0);
    const limit = Number(url.searchParams.get('limit') || items.length);
    await route.fulfill({
      json: {
        scan_id: scanId,
        observed_at: scanTime,
        total: items.length,
        items: items.slice(offset, offset + limit),
        summary: {total: items.length, ai_status: {not_run: items.length}, ai_risk: {none: items.length}, decision: {none: items.length}, review_priority: {high: items.length}},
      },
    });
  });
  await page.goto('/resources?arm_detail=collected');
  await expect(page.locator('.resource-table')).toBeVisible();
  await expect(page.getByRole('group', {name: 'Evidence quick views'}).getByRole('button', {name: 'ARM detail'})).toHaveAttribute('aria-pressed', 'true');
  await expect(page.locator('.resource-table tbody tr')).toHaveCount(items.filter(row => row.arm_detail === 'collected').length);
});
