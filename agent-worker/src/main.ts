import {connectorExecutor} from './connectors.ts';
import {boundedRequest} from './http.ts';
import {runCode} from './runtime.ts';
import {loadConnectors} from './contracts.ts';
import type {Assignment, Connector} from './contracts.ts';

const base = new URL(process.env.CLOUDSAVER_AGENT_GATEWAY_URL || 'http://agent-gateway:8006');
if (!['http:','https:'].includes(base.protocol) || base.username || base.password || base.search || base.hash || base.pathname!=='/') throw new Error('Invalid gateway origin');
if (process.env.CLOUDSAVER_ENVIRONMENT==='production' && base.protocol!=='https:') throw new Error('Production workers require TLS to the agent gateway');
const secret = process.env.CLOUDSAVER_AGENT_WORKER_TOKEN;
if (!secret || secret.length<32) throw new Error('An agent worker credential is required');
const tenants: string[] = JSON.parse(process.env.CLOUDSAVER_AGENT_TENANT_IDS || '[]');
const local: Connector[] = loadConnectors(process.env.CLOUDSAVER_AGENT_CONNECTORS || '[]');
if (!Array.isArray(tenants) || !tenants.length || tenants.length>100 || tenants.some(t=>!/^[a-fA-F0-9-]{36}$/.test(t))) throw new Error('Explicit tenant assignments are required');
if (!Array.isArray(local) || local.length>100) throw new Error('Invalid local connector grant');
const gateway = async (path: string, body: unknown) => {
  const r = await boundedRequest(base.origin+path,{method:'POST',headers:{Authorization:'Bearer '+secret,'Content-Type':'application/json'},body:JSON.stringify(body)});
  if (r.status!==200) throw new Error('Agent gateway refused the operation');
  return r.body;
};
let stop = false;
process.on('SIGTERM',()=>{stop=true;}); process.on('SIGINT',()=>{stop=true;});
console.log(JSON.stringify({event:'agent_worker_started',runtime:'typescript-runCode',tenants:tenants.length}));
while (!stop) {
  for (const tenant_id of tenants) {
    if (stop) break;
    try {
      const response = await gateway('/internal/v1/agent/claim',{tenant_id}) as {assignment:Assignment|null};
      if (!response.assignment) continue;
      const a = response.assignment;
      if (a.task.tenant_id!==tenant_id || !/^[a-f0-9-]{36}$/i.test(a.task.id)) throw new Error('Invalid assignment identity');
      const prefix = '/internal/v1/agent/tasks/'+a.task.id;
      const lease = {tenant_id,lease_token:a.lease_token};
      let heartbeatFailed = false;
      const timer = setInterval(()=>{gateway(prefix+'/heartbeat',lease).catch(()=>{heartbeatFailed=true;});},20_000);
      try {
        if (a.phase==='draft') await gateway(prefix+'/draft',lease);
        else if (a.phase==='execute') await runCode(a,local,(path,body)=>{
          if (path.endsWith('/start') && (heartbeatFailed || stop)) throw new Error('Worker is stopping or its lease heartbeat failed');
          return gateway(path,body);
        },connectorExecutor());
        else throw new Error('Unsupported assignment phase');
        console.log(JSON.stringify({event:'assignment_finished',task_id:a.task.id,phase:a.phase}));
      } catch {
        // Never retry a provider call or echo raw model/provider errors. The durable journal fences uncertain work.
        await gateway(prefix+'/fail',lease).catch(()=>{});
        console.log(JSON.stringify({event:'assignment_stopped',task_id:a.task.id,automatic_retry:false}));
      } finally {clearInterval(timer);}
    } catch {console.log(JSON.stringify({event:'gateway_unavailable_or_assignment_refused'}));}
  }
  if (!stop) await new Promise(resolve=>setTimeout(resolve,3000));
}
