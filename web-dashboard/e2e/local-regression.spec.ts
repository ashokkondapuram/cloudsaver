import {test,expect} from './test';
import {mockWorkspace,navigate} from './workspace-fixture';

test('mobile resources keep document scrolling inside the viewport',async({page})=>{
  await page.setViewportSize({width:390,height:844});
  await mockWorkspace(page);await navigate(page,'Resources');
  await expect(page.getByRole('button',{name:/^archive-data-01/})).toBeVisible();
  const outside=await page.evaluate(()=>[...document.querySelectorAll('body *')].map(node=>({tag:node.tagName,cls:node.className,left:node.getBoundingClientRect().left,right:node.getBoundingClientRect().right,width:node.getBoundingClientRect().width})).filter(node=>node.width>0&&node.left>=0&&node.right>innerWidth+1).slice(0,16));
  expect(await page.evaluate(()=>document.documentElement.scrollWidth),JSON.stringify(outside)).toBeLessThanOrEqual(390);
});

test('incomplete service payload is an evidence error, not an application crash',async({page})=>{
  await mockWorkspace(page);
  await page.route('**/api/v1/services/disks*',r=>r.fulfill({json:{}}));
  await navigate(page,'Services');
  await expect(page.getByRole('alert').filter({hasText:'Service evidence is incomplete'})).toBeVisible();
  await expect(page.getByRole('heading',{name:'Services',exact:true})).toBeVisible();
});

test('incomplete commitment payload does not erase the billing workspace',async({page})=>{
  await mockWorkspace(page);
  await page.route('**/api/v1/finops/commitments',r=>r.fulfill({json:{items:[]}}));
  await navigate(page,'Cost allocation');
  await expect(page.locator('.commitments-panel').getByRole('alert')).toContainText('Commitment evidence is incomplete');
  await expect(page.getByRole('heading',{name:'Cost allocation',exact:true})).toBeVisible();
});
