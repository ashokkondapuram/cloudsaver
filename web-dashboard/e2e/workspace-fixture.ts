import {Page,expect} from '@playwright/test';

// Test-only browser data. Production code never imports this file and every API
// route is intercepted, including mutations, before connecting the test session.
export const tenantId='11111111-1111-4111-8111-111111111111';
export const subscriptionId='22222222-2222-4222-8222-222222222222';
export const scanId='33333333-3333-4333-8333-333333333333';
export const scanTime='2026-10-22T15:30:00Z';

export function createFindings(count=12){
  const providers=['azure','aws','gcp','kubernetes'];
  const rules=['ORPHANED_DISK','AWS_UNATTACHED_EBS','GCP_UNATTACHED_DISK','K8S_CPU_OVERSIZED'];
  const names=['archive-data','analytics-backup','legacy-storage','api-worker'];
  return Array.from({length:count},(_,index)=>{
    const p=index%4;
    const name=`${names[p]}-${String(index+1).padStart(2,'0')}`;
    const scope=p===0?subscriptionId:p===1?'123456789012':p===2?'finops-project':'platform-cluster';
    return {cloud_provider:providers[p],scope_id:scope,rule_id:rules[p],severity:index%5===0?'HIGH':index%3===0?'LOW':'MEDIUM',resource_name:name,
      resource_type:p===0?'Microsoft.Compute/disks':p===1?'AWS::EC2::Volume':p===2?'compute.disks':'kubernetes/workload',resource_group:p===3?'production':'platform',subscription_id:p===0?subscriptionId:'',
      resource_id:p===0?`/subscriptions/${subscriptionId}/resourceGroups/platform/providers/Microsoft.Compute/disks/${name}`:`${providers[p]}/${scope}/${name}`,
      estimated_monthly_waste_usd:p===0?24.6+index:null,details:'TEST FIXTURE: Resource observation for interface acceptance. Review attachment state and retention requirements before considering a change.',
      evidence:{...(p===3?{dimension:'cpu',unit:'cores',window_days:14,p95_usage:0.03,minimum_request:0.5,samples:337,step_seconds:3600,window_start:'2026-10-08T15:00:00Z',window_end:'2026-10-22T15:00:00Z'}:{}),source:'TEST FIXTURE read-only observation',state:p===3?'request review':'unattached',region:['eastus2','us-east-1','us-central1','cluster'][p],tags:{Owner:index%2===0?'platform':'data',Environment:'production'}},
      cost_attribution:p===0?{confidence:'HIGH',calculation_basis:'TEST FIXTURE retail estimate',realizable_savings_usd:null}:undefined};
  });
}

export async function mockWorkspace(page:Page,options:{role?:string;count?:number;legacy?:boolean;publishing?:boolean;ai?:boolean;protected?:boolean;zeroPrice?:boolean}={}){
  const findings=createFindings(options.count??12);
  if(options.zeroPrice)findings[0].estimated_monthly_waste_usd=0;
  if(options.protected)(findings[0].evidence.tags as Record<string,string>).Role='DR-Standby';
  const current={scan_id:scanId,timestamp:scanTime,mode:'azure',status:'completed',data_origin:options.legacy?'legacy_synthetic':undefined,subscriptions_scanned:4,total_items_found:findings.length,total_monthly_waste_usd:null,realizable_monthly_savings_usd:null,cloud_providers:['azure','aws','gcp','kubernetes'],findings:options.legacy?findings.map(f=>({...f,estimated_monthly_waste_usd:null,cost_attribution:undefined})):findings};
  const mutations:{path:string;body:any;raw:string}[]=[];
  await page.route('**/api/v1/**',async route=>{
    const request=route.request(),url=new URL(request.url()),path=url.pathname;
    if(request.method()==='POST')mutations.push({path,body:request.postDataJSON(),raw:request.postData()||''});
    let response:unknown,status=200;
    if(path==='/api/v1/me')response={name:'Interface QA workspace',tenant_id:tenantId,subscription_ids:[subscriptionId],roles:[options.role||'TenantAdmin'],mode:'azure',plan_tier:'GROWTH',providers:['azure','aws','gcp','kubernetes'],configured_scope_count:4,max_scopes_per_scan:20,can_export_terraform:true,allowed_scan_frequencies:['manual','daily'],scheduled_scans_enabled:false,automated_alerts_enabled:false};
    else if(path==='/api/v1/scans')response=[current];
    else if(path==='/api/v1/settings')response={editable:false,settings:{tenant_id:tenantId,name:'Interface QA workspace',version:1,plan_tier:'GROWTH',subscription_ids:[subscriptionId],aws_accounts:[],gcp_projects:[],kubernetes_clusters:[],schedule:{frequency:'manual'},alerts:{enabled:false,channel:null,webhook_configured:false}},limits:{max_subscriptions:20,allowed_scan_frequencies:['manual','daily'],can_dispatch_automated_alerts:true},platform:null,identity:{identity_mode:'managed_identity',azure_access:'federated',aws_external_id:tenantId}};
    else if(path==='/api/v1/ai/targets')response={enabled:!!options.ai,hourly_attempt_limit:10,targets:options.ai?[{target_id:'approved-review',provider:'azure',model:'operator-model'}]:[]};
    else if(path==='/api/v1/finops/imports')response={items:[]};
    else if(path==='/api/v1/finops/summary')response={currency:new URL(request.url()).searchParams.get('currency')||'USD',records:0,billed_cost:null,effective_cost:null,list_cost:null,effective_savings_rate_pct:null,excluded_overlapping_records:0,warning:'TEST FIXTURE: Imported billing evidence is not provider-reconciled.',daily:[],forecast:null,anomaly:null,providers:[]};
    else if(path==='/api/v1/ai/assessments')response={items:[],next_cursor:null,durable:true};
    else if(path==='/api/v1/ai/usage')response={groups:[],durable:true};
    else if(path===`/api/v1/scans/${scanId}/analysis`)response={policy_version:'2026-10-23.1',review_queue_total:findings.length,review_queue:findings.slice(0,1).map(f=>({resource_key:'a'.repeat(64),resource_id:f.resource_id,rule_id:f.rule_id,review_priority:'high',risk_check_codes:['PROTECTED_INTENT'],evidence_gap_codes:['DEPENDENCY_GRAPH']})),services:[{provider:'azure',service_category:'storage',findings:3,protected_findings:options.protected?1:0,risk_findings:options.protected?1:0,unknown_price_findings:0,known_retail_subtotal_usd:85.8},{provider:'aws',service_category:'storage',findings:3,protected_findings:0,risk_findings:0,unknown_price_findings:3,known_retail_subtotal_usd:null}]};
    else if(path===`/api/v1/scans/${scanId}/analysis/resource`) {
      const selected=findings.find(f=>f.resource_id===request.postDataJSON().resource_id);
      const protectedResource=(selected?.evidence.tags as Record<string,string>|undefined)?.Role==='DR-Standby';
      const check=(code:string,status:string,explanation:string)=>({code,status,explanation:'TEST FIXTURE: '+explanation});
      const hasPrice=selected?.estimated_monthly_waste_usd!=null;
      const pillars=[
        {pillar:'cost',status:'unknown',checks:[check('RETAIL_ESTIMATE',hasPrice?'observed':'unknown',hasPrice?'A retail estimate is attached.':'No price is attached.'),check('BILLED_COST','unknown','No billing feed is attached.')]},
        {pillar:'reliability',status:protectedResource?'risk':'unknown',checks:[check('RECOVERY_SNAPSHOT','unknown','Snapshot and restore evidence require verification.'),...(protectedResource?[check('PROTECTED_INTENT','risk','Recovery intent suppresses destructive artifacts.')]:[])]},
        {pillar:'performance',status:'unknown',checks:[check('UTILIZATION_WINDOW','unknown','A complete utilization window is unavailable.')]},
        {pillar:'security',status:'unknown',checks:[check('ENCRYPTION_AT_REST','unknown','Encryption settings were not observed.')]},
        {pillar:'operations',status:'unknown',checks:[check('OWNERSHIP','observed','An ownership tag is present.'),check('DEPENDENCY_GRAPH','unknown','A complete dependency graph is unavailable.')]},
      ];
      const checks=pillars.flatMap(p=>p.checks);
      response={assessment:{policy_version:'2026-10-23.1',evidence_digest:'b'.repeat(64),review_priority:'high',evidence_gap_codes:['DEPENDENCY_GRAPH'],observation:{status:'stale',observed_at:'2026-10-01T00:00:00Z',max_age_hours:24},disposition:protectedResource?'protected':'requires_review',protected_reasons:protectedResource?['RECOVERY_OR_WITNESS_ROLE']:[],evidence_coverage:{observed:checks.filter(c=>c.status!=='unknown').length,total:checks.length},guardrails:['VERIFY_CURRENT_STATE','REVIEW_DEPENDENCIES','CREATE_PRE_DELETION_SNAPSHOT',...(protectedResource?['NO_DESTRUCTIVE_RECOMMENDATION']:[])],pillars},ai_context:{resource_reference:'a'.repeat(64),provider:'azure',service_category:'storage',rule_id:'ORPHANED_DISK',facts:{},protected:protectedResource,guardrails:['VERIFY_CURRENT_STATE'],observed_check_codes:checks.filter(c=>c.status!=='unknown').map(c=>c.code)}};
    }
    else if(path===`/api/v1/scans/${scanId}/ai-risk-evaluation`)response={usage:{input_tokens:300,output_tokens:180,billed_cost_usd:null},cached:false,advisory_only:true,automatic_execution:false,warning:'AI text is unverified advice. It does not approve actions.',guardrails:['VERIFY_CURRENT_STATE'],advice:{summary:'TEST FIXTURE: Verify retention and recovery before any decision.',risk_level:options.protected?'high':'unknown',pillars:['cost','reliability','performance','security','operations'].map(pillar=>({pillar,observation:'TEST FIXTURE: Evidence is incomplete.',evidence_codes:options.protected&&pillar==='reliability'?['PROTECTED_INTENT']:[]})),review_questions:['Who owns this resource?']}};
    else if(path==='/api/v1/billing/entitlements')response={tier:'GROWTH',max_subscriptions:20,current_subscriptions:1,can_export_terraform:true,can_use_keyvault:false,can_dispatch_automated_alerts:true,retention_days:90};
    else if(path==='/api/v1/trends')response={total_snapshots:7,direction:'unknown',net_change_usd:null,new_findings_count:3,resolved_findings_count:8,snapshots:Array.from({length:7},(_,i)=>({scan_id:'history-'+i,timestamp:new Date(Date.parse(scanTime)-(6-i)*86400000).toISOString(),total_findings:[28,25,30,23,26,18,findings.length][i],total_monthly_waste_usd:null}))};
    else if(path==='/api/v1/operations/reliability')response={available:true,dispatcher_enabled:false,targets:[{target_id:'finops-alerts',channel:'slack'}],counts:[],oldest_due_seconds:null,dispatcher:null};
    else if(path==='/api/v1/operations/deliveries')response={items:[],next_cursor:null};
    else if(path==='/api/v1/gitops/targets')response={publishing_enabled:!!options.publishing,targets:[{target_id:'infra',repository:'example/infrastructure',base_branch:'main'}]};
    else if(path==='/api/v1/gitops/requests'&&request.method()==='GET')response=[];
    else if(path==='/api/v1/gitops/preview')response={review_id:'review-test',fingerprint:'a'.repeat(64),repository:'example/infrastructure',title:'Review resource imports',branch:'cloudsaver/review-fixture',files:{'.cloudsaver/reviews/test/imports.tf':'# TEST FIXTURE\nimport {\n  to = azurerm_managed_disk.archive\n  id = "test-resource"\n}\n'},body:'Test-only package'};
    else if(path==='/api/v1/gitops/requests'&&request.method()==='POST')response={id:'request-fixture',repository:'example/infrastructure',branch:'cloudsaver/review-fixture',status:'open',attempts:1,result:{pr_url:'https://github.com/example/infrastructure/pull/42',draft:true,state:'open'}};
    else if(path===`/api/v1/scans/${scanId}/remediation-terraform`)response={hcl:'# TEST FIXTURE import review\nimport {\n  to = azurerm_managed_disk.archive\n  id = "test-resource"\n}\n',filename:'cloudsaver-review.tf'};
    else if(path===`/api/v1/scans/${scanId}/remediation`)response={script:'#!/bin/bash\n# TEST FIXTURE review only\n',filename:'cloudsaver-review.sh'};
    else if(path==='/api/v1/policies/terraform/evaluate'){
      const raw=request.postData()||'';
      if((raw.match(/"duplicate"/g)||[]).length>1){status=422;response={detail:'Invalid or unsupported JSON request'};}
      else response={decision:'fail',resources_checked:3,issues:[{code:'DELETION_BLOCKED',address:'azurerm_managed_disk.archive',message:'Deletion requires independent review.'}],cost:{status:'unknown',monthly_increase_usd:null}};
    }
    else if(path==='/api/v1/scans/multi-cloud'){status=201;response={...current,scan_id:'44444444-4444-4444-8444-444444444444',cloud_providers:request.postDataJSON().providers};}
    else throw new Error('Unmocked API call: '+request.method()+' '+path);
    await route.fulfill({status,contentType:'application/json',body:JSON.stringify(response)});
  });
  await page.goto('/');
  await page.getByLabel('Workspace access key or Entra Bearer token').fill('test-only-browser-credential');
  await page.getByRole('button',{name:'Connect workspace',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Your cloud, in focus.'})).toBeVisible();
  return {mutations,findings:current.findings};
}

export async function navigate(page:Page,label:string){
  if(await page.getByRole('button',{name:'Open navigation'}).isVisible()){
    await page.getByRole('button',{name:'Open navigation'}).click();
    await page.getByRole('navigation',{name:'Mobile navigation'}).getByRole('link',{name:new RegExp('^'+label)}).click();
  }else await page.getByRole('navigation',{name:'Primary navigation'}).getByRole('link',{name:new RegExp('^'+label)}).click();
}
