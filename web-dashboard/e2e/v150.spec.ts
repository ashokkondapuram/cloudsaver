import {test,expect} from './test';
import AxeBuilder from '@axe-core/playwright';
import {mockWorkspace,navigate,scanId} from './workspace-fixture';

test('service and optimization destinations expose observed data and honest evidence gaps',async({page})=>{
  await mockWorkspace(page);
  await page.route('**/api/v1/services/disks*',r=>r.fulfill({json:{service:'disks',total:1,warning:'TEST FIXTURE: Saved observations only.',items:[{resource_key:'a'.repeat(64),resource_name:'owned-disk',provider:'azure',resource_type:'Microsoft.Compute/disks',finding_count:1,billed_cost_usd:null,retail_estimate_usd:12}]}}));
  await page.route('**/api/v1/optimization/scans/'+scanId+'/auto-scenarios',r=>r.fulfill({json:{warning:'No synthetic savings are generated.',engines:{topology:{status:'insufficient_evidence',items:[]},commitment:{status:'insufficient_evidence',warning:'Complete hourly billing is required.'}}}}));
  await navigate(page,'Services');await expect(page.getByRole('heading',{name:'Services'})).toBeVisible();await expect(page.getByRole('link',{name:'owned-disk'})).toBeVisible();
  await expect(page.getByRole('columnheader',{name:'Imported billed USD'})).toBeVisible();
  await navigate(page,'Optimization evidence');await expect(page.getByText('Insufficient evidence',{exact:true})).toHaveCount(2);
  const audit=await new AxeBuilder({page}).include('main').withTags(['wcag2a','wcag2aa','wcag21aa']).analyze();expect(audit.violations).toEqual([]);
});

test('configured automatic billing sync refreshes durable history without a manual file',async({page})=>{
  await mockWorkspace(page);let synced=false;let writes=0;
  await page.route('**/api/v1/finops/sync-status',r=>r.fulfill({json:{configured:true,automatic_sync_enabled:true,last_synced_at:synced?'2026-10-23T12:00:00Z':null,recent_syncs:synced?[{id:'run',state:'completed',updated_at:'2026-10-23T12:00:00Z',payload:{inserted_records:2,unresolved_absent_groups:1}}]:[],warning:'TEST FIXTURE: Coverage remains unverified.'}}));
  await page.route('**/api/v1/finops/sync?*',r=>{writes++;expect(r.request().postDataJSON().idempotency_key).toMatch(/^[a-f0-9-]{36}$/);return r.fulfill({status:202,json:{status:'queued',poll_url:'/api/v1/finops/sync-jobs/77777777-7777-4777-8777-777777777777'}});});
  await page.route('**/api/v1/finops/sync-jobs/77777777-7777-4777-8777-777777777777',r=>{synced=true;return r.fulfill({json:{status:'completed'}});});
  await navigate(page,'Cost allocation');await page.getByRole('button',{name:'Sync now',exact:true}).click();
  await expect(page.getByText('Last successful synchronization:',{exact:false})).toBeVisible();expect(writes).toBe(1);await expect(page.getByText('Billing remains unreconciled:',{exact:false})).toBeVisible();
  await expect(page.getByText('Advanced: import FOCUS billing JSON manually',{exact:true})).toBeVisible();
});

test('execution timeline distinguishes draft reviews from verified parity',async({page})=>{
  await mockWorkspace(page);
  await page.route('**/api/v1/gitops/syncs',r=>r.fulfill({json:{items:[{id:'review',state:'open',updated_at:'2026-10-23T12:00:00Z',payload:{agent_task_id:'task',repository:'example/infra',parity_verified:false,result:{pr_url:'https://github.com/example/infra/pull/7'}}}]}}));
  await navigate(page,'Automation & GitOps');await page.getByRole('tab',{name:'Execution history'}).click();
  await expect(page.getByRole('link',{name:'Inspect draft PR'})).toHaveAttribute('href','https://github.com/example/infra/pull/7');
  await expect(page.getByText('Deployment parity and realized savings require separate verification.')).toBeVisible();
});

test('automatic repository preview uses the selected scan without inventing a Terraform pass',async({page})=>{
  await mockWorkspace(page);let submitted:Record<string,unknown>|null=null;
  await page.route('**/api/v1/gitops/preview-and-evaluate',r=>{submitted=r.request().postDataJSON();return r.fulfill({json:{review:{files:{'imports.tf':'# TEST FIXTURE: import review only'}},policy:{decision:'review_required',projection_only:true,automatic_apply:false},monthly_cost_delta_usd:null}});});
  await navigate(page,'Automation');await page.getByRole('tab',{name:'Plan guardrails',exact:true}).click();await page.getByRole('button',{name:'Preview & evaluate selected scan'}).click();
  await expect(page.getByText('Review required. Repository CI must supply the real Terraform plan; cost impact remains unknown.')).toBeVisible();
  expect(submitted?.['scan_id']).toBe(scanId);expect(submitted?.['target_id']).toBe('infra');
});


test('served dashboard HTML uses distinct CSP nonces and blocks framing',async({request})=>{
  const a=await request.get('/'),b=await request.get('/');
  expect(a.headers()['x-frame-options']).toBe('DENY');
  const policy=a.headers()['content-security-policy'];
  expect(policy).toContain("'nonce-");expect(policy).not.toContain("'unsafe-eval'");
  expect(policy).not.toBe(b.headers()['content-security-policy']);
  expect(a.headers()['cache-control']).toContain('no-store');
});
