import {test,expect} from './test';
import {mockWorkspace,navigate,scanId,subscriptionId,buildResourceItems,createFindings,tenantId} from './workspace-fixture';
import AxeBuilder from '@axe-core/playwright';

const wid='44444444-4444-4444-8444-444444444444',mid='55555555-5555-4555-8555-555555555555',pid='66666666-6666-4666-8666-666666666666';
const item=buildResourceItems(createFindings())[0];
const base={id:wid,tenant_id:tenantId,name:'Payments',environment:'nonproduction',owner:'Platform owner',team:'Engineering',scope_id:subscriptionId,provider:'azure',version:1,requirements:{}};
const readiness={decision:'evidence_required',evaluated_at:'2026-10-28T12:00:00Z',checks:[{code:'ATTACHMENT_HISTORY',status:'unknown',reason:'Attachment history is missing.'},{code:'TRUSTED_TERRAFORM_PLAN',status:'unknown',reason:'A reviewed saved plan is required.'}],financial_outcome:{estimated_opportunity:null,validated_run_rate:null,reconciled_benefit:null}};

async function fixture(page:Parameters<typeof mockWorkspace>[0],options:{role?:string;empty?:boolean;uncertain?:boolean}={}){
  await mockWorkspace(page,{role:options.role});
  await page.route('**/api/v1/outcomes/ownership',route=>route.fulfill({json:{items:[],basis:'current_direct_resource_mapping'}}));
  let workloads:any[]=options.empty?[]:[{...base}],members:any[]=[],plans:any[]=[],versions:any[]=[],attempts=0;
  const commands:{path:string;key:string|undefined;match:string|undefined;body:any}[]=[];
  await page.route('**/api/v1/engineering/**',async route=>{
    const req=route.request(),path=new URL(req.url()).pathname,method=req.method();let response:any;
    if(method!=='GET')commands.push({path,key:req.headers()['idempotency-key'],match:req.headers()['if-match'],body:req.postDataJSON()});
    if(path.endsWith('/capabilities'))response={stage:'local_review',scopes:[{scope_id:subscriptionId}],actions:[{id:'azure.disk.review',mode:'review_only'}],acceptance_required:['protected_pipeline_attestation','independent_approval','billing_reconciliation']};
    else if(path==='/api/v1/engineering/workloads'){
      if(method==='POST'){attempts++;if(!workloads.length)workloads=[{...base,...req.postDataJSON()}];if(options.uncertain&&attempts===1)return route.fulfill({status:503,json:{detail:'Synthetic response lost after save'}});response=workloads[0];}
      else response={items:workloads,next_cursor:null};
    }else if(path.endsWith('/members')){
      if(method==='POST'){members=[{id:mid,scan_id:scanId,...item}];workloads[0].version++;response={id:mid,workload_version:workloads[0].version};}
      else response={items:members,next_cursor:null};
    }else if(path.endsWith('/plans')||path.endsWith('/versions')){
      if(method==='POST'){
        const body=req.postDataJSON();const version={id:'77777777-7777-4777-8777-'+String(versions.length+1).padStart(12,'0'),plan_id:pid,version:versions.length+1,identity_digest:String(versions.length+1).repeat(64),context_changed:false,parameters:{...body,scan_id:body.scan_id||scanId,readiness}};
        versions.push(version);plans=[{id:pid,latest:version}];response=version;
      }else response={items:path.endsWith('/versions')?versions:plans,next_cursor:null};
    }else if(path.endsWith('/events'))response={items:[{id:'event',kind:'workload.created',created_at:'2026-10-28T12:00:00Z'}],next_cursor:null};
    else if(path.endsWith(wid))response=workloads[0];
    else return route.fulfill({status:404,json:{detail:'Unknown test route'}});
    return route.fulfill({status:method==='POST'?201:200,json:response});
  });
  await navigate(page,'Workload assessments');
  await page.getByRole('button',{name:'Engineering plans',exact:true}).click();
  return {commands};
}

test('engineering review attaches evidence and keeps immutable version history',async({page})=>{
  const {commands}=await fixture(page);
  await page.getByRole('button',{name:'Payments · nonproduction',exact:true}).click();
  await page.getByText('Attach resource from selected observation',{exact:true}).click();
  await page.getByRole('combobox',{name:'Resource',exact:true}).selectOption(item.resource_key);
  await page.getByRole('button',{name:'Attach resource',exact:true}).click();
  await expect(page.getByText('Workload version 2',{exact:false})).toBeVisible();
  await page.getByText('Prepare an improvement plan',{exact:true}).click();
  await page.getByRole('combobox',{name:'Workload resource',exact:true}).selectOption(mid);
  await page.getByLabel('Objective',{exact:true}).fill('Review disk retention and recovery evidence');
  await page.getByRole('button',{name:'Save evidence review',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Review disk retention and recovery evidence'})).toBeVisible();
  await page.getByText('Evidence checks (2)',{exact:true}).click();
  await expect(page.getByText('Attachment history is missing.',{exact:true})).toBeVisible();
  await page.getByText('Create a new review version',{exact:true}).click();
  await page.getByRole('button',{name:'Save new version',exact:true}).click();
  await page.getByRole('button',{name:'View version history',exact:true}).click();
  await expect(page.getByText(/Version 1: Disk review/)).toBeVisible();
  await expect(page.getByText(/Version 2: Disk review/)).toBeVisible();
  expect(commands.map(c=>c.match)).toEqual(['"1"','"2"','"2"']);
  expect(new Set(commands.map(c=>c.key)).size).toBe(3);
  expect(commands[1].body).toMatchObject({member_id:mid,action:'azure.disk.review',candidate_sku:null});
  expect(commands.some(c=>/executions|approvals/.test(c.path))).toBe(false);
});

test('uncertain workload creation reuses the same command and key',async({page})=>{
  const {commands}=await fixture(page,{empty:true,uncertain:true});
  await page.getByText('Create a workload',{exact:true}).click();
  await page.getByLabel('Name',{exact:true}).fill('Payments');
  await page.getByLabel('Owner',{exact:true}).fill('Platform owner');
  await page.getByLabel('Team',{exact:true}).fill('Engineering');
  await page.getByLabel('Authorized Azure subscription').selectOption(subscriptionId);
  await page.getByRole('button',{name:'Create workload',exact:true}).click();
  await expect(page.getByRole('button',{name:'Retry same request',exact:true})).toBeVisible();
  await expect(page.getByLabel('Name',{exact:true})).toBeDisabled();
  await page.getByRole('button',{name:'Retry same request',exact:true}).click();
  await expect(page.getByRole('button',{name:'Payments · nonproduction',exact:true})).toBeVisible();
  expect(commands).toHaveLength(2);expect(commands[0]).toEqual(commands[1]);
});

test('viewer can inspect engineering records without finance access or write controls',async({page})=>{
  const {commands}=await fixture(page,{role:'Viewer'});
  await page.getByRole('button',{name:'Payments · nonproduction',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Payments',exact:true})).toBeVisible();
  await expect(page.getByText('Create a workload',{exact:true})).toHaveCount(0);
  await expect(page.getByText('Attach resource from selected observation',{exact:true})).toHaveCount(0);
  await page.getByRole('button',{name:'Pilot capabilities',exact:true}).click();
  await expect(page.getByText(/Infrastructure execution is disabled/)).toBeVisible();
  expect(commands).toEqual([]);
});

test('engineering forms remain accessible in both themes and narrow layouts',async({page})=>{
  await page.emulateMedia({reducedMotion:'reduce'});
  await fixture(page);
  await page.getByRole('button',{name:'Payments · nonproduction',exact:true}).click();
  await page.getByText('Edit ownership and evidence references',{exact:true}).click();
  await page.getByRole('button',{name:'Pilot capabilities',exact:true}).click();
  for(const width of [320,390,768,1440]){
    await page.setViewportSize({width,height:900});
    for(const theme of ['light','dark']){
      const toggle=page.getByRole('button',{name:`Switch to ${theme} theme`,exact:true});if(await toggle.count())await toggle.click();
      expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
      const results=await new AxeBuilder({page}).withTags(['wcag2a','wcag2aa','wcag21aa']).analyze();expect(results.violations).toEqual([]);
    }
  }
});
