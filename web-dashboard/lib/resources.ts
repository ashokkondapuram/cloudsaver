'use client';
import {useCallback, useEffect, useState} from 'react';
import {api} from './api';
import {loadResourcePages,readBatchPage} from './resource-pages';
import type {Finding} from './types';

export type PillarStatus = 'observed' | 'risk' | 'unknown';
export type AIStatus = 'not_run' | 'queued' | 'running' | 'completed' | 'stale' | 'failed';
export type DecisionKind = 'accept' | 'dismiss' | 'defer';
export type Action = {title: string; rationale: string; kind: string; pillar: string; effort: string; change_risk: string; confidence: string; evidence_codes: string[]; prerequisites: string[]};
export type Decision = {id: string; decision: DecisionKind; note: string; defer_until: string | null; evidence_digest: string; created_at: string; scan_id: string; evidence_changed?: boolean};
export type AIState = {status: AIStatus; risk_level: string | null; summary: string | null; actions: Action[]; assessment_id: string | null; created_at: string | null; reason: string | null};
export type ResourceRow = {
  resource_key: string; provider: string; resource_id: string; resource_name: string; resource_type: string; resource_group: string; scope_id: string;
  service_category: string; finding_count: number; rule_ids: string[]; review_priority: string; disposition: string; protected_reasons: string[];
  risk_level: string; risk_check_codes: string[]; evidence_gap_codes: string[]; evidence_coverage: {observed: number; total: number};
  billed_cost_usd?:number|null;effective_cost_usd?:number|null;commitment_locked?:boolean;lifecycle_delta?:'new'|'persisting'|'regressed';
  retail_estimate_usd: number | null; evidence_digest: string; pillars: Record<string, PillarStatus>; ai: AIState; decision: Decision | null;
};
export type Summary = {total: number; ai_status: Record<string, number>; ai_risk: Record<string, number>; decision: Record<string, number>; review_priority: Record<string, number>;resolved_count?:number|null;no_longer_observed_count?:number|null};
export type ResourcePage = {scan_id: string; observed_at: string; summary: Summary;commitment_baseline?:{status:string;clean_steady_state_hr:string|null;recommended_new_commitment_hr:string|null;warning:string}; total: number; items: ResourceRow[]};
export type Check = {pillar: string; code: string; status: PillarStatus; explanation: string; evidence_fields: string[]};
export type ResourceAssessment = Omit<ResourceRow, 'pillars' | 'ai' | 'decision'> & {
  pillars: {pillar: string; status: PillarStatus; checks: Check[]}[]; guardrails: string[]; policy_version: string;
  observation: {status: string; observed_at: string | null; max_age_hours: number};
};
export type Followup = {id: string; question: string; created_at: string; answer: {answer: string; evidence_codes: string[]; limitations: string[]}};
export type AIResult = {model: string; target_id: string; warning: string; cached?: boolean; usage?: {input_tokens: number | null; output_tokens: number | null};
  confidence_band?: string;
  advice: {summary: string; risk_level: string; pillars: {pillar: string; observation: string; evidence_codes: string[]}[]; review_questions: string[]; recommended_actions?: Action[];}};
export type ResourceDetail = {scan_id: string; assessment: ResourceAssessment; findings: Finding[]; ai_context: Record<string, unknown>; ai: AIState;
  ai_result: AIResult | null; decision: Decision | null; followups: Followup[]; followups_remaining: number;
  observation?: {evidence?:{metrics?:Record<string,{window_start?:string;window_end?:string;points?:{at:string;value:number}[];sufficient?:boolean;p95?:number;p99?:number;coverage_ratio?:number}>;metric_summaries?:Record<string,{sufficient?:boolean;p95?:number;p99?:number;coverage_ratio?:number}>};observed_at?: string; collector_version?: string; evidence_schema_version?: string; configuration_snapshot?: Record<string, unknown>;
    dependency_refs?: {relationship: string; from_resource_id: string; to_resource_id: string; verification_state: string; observed_at: string | null}[]};
  rule_evaluations?: {rule_id: string; rule_version: string; outcome: string; reason: string; destructive_actions_blocked?: boolean}[];
  costs?: {billed_cost_usd: number | null;effective_cost_usd?:number|null; retail_estimate_usd: number | null; modeled_future_cost_usd: number | null; opportunity_usd: number | null; verified_realized_savings_usd: number | null; explanation: string; currency?: string};
  financial_overlaps?: {resource_id: string; resource_name?: string; rule_id: string}[];
  observability?: ObservedSignals | null};
export type ObservedMetric = {connector: string; query_id: string; metric: string; unit: string; window_start: string | null; window_end: string | null;
  samples: number; coverage_pct: number; p50: number; p95: number; max: number; avg: number};
export type ObservedService = {connector: string; service: string; requests_per_second: number | null; error_rate_pct: number | null;
  latency_p50_ms: number | null; latency_p95_ms: number | null; coverage_pct: number | null; sampled: boolean; traces_sampled?: number;
  window_start: string | null; window_end: string | null; dependencies: {service: string; calls: number}[]};
export type ObservedSignals = {metrics: ObservedMetric[]; services: ObservedService[]; latency_reasons: string[];
  cost_per_1000_requests_usd: number | null; cost_per_1000_requests_reason: string | null};
export type Batch = {id: string; scan_id: string; target_id: string; status: 'queued' | 'running' | 'waiting_for_budget' | 'completed' | 'cancelled';
  total: number; resume_after: string | null; created_at: string; updated_at: string; counts: Record<string, number>};
export type HistoryEntry = {scan_id: string; timestamp: string; present: boolean; review_priority?: string; risk_level?: string; rule_ids?: string[];
  pillars?: Record<string, PillarStatus>; retail_estimate_usd?: number | null; changes: string[]};
export type ResourceHistory = {scans: HistoryEntry[]; ai_results: {assessment_id: string; scan_id: string; created_at: string; risk_level: string; model: string}[]; decisions: Decision[]};
export type Targets = {enabled: boolean; hourly_attempt_limit: number; routing_mode?: string; platform_policy_version?: number; configuration_reason?: string;
  usage?: {attempts_current_hour: number};
  targets: {target_id: string; provider: string; model: string; destination_region?: string | null; max_input_tokens?: number; max_output_tokens?: number; allowed_source_providers?: string[]}[]};

export const PILLARS = ['cost', 'reliability', 'performance', 'security', 'operations'] as const;
export const ACTIVE_BATCH = ['queued', 'running', 'waiting_for_budget'];
export const label = (value: string) => value.replaceAll('_', ' ').toLowerCase();
export const sentence = (value: string) => {const text = label(value); return text.charAt(0).toUpperCase() + text.slice(1);};
export const aiStatusLabels: Record<AIStatus, string> = {not_run: 'Not run', queued: 'Queued', running: 'Running', completed: 'Completed', stale: 'Stale', failed: 'Failed'};
export const decisionLabels: Record<DecisionKind, string> = {accept: 'Accepted', dismiss: 'Dismissed', defer: 'Deferred'};

/** Same identity the API uses: provider plus resource ID, with Azure IDs case-insensitive. */
export function identityOf(provider: string, resourceId: string) {
  return `${provider}|${provider === 'azure' ? resourceId.toLowerCase() : resourceId}`;
}
export function findingIdentity(finding: Finding) {
  return identityOf(finding.cloud_provider || 'azure', finding.resource_id);
}
export async function resourceKeyOf(finding: Finding) {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(findingIdentity(finding)));
  return [...new Uint8Array(digest)].map(byte => byte.toString(16).padStart(2, '0')).join('');
}

export function useResources(scanId: string | undefined, token: string, enabled = true) {
  const [state, setState] = useState<{key:string;page:ResourcePage|null;error:string}>({key:'',page:null,error:''});
  const [version, setVersion] = useState(0);
  const key=JSON.stringify([scanId,token,enabled,version]);
  const reload = useCallback(() => setVersion(value => value + 1), []);
  useEffect(() => {
    const request = new AbortController();
    setState({key,page:null,error:''});
    if (scanId && enabled) loadResourcePages((path,options)=>api(path,token,options),scanId,request.signal)
      .then(page=>{if(!request.signal.aborted)setState({key,page,error:''});})
      .catch(cause=>{if(!request.signal.aborted)setState({key,page:null,error:cause instanceof Error?cause.message:'Resource evidence could not be loaded.'});});
    return () => request.abort();
  }, [scanId,token,enabled,version,key]);
  return {page:state.key===key?state.page:null,error:state.key===key?state.error:'',reload};
}

export function useActiveBatch(scanId: string | undefined, token: string, onSettled: () => void) {
  const [state, setState] = useState<{key:string;batch:Batch|null;error:string;loading:boolean}>({key:'',batch:null,error:'',loading:true}), [version, setVersion] = useState(0);
  const key=JSON.stringify([scanId,token,version]);
  const refresh = useCallback(() => setVersion(value => value + 1), []);
  useEffect(() => {
    if (!scanId) return;
    const request = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    let previous: string | null = null;
    const poll = () => api<{items: Batch[]}>(`/ai-batches?scan_id=${scanId}&limit=1`, token, {signal: request.signal}).then(result => {
      if (request.signal.aborted) return;
      const latest = readBatchPage(result,scanId);
      setState({key,batch:latest,error:'',loading:false});
      const progress = latest ? JSON.stringify([latest.status, latest.counts]) : null;
      if (previous !== null && progress !== previous) onSettled();
      previous = progress;
      if (latest && ACTIVE_BATCH.includes(latest.status)) timer = setTimeout(poll, latest.status === 'waiting_for_budget' ? 60000 : 5000);
    }).catch(() => {if (!request.signal.aborted){setState(current=>({key,batch:current.key===key?current.batch:null,error:'AI assessment status is unavailable. Existing work may still be running; check status before starting another assessment.',loading:false}));timer=setTimeout(poll,30000);}});
    poll();
    return () => {request.abort(); if (timer) clearTimeout(timer);};
  }, [scanId, token, version, onSettled]);
  return {batch:state.key===key?state.batch:null,error:state.key===key?state.error:'',loading:state.key===key?state.loading:true,refresh};
}
