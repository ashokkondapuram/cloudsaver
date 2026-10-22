import {expect,test,Page} from '@playwright/test';

// Browser-only fixtures. Every API call is intercepted; no cloud, DB, broker,
// payment or external webhook request is made by this suite.
const eventId='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const now='2026-10-22T12:00:00Z';

async function workspace(page:Page,admin=true){
  const mutations:unknown[]=[];
  let replayed=false;
  await page.route('**/api/v1/**',async route=>{
    const request=route.request(),url=new URL(request.url()),path=url.pathname;
    const row={id:eventId,kind:'notification',status:replayed?'pending':'dead_letter',target_id:'finops',job_id:null,scan_id:'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',attempts:replayed?0:8,replay_count:replayed?1:0,error_code:replayed?null:'provider_unavailable',created_at:now,updated_at:now};
    let response:unknown;
    if(path==='/api/v1/me')response={name:'Browser QA workspace',tenant_id:'11111111-1111-4111-8111-111111111111',subscription_ids:[],mode:'azure',plan_tier:'GROWTH',roles:admin?['TenantAdmin']:['Viewer'],providers:['azure'],can_export_terraform:true};
    else if(path==='/api/v1/scans')response=[];
    else if(path==='/api/v1/billing/entitlements')response={tier:'GROWTH',max_subscriptions:20,current_subscriptions:0,can_export_terraform:true,retention_days:90};
    else if(path==='/api/v1/gitops/targets')response={targets:[],publishing_enabled:false};
    else if(path==='/api/v1/gitops/requests')response=[];
    else if(path==='/api/v1/operations/reliability')response={available:true,dispatcher_enabled:true,targets:[{target_id:'finops',channel:'slack'}],counts:[{kind:'notification',status:row.status,count:1}],oldest_due_seconds:120,dispatcher:{last_poll_at:now,last_success_at:now,last_error_at:null}};
    else if(path==='/api/v1/operations/deliveries')response={items:!url.searchParams.get('status')||url.searchParams.get('status')===row.status?[row]:[],next_cursor:null};
    else if(path===`/api/v1/operations/deliveries/${eventId}/audit`)response={items:[{id:'audit-fixture',action:replayed?'replay_requested':'dead_letter',actor:'<img src=x onerror=window.qaXss=true>',status:row.status,attempts:row.attempts,error_code:row.error_code,created_at:now}],next_cursor:null};
    else if(path===`/api/v1/operations/deliveries/${eventId}/retry`){
      expect(request.method()).toBe('POST');mutations.push(request.postDataJSON());replayed=true;response={...row,status:'pending',attempts:0,replay_count:1};
    }else throw new Error('Unmocked API call: '+request.method()+' '+path);
    await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(response)});
  });
  await page.goto('/');
  await page.getByLabel('Workspace access key or Entra Bearer token').fill('test-only-browser-fixture');
  await page.getByRole('button',{name:'Connect workspace'}).click();
  await expect(page.getByRole('heading',{name:'Your cloud, in focus.'})).toBeVisible();
  if(await page.getByRole('button',{name:'Open navigation'}).isVisible()){
    await page.getByRole('button',{name:'Open navigation'}).click();
    await page.getByRole('navigation',{name:'Mobile navigation'}).getByRole('link',{name:'Activity & delivery'}).click();
  }else await page.getByRole('navigation',{name:'Primary navigation'}).getByRole('link',{name:'Activity & delivery'}).click();
  await expect(page.getByRole('heading',{name:'Delivery reliability'})).toBeVisible();
  return mutations;
}

test('admin inspects failures, acknowledges ambiguity and queues exactly one replay',async({page})=>{
  const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
  const mutations=await workspace(page);
  await page.getByRole('button',{name:/finops.*Needs intervention/}).click();
  await expect(page.getByRole('heading',{name:'Delivery audit'})).toBeVisible();
  await expect(page.getByText('Actor: <img src=x onerror=window.qaXss=true>')).toBeVisible();
  expect(await page.evaluate(()=>Boolean((window as unknown as {qaXss?:boolean}).qaXss))).toBe(false);
  const retry=page.getByRole('button',{name:'Queue retry (0/3 used)'});
  await expect(retry).toBeDisabled();
  await page.getByRole('checkbox',{name:'I understand this may send a duplicate notification.'}).check();
  await retry.click();
  await expect(page.getByText('replay requested',{exact:true})).toBeVisible();
  expect(mutations).toEqual([{acknowledge_duplicate_risk:true}]);
  expect(errors).toEqual([]);
});

test('viewer can inspect audit but has no replay controls; filtering works on mobile',async({page})=>{
  await page.setViewportSize({width:390,height:844});
  const mutations=await workspace(page,false);
  await page.getByLabel('Delivery state').selectOption('dead_letter');
  await page.getByRole('button',{name:/finops.*Needs intervention/}).click();
  await expect(page.getByRole('heading',{name:'Delivery audit'})).toBeVisible();
  await expect(page.getByRole('button',{name:/Queue retry/})).toHaveCount(0);
  await expect(page.getByRole('checkbox',{name:/duplicate notification/})).toHaveCount(0);
  expect(mutations).toEqual([]);
  const width=await page.evaluate(()=>({scroll:document.documentElement.scrollWidth,viewport:window.innerWidth}));
  expect(width.scroll).toBeLessThanOrEqual(width.viewport);
});
