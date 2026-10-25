import {test,expect,type Page} from '@playwright/test';
import {mockWorkspace,scanId,subscriptionId,scanTime} from './workspace-fixture';
import {groupWorkloads} from '../lib/workloads.mjs';
const resourceId=`/subscriptions/${subscriptionId}/resourceGroups/qa/providers/Microsoft.Compute/virtualMachines/payments-vm`;
const resource={resource_key:'a'.repeat(64),provider:'azure',scope_id:subscriptionId,resource_id:resourceId,resource_name:'payments-vm',resource_type:'Microsoft.Compute/virtualMachines',rule_ids:['UNDERUTILIZED_VM'],pillars:{cost:'unknown',security:'risk',reliability:'unknown',performance:'unknown',operations:'observed'},risk_check_codes:['PUBLIC_ACCESS'],evidence_gap_codes:['MEMORY_HISTORY'],protected_reasons:[]};
const ownership={provider:'azure',scope_id:subscriptionId,resource_id:resourceId,application:'payments',environment:'production',version:1,owner:'team-payments',team:'platform'};
async function setup(page:Page,options:{viewer?:boolean;denied?:boolean;unmapped?:boolean}={}){
  await mockWorkspace(page,{role:options.viewer?'Viewer':'TenantAdmin'});
  const calls:{path:string;method:string}[]=[];
  await page.route('**/api/v1/outcomes/ownership',async route=>{
    calls.push({path:new URL(route.request().url()).pathname,method:route.request().method()});
    await route.fulfill({status:options.denied?403:200,json:options.denied?{detail:'Scope denied'}:{items:options.unmapped?[]:[ownership]}});
  });
  await page.route(`**/api/v1/scans/${scanId}/resources?**`,async route=>{
    calls.push({path:new URL(route.request().url()).pathname,method:route.request().method()});
    await route.fulfill({json:{scan_id:scanId,observed_at:scanTime,total:1,items:[resource]}});
  });
  await page.goto('/workloads');
  await expect(page.getByRole('heading',{name:'Workload assessments',exact:true})).toBeVisible();
  return calls;
}

test('workload view groups five pillars and exposes non-executable review steps',async({page})=>{
  const calls=await setup(page);
  await page.getByRole('button',{name:'payments / production',exact:true}).click();
  await expect(page.getByText('Cost: 0 at risk · 1 unknown · 0 observed',{exact:true})).toBeVisible();
  await expect(page.getByText('Security: 1 at risk · 0 unknown · 0 observed',{exact:true})).toBeVisible();
  await page.getByText('Review VM rightsizing — needs live checks and approval',{exact:true}).click();
  await expect(page.getByText('Fresh representative CPU, memory, disk and network history',{exact:true})).toBeVisible();
  await expect(page.getByRole('link',{name:'Inspect resource evidence'})).toHaveAttribute('href',`/resources?resource=${'a'.repeat(64)}`);
  expect(calls.length).toBeGreaterThanOrEqual(2);expect(calls.every(call=>call.method==='GET')).toBe(true);
  await expect(page.getByRole('button',{name:/execute|approve|resize/i})).toHaveCount(0);
});
test('unmapped resources are not assigned to guessed applications',async({page})=>{
  await setup(page,{unmapped:true});await expect(page.locator('.settings-key-values div',{hasText:'Unassigned resources'})).toContainText('1');
  await expect(page.getByRole('button',{name:'payments / production',exact:true})).toHaveCount(0);
});
test('viewers cannot request ownership through the workload page',async({page})=>{
  const calls=await setup(page,{viewer:true});await expect(page.getByRole('heading',{name:'Finance access required'})).toBeVisible();expect(calls).toEqual([]);
});
test('source authorization error is visible with no fallback or partial totals',async({page})=>{
  const calls=await setup(page,{denied:true});await expect(page.getByRole('alert')).toContainText('Scope denied');
  await expect(page.getByRole('button',{name:'payments / production',exact:true})).toHaveCount(0);
  expect(calls.some(call=>call.path.includes('/resources'))).toBe(false);
});
test('refresh replaces old membership rather than retaining stale workload data',async({page})=>{
  await setup(page);await expect(page.getByRole('button',{name:'payments / production',exact:true})).toBeVisible();
  await page.route('**/api/v1/outcomes/ownership',route=>route.fulfill({json:{items:[]}}));
  await page.getByRole('button',{name:'Refresh saved assessments',exact:true}).click();
  await expect(page.getByText(/No mapped workloads in this observation/)).toBeVisible();
  await expect(page.getByRole('button',{name:'payments / production',exact:true})).toHaveCount(0);
});
test('projection preserves unknowns and exact account identity',()=>{
  const result=groupWorkloads([resource],[{...ownership,scope_id:'another-account'}]);
  expect(result.unassigned).toBe(1);expect(result.workloads).toEqual([]);
  const mapped=groupWorkloads([resource],[ownership]);expect(mapped.workloads[0].verified_savings).toBeNull();
  expect(mapped.workloads[0].pillars.find(p=>p.pillar==='reliability')?.counts.unknown).toBe(1);
});
