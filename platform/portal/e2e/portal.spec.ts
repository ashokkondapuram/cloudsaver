import {test,expect,type Page} from './test';
const customer=(id:string,name:string)=>({id,name,status:'active',notes:null,version:1,created_at:'2026-10-01T00:00:00Z',created_by:'synthetic',updated_at:'2026-10-01T00:00:00Z',updated_by:'synthetic',deleted_at:null,workspace_count:1,active_workspace_count:1,claim_status:'claimed'});
async function setup(page:Page,operator=true){
  const writes:{path:string;body:unknown}[]=[];
  await page.context().addCookies([{name:'cloudsaver_portal_session',value:'synthetic-ui-fixture',url:String(test.info().project.use.baseURL),httpOnly:true,sameSite:'Lax'}]);
  await page.route('**/api/**',async route=>{
    const request=route.request(),path=new URL(request.url()).pathname;
    if(path==='/api/auth/session')return route.fulfill({json:{signed_in:true,actor:'synthetic-operator',display_name:'Test operator',roles:[operator?'PlatformOperator':'PlatformAuditor'],auth_mode:'entra',provider_scoped_keys:true,environment:'development',key_prefix:'cs_test_',billing_enabled:true,billing_provider:'manual'}});
    if(request.method()!=='GET'){writes.push({path,body:request.postDataJSON()});return route.fulfill({status:409,json:{detail:'Synthetic fixture: no unconfigured mutation is accepted.'}});}
    if(path==='/api/portal/customers')return route.fulfill({json:{items:[customer('customer-a','Original customer')],next_cursor:null}});
    throw new Error(`Unmocked portal request: ${request.method()} ${path}`);
  });
  await page.goto('/customers');await expect(page.getByRole('heading',{name:'Customers',exact:true})).toBeVisible();
  return writes;
}

test('auditor has read access without customer mutation controls',async({page})=>{
  const writes=await setup(page,false);await expect(page.getByRole('link',{name:'Original customer',exact:true})).toBeVisible();
  await expect(page.getByRole('button',{name:'Create customer',exact:true})).toHaveCount(0);expect(writes).toEqual([]);
});

test('operator dialog supports keyboard dismissal and restores focus',async({page})=>{
  await setup(page);const create=page.getByRole('button',{name:'Create customer',exact:true});await create.click();
  await expect(page.getByRole('dialog',{name:'Create customer',exact:true})).toBeVisible();
  await expect(page.getByRole('textbox',{name:'Customer name',exact:true})).toBeFocused();
  await page.keyboard.press('Escape');await expect(page.getByRole('dialog')).toHaveCount(0);await expect(create).toBeFocused();
});

test('failed filtered read removes old rows and exposes recovery',async({page})=>{
  await setup(page);await expect(page.getByRole('link',{name:'Original customer',exact:true})).toBeVisible();
  await page.route('**/api/portal/customers?**',r=>r.fulfill({status:503,json:{detail:'Synthetic read unavailable'}}));
  await page.getByRole('searchbox',{name:'Search'}).fill('new');
  await expect(page.getByRole('alert').filter({hasText:'Synthetic read unavailable'})).toBeVisible();
  await expect(page.getByRole('link',{name:'Original customer',exact:true})).toHaveCount(0);
  await expect(page.getByRole('heading',{name:'Customers',exact:true})).toBeVisible();
});

test('late pagination cannot overwrite a newer customer filter',async({page})=>{
  await setup(page);
  let release=()=>{},requested=false;const gate=new Promise<void>(r=>release=r);
  await page.route('**/api/portal/customers?**',async route=>{
    const params=new URL(route.request().url()).searchParams;
    if(params.has('cursor')){requested=true;await gate;return route.fulfill({json:{items:[customer('customer-old','Late old page')],next_cursor:null}}).catch(()=>{});}
    return route.fulfill({json:{items:[params.get('q')?customer('customer-new','Filtered customer'):customer('customer-a','Original customer')],next_cursor:params.get('q')?null:'old-page'}});
  });
  await page.getByRole('button',{name:'Refresh',exact:true}).click();
  await page.getByRole('button',{name:'Load more',exact:true}).click();await expect.poll(()=>requested).toBe(true);
  await page.getByRole('searchbox',{name:'Search'}).fill('new');
  await expect(page.getByRole('link',{name:'Filtered customer',exact:true})).toBeVisible();
  const response=page.waitForResponse(r=>new URL(r.url()).searchParams.has('cursor'));release();await (await response).finished();
  await page.evaluate(()=>new Promise<void>(resolve=>requestAnimationFrame(()=>requestAnimationFrame(()=>resolve()))));
  await expect(page.getByRole('link',{name:'Filtered customer',exact:true})).toBeVisible();
  await expect(page.getByRole('link',{name:'Original customer',exact:true})).toHaveCount(0);await expect(page.getByRole('link',{name:'Late old page',exact:true})).toHaveCount(0);
});

test('malformed list success is an evidence error rather than a blank or crashed page',async({page})=>{
  await setup(page);await page.route('**/api/portal/customers?**',r=>r.fulfill({json:{}}));
  await page.getByRole('button',{name:'Refresh',exact:true}).click();
  await expect(page.getByRole('alert').filter({hasText:'incomplete response'})).toBeVisible();
  await expect(page.getByRole('heading',{name:'Customers',exact:true})).toBeVisible();
  await expect(page.getByRole('link',{name:'Original customer',exact:true})).toHaveCount(0);
});

test('ambiguous customer write is not replayed and retains the review dialog',async({page})=>{
  await setup(page);let writes=0;
  await page.route('**/api/portal/customers',async route=>{writes++;await route.abort('failed');});
  await page.getByRole('button',{name:'Create customer',exact:true}).click();
  const dialog=page.getByRole('dialog',{name:'Create customer',exact:true});
  await dialog.getByRole('textbox',{name:'Customer name',exact:true}).fill('New synthetic customer');
  await dialog.getByRole('button',{name:'Create customer',exact:true}).click();
  await expect(dialog.getByRole('alert')).toContainText('Check activity before submitting again.');expect(writes).toBe(1);
  await expect(dialog.getByRole('textbox',{name:'Customer name',exact:true})).toHaveValue('New synthetic customer');
});

test('mobile customer view fits the viewport with a loaded record',async({page})=>{
  await page.setViewportSize({width:390,height:844});await setup(page);
  await expect(page.getByRole('link',{name:'Original customer',exact:true})).toBeVisible();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
});

const tenantId='11111111-1111-4111-8111-111111111111';
const workspace={tenant_id:tenantId,customer_id:'customer-a',customer_name:'Original customer',name:'Production workspace',plan_tier:'GROWTH',status:'active',identity:{},subscription_ids:[],aws_accounts:[],gcp_projects:[],kubernetes_clusters:[],providers:['azure'],version:5,created_at:'2026-10-01T00:00:00Z',updated_at:'2026-10-01T00:00:00Z',created_by:'synthetic',updated_by:'synthetic',suspended_at:null,deleted_at:null,active_keys:1,last_used_at:null,next_expiry:null};
const rule={id:'TEST_RULE',name:'Disk assessment',description:'Synthetic rule with an explicit evidence requirement',provider:'azure',service_category:'storage',resource_type:'microsoft.compute/disks',pillar:'cost',status:'published',enabled:true,unavailable_reason:null,catalog_version:2,override_version:null};
async function workspaceRules(page:Page,operator=true){
  await setup(page,operator);
  await page.route(`**/api/portal/workspaces/${tenantId}`,route=>route.fulfill({json:workspace}));
  await page.route(`**/api/portal/workspaces/${tenantId}/analysis-rules`,route=>route.fulfill({json:{tenant_id:tenantId,version:5,items:[rule,{...rule,id:'TEST_UNAVAILABLE',name:'Unavailable rule',unavailable_reason:'Source not configured'}]}}));
  await page.goto(`/workspaces/${tenantId}?tab=rules`);await expect(page.getByRole('heading',{name:'Published rules'})).toBeVisible();
}

test('workspace rule edits require exact customer and workspace review before one versioned write',async({page})=>{
  await workspaceRules(page);const writes:unknown[]=[];
  await page.route(`**/api/portal/workspaces/${tenantId}/analysis-rules`,async route=>{
    if(route.request().method()==='PUT'){writes.push(route.request().postDataJSON());return route.fulfill({json:{tenant_id:tenantId,version:6,items:[{...rule,enabled:false}]}});}
    return route.fulfill({json:{tenant_id:tenantId,version:5,items:[rule]}});
  });
  await page.getByRole('switch',{name:'Toggle Disk assessment'}).click();expect(writes).toEqual([]);await page.getByRole('button',{name:'Review 1 rule changes'}).click();
  const review=page.getByRole('dialog',{name:'Review workspace rule changes'});await expect(review).toContainText('Original customer');await expect(review).toContainText('Production workspace');await expect(review).toContainText('Enabled → Disabled');
  await review.getByRole('button',{name:'Apply rule changes'}).click();await expect(review).toHaveCount(0);expect(writes).toEqual([{version:5,rules:[{rule_id:'TEST_RULE',enabled:false}]}]);
  await expect(page.getByRole('status').filter({hasText:'Policy version 6 saved'})).toBeVisible();
});

test('auditor can inspect rule provenance without edits and keyboard tabs preserve workspace context',async({page})=>{
  await workspaceRules(page,false);await expect(page.getByRole('switch')).toHaveCount(0);await page.getByText('Rule details: Disk assessment',{exact:true}).click();await expect(page.locator('.rule-details[open]')).toContainText('TEST_RULE');
  await expect(page.getByRole('region',{name:'Administration context'})).toContainText('Original customer');const tab=page.getByRole('tab',{name:'Rules',exact:true});await tab.focus();await page.keyboard.press('Home');await expect(page.getByRole('tab',{name:'Overview',exact:true})).toBeFocused();await expect(page).toHaveURL(/tab=overview/);
});

test('operator policy conflict blocks reapply until a read refresh and retains intended draft',async({page})=>{
  await workspaceRules(page);let writes=0,version=5;
  await page.route(`**/api/portal/workspaces/${tenantId}/analysis-rules`,async route=>{
    if(route.request().method()==='PUT'){writes++;version=6;return route.fulfill({status:409,json:{detail:'Policy changed'}});}
    return route.fulfill({json:{tenant_id:tenantId,version,items:[rule]}});
  });
  await page.getByRole('switch',{name:'Toggle Disk assessment'}).click();await page.getByRole('button',{name:'Review 1 rule changes'}).click();await page.getByRole('button',{name:'Apply rule changes'}).click();await expect(page.getByRole('button',{name:'Review 1 rule changes'})).toBeDisabled();
  await page.getByRole('button',{name:'Reload current policy',exact:true}).click();await expect(page.getByRole('switch',{name:'Toggle Disk assessment'})).not.toBeChecked();await page.getByRole('button',{name:'Review 1 rule changes'}).click();await expect(page.getByRole('dialog',{name:'Review workspace rule changes'})).toContainText('Expected policy version: 6');expect(writes).toBe(1);
});

test('workspace rule filters fit mobile and unavailable rules have no mutation control',async({page})=>{
  await page.setViewportSize({width:390,height:844});await workspaceRules(page);await page.getByLabel('Effective state',{exact:true}).selectOption('Unavailable');await expect(page.getByRole('switch')).toHaveCount(0);await expect(page.getByText('Unavailable rule',{exact:true})).toBeVisible();expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
});

test('unsaved operator rules require confirmation before leaving the workspace tab',async({page})=>{
  await workspaceRules(page);await page.getByRole('switch',{name:'Toggle Disk assessment'}).click();
  page.once('dialog',dialog=>dialog.dismiss());await page.getByRole('tab',{name:'Overview',exact:true}).click();
  await expect(page.getByRole('tab',{name:'Rules',exact:true})).toHaveAttribute('aria-selected','true');
  await page.getByRole('tab',{name:'Rules',exact:true}).focus();page.once('dialog',dialog=>dialog.dismiss());await page.keyboard.press('Home');await expect(page.getByRole('tab',{name:'Rules',exact:true})).toHaveAttribute('aria-selected','true');
  page.once('dialog',dialog=>dialog.accept());await page.getByRole('tab',{name:'Overview',exact:true}).click();
  await expect(page.getByRole('tab',{name:'Overview',exact:true})).toHaveAttribute('aria-selected','true');
});
