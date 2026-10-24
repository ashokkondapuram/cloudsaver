import test from 'node:test';
import assert from 'node:assert/strict';
import {connectorExecutor} from '../src/connectors.ts';
import {validateStepData,type Connector,type Task,type Step} from '../src/contracts.ts';

const tenant='11111111-1111-4111-8111-111111111111';const id='22222222-2222-4222-8222-222222222222';
const step=(operation:Step['operation'],args:Record<string,unknown>={}):Step=>({connector_id:'native',operation,arguments:args,purpose:'Review metadata',verification:'Read back the exact values',rollback:'Review an independent reversal'});
function task(provider:string,scope_id:string,resource_id:string):Task{return {id,tenant_id:tenant,provider,scope_id,resource_id,state:'running',payload:{plan:{summary:'Reviewed',steps:[]},plan_hash:'a'.repeat(64),connector_ids:['native'],approval:null}};}
const aws:Connector={id:'native',tenant_id:tenant,provider:'aws',scope_id:'123456789012',kind:'aws_sdk',region:'us-east-1',role_arn:'arn:aws:iam::123456789012:role/Executor',operations:['resource.inspect','tags.merge','ebs.snapshot.create'],endpoint:null,token_env:null};
const awsTask=()=>task('aws',aws.scope_id,'arn:aws:ec2:us-east-1:123456789012:volume/vol-0123456789abcdef0');

function awsFixture(encrypted=true){
  let tags=[{Key:'Owner',Value:'existing'}];let writes=0;
  const clients={sts:{send:async()=>({Account:aws.scope_id})},rds:{send:async()=>{throw new Error('Unexpected RDS call');}},ec2:{send:async(command:any)=>{
    const name=command.constructor.name;
    if(name==='DescribeVolumesCommand')return {Volumes:[{VolumeId:'vol-0123456789abcdef0',State:'available',Encrypted:encrypted,KmsKeyId:encrypted?'synthetic-kms':undefined,Tags:tags}]};
    if(name==='CreateTagsCommand'){writes++;tags=[...tags,...command.input.Tags];return {};}
    if(name==='CreateSnapshotCommand'){writes++;assert.equal(command.input.VolumeId,'vol-0123456789abcdef0');assert.ok(command.input.TagSpecifications[0].Tags.some((t:any)=>t.Key==='cloudsaver-retain-until'));return {SnapshotId:'synthetic-snapshot',State:'pending',Encrypted:true};}
    throw new Error('Unexpected SDK operation');
  }}};
  return {clients,writes:()=>writes};
}

test('AWS tag hygiene verifies account, preserves other tags and writes exactly once',async()=>{
  const f=awsFixture();const execute=connectorExecutor({aws:async()=>f.clients});const t=awsTask();
  assert.equal((await execute(t,aws,step('resource.inspect'),0)).code,'AWS_RESOURCE_INSPECTED');
  const outcome=await execute(t,aws,step('tags.merge',{tags:{CostCenter:'FINOPS-42'}}),1);
  assert.equal(outcome.code,'AWS_TAGS_VERIFIED');assert.equal(f.writes(),1);assert.ok(!JSON.stringify(outcome).includes('FINOPS-42'));
});

test('wrong AWS account/region and missing inspection never resolve credentials',async()=>{
  let calls=0;const execute=connectorExecutor({aws:async()=>{calls++;return awsFixture().clients;}});const t=awsTask();
  assert.equal((await execute({...t,resource_id:t.resource_id.replace('123456789012','999999999999')},aws,step('resource.inspect'),0)).code,'INVALID_AWS_SCOPE');
  assert.equal((await execute(t,aws,step('tags.merge',{tags:{CostCenter:'review'}}),1)).code,'PRIOR_INSPECTION_REQUIRED');assert.equal(calls,0);
});

test('AWS safety snapshots require KMS encryption and pending creation remains uncertain',async()=>{
  for(const encrypted of [false,true]){
    const f=awsFixture(encrypted);const execute=connectorExecutor({aws:async()=>f.clients});const t=awsTask();
    await execute(t,aws,step('resource.inspect'),0);
    const result=await execute(t,aws,step('ebs.snapshot.create',{snapshot_name_prefix:'review',retention_days:90}),1);
    assert.equal(result.code,encrypted?'AWS_SNAPSHOT_SUBMITTED_RECONCILE':'KMS_ENCRYPTED_SOURCE_REQUIRED');assert.equal(result.status,encrypted?'uncertain':'failed');assert.equal(f.writes(),encrypted?1:0);
  }
});

const gcp:Connector={id:'native',tenant_id:tenant,provider:'gcp',scope_id:'example-project',kind:'gcp_rest',service_account:'execution-worker@example-project.iam.gserviceaccount.com',operations:['resource.inspect','labels.merge','disk.snapshot.create'],endpoint:null,token_env:null};
function gcpFixture(){let labels={owner:'existing'} as Record<string,string>,fingerprint='original',writes=0;
  const request:typeof fetch=async(url,init)=>{
    assert.equal(init?.redirect,'error');assert.ok(String(url).startsWith('https://compute.googleapis.com/compute/v1/projects/example-project/'));
    if(String(url).endsWith('/setLabels')){writes++;const body=JSON.parse(String(init?.body));assert.equal(body.labelFingerprint,fingerprint);labels=body.labels;fingerprint='updated';return Response.json({status:'DONE'});}
    return Response.json({name:'disk',id:'synthetic',labels,labelFingerprint:fingerprint});
  };
  return {request,drift:()=>{fingerprint='external-change';},writes:()=>writes};
}
test('Google labels bind project and label fingerprint, preserve existing labels and verify readback',async()=>{
  const f=gcpFixture();const execute=connectorExecutor({gcpToken:async()=> 'synthetic',request:f.request});const t=task('gcp',gcp.scope_id,'//compute.googleapis.com/projects/example-project/zones/us-central1-a/disks/disk');
  assert.equal((await execute(t,gcp,step('resource.inspect'),0)).code,'GCP_RESOURCE_INSPECTED');
  assert.equal((await execute(t,gcp,step('labels.merge',{labels:{cost_center:'finops'}}),1)).code,'GCP_LABELS_VERIFIED');assert.equal(f.writes(),1);
});
test('Google concurrent label changes block the write rather than overwriting a newer fingerprint',async()=>{
  const f=gcpFixture();const execute=connectorExecutor({gcpToken:async()=> 'synthetic',request:f.request});const t=task('gcp',gcp.scope_id,'//compute.googleapis.com/projects/example-project/zones/us-central1-a/disks/disk');
  await execute(t,gcp,step('resource.inspect'),0);f.drift();assert.equal((await execute(t,gcp,step('labels.merge',{labels:{cost_center:'finops'}}),1)).code,'LIVE_STATE_CHANGED');assert.equal(f.writes(),0);
});

const k8s:Connector={id:'native',tenant_id:tenant,provider:'kubernetes',scope_id:'cluster-a',kind:'k8s_api',endpoint:'https://cluster.internal',token_env:'CLOUDSAVER_AGENT_K8S_TOKEN_QA',operations:['workload.inspect','annotations.merge']};
test('Kubernetes changes only reviewed recommendation annotations with UID/resourceVersion preconditions',async()=>{
  let annotations:Record<string,string>={'existing.example/key':'preserved'},version='1',writes=0;
  const execute=connectorExecutor({secrets:{CLOUDSAVER_AGENT_K8S_TOKEN_QA:'synthetic'},request:async(url,init)=>{
    assert.equal(String(url),'https://cluster.internal/apis/apps/v1/namespaces/team/deployments/app');
    if(init?.method==='PATCH'){writes++;const body=JSON.parse(String(init.body));assert.equal(body.metadata.resourceVersion,'1');assert.equal(body.metadata.uid,'owned-uid');assert.equal((init.headers as Record<string,string>)['Content-Type'],'application/strategic-merge-patch+json');annotations=body.metadata.annotations;version='2';}
    return Response.json({metadata:{name:'app',namespace:'team',uid:'owned-uid',resourceVersion:version,annotations}});
  }});
  const t=task('kubernetes','cluster-a','k8s://cluster-a/namespaces/team/deployments/app');
  assert.equal((await execute(t,k8s,step('workload.inspect'),0)).code,'K8S_WORKLOAD_INSPECTED');
  assert.equal((await execute(t,k8s,step('annotations.merge',{annotations:{'cloudsaver.io/recommended-review':'pending'}}),1)).code,'K8S_ANNOTATIONS_VERIFIED');assert.equal(writes,1);assert.equal(annotations['existing.example/key'],'preserved');
});
test('unsupported annotations and cluster identities cannot send a request',async()=>{
  let calls=0;const execute=connectorExecutor({request:async()=>{calls++;throw new Error('No request');}});const t=task('kubernetes','cluster-a','k8s://cluster-b/namespaces/team/deployments/app');
  assert.equal((await execute(t,k8s,step('workload.inspect'),0)).code,'INVALID_K8S_SCOPE');
  assert.equal((await execute(t,k8s,step('annotations.merge',{annotations:{'kubectl.kubernetes.io/restartedAt':'now'}}),1)).code,'INVALID_ACTION_ARGUMENTS');assert.equal(calls,0);
});
test('snapshot retention and metadata contracts reject extra fields and credential-shaped values',()=>{
  assert.throws(()=>validateStepData(step('ebs.snapshot.create',{snapshot_name_prefix:'review',retention_days:6}),aws));
  assert.throws(()=>validateStepData(step('ebs.snapshot.create',{snapshot_name_prefix:'review',retention_days:90,url:'https://unapproved.example'}),aws));
  assert.throws(()=>validateStepData(step('labels.merge',{labels:{api_key:'private'}}),gcp));
});

test('Azure safety snapshots verify disk identity, vacant destination, retention and copied source',async()=>{
  const scope='33333333-3333-4333-8333-333333333333';const rid=`/subscriptions/${scope}/resourceGroups/qa/providers/Microsoft.Compute/disks/source`;
  const c:Connector={id:'native',tenant_id:tenant,provider:'azure',scope_id:scope,kind:'azure_arm',operations:['resource.inspect','snapshot.create'],endpoint:null,token_env:null};let created=false,writes=0;
  const execute=connectorExecutor({token:async()=> 'synthetic',request:async(url,init)=>{
    const value=String(url);
    if(value.includes('/providers/Microsoft.Resources/tags/default'))return Response.json({properties:{tags:{}}});
    if(value.includes('/disks/source?'))return Response.json({id:rid,location:'eastus',properties:{uniqueId:'source-uid',diskState:'Unattached'}});
    assert.ok(value.includes('/providers/Microsoft.Compute/snapshots/review-'));
    if(init?.method==='PUT'){writes++;const body=JSON.parse(String(init.body));assert.equal(body.properties.creationData.sourceResourceId,rid);assert.equal(body.properties.creationData.createOption,'Copy');assert.equal(body.tags['cloudsaver-pre-delete-safety'],'true');assert.ok(Date.parse(body.tags['cloudsaver-retain-until'])>Date.now());created=true;return Response.json({properties:{provisioningState:'Creating'}},{status:202});}
    return created?Response.json({properties:{provisioningState:'Succeeded',creationData:{sourceResourceId:rid}}}):Response.json({error:{}},{status:404});
  }});const t=task('azure',scope,rid);
  assert.equal((await execute(t,c,step('resource.inspect'),0)).status,'succeeded');
  assert.equal((await execute(t,c,step('snapshot.create',{snapshot_name_prefix:'review',retention_days:7}),1)).code,'AZURE_SNAPSHOT_VERIFIED');assert.equal(writes,1);
});

test('Google snapshot acceptance remains uncertain until the snapshot reaches READY',async()=>{
  const t=task('gcp',gcp.scope_id,'//compute.googleapis.com/projects/example-project/zones/us-central1-a/disks/disk');let writes=0;
  const execute=connectorExecutor({gcpToken:async()=> 'synthetic',request:async(url,init)=>{
    if(String(url).endsWith('/createSnapshot')){writes++;const body=JSON.parse(String(init?.body));assert.equal(body.labels['cloudsaver-safety-snapshot'],'true');return Response.json({status:'RUNNING'});}
    if(String(url).includes('/global/snapshots/'))return Response.json({status:'CREATING',id:'snapshot',sourceDisk:'https://compute.googleapis.com/compute/v1/projects/example-project/zones/us-central1-a/disks/disk'});
    return Response.json({name:'disk',id:'disk-uid',labelFingerprint:'original',labels:{}});
  }});
  await execute(t,gcp,step('resource.inspect'),0);const result=await execute(t,gcp,step('disk.snapshot.create',{snapshot_name_prefix:'review',retention_days:90}),1);
  assert.equal(result.status,'uncertain');assert.equal(result.code,'GCP_SNAPSHOT_SUBMITTED_RECONCILE');assert.equal(writes,1);
});
