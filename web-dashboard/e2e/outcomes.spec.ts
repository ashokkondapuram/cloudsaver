import {test,expect,type Page} from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import {mockWorkspace,navigate,scanId,subscriptionId,scanTime} from './workspace-fixture';

const resourceId=`/subscriptions/${subscriptionId}/resourceGroups/qa/providers/Microsoft.Compute/virtualMachines/finance-vm`;
const resource={resource_id:resourceId,resource_name:'finance-vm',resource_type:'Microsoft.Compute/virtualMachines',provider:'azure',scope_id:subscriptionId};
const caseId='44444444-4444-4444-8444-444444444444',anomalyId='55555555-5555-4555-8555-555555555555';
async function setup(page:Page,options:{role?:string;human?:boolean;state?:string;negative?:boolean}={}){
  await mockWorkspace(page,{role:options.role,human:options.human});
  const calls:{path:string;body:any}[]=[];
  let ownership:any=null,anomaly:any={id:anomalyId,state:'open',version:1,provider:'azure',scope_id:subscriptionId,resource_id:resourceId,currency:'USD',payload:{owner:'team-finance',day:'2026-10-20',increase:'70.00000000',baseline_daily_cost:'10.00000000',observed_daily_cost:'80.00000000',billing_lag_days:5,source_freshness:'delayed_billing',category_changes:{Usage:'60',Credit:'10'},ownership:{application:'payments',team:'platform',environment:'production'}},events:[]};
  let item:any={id:caseId,state:options.state||'detected',version:1,legacy:false,resource_id:resourceId,baseline_scan_id:scanId,provider:'azure',payload:{resource_name:'finance-vm',currency:'USD',proposal:'Resize with finance and reliability review.',estimated_opportunity:null,baseline_observed_at:scanTime,configuration:{vm_size:'D4'},baseline_billing:{billed_cost:null}},verification:null,evidence:[],events:[]};
  await page.route(`**/api/v1/scans/${scanId}/resources?**`,r=>r.fulfill({json:{items:[resource],total:1}}));
  await page.route('**/api/v1/outcomes/**',async route=>{
    const req=route.request(),path=new URL(req.url()).pathname.replace('/api/v1/outcomes',''),body=req.method()==='GET'?null:req.postDataJSON();
    if(body)calls.push({path,body});
    let response:any;
    if(path==='/summary')response={currencies:[{currency:'USD',estimated_opportunity:null,validated_run_rate_reduction:options.negative?'-900.00000000':null,reconciled_financial_benefit:null,unsupported_financial_claims:1}],implemented_cases:1,validated_cases:0,validated_outcome_pct:0,warning:'Retail estimates are not a financial outcome. Currencies are never combined.'};
    else if(path==='/cases'&&!body)response={items:[item]};
    else if(path==='/cases'&&body){item={...item,state:'detected',payload:{...item.payload,proposal:body.proposal}};response=item;}
    else if(path===`/cases/${caseId}`)response=item;
    else if(path===`/cases/${caseId}/actions`){item={...item,version:item.version+1,state:({assign:'assigned',review:'reviewed',approve:'approved'} as any)[body.action],payload:{...item.payload,owner:body.owner||item.payload.owner},events:[...item.events,{action:body.action,version:item.version+1,created_at:scanTime,payload:{note:body.note}}]};response=item;}
    else if(path==='/ownership'&&!body)response={items:ownership?[ownership]:[]};
    else if(path==='/ownership'&&body){ownership={...resource,...body,version:body.version+1,effective_at:scanTime};response=ownership;}
    else if(path==='/ownership/history')response={items:[{version:1,effective_at:scanTime,mapping:ownership}]};
    else if(path==='/anomalies/metrics')response={investigations:1,unassigned:0,actionable_resolved_pct:null,mean_acknowledgment_seconds:null,mean_resolution_seconds:null,warning:'Billing signals are delayed; no external notification was sent.'};
    else if(path==='/anomalies')response={items:[anomaly]};
    else if(path==='/anomalies/detect')response={items:[anomaly],status:'evaluated',warning:'Same-weekday cost-change signals on delayed imported billing.'};
    else if(path===`/anomalies/${anomalyId}`)response=anomaly;
    else if(path===`/anomalies/${anomalyId}/actions`){anomaly={...anomaly,version:anomaly.version+1,state:body.action==='resolve'?'resolved':body.action==='acknowledge'?'acknowledged':'investigating',events:[...anomaly.events,{action:body.action,version:anomaly.version+1,created_at:scanTime,payload:{note:body.note}}]};response=anomaly;}
    else throw new Error('Unmocked outcome route '+path);
    await route.fulfill({json:response});
  });
  await navigate(page,'Savings & investigations');return calls;
}

test('three financial measures preserve unknowns, negative outcomes and accessible mobile navigation',async({page})=>{
  await page.setViewportSize({width:390,height:844});await setup(page,{negative:true,human:true});
  await expect(page.getByRole('heading',{name:'Savings & investigations',exact:true})).toBeVisible();
  await expect(page.getByText('USD -900.00',{exact:true})).toBeVisible();await expect(page.getByText('Unknown',{exact:true})).toHaveCount(2);
  await expect(page.getByText(/saved financial claims need renewed evidence/)).toBeVisible();
  const tabs=page.getByRole('tablist',{name:'Financial outcome workflows'});await tabs.getByRole('tab',{name:'Verified savings',exact:true}).focus();await page.keyboard.press('End');await expect(tabs.getByRole('tab',{name:'Application ownership',exact:true})).toBeFocused();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
  const audit=await new AxeBuilder({page}).include('main').withTags(['wcag2a','wcag2aa','wcag21aa']).analyze();expect(audit.violations).toEqual([]);
});

test('case ownership and human approval preserve review notes without cloud execution',async({page})=>{
  const calls=await setup(page,{human:true});await page.getByRole('button',{name:'Review case',exact:true}).click();const drawer=page.getByRole('dialog',{name:'Optimization outcome review'});
  await drawer.getByLabel('Responsible owner',{exact:true}).fill('team-finance');await drawer.getByLabel('Review note',{exact:true}).fill('Review resource, owner and financial assumptions.');await drawer.getByRole('button',{name:'Assign owner',exact:true}).click();
  await drawer.getByRole('button',{name:'Mark reviewed',exact:true}).click();await drawer.getByLabel('Approved change reference').fill('CHG-42');await drawer.getByLabel('I reviewed the resource, proposal, owner and expected benefit assumptions.').check();await drawer.getByRole('button',{name:'Approve proposed change',exact:true}).click();
  await expect(drawer.getByRole('button',{name:'Record signed implementation'})).toBeVisible();expect(calls.filter(c=>c.path.endsWith('/actions')).map(c=>c.body.action)).toEqual(['assign','review','approve']);
  await expect(drawer.getByText('Awaiting a configured signed collector receipt',{exact:true})).toHaveCount(3);
  const audit=await new AxeBuilder({page}).include('dialog[open]').withTags(['wcag2a','wcag2aa','wcag21aa']).analyze();expect(audit.violations).toEqual([]);
});

test('shared workspace keys cannot approve a saved financial change',async({page})=>{
  const calls=await setup(page,{state:'reviewed'});await page.getByRole('button',{name:'Review case',exact:true}).click();const drawer=page.getByRole('dialog',{name:'Optimization outcome review'});
  await expect(drawer.getByRole('button',{name:'Approve proposed change',exact:true})).toBeDisabled();await expect(drawer.getByText(/Verified human TenantAdmin sign-in is required/)).toBeVisible();expect(calls).toEqual([]);
});

test('cost investigation exposes delayed categories and accountable resolution',async({page})=>{
  const calls=await setup(page,{role:'BillingAdmin',human:true});await page.getByRole('tab',{name:'Cost investigations',exact:true}).click();await page.getByRole('button',{name:'Open investigation',exact:true}).click();const drawer=page.getByRole('dialog',{name:'Cost anomaly investigation'});
  await expect(drawer.getByText(/not a real-time cloud alert or a proven root cause/)).toBeVisible();await expect(drawer.getByRole('heading',{name:'Charge-category contributions'})).toBeVisible();
  await drawer.getByLabel('Investigation note').fill('Owner confirmed an unexpected batch job.');await drawer.getByRole('button',{name:'Acknowledge',exact:true}).click();await drawer.getByRole('button',{name:'Investigate',exact:true}).click();await drawer.getByRole('button',{name:'Resolve',exact:true}).click();await expect(drawer.getByLabel('Investigation note')).toHaveCount(0);
  expect(calls.filter(c=>c.path.endsWith('/actions')).map(c=>c.body.action)).toEqual(['acknowledge','investigate','resolve']);expect(calls.at(-1)?.body.resolution).toBe('actionable');
});

test('application ownership is versioned and does not claim retrospective allocation',async({page})=>{
  const calls=await setup(page,{human:true});await page.getByRole('tab',{name:'Application ownership',exact:true}).click();await page.getByLabel('Resource from selected scan',{exact:true}).selectOption(resourceId);
  for(const [name,value] of Object.entries({application:'payments',team:'platform',owner:'team-platform',environment:'production','cost center':'cc-42'}))await page.getByLabel(name,{exact:true}).fill(value);
  await page.getByRole('button',{name:'Save ownership version',exact:true}).click();await expect(page.getByText(/A new ownership version was saved/)).toBeVisible();await page.getByRole('button',{name:'Inspect ownership history',exact:true}).click();await expect(page.getByText('Version 1',{exact:true})).toBeVisible();expect(calls.find(c=>c.path==='/ownership')?.body.version).toBe(0);
  await expect(page.getByText(/do not retrospectively allocate bills/)).toBeVisible();
});

test('viewers see the finance boundary without requesting outcome records',async({page})=>{
  const calls=await setup(page,{role:'Viewer'});await expect(page.getByRole('heading',{name:'Finance access required'})).toBeVisible();expect(calls).toEqual([]);await expect(page.getByRole('tab',{name:'Verified savings',exact:true})).toHaveCount(0);
});
