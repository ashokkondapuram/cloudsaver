import {test, expect} from './test';
import AxeBuilder from '@axe-core/playwright';
import {mockWorkspace, navigate, scanId, scanTime} from './workspace-fixture';

test('overview sets expectations without fetching financial or history data', async ({page}) => {
  const reads: string[] = [];
  page.on('request', request => {if (request.url().includes('/api/v1/')) reads.push(new URL(request.url()).pathname);});
  const {mutations} = await mockWorkspace(page);
  const guide = page.getByRole('region', {name:'What you can do in each section'});
  const links = guide.getByRole('link');
  await expect(links).toHaveCount(6);
  expect(await links.evaluateAll(items => items.map(item => item.getAttribute('href')))).toEqual(['/resources', '/workloads', '/allocation', '/governance', '/automation', '/outcomes']);
  await expect(guide).toContainText('Billing has its own evidence window');
  await expect(guide).toContainText('Execution requires separate authorization');
  await expect(page.getByRole('region', {name:'Evidence health'})).toContainText('Resource estimates are not verified savings');
  expect(reads.filter(path => path === '/api/v1/trends' || path.startsWith('/api/v1/finops/'))).toEqual([]);
  expect(mutations).toEqual([]);
});

test('specialist tools remain discoverable by keyboard and reopen on their active page', async ({page}) => {
  await mockWorkspace(page);
  const nav = page.getByRole('navigation', {name:'Primary navigation'});
  const toggle = nav.getByRole('button', {name:'Specialist tools', exact:true});
  await expect(nav.getByRole('link')).toHaveCount(9);
  await expect(nav.getByRole('link', {name:'Services', exact:true})).toHaveCount(0);
  await toggle.focus(); await page.keyboard.press('Enter');
  await expect(toggle).toHaveAttribute('aria-expanded', 'true');
  await nav.getByRole('link', {name:'Services', exact:true}).click();
  await expect(page).toHaveURL(/\/services\/disks$/);
  await expect(nav.getByRole('link', {name:'Services', exact:true})).toHaveAttribute('aria-current', 'page');
  await page.reload();
  await expect(toggle).toHaveAttribute('aria-expanded', 'true');
  await navigate(page, 'Overview');
  await expect(toggle).toHaveAttribute('aria-expanded', 'false');
  await page.getByRole('button', {name:'Collapse sidebar', exact:true}).click();
  await expect(nav.getByRole('link', {name:'Resources', exact:true})).toBeVisible();
  await toggle.click();
  await expect(nav.getByRole('link', {name:'Services', exact:true})).toBeVisible();
});

for (const role of ['TenantAdmin', 'Viewer']) {
  test(`first-use guidance does not invent zero results for ${role}`, async ({page}) => {
    await mockWorkspace(page, {role});
    await page.route('**/api/v1/scans', route => route.fulfill({json:[]}));
    await page.reload();
    await expect(page.getByRole('heading', {name:'Start with your first resource snapshot'})).toBeVisible();
    const evidence = page.getByRole('region', {name:'Evidence health'});
    await expect(evidence).toContainText('No snapshot');
    await expect(evidence.getByText('—', {exact:true})).toHaveCount(2);
    await expect(page.getByRole('region', {name:'Resource review queue'})).toHaveCount(0);
    await expect(page.getByRole('button', {name:'Run new scan', exact:true})).toHaveCount(0);
    await expect(page.getByRole('button', {name:'Run first scan', exact:true})).toHaveCount(role === 'TenantAdmin' ? 1 : 0);
    if (role === 'Viewer') await expect(page.getByText('Ask a workspace administrator to run the first scan.', {exact:false})).toBeVisible();
  });
}

test('retrying unavailable evidence only reloads the saved inventory', async ({page}) => {
  const {mutations, findings} = await mockWorkspace(page);
  let reads = 0;
  await page.route(`**/api/v1/scans/${scanId}/resources?**`, async route => {
    reads++;
    if (reads === 1) await route.fulfill({status:503, json:{detail:'Synthetic inventory unavailable'}});
    else await route.fulfill({json:{scan_id:scanId, observed_at:scanTime, total:0, items:[], summary:{total:0, ai_status:{}, ai_risk:{}, decision:{}, review_priority:{}}}});
  });
  await page.reload();
  await expect(page.getByRole('heading', {name:'Resource evidence needs attention'})).toBeVisible();
  await expect(page.getByRole('region', {name:'Evidence health'})).toContainText('Unavailable');
  await expect(page.getByRole('heading', {name:'No resources require review in this view'})).toHaveCount(0);
  await page.getByRole('button', {name:'Retry evidence', exact:true}).click();
  await expect(page.getByRole('region', {name:'Evidence health'})).toContainText('0 resources');
  await expect(page.getByRole('heading', {name:'No resources require review in this view'})).toBeVisible();
  expect(reads).toBe(2); expect(findings.length).toBeGreaterThan(0); expect(mutations).toEqual([]);
});

test('historical observations do not report current assessment coverage', async ({page}) => {
  await mockWorkspace(page, {legacy:true});
  await expect(page.getByRole('heading', {name:'You are viewing a historical snapshot'})).toBeVisible();
  const evidence = page.getByRole('region', {name:'Evidence health'});
  await expect(evidence).toContainText('Unavailable');
  await expect(evidence.getByText('—', {exact:true})).toHaveCount(2);
  await expect(page.getByRole('heading', {name:'No resources require review in this view'})).toHaveCount(0);
});

test('overview and mobile navigation fit narrow screens in both accessible themes', async ({page}) => {
  test.setTimeout(150000);
  await page.emulateMedia({reducedMotion:'reduce'});
  await mockWorkspace(page);
  for (const theme of ['dark', 'light']) {
    if (theme === 'light') await page.getByRole('button', {name:'Switch to light theme', exact:true}).click();
    for (const width of [320, 390, 768, 1024, 1440]) {
      await page.setViewportSize({width, height:900});
      await expect(page.getByRole('heading', {name:'12 resources need a closer look'})).toBeVisible();
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
      const audit = await new AxeBuilder({page}).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze();
      expect(audit.violations).toEqual([]);
      if ([390, 1440].includes(width)) await page.screenshot({path:test.info().outputPath(`overview-${theme}-${width}.png`), fullPage:true});
    }
  }
  await page.setViewportSize({width:320, height:900});
  await page.getByRole('button', {name:'Open navigation'}).click();
  const nav = page.getByRole('navigation', {name:'Mobile navigation'});
  await expect(nav.getByRole('link')).toHaveCount(9);
  await nav.getByRole('button', {name:'Specialist tools', exact:true}).click();
  await nav.getByRole('link', {name:'Services', exact:true}).click();
  await expect(page).toHaveURL(/\/services\/disks$/);
  await page.getByRole('button', {name:'Open navigation'}).click();
  await expect(nav.getByRole('link', {name:'Services', exact:true})).toHaveAttribute('aria-current', 'page');
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(320);
  const audit = await new AxeBuilder({page}).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze();
  expect(audit.violations).toEqual([]);
});
