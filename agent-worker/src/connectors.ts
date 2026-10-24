import {createHash} from 'node:crypto';
import {ManagedIdentityCredential, WorkloadIdentityCredential} from '@azure/identity';
import type {Connector, Outcome, Step, Task} from './contracts.ts';
import {canonical,validateStepData,readOperations,stateMatches} from './contracts.ts';
import {multicloudExecutor,type NativeOptions} from './multicloud.ts';
import {boundedRequest, type Requester} from './http.ts';

const hash = (value: unknown) => createHash('sha256').update(canonical(value)).digest('hex');
type Token = () => Promise<string>;
export function azureToken(): Token {
  const credential = process.env.CLOUDSAVER_AGENT_AZURE_IDENTITY === 'workload_identity'
    ? new WorkloadIdentityCredential() : new ManagedIdentityCredential({clientId: process.env.AZURE_CLIENT_ID || undefined});
  return async () => (await credential.getToken('https://management.azure.com/.default'))!.token;
}

export function connectorExecutor(options: NativeOptions & {token?: Token} = {}) {
  let token = options.token;
  const inspected = new Map<string,string>();
  const states=new Map<string,string>();
  const disks=new Map<string,string>();const native=multicloudExecutor(options);
  return async (task: Task, connector: Connector, step: Step, index: number): Promise<Outcome> => {
    const write = !readOperations.has(step.operation);
    // No raw provider body, credential, tag value or exception is returned to the task journal.
    try {
      const encoded=JSON.stringify(step.arguments);
      if (/\b(?:password|client[_-]?secret|api[_-]?key|access[_-]?token|authorization)\b\s*"?\s*:/i.test(encoded) ||
          /-----BEGIN [A-Z ]*PRIVATE KEY-----|\bbearer\s+\S{8,}|\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.|(?:AccountKey|SharedAccessSignature|client_secret|api[_ -]?key|password)\s*[:=]\s*\S+|[?&]sig=[A-Za-z0-9%+/=]{8,}/i.test(encoded)) return {status:'failed',code:'SENSITIVE_ACTION_DATA_PROHIBITED'};
      if (connector.tenant_id !== task.tenant_id || connector.provider !== task.provider || connector.scope_id !== task.scope_id || !connector.operations.includes(step.operation)) {
        return {status:'failed',code:'CONNECTOR_GRANT_MISMATCH'};
      }
      if (connector.kind === 'http_json') return {status:'failed',code:'EXTERNAL_ACTION_DATA_PROHIBITED'};
      try{validateStepData(step,connector);}catch{return {status:'failed',code:'INVALID_ACTION_ARGUMENTS'};}
      if(connector.kind!=='azure_arm')return await native(task,connector,step);
      if (connector.provider !== 'azure' || !['resource.inspect','tags.merge','snapshot.create'].includes(step.operation) ||
          task.resource_id.split('/').some(s=>s==='.'||s==='..') ||
          !/^\/subscriptions\/[a-fA-F0-9-]{36}\/resourceGroups\/[A-Za-z0-9_.()-]+\/providers\/[A-Za-z0-9.]+(?:\/[A-Za-z0-9_.()-]+){2,}$/i.test(task.resource_id) ||
          task.resource_id.split('/')[2].toLowerCase() !== connector.scope_id.toLowerCase()) return {status:'failed',code:'INVALID_ARM_SCOPE'};
      token ||= azureToken();
      const bearer = await token();
      const url = 'https://management.azure.com'+task.resource_id+'/providers/Microsoft.Resources/tags/default?api-version=2021-04-01';
      const headers = {Authorization:'Bearer '+bearer,'Content-Type':'application/json'};
      const current = await boundedRequest(url,{headers},options.request);
      if (current.status !== 200 || !current.body || typeof current.body !== 'object') return {status:'failed',code:'LIVE_TAG_INSPECTION_FAILED',http_status:current.status};
      const prior = (current.body as {properties?:{tags?:unknown}}).properties?.tags;
      if (!prior || typeof prior !== 'object' || Array.isArray(prior)) return {status:'failed',code:'INVALID_TAG_EVIDENCE'};
      const kind=task.resource_id.split('/providers/')[1]?.toLowerCase().split('/').slice(0,2).join('/');
      const versions:Record<string,string>={'microsoft.compute/disks':'2023-04-02','microsoft.compute/virtualmachines':'2024-03-01','microsoft.web/serverfarms':'2023-12-01','microsoft.network/publicipaddresses':'2023-09-01','microsoft.network/applicationgateways':'2023-09-01','microsoft.network/natgateways':'2023-09-01','microsoft.storage/storageaccounts':'2023-05-01','microsoft.sql/servers':'2023-08-01','microsoft.cache/redis':'2023-08-01'};
      const version=versions[kind||''];
      if(!version)return {status:'failed',code:'LIVE_METADATA_TYPE_UNSUPPORTED'};
      const metadata=await boundedRequest('https://management.azure.com'+task.resource_id+'?api-version='+version+(kind==='microsoft.compute/virtualmachines'?'&$expand=instanceView':''),{headers},options.request);
      const resource=metadata.body as {id?:string;location?:string;managedBy?:string;properties?:Record<string,unknown>}|null;
      if(metadata.status!==200||resource?.id?.toLowerCase()!==task.resource_id.toLowerCase()||!resource.properties)return {status:'failed',code:'LIVE_RESOURCE_INSPECTION_FAILED'};
      const properties=resource.properties;
      const power=((properties.instanceView as {statuses?:{code:string}[]}|undefined)?.statuses||[]).find(v=>v.code.startsWith('PowerState/'))?.code;
      const live={diskState:properties.diskState,powerState:power,numberOfSites:properties.numberOfSites};
      const stateKey=task.id+':'+connector.id;
      const currentState=hash({id:resource.id,location:resource.location,managedBy:resource.managedBy,properties});
      if(!write){if(!stateMatches(step,live))return {status:'failed',code:'LIVE_RESOURCE_STATE_DRIFTED'};states.set(stateKey,currentState);}
      else if(states.get(stateKey)!==currentState)return {status:'failed',code:'LIVE_RESOURCE_STATE_DRIFTED'};
      if(connector.operations.includes('snapshot.create')){
        if(!/^\/subscriptions\/[a-fA-F0-9-]{36}\/resourceGroups\/[A-Za-z0-9_.()-]+\/providers\/Microsoft.Compute\/disks\/[A-Za-z0-9_.()-]+$/i.test(task.resource_id))return {status:'failed',code:'SNAPSHOT_DISK_SCOPE_REQUIRED'};
        const disk=await boundedRequest('https://management.azure.com'+task.resource_id+'?api-version=2023-04-02',{headers},options.request);
        const body=disk.body as {id?:string;location?:string;properties?:{uniqueId?:string;diskState?:string;encryption?:unknown};managedBy?:string}|null;
        if(disk.status!==200||body?.id?.toLowerCase()!==task.resource_id.toLowerCase()||!body.location||!/^[a-z0-9-]{2,40}$/.test(body.location))return {status:'failed',code:'SNAPSHOT_SOURCE_UNVERIFIED'};
        const digest=hash({id:body.id,location:body.location,properties:body.properties,managedBy:body.managedBy});const key=task.id+':'+connector.id;
        if(!write)disks.set(key,digest);
        if(step.operation==='snapshot.create'){
          if(disks.get(key)!==digest||inspected.get(key)!==hash(prior))return {status:'failed',code:'LIVE_STATE_CHANGED'};
          const group=task.resource_id.split('/').slice(0,5).join('/');const name=String(step.arguments.snapshot_name_prefix)+'-'+task.id.replaceAll('-','').slice(0,12);
          const url='https://management.azure.com'+group+'/providers/Microsoft.Compute/snapshots/'+name+'?api-version=2023-04-02';
          const existing=await boundedRequest(url,{headers},options.request);
          if(existing.status!==404)return {status:'failed',code:'SNAPSHOT_DESTINATION_NOT_FREE'};
          const response=await boundedRequest(url,{method:'PUT',headers,body:JSON.stringify({location:body.location,tags:{'cloudsaver-pre-delete-safety':'true','cloudsaver-retain-until':new Date(Date.now()+Number(step.arguments.retention_days)*86400000).toISOString()},
            properties:{creationData:{createOption:'Copy',sourceResourceId:task.resource_id}}})},options.request);
          if(![200,201,202].includes(response.status))return {status:'uncertain',code:'AZURE_SNAPSHOT_RECONCILE',http_status:response.status};
          const check=await boundedRequest(url,{headers},options.request);const snap=check.body as {properties?:{provisioningState?:string;creationData?:{sourceResourceId?:string}}}|null;
          const verified=check.status===200&&snap?.properties?.provisioningState==='Succeeded'&&snap.properties.creationData?.sourceResourceId?.toLowerCase()===task.resource_id.toLowerCase();
          return {status:verified?'succeeded':'uncertain',code:verified?'AZURE_SNAPSHOT_VERIFIED':'AZURE_SNAPSHOT_SUBMITTED_RECONCILE',evidence_digest:hash({status:snap?.properties?.provisioningState})};
        }
      }
      if (!write) {inspected.set(task.id+':'+connector.id,hash(prior)); return {status:'succeeded',code:'LIVE_TAGS_INSPECTED',evidence_digest:hash(prior)};}
      const tags = step.arguments.tags;
      if (!tags || typeof tags !== 'object' || Array.isArray(tags) || !inspected.has(task.id+':'+connector.id) ||
          inspected.get(task.id+':'+connector.id) !== hash(prior)) return {status:'failed',code:'LIVE_STATE_CHANGED'};
      const result = await boundedRequest(url,{method:'PATCH',headers:{...headers,...(current.etag?{'If-Match':current.etag}:{})},
        body:JSON.stringify({operation:'Merge',properties:{tags}})},options.request);
      if (result.status !== 200) return {status:'uncertain',code:'TAG_UPDATE_REQUIRES_RECONCILIATION',http_status:result.status};
      const check = await boundedRequest(url,{headers},options.request);
      const observed = (check.body as {properties?:{tags?:Record<string,unknown>}} | null)?.properties?.tags;
      const verified = check.status===200 && observed && Object.entries(tags).every(([k,v])=>observed[k]===v);
      return {status:verified?'succeeded':'uncertain',code:verified?'TAGS_VERIFIED':'TAG_VERIFICATION_INCOMPLETE',http_status:check.status,evidence_digest:hash(observed||{})};
    } catch {
      return {status:write?'uncertain':'failed',code:write?'CONNECTOR_OUTCOME_UNCERTAIN':'CONNECTOR_READ_FAILED'};
    }
  };
}
