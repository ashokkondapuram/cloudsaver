import {stateMatches} from './contracts.ts';
import {createHash} from 'node:crypto';
import type {Connector,Step,Task,Outcome} from './contracts.ts';
import {canonical,readOperations} from './contracts.ts';
import {boundedRequest,type Requester} from './http.ts';

type Client={send:(command:any)=>Promise<any>;destroy?:()=>void};
type AwsClients={ec2:Client;rds:Client;sts:Client};
export type NativeOptions={request?:Requester;secrets?:NodeJS.ProcessEnv;aws?:(c:Connector)=>Promise<AwsClients>;gcpToken?:(c:Connector)=>Promise<string>};
const hash=(v:unknown)=>createHash('sha256').update(canonical(v)).digest('hex');
const record=(v:any)=>v&&typeof v==='object'&&!Array.isArray(v)?v:null;
const metadata=(args:Record<string,unknown>,field:string)=>args[field] as Record<string,string>;
const snapshotName=(task:Task,step:Step)=>String(step.arguments.snapshot_name_prefix)+'-'+task.id.replaceAll('-','').slice(0,12);
const expiry=(step:Step)=>new Date(Date.now()+Number(step.arguments.retention_days)*86400000).toISOString();

async function awsClients(c:Connector):Promise<AwsClients>{
  if(!process.env.AWS_WEB_IDENTITY_TOKEN_FILE||process.env.AWS_ACCESS_KEY_ID||process.env.AWS_SECRET_ACCESS_KEY)throw new Error('Explicit keyless AWS identity is required');
  const {fromTokenFile}=await import('@aws-sdk/credential-providers');
  const {EC2Client}=await import('@aws-sdk/client-ec2');const {RDSClient}=await import('@aws-sdk/client-rds');const {STSClient}=await import('@aws-sdk/client-sts');
  const credentials=fromTokenFile({roleArn:c.role_arn!,webIdentityTokenFile:process.env.AWS_WEB_IDENTITY_TOKEN_FILE,roleSessionName:'cloudsaver-agent',clientConfig:{region:c.region!,maxAttempts:1}});
  const config={region:c.region!,credentials,maxAttempts:1};return {ec2:new EC2Client(config),rds:new RDSClient(config),sts:new STSClient(config)};
}

async function googleToken(c:Connector):Promise<string>{
  const {GoogleAuth,Impersonated}=await import('google-auth-library');
  const source=await new GoogleAuth({scopes:['https://www.googleapis.com/auth/cloud-platform']}).getClient();
  if(!['IdentityPoolClient','AwsClient','Compute'].includes(source.constructor.name))throw new Error('A keyless Google execution identity is required');
  const target=new Impersonated({sourceClient:source,targetPrincipal:c.service_account!,targetScopes:['https://www.googleapis.com/auth/cloud-platform'],lifetime:300});
  const token=await target.getAccessToken();if(!token.token)throw new Error('No scoped Google token');return token.token;
}

export function multicloudExecutor(options:NativeOptions={}){
  const inspections=new Map<string,{digest:string;uid?:string;version?:string;fingerprint?:string}>();
  return async(task:Task,c:Connector,step:Step):Promise<Outcome>=>{
    const key=task.id+':'+c.id+':'+task.resource_id;const write=!readOperations.has(step.operation);
    if(task.resource_id.split('/').some(v=>v==='.'||v==='..')||/[?#%\\]/.test(task.resource_id))return {status:'failed',code:'INVALID_RESOURCE_SCOPE'};
    if(write&&!inspections.has(key))return {status:'failed',code:'PRIOR_INSPECTION_REQUIRED'};
    if(c.kind==='aws_sdk'){
      const arn=/^arn:aws:(ec2|rds):([a-z0-9-]+):([0-9]{12}):(volume\/(vol-[0-9a-f]{8,17})|instance\/(i-[0-9a-f]{8,17})|db:([A-Za-z][A-Za-z0-9-]{0,62}))$/.exec(task.resource_id);
      if(!arn||arn[2]!==c.region||arn[3]!==c.scope_id||!new RegExp('^arn:aws:iam::'+c.scope_id+':role/[A-Za-z0-9+=,.@_/-]{1,512}$').test(c.role_arn||'')||(arn[1]==='rds')!==!!arn[7])return {status:'failed',code:'INVALID_AWS_SCOPE'};
      const sdk=await import('@aws-sdk/client-ec2'),rds=await import('@aws-sdk/client-rds'),sts=await import('@aws-sdk/client-sts');
      const clients=await (options.aws||awsClients)(c);
      try{
      if((await clients.sts.send(new sts.GetCallerIdentityCommand({}))).Account!==c.scope_id)return {status:'failed',code:'AWS_CALLER_MISMATCH'};
      const inspect=async()=>{
        if(arn[5]){const data=await clients.ec2.send(new sdk.DescribeVolumesCommand({VolumeIds:[arn[5]]}));if(data.Volumes?.length!==1||data.Volumes[0].VolumeId!==arn[5])throw new Error('Volume mismatch');return data.Volumes[0];}
        if(arn[6]){const data=await clients.ec2.send(new sdk.DescribeInstancesCommand({InstanceIds:[arn[6]]}));const rows=data.Reservations?.flatMap((r:any)=>r.Instances||[]);if(rows?.length!==1||rows[0].InstanceId!==arn[6])throw new Error('Instance mismatch');return rows[0];}
        const data=await clients.rds.send(new rds.DescribeDBInstancesCommand({DBInstanceIdentifier:arn[7]}));if(data.DBInstances?.length!==1||data.DBInstances[0].DBInstanceArn!==task.resource_id)throw new Error('RDS mismatch');
        const tags=await clients.rds.send(new rds.ListTagsForResourceCommand({ResourceName:task.resource_id}));return {...data.DBInstances[0],Tags:tags.TagList||[]};
      };
      const current=await inspect();const digest=hash(current);
      if(!write&&!stateMatches(step,{State:typeof current.State==='string'?current.State:current.State?.Name,DBInstanceStatus:current.DBInstanceStatus}))return {status:'failed',code:'LIVE_RESOURCE_STATE_DRIFTED'};
      if(!write){inspections.set(key,{digest});return {status:'succeeded',code:'AWS_RESOURCE_INSPECTED',evidence_digest:digest};}
      if(inspections.get(key)!.digest!==digest)return {status:'failed',code:'LIVE_STATE_CHANGED'};
      if(step.operation==='tags.merge'){
        const tags=metadata(step.arguments,'tags');const Tags=Object.entries(tags).map(([Key,Value])=>({Key,Value}));
        if(arn[7])await clients.rds.send(new rds.AddTagsToResourceCommand({ResourceName:task.resource_id,Tags}));
        else await clients.ec2.send(new sdk.CreateTagsCommand({Resources:[arn[5]||arn[6]],Tags}));
        const after=await inspect();const observed=Object.fromEntries((after.Tags||[]).map((v:any)=>[v.Key,v.Value]));const verified=Object.entries(tags).every(([k,v])=>observed[k]===v);
        return {status:verified?'succeeded':'uncertain',code:verified?'AWS_TAGS_VERIFIED':'AWS_TAGS_RECONCILE',evidence_digest:hash(observed)};
      }
      if(step.operation==='ebs.snapshot.create'&&arn[5]){
        // CreateSnapshot inherits encryption. It cannot encrypt an unencrypted
        // source volume; refuse rather than claim a KMS-protected backup.
        if(current.Encrypted!==true||typeof current.KmsKeyId!=='string')return {status:'failed',code:'KMS_ENCRYPTED_SOURCE_REQUIRED'};
        const result=await clients.ec2.send(new sdk.CreateSnapshotCommand({VolumeId:arn[5],Description:snapshotName(task,step),TagSpecifications:[{ResourceType:'snapshot',Tags:[
          {Key:'Name',Value:snapshotName(task,step)},{Key:'cloudsaver-safety-snapshot',Value:'true'},{Key:'cloudsaver-retain-until',Value:expiry(step)}]}]}));
        const verified=result.State==='completed'&&result.Encrypted===true&&result.VolumeId===arn[5]&&result.KmsKeyId===current.KmsKeyId;
        return {status:verified?'succeeded':'uncertain',code:verified?'AWS_SNAPSHOT_VERIFIED':'AWS_SNAPSHOT_SUBMITTED_RECONCILE',evidence_digest:hash({id:result.SnapshotId,state:result.State})};
      }
      return {status:'failed',code:'UNSUPPORTED_AWS_OPERATION'};
      }finally{for(const client of Object.values(clients))client.destroy?.();}
    }
    if(c.kind==='gcp_rest'){
      const m=/^\/\/(compute|sqladmin)\.googleapis\.com\/projects\/([a-z][a-z0-9-]{4,28}[a-z0-9])\/(?:(zones|regions)\/([a-z0-9-]+)\/(disks|instances)\/([a-z0-9-]+)|instances\/([a-z0-9-]+))$/.exec(task.resource_id);
      if(!m||m[2]!==c.scope_id||(m[1]==='sqladmin')!==!!m[7]||!new RegExp('^[a-z0-9-]{6,30}@'+c.scope_id+'\\.iam\\.gserviceaccount\\.com$').test(c.service_account||''))return {status:'failed',code:'INVALID_GCP_SCOPE'};
      const token=await (options.gcpToken||googleToken)(c);const root=m[1]==='compute'?'https://compute.googleapis.com/compute/v1/':'https://sqladmin.googleapis.com/sql/v1beta4/';
      const url=root+task.resource_id.split('.com/')[1];const headers={Authorization:'Bearer '+token,'Content-Type':'application/json'};
      const read=async()=>{const r=await boundedRequest(url,{headers},options.request);const body=record(r.body);if(r.status!==200||!body)throw new Error('Inspection unavailable');return body;};
      const current=await read();if(!write&&!stateMatches(step,{status:current.status,state:current.state}))return {status:'failed',code:'LIVE_RESOURCE_STATE_DRIFTED'};const labels=m[1]==='compute'?current.labels||{}:current.settings?.userLabels||{};
      const fingerprint=m[1]==='compute'?current.labelFingerprint:String(current.settings?.settingsVersion??'');
      const digest=hash({labels,fingerprint,id:current.id||current.name});
      if(!write){inspections.set(key,{digest,fingerprint});return {status:'succeeded',code:'GCP_RESOURCE_INSPECTED',evidence_digest:digest};}
      if(inspections.get(key)!.digest!==digest||!fingerprint)return {status:'failed',code:'LIVE_STATE_CHANGED'};
      if(step.operation==='labels.merge'){
        const merged={...labels,...metadata(step.arguments,'labels')};
        const body=m[1]==='compute'?{labels:merged,labelFingerprint:fingerprint}:{settings:{settingsVersion:current.settings.settingsVersion,userLabels:merged}};
        const result=await boundedRequest(url+(m[1]==='compute'?'/setLabels':''),{method:m[1]==='compute'?'POST':'PATCH',headers,body:JSON.stringify(body)},options.request);
        if(![200,201].includes(result.status))return {status:result.status===412?'failed':'uncertain',code:result.status===412?'LIVE_STATE_CHANGED':'GCP_LABELS_RECONCILE',http_status:result.status};
        const after=await read();const observed=m[1]==='compute'?after.labels:after.settings?.userLabels;
        const verified=observed&&Object.entries(merged).every(([k,v])=>observed[k]===v);
        return {status:verified?'succeeded':'uncertain',code:verified?'GCP_LABELS_VERIFIED':'GCP_LABELS_RECONCILE',evidence_digest:hash(observed||{})};
      }
      if(step.operation==='disk.snapshot.create'&&m[1]==='compute'&&m[5]==='disks'){
        const name=snapshotName(task,step);const retention=expiry(step).replace(/[-:.]/g,'').toLowerCase();
        const body={name,labels:{'cloudsaver-safety-snapshot':'true','cloudsaver-retain-until':retention},...(current.diskEncryptionKey?.kmsKeyName?{snapshotEncryptionKey:{kmsKeyName:current.diskEncryptionKey.kmsKeyName}}:{})};
        const result=await boundedRequest(url+'/createSnapshot',{method:'POST',headers,body:JSON.stringify(body)},options.request);
        if(![200,201].includes(result.status))return {status:'uncertain',code:'GCP_SNAPSHOT_RECONCILE',http_status:result.status};
        const verify=await boundedRequest(root+'projects/'+c.scope_id+'/global/snapshots/'+name,{headers},options.request);const snap=record(verify.body);
        const valid=verify.status===200&&snap?.status==='READY'&&snap.sourceDisk?.endsWith(task.resource_id.split('.com')[1]);
        return {status:valid?'succeeded':'uncertain',code:valid?'GCP_SNAPSHOT_VERIFIED':'GCP_SNAPSHOT_SUBMITTED_RECONCILE',evidence_digest:hash({id:snap?.id,status:snap?.status})};
      }
      return {status:'failed',code:'UNSUPPORTED_GCP_OPERATION'};
    }
    if(c.kind==='k8s_api'){
      const m=/^k8s:\/\/([a-z0-9-]+)\/namespaces\/([a-z0-9-]+)\/(deployments|statefulsets|daemonsets|cronjobs|persistentvolumeclaims|services)\/([a-z0-9.-]+)$/.exec(task.resource_id);
      if(!m||m[1]!==c.scope_id||!/^CLOUDSAVER_AGENT_K8S_TOKEN_[A-Z0-9_]{1,60}$/.test(c.token_env||''))return {status:'failed',code:'INVALID_K8S_SCOPE'};
      const origin=new URL(c.endpoint||'');if(origin.protocol!=='https:'||origin.username||origin.password||origin.search||origin.hash||origin.pathname!=='/')return {status:'failed',code:'INVALID_K8S_ENDPOINT'};
      const token=(options.secrets||process.env)[c.token_env!];if(!token)return {status:'failed',code:'K8S_CREDENTIAL_UNAVAILABLE'};
      const prefix=['persistentvolumeclaims','services'].includes(m[3])?'/api/v1':m[3]==='cronjobs'?'/apis/batch/v1':'/apis/apps/v1';
      const url=origin.origin+prefix+'/namespaces/'+m[2]+'/'+m[3]+'/'+m[4];const headers={Authorization:'Bearer '+token};
      const read=async()=>{const r=await boundedRequest(url,{headers},options.request);const body=record(r.body);if(r.status!==200||!body||body.metadata?.namespace!==m[2]||body.metadata?.name!==m[4]||typeof body.metadata?.uid!=='string'||typeof body.metadata?.resourceVersion!=='string')throw new Error('Kubernetes identity mismatch');return body;};
      const current=await read();if(!write&&!stateMatches(step,{generation:current.metadata?.generation,replicas:current.spec?.replicas}))return {status:'failed',code:'LIVE_RESOURCE_STATE_DRIFTED'};const meta=current.metadata;const digest=hash(meta);
      if(!write){inspections.set(key,{digest,uid:meta.uid,version:meta.resourceVersion});return {status:'succeeded',code:'K8S_WORKLOAD_INSPECTED',evidence_digest:digest};}
      const prior=inspections.get(key)!;if(prior.digest!==digest||prior.uid!==meta.uid)return {status:'failed',code:'LIVE_STATE_CHANGED'};
      if(step.operation!=='annotations.merge')return {status:'failed',code:'UNSUPPORTED_K8S_OPERATION'};
      const annotations={...(meta.annotations||{}),...metadata(step.arguments,'annotations')};
      const result=await boundedRequest(url,{method:'PATCH',headers:{...headers,'Content-Type':'application/strategic-merge-patch+json'},body:JSON.stringify({metadata:{uid:meta.uid,resourceVersion:meta.resourceVersion,annotations}})},options.request);
      if(result.status!==200)return {status:result.status===409?'failed':'uncertain',code:result.status===409?'LIVE_STATE_CHANGED':'K8S_ANNOTATIONS_RECONCILE',http_status:result.status};
      const after=await read();const verified=after.metadata.uid===meta.uid&&Object.entries(annotations).every(([k,v])=>after.metadata.annotations?.[k]===v);
      return {status:verified?'succeeded':'uncertain',code:verified?'K8S_ANNOTATIONS_VERIFIED':'K8S_ANNOTATIONS_RECONCILE',evidence_digest:hash(after.metadata)};
    }
    return {status:'failed',code:'UNSUPPORTED_CONNECTOR'};
  };
}
