import type {Page} from '@playwright/test';
import {scanId,subscriptionId} from './workspace-fixture';
export const assessmentId='55555555-5555-4555-8555-555555555555';
export function billingFile(){return {source_id:'test-export-october',provider:'azure',sub_account_id:subscriptionId,billing_currency:'USD',period_start:'2026-10-01',period_end:'2026-10-22',complete:true,records:Array.from({length:21},(_,i)=>({x_ChargeId:'test-charge-'+i,ProviderName:'Azure',BillingAccountId:'test-billing-account',SubAccountId:subscriptionId,BillingCurrency:'USD',ChargePeriodStart:new Date(Date.UTC(2026,9,i+1)).toISOString(),ChargePeriodEnd:new Date(Date.UTC(2026,9,i+2)).toISOString(),ResourceId:null,ChargeCategory:'Usage',BilledCost:'10.00000000',EffectiveCost:'10.00000000',ListCost:'20.00000000'}))};}
export async function mockEnterprise(page:Page,status:'completed'|'uncertain'='completed'){
  const writes:any[]=[];let imported=false;
  const row={id:assessmentId,scan_id:scanId,status,input_tokens:status==='completed'?300:null,output_tokens:status==='completed'?180:null,created_at:'2026-10-23T12:00:00Z',metadata:{provider:'azure',model:'TEST-FIXTURE-MODEL',target_id:'review',evidence_digest:'c'.repeat(64),policy_version:'2026-10-23.1'}};
  await page.route('**/api/v1/finops/**',async route=>{
    const request=route.request(),url=new URL(request.url());let response:any;
    if(url.pathname.endsWith('/imports')&&request.method()==='POST'){
      writes.push(request.postDataJSON());response={import_id:'test-import',records:21,inserted:21,cached:imported};imported=true;
    }else if(url.pathname.endsWith('/imports'))response={items:imported?[{id:'test-import',source_id:'test-export-october',provider:'azure',sub_account:subscriptionId,currency:'USD',records:21,inserted:21,complete:true,created_at:'2026-10-23T12:00:00Z'}]:[]};
    else{const currency=url.searchParams.get('currency')||'USD',available=imported&&currency==='USD';response={currency,records:available?21:0,billed_cost:available?'210.00000000':null,effective_cost:available?'210.00000000':null,list_cost:available?'420.00000000':null,effective_savings_rate_pct:available?'50.0000':null,excluded_overlapping_records:0,warning:'TEST FIXTURE: Imported billing evidence is not provider-reconciled.',forecast:available?{month_end_billed_cost:'310.00000000',daily_velocity:'10.00000000',projected_budget_overrun:true}:null,anomaly:null,daily:available?[{date:'2026-10-01',complete:true,billed_cost:'10.00000000'}]:[],providers:available?[{provider:'azure',records:21,billed_cost:'210.00000000',effective_cost:'210.00000000'}]:[]};}
    await route.fulfill({status:request.method()==='POST'?201:200,contentType:'application/json',body:JSON.stringify(response)});
  });
  await page.route('**/api/v1/ai/usage*',route=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({groups:[{provider:'azure',model:'TEST-FIXTURE-MODEL',attempts:1,completed:status==='completed'?1:0,incomplete_outcomes:status==='uncertain'?1:0,input_tokens:row.input_tokens,output_tokens:row.output_tokens,unmetered_completions:0}]})}));
  await page.route('**/api/v1/ai/assessments**',route=>{const path=new URL(route.request().url()).pathname;const response=path.endsWith(assessmentId)?{...row,events:[{action:'claimed',created_at:row.created_at},{action:status,created_at:row.created_at}],response:status==='completed'?{warning:'TEST FIXTURE: Model prose remains unverified.',guardrails:['INDEPENDENT_CHANGE_APPROVAL'],advice:{summary:'TEST FIXTURE: Retained advisory for independent evidence review.',risk_level:'unknown',review_questions:[]}}:null}:{items:[row],next_cursor:null,durable:true};return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(response)});});
  return {writes,row};
}
