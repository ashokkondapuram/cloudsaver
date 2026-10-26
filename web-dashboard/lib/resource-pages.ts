import type {ResourcePage, ResourceRow, Batch} from './resources';

export const RESOURCE_PAGE_SIZE = 1000;
export const MAX_RESOURCE_ROWS = 10000;
const invalid = () => new Error('Resource evidence is incomplete or changed during loading. Refresh the workspace before reviewing resources.');
const object = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === 'object' && !Array.isArray(value);
const strings = (value: unknown) => Array.isArray(value) && value.every(item => typeof item === 'string');
const counts = (value: unknown) => object(value) && Object.values(value).every(n => Number.isSafeInteger(n) && Number(n) >= 0);
const nullableString = (value: unknown) => value === null || typeof value === 'string';
const finiteMoney = (value: unknown) => value === undefined || value === null || (typeof value === 'number' && Number.isFinite(value));
const pillars = ['cost', 'reliability', 'performance', 'security', 'operations'];

function validRow(value: unknown): value is ResourceRow {
  if (!object(value) || !['resource_key','provider','scope_id','resource_id','resource_name','resource_type','resource_group','service_category','disposition','risk_level','evidence_digest'].every(key => typeof value[key] === 'string')) return false;
  if (!/^[a-f0-9]{64}$/.test(String(value.resource_key)) || !['azure','aws','gcp','kubernetes'].includes(String(value.provider)) || !['critical','high','evidence_required'].includes(String(value.review_priority))) return false;
  if (!Number.isSafeInteger(value.finding_count) || Number(value.finding_count) < 0 || !strings(value.rule_ids) || !strings(value.protected_reasons) || !strings(value.risk_check_codes) || !strings(value.evidence_gap_codes)) return false;
  if (!object(value.pillars) || !pillars.every(p => ['observed','risk','unknown'].includes(String((value.pillars as Record<string,unknown>)[p])))) return false;
  const coverage=value.evidence_coverage, ai=value.ai, decision=value.decision;
  if (!object(coverage) || !Number.isSafeInteger(coverage.observed) || !Number.isSafeInteger(coverage.total) || Number(coverage.observed)<0 || Number(coverage.total)<Number(coverage.observed)) return false;
  if (!object(ai) || !['not_run','queued','running','completed','stale','failed'].includes(String(ai.status)) || !nullableString(ai.risk_level) || !nullableString(ai.summary) || !Array.isArray(ai.actions)) return false;
  if (decision !== null && (!object(decision) || !['accept','dismiss','defer','none'].includes(String(decision.decision)) || typeof decision.created_at !== 'string')) return false;
  if(value.retail_estimate_usd===undefined||!/^[a-f0-9]{64}$/.test(String(value.evidence_digest)))return false;
  return ['billed_cost_usd','effective_cost_usd','retail_estimate_usd'].every(key => finiteMoney(value[key]));
}

/** Assemble one authorized immutable inventory; never return a partial or duplicate rollup. */
export async function loadResourcePages(request: (path: string, options: {signal?: AbortSignal}) => Promise<unknown>, scanId: string, signal?: AbortSignal): Promise<ResourcePage> {
  let first: ResourcePage | null = null;
  const items: ResourceRow[] = [], seen = new Set<string>();
  for (let offset=0; offset<MAX_RESOURCE_ROWS;) {
    signal?.throwIfAborted();
    const raw=await request(`/scans/${encodeURIComponent(scanId)}/resources?limit=${RESOURCE_PAGE_SIZE}&offset=${offset}`, {signal});
    signal?.throwIfAborted();
    if(object(raw)&&Number.isSafeInteger(raw.total)&&Number(raw.total)>MAX_RESOURCE_ROWS)throw new Error('Resource evidence is incomplete: the explorer supports up to 10,000 resources per scan. Select smaller scan scopes before reviewing this estate.');
    if (!object(raw) || raw.scan_id!==scanId || typeof raw.observed_at!=='string' || !Number.isSafeInteger(raw.total) || Number(raw.total)<0 || Number(raw.total)>MAX_RESOURCE_ROWS || !Array.isArray(raw.items) || raw.items.length>RESOURCE_PAGE_SIZE || !raw.items.every(validRow)) throw invalid();
    const summary=raw.summary;
    if (!object(summary) || summary.total!==raw.total || !['ai_status','ai_risk','decision','review_priority'].every(key=>counts(summary[key]))) throw invalid();
    const page=raw as unknown as ResourcePage;
    if (first && (first.total!==page.total || first.observed_at!==page.observed_at)) throw invalid();
    first ??= page;
    if (offset+page.items.length>page.total || (!page.items.length && offset<page.total)) throw invalid();
    for (const row of page.items) {
      if (seen.has(row.resource_key)) throw invalid();
      seen.add(row.resource_key); items.push(row);
    }
    offset=items.length;
    if (offset===page.total) return {...first,items};
  }
  throw invalid();
}

/** A missing progress counter must not become zero, NaN or permission to queue duplicate work. */
export function readBatchPage(raw:unknown,scanId:string):Batch|null {
  if(!object(raw)||!Array.isArray(raw.items)||raw.items.length>1)throw new Error('AI assessment status is unavailable.');
  if(!raw.items.length)return null;
  const batch=raw.items[0];
  if(!object(batch)||typeof batch.id!=='string'||!batch.id||batch.scan_id!==scanId||!['queued','running','waiting_for_budget','completed','cancelled'].includes(String(batch.status))||!Number.isSafeInteger(batch.total)||Number(batch.total)<1||Number(batch.total)>500||!object(batch.counts))throw new Error('AI assessment status is unavailable.');
  const values=['queued','running','completed','failed','skipped','uncertain','cancelled'].map(key=>(batch.counts as Record<string,unknown>)[key]);
  if(!values.every(n=>Number.isSafeInteger(n)&&Number(n)>=0)||values.reduce<number>((total,n)=>total+Number(n),0)!==batch.total)throw new Error('AI assessment status is unavailable.');
  return batch as unknown as Batch;
}
