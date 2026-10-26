import {test,expect} from './test';
import AxeBuilder from '@axe-core/playwright';
import {mockWorkspace,navigate,scanId,scanTime} from './workspace-fixture';

function fixture(){
  const capacity={allocatable:8,requested:2,daemonset:.5,actual_p95:null,physical:null};
  const cpuRule={rule_id:'K8S_CONTAINER_CPU_OVERREQUEST',name:'Container CPU request rightsizing review',outcome:'condition_detected',reason:'CPU request exceeds validated P95 headroom.',safety_blocks:[] as string[],recommendation:{cpu_request_cores:.3}};
  const row={resource_id:'k8s://fixture-cluster/namespaces/production/pods/checkout-pod/containers/api',resource_name:'checkout-api',cluster_id:'fixture-cluster',resource_type:'kubernetes.io/Container',namespace:'production',evidence_digest:'a'.repeat(64),data_sources:[],reconciliation_status:'partial_telemetry',
    evidence:{pod:'checkout-pod',container:'api',node:'node-a',controller:{kind:'Deployment',name:'checkout'},qos_class:'Burstable',hpa_present:false,metrics:{cpu:{sufficient:true,p95:.2,p99:.3,maximum:.4,coverage_ratio:1,gap_reason:null,window_start:'2026-09-22T15:00:00Z',window_end:scanTime,max_gap_minutes:5},memory:null}},
    costs:{workload_used_estimate_usd:null,workload_request_slack_estimate_usd:null,cluster_unallocated_slack_usd:null,billed_node_cost_usd:null,realizable_node_savings_usd:null,allocation_total_usd:null,explanation:'Allocation evidence cannot prove a cloud invoice reduction.'},evaluations:[cpuRule]};
  return {scan_id:scanId,observed_at:scanTime,clusters:[{cluster_id:'fixture-cluster',coverage:{discovered_count:4,in_scope_count:4,evaluated_count:1,insufficient_evidence_count:1,excluded_count:0,unsupported_count:2},
    sources:[{source_id:'kubernetes_api:Pod',collector_type:'kubernetes_api',status:'available',coverage_ratio:null,valid_samples:null,expected_samples:null,observed_window_start:null,observed_window_end:scanTime,reason_code:null},
      {source_id:'prometheus:memory',collector_type:'prometheus_range_api',status:'unavailable',coverage_ratio:null,valid_samples:null,expected_samples:null,observed_window_start:null,observed_window_end:null,reason_code:'metric_unavailable_invalid_or_ambiguous'}],capacity:{cpu:capacity,memory:{...capacity,allocatable:16*1024**3,requested:4*1024**3,daemonset:1024**3}},reconciliation_status:'partial_telemetry'}],resources:[row],financial_note:'Allocation opportunities are not additive to node consolidation.',rule_matrix:[{rule_id:cpuRule.rule_id,name:cpuRule.name,pillar:'cost',outcomes:{condition_detected:1}}]};
}

test('Kubernetes workspace preserves missing-source evidence and review-only patches',async({page})=>{
  const {mutations}=await mockWorkspace(page);
  let previews=0;
  await page.route(`**/api/v1/scans/${scanId}/kubernetes`,route=>route.fulfill({json:fixture()}));
  await page.route(`**/api/v1/scans/${scanId}/kubernetes/patch-preview`,route=>{previews++;return route.fulfill({json:{filename:'checkout.requests-review.patch.yaml',content:'{"spec":{"template":{"spec":{"containers":[]}}}}',diff:'- cpu: 2\n+ cpu: 300m',replicas_reviewed:1,review_commands:['kubectl patch deployment checkout --dry-run=server','kubectl diff -f proposed-workload.yaml'],warning:'Review-only patch. No API write or GitOps submission was executed.'}});});
  await navigate(page,'Kubernetes & containers');
  await expect(page.getByRole('heading',{name:'Kubernetes & containers',exact:true})).toBeVisible();
  await expect(page.getByText('prometheus:memory',{exact:true})).toBeVisible();
  await expect(page.getByText('Partial telemetry',{exact:true})).toBeVisible();
  await page.getByLabel('Search',{exact:true}).fill('no-such-resource');
  await expect(page.getByText('No resources match these filters.')).toBeVisible();
  await page.getByLabel('Search',{exact:true}).fill('checkout');
  await page.getByRole('button',{name:'checkout-api Container'}).click();
  const drawer=page.getByRole('dialog',{name:'Kubernetes resource review'});
  await expect(drawer.locator('dl').getByText('Unknown',{exact:true})).toHaveCount(5);
  await drawer.getByRole('button',{name:'Preview CPU request patch'}).click();
  await expect(drawer.getByText(/No API write or GitOps submission was executed/)).toBeVisible();
  expect(previews).toBe(1);expect(mutations).toEqual([]);
  const audit=await new AxeBuilder({page}).include('dialog[open]').withTags(['wcag2a','wcag2aa','wcag21aa']).analyze();
  expect(audit.violations).toEqual([]);
});

test('viewer can inspect Kubernetes safety blocks without patch controls on mobile',async({page})=>{
  await page.setViewportSize({width:390,height:844});
  await mockWorkspace(page,{role:'Viewer'});
  const view=fixture();view.resources[0].evaluations[0].safety_blocks=['OOMKILL_OBSERVED'];
  await page.route(`**/api/v1/scans/${scanId}/kubernetes`,route=>route.fulfill({json:view}));
  await navigate(page,'Kubernetes & containers');
  await page.getByRole('button',{name:'checkout-api Container'}).click();
  const drawer=page.getByRole('dialog',{name:'Kubernetes resource review'});
  await expect(drawer.getByText('Blocked: Out-of-memory kill observed')).toBeVisible();
  await expect(drawer.getByRole('button',{name:/Preview.*request patch/})).toHaveCount(0);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
  await page.screenshot({path:test.info().outputPath('kubernetes-mobile-review.png'),fullPage:true});
});

test('empty scan does not claim Kubernetes health or start discovery',async({page})=>{
  const {mutations}=await mockWorkspace(page);
  await page.route(`**/api/v1/scans/${scanId}/kubernetes`,route=>route.fulfill({json:{...fixture(),clusters:[],resources:[]}}));
  await navigate(page,'Kubernetes & containers');
  await expect(page.getByRole('heading',{name:'No Kubernetes inventory in this scan'})).toBeVisible();
  expect(mutations).toEqual([]);
});
