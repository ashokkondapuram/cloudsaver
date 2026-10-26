import {test,expect} from './test';
import AxeBuilder from '@axe-core/playwright';
import {mockWorkspace,navigate} from './workspace-fixture';

test('latest console defaults to dark and preserves only the chosen appearance preference',async({page})=>{
  await mockWorkspace(page);
  await expect(page.locator('html')).toHaveAttribute('data-theme','dark');
  await page.getByRole('button',{name:'Switch to light theme',exact:true}).click();
  await navigate(page,'Cost allocation');await expect(page.locator('html')).toHaveAttribute('data-theme','light');
  await page.reload();await expect(page.locator('html')).toHaveAttribute('data-theme','light');
  await expect(page.getByRole('button',{name:'Switch to dark theme',exact:true})).toBeVisible();
  const stored=await page.evaluate(()=>JSON.stringify(localStorage));
  expect(stored).not.toContain('test-only-browser-credential');expect(stored).not.toContain('archive-data');
});

test('provider/category facets, price gaps and protected intent combine without treating zero as unknown',async({page})=>{
  await mockWorkspace(page,{protected:true,zeroPrice:true});await navigate(page,'Resources');
  await expect(page.locator('.resource-table tbody tr').filter({hasText:'archive-data-01'})).toContainText('$0.00');
  await page.getByRole('group',{name:'Evidence quick views'}).getByRole('button',{name:'Missing prices',exact:true}).click();
  await expect(page.locator('.resource-table tbody tr')).toHaveCount(9);
  await page.getByRole('button',{name:/^Azure \d+$/}).click();
  await expect(page.getByRole('heading',{name:'No matching resources',exact:true})).toBeVisible();
  await page.getByRole('group',{name:'Evidence quick views'}).getByRole('button',{name:'Protected intent',exact:true}).click();
  await expect(page.locator('.resource-table tbody tr')).toHaveCount(1);
  await page.getByRole('button',{name:/^archive-data-01/}).click();
  await page.getByRole('tab',{name:'Code',exact:true}).click();
  await expect(page.getByRole('button',{name:'Preview Bash script',exact:true})).toBeDisabled();
  await expect(page.getByRole('button',{name:'Preview Terraform imports',exact:true})).toBeEnabled();
});

test('historical drawer comparison preserves review context without fabricating a live assessment',async({page})=>{
  await page.setViewportSize({width:1440,height:1100});
  await mockWorkspace(page,{protected:true,legacy:true});await navigate(page,'Resources');
  await page.getByRole('button',{name:/^Azure \d+ findings$/}).click();
  await page.getByRole('button',{name:/^archive-data-01/}).click();
  const dialog=page.getByRole('dialog',{name:'Finding details',exact:true});
  await dialog.getByRole('tab',{name:'360° assessment',exact:true}).click();
  await expect(dialog.getByRole('alert')).toContainText('Assessment requires a completed live scan observation.');
  await expect(dialog.getByRole('button',{name:'Request AI advisory',exact:true})).toHaveCount(0);
  await dialog.getByRole('button',{name:'Next finding',exact:true}).click();
  await expect(dialog.getByRole('tab',{name:'360° assessment',exact:true})).toHaveAttribute('aria-selected','true');
  await expect(dialog.getByRole('alert')).toContainText('Assessment requires a completed live scan observation.');
  await expect(dialog.locator('.finding-navigation')).toContainText('2 / 3');
  await dialog.getByRole('button',{name:'Previous finding',exact:true}).click();
  await expect(dialog.getByRole('tab',{name:'360° assessment',exact:true})).toHaveAttribute('aria-selected','true');
  await expect(dialog.getByRole('alert')).toContainText('Assessment requires a completed live scan observation.');
  await dialog.locator('.drawer-tab-content').evaluate(el=>el.scrollTop=0);
  await page.evaluate(()=>window.scrollTo(0,0));
  await page.screenshot({path:test.info().outputPath('dark-assessment-radar.png'),fullPage:true});
  await page.keyboard.press('Escape');await expect(page.getByRole('button',{name:/^archive-data-01/})).toBeFocused();await expect(page.getByRole('button',{name:/^Azure \d+ findings$/})).toHaveAttribute('aria-pressed','true');
});

test('command quick views open real filters; telemetry distinguishes observations from missing series',async({page})=>{
  await mockWorkspace(page,{legacy:true});
  await page.keyboard.press('Control+k');await page.getByRole('combobox',{name:'Search commands and resources'}).fill('storage findings');await page.keyboard.press('Enter');
  await expect(page).toHaveURL(/category=storage/);
  await expect(page.getByRole('group',{name:'Resource categories'}).getByRole('button',{name:/^Storage/})).toHaveAttribute('aria-pressed','true');
  await expect(page.locator('.data-table tbody tr[aria-rowindex]')).toHaveCount(9);
  await page.getByRole('button',{name:'Clear all',exact:true}).click();
  await page.getByRole('button',{name:/^api-worker-04/}).click();await page.getByRole('tab',{name:'Telemetry',exact:true}).click();
  await expect(page.getByText('0.03',{exact:true})).toBeVisible();
  await expect(page.getByText('Complete 14-day sampled window',{exact:true})).toBeVisible();
  await expect(page.getByText(/Raw time-series samples are not returned/)).toBeVisible();
  await page.keyboard.press('Escape');await page.getByRole('button',{name:/^archive-data-01/}).click();
  await page.getByRole('tab',{name:'Telemetry',exact:true}).click();
  await expect(page.getByRole('heading',{name:'No utilization series is attached',exact:true})).toBeVisible();
  await expect(page.locator('.telemetry-evidence svg[role="img"]')).toHaveCount(0);
});

test('dark and light themes retain accessible operational views and readable inventory',async({page})=>{
  test.setTimeout(120000);
  await page.setViewportSize({width:1440,height:1100});
  await mockWorkspace(page,{protected:true});
  const problems:unknown[]=[];
  for(const theme of ['dark','light']){
    if(theme==='light')await page.getByRole('button',{name:'Switch to light theme',exact:true}).click();
    for(const view of ['Overview','Resources','Cost allocation','Automation','Activity & delivery','Settings & integrations']){
      await navigate(page,view);await page.waitForTimeout(150);
      const result=await new AxeBuilder({page}).withTags(['wcag2a','wcag2aa','wcag21a','wcag21aa']).analyze();
      const serious=result.violations.filter(v=>v.impact==='serious'||v.impact==='critical');
      if(serious.length)problems.push({theme,view,issues:serious.map(v=>({id:v.id,nodes:v.nodes.map(n=>({target:n.target,summary:n.failureSummary}))}))});
    }
    await navigate(page,'Resources');
    await page.screenshot({path:test.info().outputPath(`${theme}-resource-explorer.png`),fullPage:false});
  }
  expect(problems,JSON.stringify(problems)).toEqual([]);
});

test('mobile dark explorer and drawer fit the viewport and support keyboard tab endpoints',async({page})=>{
  await page.setViewportSize({width:390,height:844});await mockWorkspace(page,{legacy:true});await navigate(page,'Resources');
  await page.screenshot({path:test.info().outputPath('dark-resource-explorer-mobile.png'),fullPage:true});
  const size=await page.evaluate(()=>({scroll:document.documentElement.scrollWidth,width:innerWidth}));expect(size.scroll).toBeLessThanOrEqual(size.width);
  await page.getByRole('button',{name:/^archive-data-01/}).click();
  await page.getByRole('tab',{name:'Evidence',exact:true}).focus();await page.keyboard.press('End');
  await expect(page.getByRole('tab',{name:'Activity & ITSM',exact:true})).toBeFocused();
  await page.keyboard.press('Home');await expect(page.getByRole('tab',{name:'Evidence',exact:true})).toBeFocused();
});


test('a resource click without native button focus still returns to its stable row after review',async({page})=>{
  await mockWorkspace(page,{legacy:true});await navigate(page,'Resources');
  const resource=page.getByRole('button',{name:/^archive-data-01/});
  // Safari/pointer interactions need not focus a button before dispatching its click.
  await resource.dispatchEvent('click');
  await page.getByRole('tab',{name:'Cost breakdown',exact:true}).click();
  await page.keyboard.press('Escape');await expect(resource).toBeFocused();
});
