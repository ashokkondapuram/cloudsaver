import {test,expect} from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import {mockWorkspace,navigate} from './workspace-fixture';
import {assessmentId,billingFile,mockEnterprise} from './enterprise-fixture';

test('billing import is explicit, preserves decimal evidence and isolates currency summaries',async({page})=>{
  await mockWorkspace(page);const {writes}=await mockEnterprise(page);
  await navigate(page,'Cost allocation');const panel=page.locator('.billing-evidence');
  await expect(panel.getByRole('heading',{name:'No imported charges in this period'})).toBeVisible();
  await panel.getByLabel('From (UTC)',{exact:true}).fill('2026-10-01');await panel.getByLabel('Until, exclusive (UTC)').fill('2026-10-22');
  await panel.getByLabel('Monthly budget (optional)').fill('300');await panel.getByRole('button',{name:'Apply billing period'}).click();
  const file={name:'test-billing.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(billingFile()))};
  await panel.getByText('Advanced: import FOCUS billing JSON manually',{exact:true}).click();
  await panel.getByLabel('Choose billing JSON',{exact:false}).setInputFiles(file);
  const submit=panel.getByRole('button',{name:'Import cloud billing data',exact:true});await expect(submit).toBeDisabled();expect(writes).toHaveLength(0);
  await panel.getByRole('checkbox',{name:/I have reviewed the account scope/}).check();await submit.click();
  await expect(panel.getByText(/Import saved: 21 new charges/)).toBeVisible();expect(writes).toHaveLength(1);
  expect(writes[0].records[0].BilledCost).toBe('10.00000000');expect(writes[0].source_id).toBe('test-export-october');
  await expect(panel.getByText('$310.00',{exact:true})).toBeVisible();
  await expect(panel.getByText('Projected above the supplied budget',{exact:true})).toBeVisible();
  const accessibility=await new AxeBuilder({page}).include('.billing-evidence').withTags(['wcag2a','wcag2aa','wcag21aa']).analyze();expect(accessibility.violations).toEqual([]);
  await panel.screenshot({path:test.info().outputPath('billing-evidence-v100.png')});
  await panel.getByLabel('Billing currency',{exact:true}).fill('EUR');await panel.getByRole('button',{name:'Apply billing period'}).click();
  await expect(panel.getByRole('heading',{name:'No imported charges in this period'})).toBeVisible();
  expect(writes).toHaveLength(1);
});

test('viewer cannot upload billing data and reads saved assessments without inference',async({page})=>{
  const {mutations}=await mockWorkspace(page,{role:'Viewer'});await mockEnterprise(page);
  await navigate(page,'Cost allocation');await expect(page.getByRole('heading',{name:'Finance access required'})).toBeVisible();
  await expect(page.getByLabel('Choose billing JSON',{exact:false})).toHaveCount(0);
  await navigate(page,'Activity & delivery');await page.getByRole('tab',{name:'AI assessments',exact:true}).click();
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
