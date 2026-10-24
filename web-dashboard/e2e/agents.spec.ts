import {test,expect} from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import {mockWorkspace,navigate,scanId,subscriptionId,scanTime} from './workspace-fixture';

const id='99999999-9999-4999-8999-999999999999';
const resource={resource_id:`/subscriptions/${subscriptionId}/resourceGroups/rg/providers/Microsoft.Compute/disks/qa`,resource_name:'qa',cloud_provider:'azure',subscription_id:subscriptionId,scope_id:subscriptionId};
const connector={id:'azure-tags',provider:'azure',scope_id:subscriptionId,kind:'azure_arm',operations:['resource.inspect','tags.merge'],endpoint:null};
function task(state='awaiting_approval'){
  return {id,resource_id:resource.resource_id,state,version:3,created_at:scanTime,code:'export async function run(ctx: AgentContext) { await ctx.call(0); }',
    payload:{intent:'Set CostCenter to FINOPS-42 after inspecting tags.',plan_hash:'a'.repeat(64),approval:null,connector_bindings:[connector],
      plan:{summary:'Inspect and apply the reviewed cost center.',steps:[{connector_id:'azure-tags',operation:'tags.merge',arguments:{tags:{CostCenter:'FINOPS-42'}},purpose:'Apply the requested allocation tag.',verification:'Read the exact tag back.',rollback:'Review the previous value before reversal.'}]},steps:[{state:'pending'}]},events:[{version:3,action:'ai_plan_drafted',created_at:scanTime}]};
}
async function mocks(page:import('@playwright/test').Page,state='awaiting_approval'){
  let current=task(state);const reviews:Record<string,unknown>[]=[];
  await page.route('**/api/v1/agents/catalog',r=>r.fulfill({json:{enabled:true,connectors:[connector]}}));
  await page.route(`**/api/v1/scans/${scanId}/resources?limit=1000`,r=>r.fulfill({json:{items:[{...resource,provider:resource.cloud_provider}]}}));
  await page.route('**/api/v1/agents/tasks',r=>r.fulfill({json:{items:[current]}}));
  await page.route('**/api/v1/agents/tasks/'+id,r=>r.fulfill({json:current}));
  await page.route('**/api/v1/agents/tasks/'+id+'/review',r=>{
    reviews.push(r.request().postDataJSON());current={...current,state:'approved',version:4};return r.fulfill({json:current});
  });
  return reviews;
}

test('administrator reviews exact connector arguments and explicitly approves a versioned plan',async({page})=>{
  await mockWorkspace(page,{ai:true,human:true});const reviews=await mocks(page);
  await navigate(page,'Agent workspace');await page.getByRole('button',{name:/Set CostCenter to FINOPS-42/}).click();
  const review=page.getByRole('region',{name:'Agent plan review'});
  await expect(review.getByText('Apply the requested allocation tag.')).toBeVisible();
  const approve=review.getByRole('button',{name:'Approve this plan'});await expect(approve).toBeDisabled();
  await review.getByLabel('I reviewed the resource, connector destinations, exact arguments and recovery limits.').check();
  await approve.click();expect(reviews).toHaveLength(1);expect(reviews[0]).toMatchObject({version:3,decision:'approve',plan_hash:'a'.repeat(64),expires_in_minutes:15});
  await expect(approve).toHaveCount(0);
  const audit=await new AxeBuilder({page}).include('main').withTags(['wcag2a','wcag2aa','wcag21aa']).analyze();expect(audit.violations).toEqual([]);
});

test('viewer can inspect plans without assigning or approving tasks on mobile',async({page})=>{
  await page.setViewportSize({width:390,height:844});await mockWorkspace(page,{role:'Viewer'});await mocks(page);
  await navigate(page,'Agent workspace');await page.getByRole('button',{name:/Set CostCenter to FINOPS-42/}).click();
  await expect(page.getByRole('button',{name:'Approve this plan'})).toHaveCount(0);
  await expect(page.getByRole('button',{name:'Request AI execution plan'})).toHaveCount(0);
  await page.getByText('TypeScript runCode program',{exact:true}).click();
  await expect(page.getByText(/export async function run/)).toBeVisible();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
  const audit=await new AxeBuilder({page}).include('main').withTags(['wcag2a','wcag2aa','wcag21aa']).analyze();expect(audit.violations).toEqual([]);
  await page.screenshot({path:test.info().outputPath('agent-review-mobile.png'),fullPage:true});
});

test('uncertain actions expose reconciliation without replay controls',async({page})=>{
  await mockWorkspace(page,{human:true});const reviews=await mocks(page,'needs_reconciliation');
  await navigate(page,'Agent workspace');await page.getByRole('button',{name:/Set CostCenter to FINOPS-42/}).click();
  await expect(page.getByText(/This task will not replay automatically/)).toBeVisible();
  await expect(page.getByRole('button',{name:'Request new AI draft'})).toHaveCount(0);
  await expect(page.getByRole('button',{name:'Approve this plan'})).toHaveCount(0);expect(reviews).toEqual([]);
});

test('task assignment sends the selected owned resource, explicit connectors and task instruction',async({page})=>{
  await mockWorkspace(page,{ai:true,human:true});await mocks(page);let submitted:Record<string,unknown>|null=null;
  await page.route('**/api/v1/agents/tasks',r=>{
    if(r.request().method()==='POST'){submitted=r.request().postDataJSON();return r.fulfill({status:201,json:{...task('draft_queued'),payload:{...task().payload,plan:null,plan_hash:null}}});}
    return r.fulfill({json:{items:[]}});
  });
  await navigate(page,'Agent workspace');await page.getByLabel('Resource from selected scan').selectOption(resource.resource_id);
  await page.getByLabel('Approved planning model').selectOption('approved-review');
  await page.getByRole('checkbox',{name:/azure-tags/}).check();await page.getByLabel('Task instruction').fill('Set CostCenter to FINOPS-42 after inspecting tags.');
  await page.getByRole('button',{name:'Request AI execution plan'}).click();
  await expect(page.getByText('The gateway is waiting for a worker to draft the plan. No cloud action is approved.')).toBeVisible();
  expect(submitted).toMatchObject({scan_id:scanId,resource_id:resource.resource_id,target_id:'approved-review',connector_ids:['azure-tags']});
});

test('completed drafting updates the open review panel when queue polling stops',async({page})=>{
  await mockWorkspace(page,{ai:true,human:true});await mocks(page);let ready=false;
  const current=()=>ready?task():{...task('drafting'),payload:{...task().payload,plan:null,plan_hash:null}};
  await page.route('**/api/v1/agents/tasks',r=>r.fulfill({json:{items:[current()]}}));
  await page.route('**/api/v1/agents/tasks/'+id,r=>r.fulfill({json:current()}));
  await navigate(page,'Agent workspace');await page.getByRole('button',{name:/Set CostCenter to FINOPS-42/}).click();
  await expect(page.getByText('The gateway is waiting for a worker to draft the plan. No cloud action is approved.')).toBeVisible();ready=true;
  await expect(page.getByRole('button',{name:'Approve this plan'})).toBeVisible({timeout:10000});
  await expect(page.getByText('Inspect and apply the reviewed cost center.')).toBeVisible();
});
