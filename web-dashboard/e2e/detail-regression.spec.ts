import {test,expect} from './test';
import {mockWorkspace,navigate,buildResourceItems,resourceDetail,createFindings,scanId,scanTime} from './workspace-fixture';

test('resource search and bounded table paging include resources beyond the first source page',async({page})=>{
  await mockWorkspace(page);
  const findings=createFindings(1001),items=buildResourceItems(findings),offsets:number[]=[];
  await page.route(`**/api/v1/scans/${scanId}/resources?**`,async route=>{
    const offset=Number(new URL(route.request().url()).searchParams.get('offset')||0);offsets.push(offset);
    await route.fulfill({json:{scan_id:scanId,observed_at:scanTime,total:items.length,items:items.slice(offset,offset+1000),summary:{total:items.length,ai_status:{not_run:items.length},ai_risk:{none:items.length},decision:{none:items.length},review_priority:{high:items.length}}}});
  });
  await navigate(page,'Resources');
  await expect(page.locator('.resource-table tbody tr')).toHaveCount(50);
  expect(offsets).toEqual([0,1000]);
  await page.getByRole('navigation',{name:'Resource pages'}).getByRole('button',{name:'Next resources',exact:true}).click();
  await expect(page.getByRole('button',{name:/^legacy-storage-51/})).toBeVisible();
  await page.getByRole('searchbox',{name:'Search resources'}).fill('archive-data-1001');
  await expect(page.locator('.resource-table tbody tr')).toHaveCount(1);
  await expect(page.getByRole('button',{name:/^archive-data-1001/})).toBeVisible();
});

test('closing and reopening a resource requires fresh details before showing old decisions',async({page})=>{
  const {findings}=await mockWorkspace(page);await navigate(page,'Resources');
  await page.getByRole('button',{name:/^archive-data-01/}).click();
  const drawer=page.getByRole('dialog',{name:'Resource details',exact:true});
  await expect(drawer.getByRole('heading',{name:'Resource identity'})).toBeVisible();
  await page.keyboard.press('Escape');
  let requested=false,release=()=>{};const gate=new Promise<void>(r=>release=r);
  await page.route(`**/api/v1/scans/${scanId}/resources/*`,async route=>{
    requested=true;await gate;const key=new URL(route.request().url()).pathname.split('/').at(-1)!;
    await route.fulfill({json:resourceDetail(scanId,findings,key)}).catch(()=>{});
  });
  await page.getByRole('button',{name:/^archive-data-01/}).click();
  await expect.poll(()=>requested).toBe(true);
  await expect(drawer.getByText('Loading resource details…')).toBeVisible();
  await expect(drawer.getByRole('heading',{name:'Resource identity'})).toHaveCount(0);
  release();await expect(drawer.getByRole('heading',{name:'Resource identity'})).toBeVisible();
});

test('revoked session clears workspace data, credentials and action controls',async({page})=>{
  await mockWorkspace(page);await navigate(page,'Resources');
  await expect(page.getByRole('button',{name:/^archive-data-01/})).toBeVisible();
  await page.route('**/api/v1/scans',r=>r.fulfill({status:401,json:{detail:'Session revoked'}}));
  await page.getByRole('button',{name:'Refresh workspace',exact:true}).click();
  await expect(page.getByLabel('Workspace access key or Entra Bearer token')).toBeVisible();
  await expect(page.getByRole('button',{name:'Run new scan',exact:true})).toHaveCount(0);
  await expect(page.getByText('Your session ended. Connect again to continue.',{exact:true})).toBeVisible();
  expect(await page.evaluate(()=>sessionStorage.getItem('cloudsaver:session:token'))).toBeNull();
  await expect(page.getByText('archive-data-01',{exact:true})).toHaveCount(0);
});

test('forbidden resource data keeps login but exposes no stale resource list',async({page})=>{
  await mockWorkspace(page);
  await page.route(`**/api/v1/scans/${scanId}/resources?**`,r=>r.fulfill({status:403,json:{detail:'Current scope denied'}}));
  await navigate(page,'Resources');
  await expect(page.getByRole('alert').filter({hasText:'Current scope denied'})).toBeVisible();
  await expect(page.getByRole('heading',{name:'Resources',exact:true})).toBeVisible();
  await expect(page.getByLabel('Workspace access key or Entra Bearer token')).toHaveCount(0);
  await expect(page.getByRole('button',{name:/^archive-data-01/})).toHaveCount(0);
});

test('scope changes discard selections from the previous scope',async({page})=>{
  await mockWorkspace(page);await navigate(page,'Resources');
  await page.getByRole('checkbox',{name:'Select archive-data-01',exact:true}).check();
  await expect(page.getByRole('region',{name:'Selected resources actions'})).toBeVisible();
  await page.locator('.scope-picker>summary').click();
  await page.getByRole('checkbox',{name:'finops-project',exact:true}).check();
  await page.locator('.scope-picker>summary').click();
  await expect(page.getByRole('region',{name:'Selected resources actions'})).toHaveCount(0);
  await expect(page.locator('.resource-table tbody tr')).toHaveCount(3);
});

test('unavailable batch status blocks duplicate assessment and can recover without invoking AI',async({page})=>{
  const {mutations}=await mockWorkspace(page);
  await page.route('**/api/v1/ai-batches?**',r=>r.fulfill({json:{items:[{id:'broken',scan_id:scanId,status:'running',total:1,counts:{}}]}}));
  await navigate(page,'Resources');
  await expect(page.getByRole('status').filter({hasText:'AI assessment status is unavailable.'})).toBeVisible();
  await expect(page.getByRole('button',{name:'Run AI assessment',exact:true})).toBeDisabled();
  await page.route('**/api/v1/ai-batches?**',r=>r.fulfill({json:{items:[]}}));
  await page.getByRole('button',{name:'Check assessment status',exact:true}).click();
  await expect(page.getByRole('button',{name:'Run AI assessment',exact:true})).toBeEnabled();
  expect(mutations).toEqual([]);
});

test('inventory-only resources remain discoverable in provider, category and missing-price views',async({page})=>{
  await mockWorkspace(page);
  const row={...buildResourceItems(createFindings(1))[0],provider:'gcp',resource_id:'gcp/finops-project/inventory-only',resource_name:'inventory-only',scope_id:'finops-project',resource_type:'compute.disks',rule_ids:[],finding_count:0,retail_estimate_usd:null};
  await page.route(`**/api/v1/scans/${scanId}/resources?**`,r=>r.fulfill({json:{scan_id:scanId,observed_at:scanTime,total:1,items:[row],summary:{total:1,ai_status:{not_run:1},ai_risk:{none:1},decision:{none:1},review_priority:{high:1}}}}));
  await navigate(page,'Resources');
  await expect(page.getByRole('button',{name:/^Google Cloud 1$/})).toBeVisible();
  await page.getByRole('group',{name:'Resource categories'}).getByRole('button',{name:/^Storage 1$/}).click();
  await page.getByRole('group',{name:'Evidence quick views'}).getByRole('button',{name:'Missing prices',exact:true}).click();
  await expect(page.getByRole('button',{name:/^inventory-only/})).toBeVisible();
});

test('malformed workspace connection remains on login without cached credentials or runtime errors',async({page})=>{
  await mockWorkspace(page);
  await page.locator('.workspace-menu>summary').click();await page.locator('.workspace-menu').getByRole('button',{name:'Disconnect',exact:true}).click();
  await page.route('**/api/v1/me',r=>r.fulfill({json:{roles:'TenantAdmin'}}));
  await page.getByLabel('Workspace access key or Entra Bearer token').fill('invalid-bootstrap-fixture');
  await page.getByRole('button',{name:'Connect workspace',exact:true}).click();
  await expect(page.getByRole('alert').filter({hasText:'Workspace evidence is incomplete or inconsistent.'})).toBeVisible();
  await expect(page.getByRole('button',{name:'Run new scan',exact:true})).toHaveCount(0);
  expect(await page.evaluate(()=>sessionStorage.getItem('cloudsaver:session:token'))).toBeNull();
});
