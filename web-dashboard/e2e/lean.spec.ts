import {test,expect,type Page} from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import {mockWorkspace,navigate,scanId,subscriptionId,scanTime} from './workspace-fixture';

const pillars=Object.fromEntries(['cost','reliability','performance','security','operations'].map(p=>[p,'unknown']));
const ai={status:'not_run',risk_level:null,summary:null,actions:[],assessment_id:null,created_at:null,reason:null};
function resource(index=0){return {resource_key:(index?'b':'a').repeat(64),provider:index?'aws':'azure',resource_id:index?'arn:aws:ec2:us-east-1:123456789012:volume/vol-0123456789abcdef0':`/subscriptions/${subscriptionId}/resourceGroups/qa/providers/Microsoft.Compute/disks/review`,resource_name:index?'aws-disk':'review-disk',resource_type:index?'aws:ec2:volume':'Microsoft.Compute/disks',resource_group:'qa',scope_id:index?'123456789012':subscriptionId,service_category:'storage',finding_count:1,rule_ids:['ORPHANED_DISK'],review_priority:'evidence_required',disposition:'requires_review',protected_reasons:[],risk_level:'unknown',risk_check_codes:[],evidence_gap_codes:['BILLED_COST'],evidence_coverage:{observed:1,total:10},billed_cost_usd:index?null:12.5,effective_cost_usd:index?null:15,retail_estimate_usd:index?null:7.5,evidence_digest:'c'.repeat(64),pillars,ai,decision:null,lifecycle_delta:index?'regressed':'new'};}
async function resources(page:Page){
  const rows=[resource(),resource(1)];
  await page.route(`**/api/v1/scans/${scanId}/resources?**`,route=>route.fulfill({json:{scan_id:scanId,observed_at:scanTime,total:2,items:rows,summary:{total:2,ai_status:{not_run:2},ai_risk:{none:2},decision:{none:2},review_priority:{evidence_required:2},resolved_count:1,no_longer_observed_count:2},commitment_baseline:{status:'insufficient_evidence',recommended_new_commitment_hr:null,clean_steady_state_hr:null,warning:'Complete hourly evidence is required.'}}}));
  await page.route(`**/api/v1/scans/${scanId}/resources/${'a'.repeat(64)}`,route=>route.fulfill({json:{scan_id:scanId,assessment:{...rows[0],policy_version:'current',observation:{status:'recent',observed_at:scanTime,max_age_hours:24},guardrails:['VERIFY_CURRENT_STATE'],pillars:Object.keys(pillars).map(p=>({pillar:p,status:'unknown',checks:[]}))},findings:[],ai_context:{},ai,ai_result:null,decision:null,followups:[],followups_remaining:5,observation:{observed_at:scanTime,collector_version:'test',evidence_schema_version:'2',configuration_snapshot:{},evidence:{metrics:{cpu_percent:{window_start:scanTime,window_end:scanTime,points:[]}},metric_summaries:{cpu_percent:{sufficient:false}}}},rule_evaluations:[],costs:{billed_cost_usd:12.5,effective_cost_usd:15,retail_estimate_usd:7.5,modeled_future_cost_usd:null,opportunity_usd:null,verified_realized_savings_usd:null,explanation:'Imported costs are evidence, not verified savings.'}}}));
}

test('restored navigation coexists with current resource, Kubernetes, agent and settings workflows',async({page})=>{
  await mockWorkspace(page);const nav=page.getByRole('navigation',{name:'Primary navigation'});
  await expect(nav.getByRole('link')).toHaveCount(13);
  for(const name of ['Overview','Inventory & findings','Resources & 5-Pillar','Kubernetes','Agent worker','Cost allocation','Automation & GitOps','Activity & delivery','Settings & governance'])await expect(nav.getByRole('link',{name,exact:true})).toBeVisible();
  await navigate(page,'Settings & integrations');const tabs=page.getByRole('tablist',{name:'Workspace settings'});
  await expect(tabs.getByRole('tab')).toHaveCount(4);await tabs.getByRole('tab',{name:'Analysis rules',exact:true}).focus();await page.keyboard.press('End');
  await expect(tabs.getByRole('tab',{name:'Access & API keys'})).toBeFocused();await expect(tabs.getByRole('tab',{name:'Access & API keys'})).toHaveAttribute('aria-selected','true');
});

test('unified resources keep imported billing separate from retail estimates and expose scan deltas',async({page})=>{
  await mockWorkspace(page);await resources(page);await navigate(page,'Resource analysis');
  await expect(page.getByRole('columnheader',{name:'30d billed USD'})).toBeVisible();await expect(page.getByRole('columnheader',{name:'30d effective USD'})).toBeVisible();
  await expect(page.getByText('regressed',{exact:true})).toBeVisible();await expect(page.getByText('new',{exact:true})).toBeVisible();
  await page.getByLabel('Cloud provider',{exact:true}).selectOption('azure');await expect(page.getByRole('button',{name:'View analysis for aws-disk'})).toHaveCount(0);
  await page.getByLabel('Pillar status',{exact:true}).selectOption('unknown');await expect(page.getByRole('button',{name:'View analysis for review-disk'})).toBeVisible();
  await page.getByRole('button',{name:'View analysis for review-disk'}).click();const drawer=page.getByRole('dialog',{name:'Resource analysis',exact:true});
  await drawer.getByRole('tab',{name:'Cost',exact:true}).click();await expect(drawer.getByText('$12.50',{exact:true})).toBeVisible();await expect(drawer.getByText('$15.00',{exact:true})).toBeVisible();
  await drawer.getByRole('tab',{name:'30d telemetry'}).click();await expect(drawer.getByText('Insufficient or unverified')).toBeVisible();
  const audit=await new AxeBuilder({page}).include('dialog[open]').withTags(['wcag2a','wcag2aa','wcag21aa']).analyze();expect(audit.violations).toEqual([]);
});

test('resource handoff selects the same owned resource in the agent workspace',async({page})=>{
  await mockWorkspace(page);await resources(page);
  await page.route('**/api/v1/agents/catalog',r=>r.fulfill({json:{enabled:false,connectors:[]}}));await page.route('**/api/v1/agents/tasks',r=>r.fulfill({json:{items:[]}}));
  await navigate(page,'Resource analysis');await page.getByRole('button',{name:'View analysis for review-disk'}).click();
  await page.getByRole('link',{name:'Draft a safe tag or snapshot plan'}).click();await expect(page.getByLabel('Resource from selected scan')).toHaveValue(resource().resource_id);
});

test('mobile resource explorer and consolidated AI settings fit the viewport',async({page})=>{
  await page.setViewportSize({width:390,height:844});await mockWorkspace(page,{role:'Viewer'});await resources(page);await navigate(page,'Resource analysis');
  await expect(page.getByRole('button',{name:'Run AI assessment',exact:true})).toHaveCount(0);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
  await navigate(page,'AI data governance');await expect(page.getByRole('heading',{name:'AI Foundry configuration'})).toBeVisible();
  const audit=await new AxeBuilder({page}).include('main').withTags(['wcag2a','wcag2aa','wcag21aa']).analyze();expect(audit.violations).toEqual([]);
});

test('unsupported BFF paths still return 404 before reaching an upstream service',async({request})=>{
  for(const path of ['optimization/catalog','services/unsupported']){
    const response=path.includes('evaluate')||path.includes('remediation')?await request.post('/api/v1/'+path,{data:{}}):await request.get('/api/v1/'+path);expect(response.status()).toBe(404);
  }
});
