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
