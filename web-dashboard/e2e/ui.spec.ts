import {test,expect} from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import {mockWorkspace,navigate,scanId} from './workspace-fixture';

test('overview uses observed data and provides provider drill-down',async({page})=>{
  const {mutations}=await mockWorkspace(page);
  await expect(page.getByRole('heading',{name:'Finding trajectory'})).toBeVisible();
  await expect(page.getByRole('button',{name:'Retail estimate',exact:true})).toBeDisabled();
  await expect(page.getByText('Not estimated',{exact:true}).first()).toBeVisible();
  await expect(page.getByRole('img',{name:'Finding count across 7 comparable snapshots'})).toBeVisible();
  await page.screenshot({path:test.info().outputPath('overview-desktop.png'),fullPage:true});
  await page.locator('.distribution-legend').getByRole('link',{name:/AWS/}).click();
  await expect(page.getByRole('heading',{name:'Resources',exact:true})).toBeVisible();
  await expect(page.getByRole('button',{name:/^AWS \d+$/})).toHaveAttribute('aria-pressed','true');
  await expect(page.locator('.resource-table tbody tr')).toHaveCount(3);
  expect(mutations).toEqual([]);
});

test('findings combine filters, density, column visibility, and page selection',async({page})=>{
  await mockWorkspace(page,{legacy:true});await navigate(page,'Resources');
  await page.getByRole('button',{name:/^Azure \d+ findings$/}).click();
  await page.getByRole('combobox',{name:'Finding priority',exact:true}).selectOption('HIGH');
  await page.getByRole('textbox',{name:'Tag filter',exact:true}).fill('Owner=platform');
  await expect(page.locator('.data-table tbody tr[aria-rowindex]')).toHaveCount(1);
  await page.getByRole('button',{name:'compact density',exact:true}).click();
  const height=await page.locator('.data-table tbody tr[aria-rowindex]').first().evaluate(el=>el.getBoundingClientRect().height);
  expect(height).toBe(28);
  await page.getByText('Columns',{exact:true}).click();
  await page.getByRole('checkbox',{name:'Net savings',exact:true}).check();
  await expect(page.getByRole('columnheader',{name:/Net savings/})).toBeVisible();
  await page.keyboard.press('Escape');
  await page.getByRole('checkbox',{name:'Select all findings on this page',exact:true}).check();
  await expect(page.getByRole('region',{name:/Selected (findings|resources) actions/})).toBeVisible();
  await page.keyboard.press('Shift+R');
  await expect(page.getByRole('dialog',{name:'Review selected resources',exact:true})).toBeVisible();
  await expect(page.getByRole('heading',{name:'1 findings selected'})).toBeVisible();
  await page.keyboard.press('Escape');
  await page.getByRole('button',{name:'Clear all',exact:true}).click();
  await expect(page.locator('.data-table tbody tr[aria-rowindex]')).toHaveCount(12);
});

test('detail drawer preserves context and previews actual returned review code',async({page})=>{
  const {mutations}=await mockWorkspace(page);await navigate(page,'Resources');
  const resource=page.getByRole('button',{name:/^archive-data-01/});await resource.click();
  const drawer=page.getByRole('dialog',{name:'Resource details',exact:true});
  await expect(drawer).toBeVisible();
  await expect(drawer.getByRole('heading',{name:'Resource identity'})).toBeVisible();
  await drawer.getByRole('tab',{name:'Costs',exact:true}).click();
  await expect(drawer.getByRole('heading',{name:'Financial evidence'})).toBeVisible();
  await drawer.getByRole('tab',{name:'Code',exact:true}).click();
  await drawer.getByRole('button',{name:'Preview Terraform imports',exact:true}).click();
  await drawer.getByRole('button',{name:'Preview Terraform imports',exact:true}).click();
  await expect(drawer.getByLabel('Generated code preview')).toContainText('TEST FIXTURE import review');
  expect(mutations).toHaveLength(1);
  expect(mutations[0].path).toBe(`/api/v1/scans/${scanId}/remediation-terraform`);
  await page.screenshot({path:test.info().outputPath('finding-drawer.png'),fullPage:true});
  await page.keyboard.press('Escape');
  await expect(drawer).toHaveCount(0);await expect(resource).toBeFocused();
});

test('viewer can inspect evidence but cannot generate review artifacts or scan',async({page})=>{
  const {mutations}=await mockWorkspace(page,{role:'Viewer'});
  await expect(page.getByRole('button',{name:'Run new scan',exact:true})).toHaveCount(0);
  await navigate(page,'Resources');
  await page.getByRole('button',{name:/^archive-data-01/}).click();
  const drawer=page.getByRole('dialog',{name:'Resource details',exact:true});
  await drawer.getByRole('tab',{name:'Code',exact:true}).click();
  await expect(drawer.getByRole('button',{name:'Preview Terraform imports',exact:true})).toBeDisabled();
  await expect(drawer.getByRole('button',{name:'Preview Bash script',exact:true})).toBeDisabled();
  expect(mutations).toEqual([]);
});

test('command palette, navigation shortcuts, and scoped filters retain session',async({page})=>{
  await mockWorkspace(page);
  await page.keyboard.press('Control+k');
  const command=page.getByRole('dialog',{name:'Search & commands',exact:true});
  await expect(command).toBeVisible();
  await page.getByRole('combobox',{name:'Search commands and resources',exact:true}).fill('Resources');
  await page.keyboard.press('Enter');
  await expect(page).toHaveURL(/\/resources$/);
  await page.locator('.scope-picker>summary').click();
  await page.getByRole('checkbox',{name:'finops-project',exact:true}).check();
  await page.locator('.scope-picker>summary').click();
  await expect(page.locator('.resource-table tbody tr, .data-table tbody tr[aria-rowindex]')).toHaveCount(3);
  await page.keyboard.press('g');await page.keyboard.press('d');
  await expect(page.getByRole('heading',{name:'Overview',exact:true})).toBeVisible();
  await expect(page.getByText('History uses complete scan scopes',{exact:true})).toBeVisible();
  const stored=await page.evaluate(()=>JSON.stringify({...localStorage}));
  expect(stored).not.toContain('test-only-browser-credential');
  await page.locator('.workspace-menu>summary').click();
  await page.locator('.workspace-menu').getByRole('button',{name:'Disconnect',exact:true}).click();
  await expect(page.getByLabel('Workspace access key or Entra Bearer token')).toBeVisible();
});

test('plan upload preserves duplicate keys for server rejection',async({page})=>{
  const {mutations}=await mockWorkspace(page);await navigate(page,'Automation');
  await page.getByRole('tab',{name:'Plan guardrails',exact:true}).click();
  await page.getByText('Advanced: offline Terraform plan evaluation',{exact:true}).click();
  await page.getByLabel('Terraform plan JSON',{exact:true}).setInputFiles({name:'plan.json',mimeType:'application/json',buffer:Buffer.from('{"duplicate":1,"duplicate":2}')});
  await page.getByRole('button',{name:'Check plan',exact:true}).click();
  await expect(page.getByRole('tabpanel',{name:'Plan guardrails'}).getByRole('alert')).toContainText('Invalid or unsupported JSON request');
  expect(mutations[0].raw).toContain('"duplicate":1,"duplicate":2');
});

test('GitOps requires file review acknowledgment before publishing a draft',async({page})=>{
  const {mutations}=await mockWorkspace(page,{publishing:true});await navigate(page,'Automation');
  await page.getByRole('checkbox',{name:/archive-data-01/}).check();
  await page.getByRole('button',{name:'Preview review package',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Inspect your package',exact:true})).toBeVisible();
  const publish=page.getByRole('button',{name:'Open draft PR',exact:true});
  await expect(publish).toBeDisabled();
  await page.getByRole('checkbox',{name:/I reviewed these files/}).check();await publish.click();
  await expect(page.getByRole('link',{name:/View pull request/})).toBeVisible();
  expect(mutations.map(m=>m.path)).toEqual(['/api/v1/gitops/preview','/api/v1/gitops/requests']);
  expect(mutations[1].body.idempotency_key).toBeTruthy();
});

test('new scan dialog requires an explicit provider selection and action',async({page})=>{
  const {mutations}=await mockWorkspace(page);
  await page.getByRole('button',{name:'Run new scan',exact:true}).click();
  const dialog=page.getByRole('dialog',{name:'Run a resource scan',exact:true});
  for(const provider of ['Azure','Google Cloud','Kubernetes'])await dialog.getByRole('checkbox',{name:new RegExp(provider)}).uncheck();
  expect(mutations).toEqual([]);
  await dialog.getByRole('button',{name:'Start scan',exact:true}).click();
  await expect(page.getByRole('status').filter({hasText:'Scan completed.'})).toBeVisible();
  expect(mutations[0].body).toEqual({providers:['aws']});
  await expect(page.getByLabel('Selected scan snapshot')).toHaveValue('44444444-4444-4444-8444-444444444444');
});

test('10,000 findings stay virtualized and selection follows the current page',async({page})=>{
  await mockWorkspace(page,{count:10000,legacy:true});await navigate(page,'Resources');
  await expect(page.locator('.grid-footer')).toContainText('10,000 matching findings');
  expect(await page.locator('.data-table tbody tr[aria-rowindex]').count()).toBeLessThan(50);
  await page.getByLabel('Scrollable findings table',{exact:true}).focus();await page.keyboard.press('Control+a');
  await expect(page.locator('.bulk-count')).toContainText('100');
  await page.getByRole('button',{name:'Next page',exact:true}).click();
  await expect(page.locator('.pagination')).toContainText('2 of 100');
});

test('mobile navigation, filters, and drawer fit the viewport',async({page})=>{
  await page.setViewportSize({width:390,height:844});await mockWorkspace(page);
  await page.screenshot({path:test.info().outputPath('overview-mobile.png'),fullPage:true});
  await navigate(page,'Resources');
  await page.getByRole('button',{name:/^archive-data-01/}).click();
  const drawer=page.getByRole('dialog',{name:'Resource details',exact:true});
  await expect(drawer).toBeVisible();
  expect(await drawer.evaluate(el=>el.getBoundingClientRect().width)).toBeLessThanOrEqual(390);
  await page.keyboard.press('Escape');
  const width=await page.evaluate(()=>({scroll:document.documentElement.scrollWidth,viewport:window.innerWidth}));
  expect(width.scroll).toBeLessThanOrEqual(width.viewport);
});

test('overview, inventory, drawer, and settings have no serious automated accessibility violations',async({page})=>{
  await mockWorkspace(page);
  for(const view of ['Overview','Resources','Settings & integrations']){
    await navigate(page,view);
    await page.waitForTimeout(200);
    const result=await new AxeBuilder({page}).withTags(['wcag2a','wcag2aa','wcag21a','wcag21aa']).analyze();
    expect(result.violations.filter(v=>v.impact==='serious'||v.impact==='critical'),JSON.stringify(result.violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>n.target)})))).toEqual([]);
  }
  await navigate(page,'Resources');await page.getByRole('button',{name:/^archive-data-01/}).click();
  const result=await new AxeBuilder({page}).analyze();
  expect(result.violations.filter(v=>v.impact==='serious'||v.impact==='critical'),JSON.stringify(result.violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>n.target)})))).toEqual([]);
});
