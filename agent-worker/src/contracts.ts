export type Connector = {
  id: string; tenant_id: string; provider: string; scope_id: string;
  kind: 'azure_arm' | 'aws_sdk' | 'gcp_rest' | 'k8s_api' | 'http_json'; operations: string[]; endpoint: string | null; token_env: string | null;
  region?: string | null; role_arn?: string | null; service_account?: string | null;
};
export type Step = {connector_id: string; operation: 'resource.inspect' | 'workload.inspect' | 'tags.merge' | 'labels.merge' | 'annotations.merge' | 'snapshot.create' | 'ebs.snapshot.create' | 'disk.snapshot.create' | 'action.submit';
  arguments: Record<string, unknown>; purpose: string; verification: string; rollback: string};
export type Plan = {summary: string; steps: Step[]};
export type Outcome = {status: 'succeeded' | 'failed' | 'uncertain'; code: string; http_status?: number; evidence_digest?: string};
export type Task = {id: string; tenant_id: string; provider: string; scope_id: string; resource_id: string; state: string;
  payload: {plan: Plan; plan_hash: string; connector_ids: string[];
    approval: {plan_hash: string; expires_at: string} | null}};
export type Assignment = {task: Task; phase: 'draft' | 'execute'; lease_token: string; code: string | null; connectors: Connector[]};

export function loadConnectors(raw: string): Connector[] {
  const values: unknown = JSON.parse(raw);
  if (!Array.isArray(values) || values.length>100) throw new Error('Invalid connector catalog');
  const result = values.map((value) => {
    if (!value || typeof value!=='object' || Object.keys(value).some(k=>!['id','tenant_id','provider','scope_id','kind','operations','endpoint','token_env','region','role_arn','service_account'].includes(k))) throw new Error('Invalid connector fields');
    const c = {...value,endpoint:value.endpoint??null,token_env:value.token_env??null,region:value.region??null,role_arn:value.role_arn??null,service_account:value.service_account??null} as Connector;
    if (!/^[a-z][a-z0-9-]{0,59}$/.test(c.id) || !/^[a-f0-9-]{36}$/i.test(c.tenant_id) || !c.scope_id ||
        !['azure','aws','gcp','kubernetes'].includes(c.provider) || !['azure_arm','aws_sdk','gcp_rest','k8s_api','http_json'].includes(c.kind) ||
        !Array.isArray(c.operations) || !c.operations.length || c.operations.some(o=>typeof o!=='string')) throw new Error('Invalid connector grant');
    return c;
  });
  if (new Set(result.map(c=>c.id)).size!==result.length) throw new Error('Duplicate connector IDs');
  return result;
}

export const readOperations=new Set(['resource.inspect','workload.inspect']);
export const allowedOperations:Record<Connector['kind'],string[]>={azure_arm:['resource.inspect','tags.merge','snapshot.create'],aws_sdk:['resource.inspect','tags.merge','ebs.snapshot.create'],
  gcp_rest:['resource.inspect','labels.merge','disk.snapshot.create'],k8s_api:['workload.inspect','annotations.merge'],http_json:[]};
export function validateStepData(step:Step,c:Connector):void {
  if(!allowedOperations[c.kind]?.includes(step.operation))throw new Error('Unsupported connector operation');
  const args=step.arguments;
  if(!args||typeof args!=='object'||Array.isArray(args))throw new Error('Invalid action arguments');
  const encoded=JSON.stringify(args);
  if(/(?:password|secret|client[_-]?secret|api[_-]?key|access[_-]?token|refresh[_-]?token|authorization|connection[_-]?string)"\s*:/i.test(encoded)||
      /-----BEGIN [A-Z ]*PRIVATE KEY-----|\bbearer\s+\S{8,}|\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.|(?:AccountKey|SharedAccessSignature|client_secret|api[_ -]?key|password)\s*[:=]\s*\S+|[?&]sig=[A-Za-z0-9%+/=]{8,}|\bsk-[A-Za-z0-9_-]{16,}/i.test(encoded))throw new Error('Sensitive action data');
  if(readOperations.has(step.operation)){
    if(Object.keys(args).some(k=>k!=='expected_state'))throw new Error('Only expected state is accepted');
    const bounds:Record<string,Record<string,string>>={azure_arm:{diskState:'string',powerState:'string',numberOfSites:'number'},aws_sdk:{State:'string',DBInstanceStatus:'string'},gcp_rest:{status:'string',state:'string'},k8s_api:{generation:'number',replicas:'number'}};
    const expected=args.expected_state??{};
    if(!expected||typeof expected!=='object'||Array.isArray(expected)||Object.keys(expected).length>3)throw new Error('Invalid expected state');
    for(const [key,value] of Object.entries(expected)){
      if(!bounds[c.kind]?.[key]||typeof value!==bounds[c.kind][key]||typeof value==='number'&&(!Number.isInteger(value)||value<0||value>1000000)||typeof value==='string'&&!/^[A-Za-z0-9/_-]{1,80}$/.test(value))throw new Error('Invalid expected state');
    }
    return;
  }
  if(step.operation.endsWith('snapshot.create')){
    if(Object.keys(args).sort().join(',')!=='retention_days,snapshot_name_prefix'||typeof args.snapshot_name_prefix!=='string'||!/^[a-z][a-z0-9-]{0,39}$/.test(args.snapshot_name_prefix)||!Number.isInteger(args.retention_days)||Number(args.retention_days)<7||Number(args.retention_days)>90)throw new Error('Invalid safety snapshot');
    return;
  }
  const field=step.operation.split('.')[0];const values=args[field];
  if(Object.keys(args).length!==1||!values||typeof values!=='object'||Array.isArray(values)||Object.keys(values).length<1||Object.keys(values).length>10)throw new Error('Explicit bounded metadata required');
  for(const [key,val] of Object.entries(values)){
    if(!/^[A-Za-z0-9._:/-]{1,64}$/.test(key)||/^(hidden|microsoft|azure|aws:)/i.test(key)||typeof val!=='string'||val.length<1||val.length>128||/[\x00-\x1f]/.test(val))throw new Error('Invalid metadata');
    if(field==='labels'&&(!/^[a-z][a-z0-9_-]{0,62}$/.test(key)||!/^[a-z0-9_-]{0,63}$/.test(val)))throw new Error('Invalid Google label');
    if(field==='annotations'&&!/^cloudsaver\.io\/recommended-[A-Za-z0-9_.-]{1,38}$/.test(key))throw new Error('Invalid recommendation annotation');
  }
}

export function canonical(value: unknown): string {
  if (value === null || typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) return '[' + value.map(canonical).join(',') + ']';
  return '{' + Object.keys(value).sort().map(k => JSON.stringify(k) + ':' + canonical((value as Record<string, unknown>)[k])).join(',') + '}';
}

export function renderCode(plan: Plan): string {
  return ['type AgentContext = { call(index: number): Promise<unknown> };',
    'export async function run(ctx: AgentContext): Promise<unknown[]> {', '  const results: unknown[] = [];',
    ...plan.steps.map((_,i) => `  results.push(await ctx.call(${i}));`), '  return results;', '}', ''].join('\n');
}

export function checkAssignment(a: Assignment, local: Connector[]): void {
  const t = a.task;
  if (a.phase !== 'execute' || t.state !== 'running' || !t.payload.approval ||
      !/^[a-f0-9]{64}$/.test(t.payload.plan_hash) || t.payload.approval.plan_hash !== t.payload.plan_hash ||
      Date.parse(t.payload.approval.expires_at) <= Date.now() || !Number.isFinite(Date.parse(t.payload.approval.expires_at))) {
    throw new Error('Execution requires an unexpired approval');
  }
  if (!Array.isArray(t.payload.plan?.steps) || t.payload.plan.steps.length < 1 || t.payload.plan.steps.length > 8 || a.code !== renderCode(t.payload.plan)) {
    throw new Error('The runCode artifact does not match the reviewed connector program');
  }
  let writes=0;const inspected=new Set<string>();
  for (const step of t.payload.plan.steps) {
    const remote = a.connectors.find(c => c.id === step.connector_id);
    const own = local.find(c => c.id === step.connector_id);
    if (!remote || !own || canonical(remote) !== canonical(own) || own.tenant_id !== t.tenant_id ||
        own.provider !== t.provider || own.scope_id !== t.scope_id || !own.operations.includes(step.operation)) {
      throw new Error('Connector is outside the worker deployment grant');
    }
    validateStepData(step,own);
    if(readOperations.has(step.operation))inspected.add(own.id);
    else if(!inspected.has(own.id)||++writes>1)throw new Error('Each single write requires prior inspection');
  }
}


export function stateMatches(step:Step,live:Record<string,unknown>):boolean {
  const expected=(step.arguments.expected_state??{}) as Record<string,unknown>;
  return Object.entries(expected).every(([key,value])=>live[key]===value);
}
