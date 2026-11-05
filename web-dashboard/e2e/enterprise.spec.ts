import {test,expect} from './test';
import AxeBuilder from '@axe-core/playwright';
import {mockWorkspace,navigate} from './workspace-fixture';
import {assessmentId,mockEnterprise} from './enterprise-fixture';

test('billing summary reflects Azure sync and isolates currency summaries',async({page})=>{
  await mockWorkspace(page);
  let synced=false;
  await page.route('**/api/v1/finops/sync-status',r=>r.fulfill({json:{configured:true,automatic_sync_enabled:true,last_synced_at:synced?'2026-10-23T12:00:00Z':null,recent_syncs:synced?[{id:'run',state:'completed',updated_at:'2026-10-23T12:00:00Z',payload:{inserted_records:21,unresolved_absent_groups:0}}]:[],warning:'TEST FIXTURE: Synced billing evidence is not provider-reconciled.'}}));
  await page.route('**/api/v1/finops/sync?*',r=>{synced=true;return r.fulfill({status:202,json:{status:'queued',poll_url:'/api/v1/finops/sync-jobs/77777777-7777-4777-8777-777777777777'}});});
  await page.route('**/api/v1/finops/sync-jobs/77777777-7777-4777-8777-777777777777',r=>r.fulfill({json:{status:'completed'}}));
  await page.route('**/api/v1/finops/summary*',r=>{
    const currency=new URL(r.request().url()).searchParams.get('currency')||'USD';
    const available=synced&&currency==='USD';
    return r.fulfill({json:{currency,records:available?21:0,billed_cost:available?'210.00000000':null,effective_cost:available?'210.00000000':null,list_cost:available?'420.00000000':null,effective_savings_rate_pct:available?'50.0000':null,excluded_overlapping_records:0,warning:'TEST FIXTURE: Synced billing evidence is not provider-reconciled.',forecast:available?{month_end_billed_cost:'310.00000000',daily_velocity:'10.00000000',projected_budget_overrun:true}:null,anomaly:null,daily:available?[{date:'2026-10-01',complete:true,billed_cost:'10.00000000'}]:[],providers:available?[{provider:'azure',records:21,billed_cost:'210.00000000',effective_cost:'210.00000000'}]:[]}});
  });
  await mockEnterprise(page);
  await navigate(page,'Cost allocation');
  const panel=page.locator('.billing-evidence');
  await expect(panel.getByRole('heading',{name:'No synced charges in this period'})).toBeVisible();
  await panel.getByLabel('From (UTC)',{exact:true}).fill('2026-10-01');
  await panel.getByLabel('Until, exclusive (UTC)').fill('2026-10-22');
  await panel.getByLabel('Monthly budget (optional)').fill('300');
  await panel.getByRole('button',{name:'Apply billing period'}).click();
  await panel.getByRole('button',{name:'Sync now',exact:true}).click();
  await expect(panel.getByText('$310.00',{exact:true})).toBeVisible();
  await expect(panel.getByText('Projected above the supplied budget',{exact:true})).toBeVisible();
  await expect(panel.getByText('Advanced: import FOCUS billing JSON manually')).toHaveCount(0);
  const accessibility=await new AxeBuilder({page}).include('.billing-evidence').withTags(['wcag2a','wcag2aa','wcag21aa']).analyze();
  expect(accessibility.violations).toEqual([]);
  await panel.screenshot({path:test.info().outputPath('billing-evidence-v100.png')});
  await panel.getByLabel('Billing currency',{exact:true}).fill('EUR');
  await panel.getByRole('button',{name:'Apply billing period'}).click();
  await expect(panel.getByRole('heading',{name:'No synced charges in this period'})).toBeVisible();
});

test('viewer cannot sync billing data and reads saved assessments without inference',async({page})=>{
  const {mutations}=await mockWorkspace(page,{role:'Viewer'});
  await mockEnterprise(page);
  await navigate(page,'Cost allocation');
  await expect(page.getByRole('heading',{name:'Finance access required'})).toBeVisible();
  await expect(page.getByRole('button',{name:'Sync now'})).toHaveCount(0);
  await navigate(page,'Activity & delivery');
  await page.getByRole('tab',{name:'AI assessments',exact:true}).click();
  await page.getByRole('button',{name:'Inspect assessment 55555555'}).click();
  await expect(page.getByText('TEST FIXTURE: Retained advisory for independent evidence review.',{exact:true})).toBeVisible();
  expect(mutations).toHaveLength(0);
});

test('durable AI history exposes outcomes, usage and lifecycle without action approval',async({page})=>{
  const {mutations}=await mockWorkspace(page);await mockEnterprise(page);
  await navigate(page,'Activity & delivery');await page.getByRole('tab',{name:'AI assessments',exact:true}).click();
  const panel=page.locator('.ai-history');await expect(panel.getByRole('heading',{name:'AI assessment history'})).toBeVisible();
  await expect(panel.getByRole('cell',{name:'300',exact:true})).toBeVisible();
  await panel.getByRole('button',{name:'Inspect assessment 55555555'}).click();
  await expect(panel.getByRole('heading',{name:'Recorded lifecycle'})).toBeVisible();
  await expect(panel.getByText('independent change approval',{exact:true})).toBeVisible();
  await expect(panel.getByRole('button',{name:/approve|execute|retry/i})).toHaveCount(0);
  const accessibility=await new AxeBuilder({page}).include('.ai-history').withTags(['wcag2a','wcag2aa','wcag21aa']).analyze();expect(accessibility.violations).toEqual([]);
  await panel.screenshot({path:test.info().outputPath('ai-history-v100.png')});expect(mutations).toHaveLength(0);
});

test('uncertain inference retains the fence and unknown usage on a mobile viewport',async({page})=>{
  await page.setViewportSize({width:390,height:844});await mockWorkspace(page);await mockEnterprise(page,'uncertain');
  await navigate(page,'Activity & delivery');await page.getByRole('tab',{name:'AI assessments',exact:true}).click();
  const panel=page.locator('.ai-history');await panel.getByRole('button',{name:'Inspect assessment 55555555'}).click();
  await expect(panel.getByText(/No completed advisory is stored/)).toBeVisible();
  await expect(panel.getByRole('button',{name:/retry|approve|execute/i})).toHaveCount(0);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth+1)).toBe(true);
});
