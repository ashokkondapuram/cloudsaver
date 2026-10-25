/** Pure projections of already authorized resource assessments and current ownership. */
export const PILLARS = ['cost', 'reliability', 'performance', 'security', 'operations'];
export const MAX_RESOURCES = 10000;
const normalize = (provider, value) => provider === 'azure' ? value.toLowerCase() : value;
export function resourceIdentity(item) {
  if (!item || typeof item.provider !== 'string' || typeof item.scope_id !== 'string' || typeof item.resource_id !== 'string' || !item.scope_id || !item.resource_id) throw new Error('Incomplete resource identity. Refresh the saved assessment.');
  return JSON.stringify([item.provider, normalize(item.provider, item.scope_id), normalize(item.provider, item.resource_id)]);
}
export function remediationPreview(item) {
  const actions = [];
  const rules = (item.rule_ids || []).join(' ').toUpperCase();
  if (item.provider === 'azure' && item.resource_type.toLowerCase() === 'microsoft.compute/virtualmachines' && /UNDERUTIL|RIGHTSIZ|OVERSIZ|LOW_CPU/.test(rules)) actions.push({
    id:'vm-rightsizing-review-v1', title:'Review VM rightsizing',
    prerequisites:['Fresh representative CPU, memory, disk and network history','Application peaks, service objectives and recovery headroom','Compatible target SKU, actual rates, licensing and commitment effects'],
    steps:['Confirm ownership and required capacity','Compare compatible target SKUs against peak demand','Review interruption and recovery feasibility','Submit an exact change through existing approval workflows'],
    verification:['Validate latency, errors, utilization and capacity limits','Reconcile subsequent billing independently'],
    recovery:'Check original SKU availability and recovery procedures; rollback is not guaranteed.'
  });
  if ((item.risk_check_codes || []).some(code => /NETWORK|PUBLIC_ACCESS|EXPOSURE|INBOUND|SSH|RDP/.test(code.toUpperCase()))) actions.push({
    id:'network-access-review-v1', title:'Review network access',
    prerequisites:['Current access configuration and confirmed required traffic','Approved management path and lockout recovery','Applicable exceptions and compensating controls'],
    steps:['Confirm the exact affected access path','Identify required sources, destinations, ports and dependencies','Prepare the smallest reviewed change','Obtain approval before deployment'],
    verification:['Test required application and administrator access','Verify unapproved access is denied','Refresh security evidence'],
    recovery:'Prepare a separately approved recovery path before changing access.'
  });
  return {status:actions.length ? 'review_only' : 'unsupported_template', actions:actions.map(action=>({...action,executable:false,approval_granted:false,target_sku:null})), automatic_execution:false, protected_reasons:[...(item.protected_reasons || [])]};
}
export function groupWorkloads(resources, mappings) {
  if (!Array.isArray(resources) || !Array.isArray(mappings) || resources.length > MAX_RESOURCES || mappings.length > MAX_RESOURCES) throw new Error('The workload pilot supports at most 10000 resources and ownership mappings.');
  const latest = new Map(), ambiguous = new Set(), visible = new Map();
  for (const row of resources) {
    const identity = resourceIdentity(row);
    if (visible.has(identity)) throw new Error('Duplicate resource identity. Refresh the assessment; no partial rollup was returned.');
    if (typeof row.resource_type !== 'string' || !row.pillars || !Array.isArray(row.rule_ids)) throw new Error('Incomplete resource assessment.');
    visible.set(identity, row);
  }
  for (const mapping of mappings) {
    const identity = resourceIdentity(mapping);
    if (!visible.has(identity)) continue;
    if (typeof mapping.application !== 'string' || !mapping.application || typeof mapping.environment !== 'string' || !mapping.environment || !Number.isSafeInteger(mapping.version) || mapping.version < 1) throw new Error('Incomplete ownership mapping.');
    const previous = latest.get(identity);
    if (!previous || mapping.version > previous.version) {latest.set(identity,mapping);ambiguous.delete(identity);}
    else if (mapping.version === previous.version && ['application','environment','owner','team'].some(field=>mapping[field] !== previous[field])) ambiguous.add(identity);
  }
  const grouped = new Map();
  let unassigned = 0, ambiguousCount = 0;
  for (const [identity,resource] of visible) {
    const owner = latest.get(identity);
    if (!owner || ambiguous.has(identity)) {unassigned++;if(ambiguous.has(identity))ambiguousCount++;continue;}
    const id = JSON.stringify([owner.application,owner.environment]);
    if (!grouped.has(id)) grouped.set(id,{id,application:owner.application,environment:owner.environment,members:[]});
    grouped.get(id).members.push({identity,resource_key:resource.resource_key,resource_id:resource.resource_id,resource_name:resource.resource_name || resource.resource_id,resource_type:resource.resource_type,provider:resource.provider,scope_id:resource.scope_id,owner:owner.owner || '',team:owner.team || '',pillars:{...resource.pillars},evidence_gap_codes:[...(resource.evidence_gap_codes || [])],preview:remediationPreview(resource)});
  }
  const workloads = [...grouped.values()].map(workload=>{
    workload.members.sort((a,b)=>a.identity.localeCompare(b.identity));
    return {...workload,pillars:PILLARS.map(pillar=>{
      const counts={risk:0,unknown:0,observed:0};
      for(const member of workload.members){const status=member.pillars[pillar];counts[status==='risk'||status==='observed'?status:'unknown']++;}
      return {pillar,counts};
    }),automatic_execution:false,verified_savings:null,dependency_coverage:'unknown'};
  }).sort((a,b)=>a.application.localeCompare(b.application)||a.environment.localeCompare(b.environment));
  return {workloads,unassigned,ambiguous:ambiguousCount,total:visible.size,membership_basis:'current_explicit_mapping_not_historical_membership',automatic_execution:false};
}
/** Fetch every bounded page through existing authorized APIs. Never use a partial rollup. */
export async function loadWorkloadInputs(request, scanId, signal) {
  const ownership = await request('/outcomes/ownership',{signal});
  if (!Array.isArray(ownership.items) || ownership.items.length > MAX_RESOURCES) throw new Error('Ownership data is incomplete or exceeds the pilot limit.');
  const rows=[];let expected=null;let observedAt=null;
  for(let offset=0;offset<MAX_RESOURCES;){
    if(signal?.aborted) throw new Error('Workload loading cancelled.');
    const page=await request(`/scans/${encodeURIComponent(scanId)}/resources?limit=1000&offset=${offset}`,{signal});
    if(page.scan_id!==scanId || !Number.isSafeInteger(page.total) || page.total<0 || page.total>MAX_RESOURCES || !Array.isArray(page.items) || page.items.length>1000) throw new Error('Resource data is incomplete or exceeds the pilot limit.');
    if(expected!==null && (page.total!==expected || page.observed_at!==observedAt)) throw new Error('Assessment changed during pagination. Refresh before reviewing workloads.');
    expected=page.total;observedAt=page.observed_at;
    if(rows.length+page.items.length>expected || (!page.items.length && rows.length<expected)) throw new Error('Incomplete resource pagination; no partial rollup was returned.');
    rows.push(...page.items);offset+=page.items.length;
    if(rows.length===expected) return {projection:groupWorkloads(rows,ownership.items),observed_at:observedAt};
  }
  throw new Error('Resource pagination exceeds the pilot limit.');
}
