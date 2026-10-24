import {createHash} from 'node:crypto';
import {ManagedIdentityCredential, WorkloadIdentityCredential} from '@azure/identity';
import type {Connector, Outcome, Step, Task} from './contracts.ts';
import {canonical} from './contracts.ts';
import {boundedRequest, type Requester} from './http.ts';

const hash = (value: unknown) => createHash('sha256').update(canonical(value)).digest('hex');
type Token = () => Promise<string>;
export function azureToken(): Token {
  const credential = process.env.CLOUDSAVER_AGENT_AZURE_IDENTITY === 'workload_identity'
    ? new WorkloadIdentityCredential() : new ManagedIdentityCredential({clientId: process.env.AZURE_CLIENT_ID || undefined});
  return async () => (await credential.getToken('https://management.azure.com/.default'))!.token;
}

export function connectorExecutor(options: {token?: Token; request?: Requester; secrets?: NodeJS.ProcessEnv} = {}) {
  let token = options.token;
  const inspected = new Map<string,string>();
  return async (task: Task, connector: Connector, step: Step, index: number): Promise<Outcome> => {
    const write = step.operation !== 'resource.inspect';
    // No raw provider body, credential, tag value or exception is returned to the task journal.
    try {
      const encoded=JSON.stringify(step.arguments);
      if (/\b(?:password|client[_-]?secret|api[_-]?key|access[_-]?token|authorization)\b\s*"?\s*:/i.test(encoded) ||
          /-----BEGIN [A-Z ]*PRIVATE KEY-----|\bbearer\s+\S{8,}|\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.|(?:AccountKey|SharedAccessSignature|client_secret|api[_ -]?key|password)\s*[:=]\s*\S+|[?&]sig=[A-Za-z0-9%+/=]{8,}/i.test(encoded)) return {status:'failed',code:'SENSITIVE_ACTION_DATA_PROHIBITED'};
      if (connector.tenant_id !== task.tenant_id || connector.provider !== task.provider || connector.scope_id !== task.scope_id || !connector.operations.includes(step.operation)) {
        return {status:'failed',code:'CONNECTOR_GRANT_MISMATCH'};
      }
      if (connector.kind === 'http_json') return {status:'failed',code:'EXTERNAL_ACTION_DATA_PROHIBITED'};
      if (connector.provider !== 'azure' || !['resource.inspect','tags.merge'].includes(step.operation) ||
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
