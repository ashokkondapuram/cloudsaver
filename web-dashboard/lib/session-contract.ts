import type {Workspace,Scan,Entitlements} from './types';
const record=(value:unknown):value is Record<string,unknown>=>value!==null&&typeof value==='object'&&!Array.isArray(value);
const strings=(value:unknown)=>Array.isArray(value)&&value.every(v=>typeof v==='string');
const money=(value:unknown)=>value===null||(typeof value==='number'&&Number.isFinite(value));
const uuid=(value:unknown)=>typeof value==='string'&&/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i.test(value);
const failure=()=>new Error('Workspace evidence is incomplete or inconsistent. Refresh or reconnect before continuing.');

export function validateProfile(workspace:unknown,plan:unknown):asserts workspace is Workspace {
  if(!record(workspace)||!uuid(workspace.tenant_id)||typeof workspace.name!=='string'||!workspace.name.trim()||!strings(workspace.roles)||!strings(workspace.subscription_ids)||!record(plan)||plan.tenant_id!==workspace.tenant_id||typeof plan.plan_name!=='string'||!strings(plan.allowed_providers)||!strings(plan.allowed_scan_frequencies)||typeof plan.can_export_terraform!=='boolean')throw failure();
}

export function validateScan(value:unknown):asserts value is Scan {
  if(!record(value)||!uuid(value.scan_id)||typeof value.timestamp!=='string'||typeof value.status!=='string'||!Number.isSafeInteger(value.total_items_found)||Number(value.total_items_found)<0||!money(value.total_monthly_waste_usd)||!Array.isArray(value.findings))throw failure();
  if(value.cloud_providers!==undefined&&!strings(value.cloud_providers))throw failure();
  for(const finding of value.findings){
    if(!record(finding)||!['resource_id','resource_name','resource_type','resource_group','subscription_id','rule_id','severity','details'].every(key=>typeof finding[key]==='string')||!money(finding.estimated_monthly_waste_usd))throw failure();
  }
}

export function validateWorkspaceEvidence(workspace:Workspace,history:Scan[],plan:Entitlements){
  validateProfile(workspace,plan);
  if(!Array.isArray(history))throw failure();
  const ids=new Set<string>();for(const scan of history){validateScan(scan);if(ids.has(scan.scan_id))throw failure();ids.add(scan.scan_id);}
}
