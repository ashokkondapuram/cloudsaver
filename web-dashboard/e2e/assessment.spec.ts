import {test,expect} from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import {mockWorkspace,navigate,scanId} from './workspace-fixture';

test('five-pillar assessment preserves protection and gates explicit AI processing',async({page})=>{
  test.setTimeout(60000); // Axe and screenshots run within this workflow on shared CI runners.
  const {mutations}=await mockWorkspace(page,{ai:true,protected:true});
  await navigate(page,'Inventory & findings');
  await page.getByRole('button',{name:/^archive-data-01/}).click();
  const drawer=page.getByRole('dialog',{name:'Finding details',exact:true});
  await drawer.getByRole('tab',{name:'360° assessment',exact:true}).click();
  await expect(drawer.getByRole('heading',{name:'Protected resource',exact:true})).toBeVisible();
  await expect(drawer.getByText(/Destructive script generation is blocked/)).toBeVisible();
  const submit=drawer.getByRole('button',{name:'Request AI advisory',exact:true});
  await expect(submit).toBeDisabled();
  expect(mutations.filter(m=>m.path.endsWith('ai-risk-evaluation'))).toHaveLength(0);
  await drawer.getByText('Inspect the exact evidence sent to the model',{exact:true}).click();
  const context=drawer.locator('pre.evidence-json');
  await expect(context).not.toContainText('archive-data-01');await expect(context).not.toContainText('/subscriptions/');
  const accessibility=await new AxeBuilder({page}).include('dialog[open]').withTags(['wcag2a','wcag2aa','wcag21aa']).analyze();
  expect(accessibility.violations).toEqual([]);
  await page.screenshot({path:test.info().outputPath('assessment-protected.png'),fullPage:true});
  await drawer.getByRole('checkbox',{name:/I acknowledge external processing/}).check();
  await submit.click();
  await expect(drawer.getByText('TEST FIXTURE: Verify retention and recovery before any decision.',{exact:true})).toBeVisible();
  await expect(drawer.getByRole('heading',{name:'Protected resource',exact:true})).toBeVisible();
  const first=mutations.find(m=>m.path.endsWith('ai-risk-evaluation'))!;
  expect(first.body.acknowledge_external_processing).toBe(true);
  expect(first.body.evidence_digest).toBe('b'.repeat(64));
  expect(first.body).not.toHaveProperty('prompt');
  await drawer.getByRole('button',{name:'Read cached advisory',exact:true}).click();
  await expect.poll(()=>mutations.filter(m=>m.path.endsWith('ai-risk-evaluation')).length).toBe(2);
  expect(mutations.filter(m=>m.path.endsWith('ai-risk-evaluation'))[1].body.idempotency_key).toBe(first.body.idempotency_key);
});

test('service analysis labels partial pricing and protected counts without invoking AI',async({page})=>{
  const {mutations}=await mockWorkspace(page,{protected:true});
  await navigate(page,'Cost allocation');
  const panel=page.locator('.service-analysis');
  await expect(panel.getByRole('heading',{name:'Service architecture analysis'})).toBeVisible();
  await expect(panel.getByRole('columnheader',{name:'Protected',exact:true})).toBeVisible();
  await expect(panel.getByText('Not estimated',{exact:true})).toBeVisible();
  await expect(panel.getByText(/subset of your inventory/)).toBeVisible();
  await page.screenshot({path:test.info().outputPath('service-analysis-desktop.png'),fullPage:true});
  expect(mutations).toEqual([]);
});

test('viewer and disabled integrations retain the deterministic assessment',async({page})=>{
  const {mutations}=await mockWorkspace(page,{role:'Viewer',ai:true});
  await navigate(page,'Inventory & findings');await page.getByRole('button',{name:/^archive-data-01/}).click();
  await page.getByRole('tab',{name:'360° assessment',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Independent review required',exact:true})).toBeVisible();
  await expect(page.getByRole('checkbox',{name:/I acknowledge external processing/})).toBeDisabled();
  await expect(page.getByRole('button',{name:'Request AI advisory',exact:true})).toBeDisabled();
  expect(mutations.filter(m=>m.path.endsWith('ai-risk-evaluation'))).toHaveLength(0);
});

test('late AI response cannot appear in another finding after the drawer closes',async({page})=>{
  await mockWorkspace(page,{ai:true});
  let release:()=>void=()=>{};const gate=new Promise<void>(resolve=>release=resolve);
  await page.route(`**/api/v1/scans/${scanId}/ai-risk-evaluation`,async route=>{
    await gate;
    await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({cached:false,warning:'Late old response',guardrails:[],advice:{summary:'STALE OLD RESOURCE RESPONSE',risk_level:'unknown',pillars:[],review_questions:[]}})}).catch(()=>{});
  });
  await navigate(page,'Inventory & findings');await page.getByRole('button',{name:/^archive-data-01/}).click();
  await page.getByRole('tab',{name:'360° assessment',exact:true}).click();
  await page.getByRole('checkbox',{name:/I acknowledge external processing/}).check();
  await page.getByRole('button',{name:'Request AI advisory',exact:true}).click();
  await expect(page.getByRole('button',{name:'Requesting advisory…',exact:true})).toBeVisible();
  await page.keyboard.press('Escape');await page.getByRole('button',{name:/^archive-data-05/}).click();
  await page.getByRole('tab',{name:'360° assessment',exact:true}).click();release();
  await expect(page.getByRole('button',{name:'Request AI advisory',exact:true})).toBeVisible();
  await expect(page.getByText('STALE OLD RESOURCE RESPONSE')).toHaveCount(0);
  await expect(page.getByRole('checkbox',{name:/I acknowledge external processing/})).not.toBeChecked();
});

test('review priorities open saved findings and stale evidence exposes provenance',async({page})=>{
  const {mutations}=await mockWorkspace(page,{ai:true,protected:true});
  await navigate(page,'Cost allocation');
  const panel=page.locator('.service-analysis');
  await expect(panel.getByRole('heading',{name:'Review priorities',exact:true})).toBeVisible();
  await panel.getByRole('button',{name:'archive-data-01 · high',exact:true}).click();
  const drawer=page.getByRole('dialog',{name:'Finding details',exact:true});
  await drawer.getByRole('tab',{name:'360° assessment',exact:true}).click();
  await expect(drawer.getByRole('heading',{name:'Assessment provenance',exact:true})).toBeVisible();
  await expect(drawer.getByText(/Policy 2026-10-23.1/)).toBeVisible();
  await expect(drawer.getByText(/Refresh the scan before planning a change/)).toBeVisible();
  await drawer.getByRole('checkbox',{name:/I acknowledge external processing/}).check();
  await drawer.getByRole('button',{name:'Request AI advisory',exact:true}).click();
  await expect(drawer.getByText(/Provider-reported usage: 300 input tokens/)).toBeVisible();
  expect(mutations.filter(m=>m.path.endsWith('ai-risk-evaluation'))).toHaveLength(1);
  await page.screenshot({path:test.info().outputPath('assessment-engine-v0110.png'),fullPage:true});
});
