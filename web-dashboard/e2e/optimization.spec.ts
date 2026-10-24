import {test,expect} from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import {mockWorkspace,navigate,scanId,subscriptionId,scanTime} from './workspace-fixture';

test('causal planner keeps money as decimal strings and exposes transition payback',async({page})=>{
  await mockWorkspace(page);const calls:Record<string,any>[]=[];
  await page.route('**/api/v1/optimization/simulate/topology',route=>{calls.push(route.request().postDataJSON());return route.fulfill({json:{status:'modeled',direct_monthly_savings_usd:'560',cascading_downstream_savings_usd:'64',net_monthly_savings_usd:'624',one_time_transition_cost_usd:'3.20',recurring_new_overhead_usd:'0',payback_days:'0.1538',verified_realized_savings_usd:null,warning:'Scenario results are not billing proof.'}});});
  await navigate(page,'Optimization studio');
  await page.getByLabel('Root action',{exact:true}).fill('Consolidate reviewed node capacity');
  await page.getByLabel('Direct savings, USD/month',{exact:true}).fill('560');
  await page.getByLabel('One-time transition cost, USD',{exact:true}).fill('3.20');
  await page.getByLabel('New recurring overhead, USD/month',{exact:true}).fill('0');
  await page.getByRole('button',{name:'Add downstream component'}).click();
  await page.getByRole('group',{name:'Downstream component 1'}).getByLabel('Name',{exact:true}).fill('Released root disk');
  await page.getByLabel('Avoidable cost, USD/month',{exact:true}).fill('64');
  await page.getByRole('checkbox',{name:'Dependency verified for this scenario'}).check();
  await page.getByRole('button',{name:'Model architecture change'}).click();
  await expect(page.getByText('$624',{exact:true})).toBeVisible();
  await expect(page.getByText('Scenario results are not billing proof.')).toBeVisible();
  expect(calls[0].nodes.map((node:any)=>typeof node.monthly_savings_usd)).toEqual(['string','string']);
  expect(calls[0].edges[0].verification_state).toBe('verified');
  const audit=await new AxeBuilder({page}).include('main').withTags(['wcag2a','wcag2aa','wcag21aa']).analyze();expect(audit.violations).toEqual([]);
  await page.screenshot({path:test.info().outputPath('optimization-causal.png'),fullPage:true});
});

test('commitment planner exposes a ceiling without purchase approval',async({page})=>{
  await mockWorkspace(page);
  await page.route('**/api/v1/optimization/simulate/commitments',route=>route.fulfill({json:{status:'scenario_only',clean_steady_state_hr:'7',recommended_new_commitment_hr:'3',purchase_authorized:false,warning:'Planning ceiling only.'}}));
  await navigate(page,'Optimization studio');await page.getByRole('button',{name:'Commitment planning',exact:true}).click();
  await page.getByLabel('Raw P10 spend, USD/hour').fill('10');await page.getByLabel('Open rightsizing & waste, USD/hour').fill('3');await page.getByLabel('Existing commitments, USD/hour').fill('4');
  await page.getByRole('button',{name:'Calculate clean ceiling'}).click();await expect(page.getByText('$3',{exact:true})).toBeVisible();
  await expect(page.getByText('Planning ceiling only.',{exact:true})).toBeVisible();await expect(page.getByRole('button',{name:/Purchase|Buy reservation/})).toHaveCount(0);
});

test('SLO file workflow shows a hard burn-rate block instead of approving a change',async({page})=>{
  await mockWorkspace(page);await page.route('**/api/v1/optimization/simulate/slo',route=>route.fulfill({json:{status:'blocked',capacity_reduction_allowed:false,blocks:['BLOCKED_BY_SLO_BURN_RATE'],evidence_gaps:[],pearson_r:null,paired_samples:0,warning:'Statistical screening is not change approval.'}}));
  await navigate(page,'Optimization studio');await page.getByRole('button',{name:'SLO safety',exact:true}).click();
  await expect(page.getByRole('button',{name:'Evaluate SLO safety'})).toBeDisabled();
  await page.getByLabel('CPU / interval P99 evidence file').setInputFiles({name:'synthetic-slo.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify({error_budget_burn_rate_30d:1.5}))});
  await page.getByRole('button',{name:'Evaluate SLO safety'}).click();await expect(page.getByText('BLOCKED BY SLO BURN RATE')).toBeVisible();
  await expect(page.getByText('Statistical screening is not change approval.')).toBeVisible();
});

test('cloud-specific endpoint choices avoid free registry gateway claims on mobile',async({page})=>{
  await page.setViewportSize({width:390,height:844});await mockWorkspace(page);
  await navigate(page,'Optimization studio');await page.getByRole('button',{name:'Network & batch',exact:true}).click();
  await page.getByRole('combobox',{name:'Destination service',exact:true}).selectOption('registry');
  await expect(page.getByRole('combobox',{name:'Endpoint type',exact:true})).toHaveValue('interface');
  await page.getByRole('combobox',{name:'Cloud',exact:true}).selectOption('azure');await expect(page.getByRole('combobox',{name:'Destination service',exact:true})).toHaveValue('blob');
  await expect(page.getByRole('combobox',{name:'Endpoint type',exact:true})).toHaveValue('azure_service_endpoint');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
  const audit=await new AxeBuilder({page}).include('main').withTags(['wcag2a','wcag2aa','wcag21aa']).analyze();expect(audit.violations).toEqual([]);
});

test('case workflow preserves unknown verification and exposes no self-completion action',async({page})=>{
  await mockWorkspace(page);
  let item:any=null;const writes:{method:string;body:any}[]=[];
  const id='77777777-7777-4777-8777-777777777777';const resource='/subscriptions/'+subscriptionId+'/resourceGroups/rg/providers/Microsoft.Compute/disks/fixture';
  await page.route('**/api/v1/optimization/scans/*',route=>route.fulfill({json:{resources:[{resource_id:resource,resource_name:'retained-disk',resource_type:'Microsoft.Compute/disks',cloud_provider:'azure',scope_id:subscriptionId}]}}));
  await page.route('**/api/v1/optimization/cases**',route=>{
    const request=route.request(),method=request.method(),path=new URL(request.url()).pathname;
    if(method==='POST'&&path.endsWith('/cases')){const body=request.postDataJSON();writes.push({method,body});item={id,resource_id:resource,provider:'azure',state:'reviewed',version:1,updated_at:scanTime,payload:{resource_name:'retained-disk',action:body.action,note:body.note,scheduled_at:null},verification:null};return route.fulfill({status:201,json:item});}
    if(method==='PATCH'){const body=request.postDataJSON();writes.push({method,body});item={...item,state:body.state,version:item.version+1};return route.fulfill({json:item});}
    if(method==='POST'&&path.endsWith('/verify')){writes.push({method,body:request.postDataJSON()});item={...item,version:item.version+1,verification:{status:'insufficient_evidence',verified_realized_savings_usd:null,reasons:['unverified_scope_missing']}};return route.fulfill({json:item});}
    return route.fulfill({json:{items:item?[item]:[]}});
  });
  await navigate(page,'Optimization studio');await page.getByRole('button',{name:'Verified savings',exact:true}).click();
  await page.getByLabel('Resource from selected scan').selectOption(resource);await page.getByRole('button',{name:'Create review case'}).click();
  await page.getByRole('button',{name:'accepted for investigation',exact:true}).click();await page.getByRole('button',{name:'scheduled',exact:true}).click();
  await page.getByRole('button',{name:'Verify saved evidence'}).click();await expect(page.getByRole('cell').filter({hasText:'insufficient evidence'})).toBeVisible();
  await expect(page.getByRole('button',{name:'verified completed',exact:true})).toHaveCount(0);
  expect(writes.filter(w=>w.method==='PATCH').map(w=>w.body.state)).toEqual(['accepted_for_investigation','scheduled']);
});

test('viewer savings ledger has no create or review-mutation controls',async({page})=>{
  await mockWorkspace(page,{role:'Viewer'});
  await page.route('**/api/v1/optimization/scans/*',route=>route.fulfill({json:{resources:[]}}));
  await page.route('**/api/v1/optimization/cases',route=>route.fulfill({json:{items:[]}}));
  await navigate(page,'Optimization studio');await page.getByRole('button',{name:'Verified savings',exact:true}).click();
  await expect(page.getByRole('heading',{name:'No savings cases yet'})).toBeVisible();await expect(page.getByRole('button',{name:'Create review case'})).toHaveCount(0);
});

test('observed dependency map comes from the selected snapshot without guessed savings',async({page})=>{
  await mockWorkspace(page);
  const root='a'.repeat(64),child='b'.repeat(64);
  await page.route('**/api/v1/optimization/scans/*',route=>route.fulfill({json:{resources:[{resource_key:root,resource_name:'node-vm'}]}}));
  await page.route('**/api/v1/optimization/scans/*/topology/*',route=>route.fulfill({json:{observed_at:scanTime,nodes:[{resource_key:root,name:'node-vm',provider:'azure',resource_type:'Microsoft.Compute/virtualMachines',protected_reasons:[]},{resource_key:child,name:'root-disk',provider:'azure',resource_type:'Microsoft.Compute/disks',protected_reasons:['EXPLICIT_RETENTION']}],edges:[{from_key:root,to_key:child,relationship:'vm_to_disk',verification_state:'verified'}],warning:'Observed connectivity does not prove avoidable billed cost.'}}));
  await navigate(page,'Optimization studio');await page.getByRole('button',{name:'Load saved dependencies'}).click();
  await page.getByRole('combobox',{name:'Observed root resource',exact:true}).selectOption(root);
  await expect(page.getByRole('cell',{name:'vm to disk',exact:true})).toBeVisible();await expect(page.getByText('Protected resources: root-disk')).toBeVisible();
  await expect(page.getByText('Observed connectivity does not prove avoidable billed cost.')).toBeVisible();
});
