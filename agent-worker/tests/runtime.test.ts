import {test} from 'node:test';
import assert from 'node:assert/strict';
import {checkAssignment,renderCode} from '../src/contracts.ts';
import type {Assignment,Connector} from '../src/contracts.ts';
import {runCode} from '../src/runtime.ts';
import {connectorExecutor} from '../src/connectors.ts';
import {boundedRequest} from '../src/http.ts';

const tid='11111111-1111-4111-8111-111111111111',sid='22222222-2222-4222-8222-222222222222';
const connector:Connector={id:'azure-tags',tenant_id:tid,provider:'azure',scope_id:sid,kind:'azure_arm',operations:['resource.inspect','tags.merge'],endpoint:null,token_env:null};
function assignment():Assignment{
  const plan={summary:'Inspect and tag',steps:[{connector_id:connector.id,operation:'resource.inspect' as const,arguments:{},purpose:'Read',verification:'Read',rollback:'Read-only'},
    {connector_id:connector.id,operation:'tags.merge' as const,arguments:{tags:{CostCenter:'FINOPS-42'}},purpose:'Tag',verification:'Readback',rollback:'Separate review'}]};
  return {phase:'execute',lease_token:'synthetic-lease',code:renderCode(plan),connectors:[connector],task:{id:'33333333-3333-4333-8333-333333333333',tenant_id:tid,provider:'azure',scope_id:sid,
    resource_id:`/subscriptions/${sid}/resourceGroups/rg/providers/Microsoft.Compute/disks/qa`,state:'running',payload:{plan,plan_hash:'a'.repeat(64),connector_ids:[connector.id],approval:{plan_hash:'a'.repeat(64),expires_at:new Date(Date.now()+60000).toISOString()}}}};
}

test('runCode executes the exact TypeScript artifact with ordered one-time gateway permits',async()=>{
  const a=assignment();const calls:string[]=[];
  await runCode(a,[connector],async(path)=>{calls.push(path);return {permitted:true,index:path.includes('/0/')?0:1,plan_hash:a.task.payload.plan_hash};},async(_t,_c,_s,i)=>{calls.push('provider:'+i);return {status:'succeeded',code:'VERIFIED'};});
  assert.deepEqual(calls.map(x=>x.includes('provider:')?x:x.split('/').slice(-3).join('/')),['steps/0/start','provider:0','steps/0/complete','steps/1/start','provider:1','steps/1/complete']);
});

test('arbitrary TypeScript, expired approvals and connector changes never reach a provider',async()=>{
  for(const alter of [(a:Assignment)=>{a.code+='\nprocess.env';},(a:Assignment)=>{a.task.payload.approval!.expires_at='2000-01-01T00:00:00Z';},
    (a:Assignment)=>{a.task.payload.approval=null;},(a:Assignment)=>{a.connectors=[{...connector,scope_id:'different'}];}]){
    const a=assignment();alter(a);let calls=0;
    await assert.rejects(runCode(a,[connector],async()=>{calls++;return {};},async()=>{calls++;return {status:'succeeded',code:'BAD'};}));
    assert.equal(calls,0);
  }
});

test('refused and ambiguous permits do not call a connector',async()=>{
  const a=assignment();let calls=0;
  await assert.rejects(runCode(a,[connector],async()=>{throw new Error('409');},async()=>{calls++;return {status:'succeeded',code:'BAD'};}));
  assert.equal(calls,0);
  await assert.rejects(runCode(a,[connector],async()=>({permitted:true,index:0,plan_hash:'wrong'}),async()=>{calls++;return {status:'succeeded',code:'BAD'};}));
  assert.equal(calls,0);
});

test('uncertain writes stop immediately and completion transport errors never repeat a provider call',async()=>{
  const a=assignment();let calls=0;
  await assert.rejects(runCode(a,[connector],async(path)=>{if(path.endsWith('/complete'))throw new Error('lost ACK');return {permitted:true,index:0,plan_hash:a.task.payload.plan_hash};},async()=>{calls++;return {status:'succeeded',code:'READ'};}));
  assert.equal(calls,1);
  calls=0;
  await assert.rejects(runCode(a,[connector],async(path)=>({permitted:true,index:path.includes('/0/')?0:1,plan_hash:a.task.payload.plan_hash}),async()=>{calls++;return {status:'uncertain',code:'TIMEOUT'};}));
  assert.equal(calls,1);
});

test('Azure tag connector preserves other tags, verifies changes and never returns raw values',async()=>{
  const a=assignment();let tags:Record<string,string>={Owner:'private-owner'};const methods:string[]=[];
  const execute=connectorExecutor({token:async()=>'synthetic-provider-token',request:async(url,init)=>{
    assert.ok(String(url).startsWith('https://management.azure.com/subscriptions/'+sid+'/'));
    methods.push(init?.method||'GET');
    if(!String(url).includes('/tags/default?'))return Response.json({id:a.task.resource_id,properties:{diskState:'Unattached'}});
    if(init?.method==='PATCH'){const body=JSON.parse(String(init.body));assert.equal(body.operation,'Merge');tags={...tags,...body.properties.tags};}
    return Response.json({properties:{tags}},{status:200});
  }});
  const first=await execute(a.task,connector,a.task.payload.plan.steps[0],0);
  const second=await execute(a.task,connector,a.task.payload.plan.steps[1],1);
  assert.equal(first.status,'succeeded');assert.equal(second.code,'TAGS_VERIFIED');assert.equal(tags.Owner,'private-owner');
  assert.deepEqual(methods,['GET','GET','GET','GET','PATCH','GET']);assert.ok(!JSON.stringify(second).includes('private-owner'));
});

test('live state drift, cross-scope IDs and missing credentials cannot mutate',async()=>{
  const a=assignment();let gets=0;let writes=0;
  const execute=connectorExecutor({token:async()=>'synthetic',request:async(_u,init)=>{
    if(!String(_u).includes('/tags/default?'))return Response.json({id:a.task.resource_id,properties:{diskState:'Unattached'}});
    if(init?.method==='PATCH')writes++;
    return Response.json({properties:{tags:{version:String(gets++)}}});
  }});
  await execute(a.task,connector,a.task.payload.plan.steps[0],0);
  assert.equal((await execute(a.task,connector,a.task.payload.plan.steps[1],1)).code,'LIVE_STATE_CHANGED');assert.equal(writes,0);
  assert.equal((await execute({...a.task,resource_id:a.task.resource_id.replace(sid,tid)},connector,a.task.payload.plan.steps[1],1)).code,'INVALID_ARM_SCOPE');
  assert.equal((await execute({...a.task,resource_id:a.task.resource_id+'/../../../../subscriptions/'+tid+'/resources/other'},connector,a.task.payload.plan.steps[1],1)).code,'INVALID_ARM_SCOPE');
});

test('generic HTTP action transfers are blocked before any credential or endpoint use',async()=>{
  const a=assignment();const c:Connector={...connector,kind:'http_json',operations:['action.submit'],endpoint:'https://approved.example/actions',token_env:'CLOUDSAVER_AGENT_CONNECTOR_TEST'};
  const step={...a.task.payload.plan.steps[0],operation:'action.submit' as const,arguments:{body:{action:'create-review'}}};let calls=0;
  const execute=connectorExecutor({request:async()=>{calls++;return Response.json({ok:true});}});
  const result=await execute(a.task,c,step,0);
  assert.equal(result.status,'failed');assert.equal(result.code,'EXTERNAL_ACTION_DATA_PROHIBITED');assert.equal(calls,0);
});

test('credential-shaped first-party tag data never reaches Azure',async()=>{
  const a=assignment();let calls=0;
  const execute=connectorExecutor({token:async()=>{calls++;return 'unused';},request:async()=>{calls++;return Response.json({});}});
  const step={...a.task.payload.plan.steps[1],arguments:{tags:{Password:'must-never-leave'}}};
  assert.equal((await execute(a.task,connector,step,1)).code,'SENSITIVE_ACTION_DATA_PROHIBITED');assert.equal(calls,0);
});

test('oversize responses are bounded before they can enter the task journal',async()=>{
  await assert.rejects(boundedRequest('https://approved.example',{},async()=>new Response('x'.repeat(1_000_001))));
});

test('expected disk state is checked against live metadata before tags or snapshots can run',async()=>{
  const a=assignment();let writes=0;
  const execute=connectorExecutor({token:async()=>'synthetic',request:async(url,init)=>{
    if(init?.method==='PATCH')writes++;
    return String(url).includes('/tags/default?')?Response.json({properties:{tags:{}}}):Response.json({id:a.task.resource_id,properties:{diskState:'Attached'}});
  }});
  const inspect={...a.task.payload.plan.steps[0],arguments:{expected_state:{diskState:'Unattached'}}};
  assert.equal((await execute(a.task,connector,inspect,0)).code,'LIVE_RESOURCE_STATE_DRIFTED');
  assert.equal((await execute(a.task,connector,a.task.payload.plan.steps[1],1)).status,'failed');assert.equal(writes,0);
});

test('operational drift after inspection blocks a write even when tags did not change',async()=>{
  const a=assignment();let reads=0,writes=0;
  const execute=connectorExecutor({token:async()=>'synthetic',request:async(url,init)=>{
    if(init?.method==='PATCH')writes++;
    return String(url).includes('/tags/default?')?Response.json({properties:{tags:{}}}):Response.json({id:a.task.resource_id,properties:{diskState:++reads===1?'Unattached':'Attached'}});
  }});
  assert.equal((await execute(a.task,connector,a.task.payload.plan.steps[0],0)).status,'succeeded');
  assert.equal((await execute(a.task,connector,a.task.payload.plan.steps[1],1)).code,'LIVE_RESOURCE_STATE_DRIFTED');assert.equal(writes,0);
});
