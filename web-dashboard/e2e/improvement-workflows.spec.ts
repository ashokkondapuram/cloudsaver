import {test, expect} from './test';
import {mockWorkspace, navigate, scanId, subscriptionId} from './workspace-fixture';
import AxeBuilder from '@axe-core/playwright';

const rule = {id:'TEST_DISK_HISTORY',name:'Disk history assessment',provider:'azure',resource_type:'microsoft.compute/disks',service_category:'storage',pillar:'cost',catalog_version:3,override_version:null,description:'History is required before reviewing a disk.',enabled:true,status:'published',parameters:{minimum_days:14},unavailable_reason:null,allowed_override_bounds:{minimum_days:{minimum:7,maximum:90}}};
async function rules(page: Parameters<typeof mockWorkspace>[0], role='TenantAdmin') {
  const session = await mockWorkspace(page,{role});
  await page.route('**/api/v1/rules/effective', route => route.fulfill({json:{version:1,items:[rule,{...rule,id:'TEST_UNAVAILABLE',name:'Unavailable assessment',enabled:false,unavailable_reason:'Not supported for this service',parameters:{},allowed_override_bounds:{}}]}}));
  await navigate(page,'Analysis rules');return session;
}

test('overview describes evidence coverage without merging billing windows or calling providers',async({page})=>{
  const {mutations}=await mockWorkspace(page);
  const health=page.getByRole('region',{name:'Evidence health',exact:true});
  await expect(health).toContainText('12 resources');await expect(health).toContainText('24 / 120 checks');await expect(health).toContainText('12 resources have evidence gaps');
  const context=page.getByRole('region',{name:'Current evidence context'});
  await expect(context).toContainText('2026-10-22 15:30:00 UTC');await expect(context).toContainText('All authorized scan scopes');
  await page.locator('.scope-picker>summary').click();await page.getByRole('checkbox',{name:subscriptionId,exact:true}).check();await page.locator('.scope-picker>summary').click();
  await expect(context).toContainText('1 selected');await expect(health).toContainText('3 resources');await expect(health).toContainText('6 / 30 checks');expect(mutations).toEqual([]);
});

test('unavailable evidence does not render a successful empty review queue',async({page})=>{
  await mockWorkspace(page);await page.route(`**/api/v1/scans/${scanId}/resources?**`,route=>route.fulfill({status:503,json:{detail:'Synthetic inventory unavailable'}}));
  await page.reload();
  await expect(page.getByRole('region',{name:'Evidence health'})).toContainText('Unavailable');
  await expect(page.getByText('The review queue is unavailable until resource evidence can be loaded.',{exact:true})).toBeVisible();
  await expect(page.getByText('No resources require review in this view',{exact:true})).toHaveCount(0);
});

test('rule details explain unavailable checks and saved filters independently of drafts',async({page})=>{
  await rules(page,'Viewer');await page.getByText('Rule details: Disk history assessment',{exact:true}).click();
  await expect(page.locator('.rule-details[open]')).toContainText('TEST_DISK_HISTORY');
  await page.getByLabel('Effective state',{exact:true}).selectOption('Unavailable');await expect(page.getByRole('checkbox',{name:'Enable Unavailable assessment'})).toBeDisabled();
  await expect(page.getByRole('checkbox',{name:'Enable Disk history assessment'})).toHaveCount(0);
  await page.getByRole('button',{name:'Reset rule filters'}).click();await expect(page.getByRole('checkbox',{name:'Enable Disk history assessment'})).toBeDisabled();
});

test('rule preview rejects empty parameters and removes reverted edits',async({page})=>{
  const {mutations}=await rules(page);const threshold=page.getByRole('spinbutton',{name:/Minimum days/});const preview=page.getByRole('button',{name:/Preview.*rule changes/});
  await threshold.fill('');await expect(preview).toBeDisabled();await threshold.fill('100');await expect(preview).toBeDisabled();await threshold.fill('21');await expect(preview).toBeEnabled();await threshold.fill('14');await expect(preview).toBeDisabled();expect(mutations).toEqual([]);
});

test('policy conflict retains the draft and requires a new versioned preview',async({page})=>{
  await rules(page);const writes:{path:string;body:any}[]=[];
  await page.route('**/api/v1/rules/preview',async route=>{const body=route.request().postDataJSON();writes.push({path:'preview',body});await route.fulfill({json:{version:body.version,resources_changed:1,scan_id:scanId,message:'Synthetic saved observation preview'}});});
  await page.route('**/api/v1/rules/overrides',async route=>{writes.push({path:'apply',body:route.request().postDataJSON()});await route.fulfill({status:409,json:{detail:'Policy version changed'}});});
  await page.getByRole('checkbox',{name:'Enable Disk history assessment'}).uncheck();await page.getByRole('button',{name:'Preview 1 rule changes'}).click();
  const review=page.getByRole('dialog',{name:'Review rule policy changes'});await expect(review).toContainText('Enabled → Disabled');await review.getByRole('button',{name:'Apply changes'}).click();
  await expect(page.getByRole('button',{name:'Preview 1 rule changes'})).toBeDisabled();
  await page.route('**/api/v1/rules/effective',route=>route.fulfill({json:{version:2,items:[{...rule,catalog_version:4}]}}));await page.getByRole('button',{name:'Reload current policy',exact:true}).click();
  await expect(page.getByRole('checkbox',{name:'Enable Disk history assessment'})).not.toBeChecked();await page.getByRole('button',{name:'Preview 1 rule changes'}).click();await expect(review).toContainText('Policy version 2');
  expect(writes.map(item=>[item.path,item.body.version])).toEqual([['preview',1],['apply',1],['preview',2]]);
});

test('evidence context and rule review remain accessible in mobile and both themes',async({page})=>{
  await page.emulateMedia({reducedMotion:'reduce'});
  await page.setViewportSize({width:390,height:844});await rules(page);
  for(const theme of ['dark','light']){
    if(theme==='light')await page.getByRole('button',{name:'Switch to light theme',exact:true}).click();
    expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
    const results=await new AxeBuilder({page}).withTags(['wcag2a','wcag2aa','wcag21aa']).analyze();expect(results.violations).toEqual([]);
  }
});

test('a rule draft cannot be silently discarded by workspace navigation',async({page})=>{
  await rules(page);await page.getByRole('checkbox',{name:'Enable Disk history assessment'}).uncheck();
  page.once('dialog',dialog=>dialog.dismiss());await navigate(page,'Resources');
  await expect(page.getByRole('heading',{name:'Analysis rules',exact:true})).toBeVisible();
  await expect(page.getByRole('checkbox',{name:'Enable Disk history assessment'})).not.toBeChecked();
  page.once('dialog',dialog=>dialog.accept());await navigate(page,'Resources');await expect(page.getByRole('heading',{name:'Resources',exact:true})).toBeVisible();
});

test('a billing status failure recovers by reading the same job without another submission',async({page})=>{
  await mockWorkspace(page);let submissions=0,reads=0;
  const url='/api/v1/finops/sync-jobs/77777777-7777-4777-8777-777777777777';
  await page.route('**/api/v1/finops/sync-status',route=>route.fulfill({json:{configured:true,automatic_sync_enabled:true,last_synced_at:null,recent_syncs:[],warning:'Synthetic source; coverage unverified.'}}));
  await page.route('**/api/v1/finops/sync?*',route=>{submissions++;return route.fulfill({status:202,json:{status:'queued',poll_url:url}});});
  await page.route('**'+url,route=>{reads++;return reads===1?route.fulfill({status:503,json:{detail:'Synthetic status outage'}}):route.fulfill({json:{status:'completed'}});});
  await navigate(page,'Cost allocation');await page.getByRole('button',{name:'Sync now',exact:true}).click();
  await expect(page.getByRole('alert').filter({hasText:'Synthetic status outage'})).toBeVisible();
  await page.getByRole('button',{name:'Check billing job status',exact:true}).click();
  await expect.poll(()=>reads).toBe(2);expect(submissions).toBe(1);
});
