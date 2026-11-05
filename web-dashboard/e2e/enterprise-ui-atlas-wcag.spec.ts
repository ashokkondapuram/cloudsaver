import {test, expect} from './test';
import AxeBuilder from '@axe-core/playwright';
import {mockWorkspace, navigate} from './workspace-fixture';
import {mockGovernanceRoutes} from './control-plane-fixture';

const ATLAS_PAGES: {nav: string; route: RegExp; rollout: string}[] = [
  {nav: 'Overview', route: /\/$/, rollout: 'overview'},
  {nav: 'Cost allocation', route: /\/allocation/, rollout: 'allocation'},
  {nav: 'Activity & delivery', route: /\/activity/, rollout: 'activity'},
  {nav: 'Risk & compliance', route: /\/governance/, rollout: 'governance'},
  {nav: 'Resources', route: /\/resources/, rollout: 'resources'},
];

async function applyAtlasPreset(page: import('@playwright/test').Page) {
  await page.addInitScript(() => {
    document.documentElement.dataset.uiPreset = 'atlas';
  });
}

test('Atlas §12 routes expose rollout markers', async ({page}) => {
  await mockWorkspace(page);
  await mockGovernanceRoutes(page);
  await applyAtlasPreset(page);
  for (const entry of ATLAS_PAGES) {
    await navigate(page, entry.nav);
    await expect(page.locator('.atlas-route-boundary')).toHaveAttribute('data-atlas-rollout', entry.rollout);
    await expect(page.locator('.atlas-route-boundary')).toHaveAttribute('data-atlas-status', 'pilot');
    await expect(page).toHaveURL(entry.route);
  }
});

test('Atlas preset passes axe WCAG 2.1 AA on primary finance and activity surfaces', async ({page}) => {
  test.setTimeout(180000);
  await page.emulateMedia({reducedMotion: 'reduce'});
  await mockWorkspace(page);
  await applyAtlasPreset(page);
  await page.route('**/api/v1/finops/summary*', route =>
    route.fulfill({
      json: {
        currency: 'USD',
        records: 3,
        billed_cost: '15',
        effective_cost: '14',
        list_cost: null,
        effective_savings_rate_pct: null,
        excluded_overlapping_records: 0,
        warning: 'TEST FIXTURE',
        daily: [{date: '2026-10-01', billed_cost: '15', complete: true}],
        forecast: null,
        anomaly: null,
        providers: [],
      },
    }),
  );
  await page.route('**/api/v1/operations/reliability', route =>
    route.fulfill({
      json: {
        available: true,
        dispatcher_enabled: true,
        targets: [{target_id: 'finops', channel: 'slack'}],
        counts: [
          {kind: 'notification', status: 'pending', count: 2},
          {kind: 'notification', status: 'delivered', count: 5},
        ],
        oldest_due_seconds: null,
        dispatcher: {last_poll_at: '2026-10-22T15:30:00Z', last_success_at: '2026-10-22T15:30:00Z', last_error_at: null},
      },
    }),
  );

  for (const label of ['Overview', 'Cost allocation', 'Activity & delivery']) {
    await navigate(page, label);
    await page.setViewportSize({width: 1280, height: 900});
    const audit = await new AxeBuilder({page})
      .include('#main-content')
      .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
      .analyze();
    expect(audit.violations, `${label} axe violations`).toEqual([]);
  }
});

test('overview billing mini-chart loads only after expand', async ({page}) => {
  const finopsReads: string[] = [];
  page.on('request', req => {
    if (req.url().includes('/api/v1/finops/summary')) finopsReads.push(req.url());
  });
  await mockWorkspace(page);
  await applyAtlasPreset(page);
  await navigate(page, 'Overview');
  expect(finopsReads.length).toBe(0);
  await page.locator('.overview-finops-mini summary').click();
  await expect(page.locator('.analytics-chart-compact')).toBeVisible();
  expect(finopsReads.length).toBeGreaterThan(0);
});
