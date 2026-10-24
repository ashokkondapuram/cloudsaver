import {test,expect,type Page} from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import {mockWorkspace,navigate,scanTime} from './workspace-fixture';

const attempt='77777777-7777-4777-8777-777777777777';
function view(){return {policy:{status:'enforced',policy_revision:4,environment_id:'company-production',response_retention_days:7,
  processors:[{target_id:'approved-review',deployment_name:'company-review',endpoint_url:'https://company.openai.azure.com',azure_resource_id:'/subscriptions/synthetic/resourceGroups/rg/providers/Microsoft.CognitiveServices/accounts/company',
    purposes:['assessment','agent_planning'],review_reference:'DATA-REVIEW-42',review_expires_at:'2026-12-01T00:00:00Z'}]},
  records:[{attempt_id:attempt,purpose:'assessment',expires_at:'2026-10-31T00:00:00Z',erased_at:null as string|null}],active_holds:[] as {attempt_id:string;hold_until:string;review_reference:string}[],
  events:[{id:'review-1',purpose:'assessment',decision:'blocked',reason:'SECRET_DETECTED',created_at:scanTime,actor_reference:'a'.repeat(64)}],counts:{allowed:2,blocked:1,erased:0}};}
async function mock(page:Page,initial=view()){
  let current=initial;const mutations:Record<string,unknown>[]=[];
  await page.route('**/api/v1/ai/governance',route=>route.fulfill({json:current}));
  await page.route(`**/api/v1/ai/governance/records/${attempt}/*`,route=>{
    const body=route.request().postDataJSON();mutations.push(body);
    if(route.request().url().endsWith('/erase'))current={...current,records:current.records.map(r=>({...r,erased_at:scanTime})),counts:{...current.counts,erased:1}};
    else current={...current,active_holds:[{attempt_id:attempt,hold_until:body.hold_until,review_reference:body.review_reference}]};
    return route.fulfill({json:{content_erased:true}});
  });
  return mutations;
}

test('data owner reviews classification and explicitly erases content with an internal reference',async({page})=>{
  await mockWorkspace(page);const mutations=await mock(page);await navigate(page,'AI data governance');
  await expect(page.getByText('Prohibited',{exact:true})).toHaveCount(2);
  await expect(page.getByRole('cell').filter({hasText:'DATA-REVIEW-42'})).toBeVisible();
  await page.getByRole('button',{name:'Erase AI content',exact:true}).click();
  const form=page.getByRole('form',{name:'Privacy action review'});const confirm=form.getByRole('button',{name:'Confirm content erasure'});
  await expect(confirm).toBeDisabled();await form.getByLabel('Internal review reference').fill('PRIVACY-42');
  await form.getByRole('checkbox').check();await confirm.click();
  await expect(page.getByRole('cell').filter({hasText:'Content erased'})).toBeVisible();expect(mutations).toEqual([{review_reference:'PRIVACY-42'}]);
});

test('viewer sees governance evidence without privacy mutation controls on mobile',async({page})=>{
  await page.setViewportSize({width:390,height:844});await mockWorkspace(page,{role:'Viewer'});const mutations=await mock(page);
  await navigate(page,'AI data governance');await expect(page.getByRole('heading',{name:'Data-use audit'})).toBeVisible();
  await expect(page.getByRole('button',{name:'Erase AI content'})).toHaveCount(0);await expect(page.getByRole('button',{name:'Place legal hold'})).toHaveCount(0);
  expect(mutations).toEqual([]);expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
  const audit=await new AxeBuilder({page}).include('main').withTags(['wcag2a','wcag2aa','wcag21aa']).analyze();expect(audit.violations).toEqual([]);
});

test('unregistered environment exposes a blocked state without starting inference',async({page})=>{
  await mockWorkspace(page);const data=view();data.policy.status='processing_blocked';data.policy.processors=[];data.records=[];data.events=[];
  const mutations=await mock(page,data);await navigate(page,'AI data governance');
  await expect(page.getByRole('heading',{name:'No processing approvals'})).toBeVisible();
  await expect(page.getByText(/AI processing is blocked until/)).toBeVisible();expect(mutations).toEqual([]);
});

test('legal hold requires explicit confirmation and then disables erasure controls',async({page})=>{
  await mockWorkspace(page);const mutations=await mock(page);await navigate(page,'AI data governance');
  await page.getByRole('button',{name:'Place legal hold',exact:true}).click();const form=page.getByRole('form',{name:'Privacy action review'});
  await form.getByLabel('Internal review reference').fill('LEGAL-42');await form.getByLabel('Hold expiry (within 30 days)').fill('2026-10-30T12:00');
  await form.getByRole('checkbox').check();await form.getByRole('button',{name:'Confirm legal hold'}).click();
  await expect(page.getByRole('cell').filter({hasText:'LEGAL-42'})).toBeVisible();await expect(page.getByRole('button',{name:'Erase AI content',exact:true})).toBeDisabled();
  expect(mutations[0]).toMatchObject({review_reference:'LEGAL-42'});expect(typeof mutations[0].hold_until).toBe('string');
});
