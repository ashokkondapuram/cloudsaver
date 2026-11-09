import {test,expect} from './test';
import {mockWorkspace} from './workspace-fixture';
import AxeBuilder from '@axe-core/playwright';

test('mobile credential entry is accessible, optional to reveal, and stays within the viewport',async({page})=>{
  await page.setViewportSize({width:390,height:844});
  await page.goto('/');
  await expect(page.getByRole('main')).toBeVisible();
  const input=page.getByLabel('Workspace credential',{exact:true});
  await input.fill('synthetic-local-test');
  await expect(input).toHaveAttribute('type','password');
  await page.getByRole('button',{name:'Show credential',exact:true}).click();
  await expect(input).toHaveAttribute('type','text');
  await page.getByRole('button',{name:'Hide credential',exact:true}).click();
  await expect(input).toHaveAttribute('type','password');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  const results=await new AxeBuilder({page}).withTags(['wcag2a','wcag2aa','wcag21a','wcag21aa']).analyze();
  expect(results.violations).toEqual([]);
  await page.screenshot({path:test.info().outputPath('mobile-login.png'),fullPage:true});
});

test('global navigation shortcuts do not change pages behind a dialog',async({page})=>{
  await mockWorkspace(page);
  await page.getByRole('button',{name:'Notifications',exact:true}).click();
  const dialog=page.getByRole('dialog',{name:'Workspace notifications'});
  await expect(dialog).toBeVisible();
  await dialog.evaluate(el => {const box=el.getBoundingClientRect();el.dispatchEvent(new MouseEvent('click',{bubbles:true,clientX:box.left+2,clientY:box.top+2}));});
  await expect(dialog).toBeVisible();
  const before=page.url();
  await page.keyboard.press('g');await page.keyboard.press('r');
  expect(page.url()).toBe(before);
  await expect(dialog).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(dialog).not.toBeVisible();
  await expect(page.getByRole('button',{name:'Notifications',exact:true})).toBeFocused();
});

test('flat interface has no decorative animation or backdrop blur',async({page})=>{
  await page.goto('/');
  const styles=await page.locator('.connection-form').evaluate(el=>({
    animation:getComputedStyle(el).animationName,transition:getComputedStyle(el).transitionDuration,
    backdrop:getComputedStyle(el).backdropFilter,
  }));
  expect(styles).toEqual({animation:'none',transition:'0s',backdrop:'none'});
});


test('failed notification refresh shows unavailable instead of old operational state',async({page})=>{
  await page.clock.install();
  await mockWorkspace(page);
  await page.getByRole('button',{name:'Notifications',exact:true}).click();
  await expect(page.getByRole('heading',{name:'No failed deliveries',exact:true})).toBeVisible();
  await page.route('**/api/v1/operations/reliability',route=>route.fulfill({status:503,contentType:'application/json',body:'{"detail":"Unavailable"}'}));
  await page.clock.fastForward(31_000);
  await expect(page.getByRole('heading',{name:'Status not available',exact:true})).toBeVisible();
});
