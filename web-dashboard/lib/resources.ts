'use client';
import {useCallback, useEffect, useMemo, useState, useSyncExternalStore} from 'react';
import {api} from './api';
import {loadResourcePages, readBatchPage, RUNNING_RESOURCE_PAGE_SIZE, type ResourceLoadProgress} from './resource-pages';
import {lookupResourceSignals} from './resource-signals';
import type {ArmDetailStatus} from './arm-detail';
export type {ArmDetailStatus} from './arm-detail';
export {ARM_DETAIL_STATUSES, armDetailFromQuery, armDetailLabels} from './arm-detail';
import type {Finding, Scan} from './types';

/** Live inventory from a real scan, including in-progress snapshots. */
export function isLiveSnapshot(scan: Scan | undefined): boolean {
  return !!scan && scan.data_origin !== 'legacy_synthetic' && (scan.status === 'completed' || scan.status === 'running');
}

export type PillarStatus = 'observed' | 'risk' | 'unknown';
export type AIStatus = 'not_run' | 'queued' | 'running' | 'completed' | 'stale' | 'failed';
export type DecisionKind = 'accept' | 'dismiss' | 'defer';
export type Action = {title: string; rationale: string; kind: string; pillar: string; category?: string; effort: string; change_risk: string; confidence: string; evidence_codes: string[]; prerequisites: string[]};
export type Decision = {id: string; decision: DecisionKind; note: string; defer_until: string | null; evidence_digest: string; created_at: string; scan_id: string; evidence_changed?: boolean};
export type AIState = {status: AIStatus; risk_level: string | null; summary: string | null; actions: Action[]; assessment_id: string | null; created_at: string | null; reason: string | null};
export type ResourceRow = {
  resource_key: string; provider: string; resource_id: string; resource_name: string; resource_type: string; resource_group: string; scope_id: string;
  service_category: string; finding_count: number; rule_ids: string[]; review_priority: string; disposition: string; protected_reasons: string[];
  risk_level: string; risk_check_codes: string[]; evidence_gap_codes: string[]; evidence_coverage: {observed: number; total: number};
  billed_cost_usd?:number|null;effective_cost_usd?:number|null;commitment_locked?:boolean;lifecycle_delta?:'new'|'persisting'|'regressed';
  retail_estimate_usd: number | null; evidence_digest: string; pillars: Record<string, PillarStatus>; ai: AIState; decision: Decision | null;
  arm_detail?: ArmDetailStatus | null;
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
export type RuleMatchRow = {rule_id: string; display_channel: string; action_class: string; match_confidence: string; safety_blocks?: string[]; protected_reasons?: string[]; suppressed_reason?: string};
export type RuleMatches = {resource_id: string; cloud_provider: string; primary_match: RuleMatchRow | null; alternate_matches: RuleMatchRow[]; opportunity_group_id?: string | null; overlap_policy: string; strategy_version?: string};
export type RuleConflict = {kind: 'source_reconciliation' | 'finding_without_evaluation' | 'outcome_mismatch' | 'evaluation_without_finding'; severity: 'block' | 'review' | 'info'; rule_id: string | null; message: string};
export type ResourceDetail = {scan_id: string; assessment: ResourceAssessment; findings: Finding[]; ai_context: Record<string, unknown>; ai: AIState;
  ai_result: AIResult | null; decision: Decision | null; followups: Followup[]; followups_remaining: number;
  analysis_readiness?: {configuration?: string; configuration_observed?: number; configuration_total?: number; telemetry_pending_rule_ids?: string[]};
  configuration_detail?: Record<string, unknown> | null;
  evidence_schema_version?: string | null;
  observation?: {evidence?:{metrics?:Record<string,{window_start?:string;window_end?:string;points?:{at:string;value:number}[];sufficient?:boolean;p95?:number;p99?:number;coverage_ratio?:number}>;metric_summaries?:Record<string,{sufficient?:boolean;p95?:number;p99?:number;coverage_ratio?:number}>;analysis_readiness?:{configuration?:string;configuration_observed?:number;configuration_total?:number;telemetry_pending_rule_ids?:string[]}};observed_at?: string; collector_version?: string; evidence_schema_version?: string; configuration_snapshot?: Record<string, unknown>;
    dependency_refs?: {relationship: string; from_resource_id: string; to_resource_id: string; verification_state: string; observed_at: string | null}[]};
  rule_evaluations?: {rule_id: string; rule_version: string; outcome: string; reason: string; destructive_actions_blocked?: boolean; safety_blocks?: string[]}[];
  rule_matches?: RuleMatches;
  rule_conflicts?: RuleConflict[];
  reconciliation_status?: string | null;
  costs?: {
    billed_cost_usd: number | null;
    effective_cost_usd?: number | null;
    retail_estimate_usd: number | null;
    modeled_future_cost_usd: number | null;
    opportunity_usd: number | null;
    verified_realized_savings_usd: number | null;
    explanation: string;
    currency?: string;
    retail_run_rate_usd?: number | null;
    retail_waste_opportunity_usd?: number | null;
    retail_waste_opportunity_incomplete?: boolean;
    billed_vs_retail_usd?: number | null;
    retail_list_savings_usd?: number | null;
    commitment_benefit_usd?: number | null;
    modeled_payable_reduction_usd?: number | null;
  };
  financial_overlaps?: {resource_id: string; resource_name?: string; rule_id: string}[];
  action_items?: Action[];
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

type UseResourcesOptions = {running?: boolean; armDetail?: ArmDetailStatus; overview?: boolean};
type ResourceHookState = {page: ResourcePage | null; error: string; loading: boolean; progress: ResourceLoadProgress | null};

const emptyResourceState: ResourceHookState = {page: null, error: '', loading: false, progress: null};
const resourceCache = new Map<string, ResourceHookState>();
const resourceListeners = new Map<string, Set<() => void>>();
const resourceInflight = new Map<string, AbortController>();

function resourceCacheKey(scanId: string, token: string, syncEpoch: number, options: UseResourcesOptions) {
  return JSON.stringify([scanId, token, syncEpoch, !!options.running, options.armDetail ?? '', !!options.overview]);
}

function publishResourceCache(key: string, next: ResourceHookState) {
  resourceCache.set(key, next);
  resourceListeners.get(key)?.forEach(listener => listener());
}

function subscribeResourceCache(key: string, listener: () => void) {
  const set = resourceListeners.get(key) ?? new Set();
  set.add(listener);
  resourceListeners.set(key, set);
  return () => {
    set.delete(listener);
    if (!set.size) resourceListeners.delete(key);
  };
}

function readResourceCache(key: string): ResourceHookState {
  return resourceCache.get(key) ?? emptyResourceState;
}

function startResourceLoad(key: string, scanId: string, token: string, options: UseResourcesOptions, force: boolean) {
  const cached = resourceCache.get(key);
  if (!force && cached?.progress?.complete && cached.page) return;
  const existing = resourceInflight.get(key);
  if (existing && !force) return;
  existing?.abort();

  const request = new AbortController();
  resourceInflight.set(key, request);
  const kept = cached?.page?.scan_id === scanId ? cached.page : null;
  publishResourceCache(key, {
    page: kept,
    error: '',
    loading: true,
    progress: kept
      ? {loaded: kept.items.length, total: kept.total, complete: false}
      : null,
  });

  loadResourcePages(
    (path, opts) => api(path, token, opts),
    scanId,
    request.signal,
    {
      partial: options.running,
      incremental: !options.running && !options.overview,
      overview: options.overview,
      costScope: options.running ? 'all' : 'billable',
      pageSize: options.running ? RUNNING_RESOURCE_PAGE_SIZE : undefined,
      armDetail: options.armDetail,
      onProgress: (page, progress) => {
        if (request.signal.aborted) return;
        publishResourceCache(key, {
          page,
          error: '',
          loading: !progress.complete,
          progress,
        });
      },
    },
  )
    .then(page => {
      if (request.signal.aborted) return;
      publishResourceCache(key, {
        page,
        error: '',
        loading: false,
        progress: {loaded: page.items.length, total: page.total, complete: true},
      });
    })
    .catch(cause => {
      if (request.signal.aborted) return;
      publishResourceCache(key, {
        page: options.running ? kept : null,
        error: cause instanceof Error ? cause.message : 'Resource evidence could not be loaded.',
        loading: false,
        progress: null,
      });
    })
    .finally(() => {
      if (resourceInflight.get(key) === request) resourceInflight.delete(key);
    });
}

export function useResources(scanId: string | undefined, token: string, enabled = true, syncEpoch = 0, options: UseResourcesOptions = {}) {
  const running = !!options.running;
  const overview = !!options.overview;
  const armDetail = options.armDetail;
  const key = useMemo(() => (
    scanId && enabled ? resourceCacheKey(scanId, token, syncEpoch, {running, armDetail, overview}) : ''
  ), [scanId, token, enabled, syncEpoch, running, armDetail, overview]);

  const subscribe = useCallback((listener: () => void) => (
    key ? subscribeResourceCache(key, listener) : () => undefined
  ), [key]);

  const getSnapshot = useCallback(() => (
    key ? readResourceCache(key) : emptyResourceState
  ), [key]);

  const state = useSyncExternalStore(subscribe, getSnapshot, () => (key ? readResourceCache(key) : emptyResourceState));

  const reload = useCallback(() => {
    if (!scanId || !enabled || !key) return;
    startResourceLoad(key, scanId, token, {running, armDetail, overview}, true);
  }, [scanId, token, enabled, key, running, armDetail, overview]);

  useEffect(() => {
    if (!scanId || !enabled || !key) return;
    startResourceLoad(key, scanId, token, {running, armDetail, overview}, false);
  }, [scanId, token, enabled, key, running, armDetail, overview]);

  useEffect(() => {
    if (!running || !scanId || !enabled || !key) return;
    const timer = window.setInterval(() => startResourceLoad(key, scanId, token, {running, armDetail, overview}, true), 3000);
    return () => window.clearInterval(timer);
  }, [running, scanId, enabled, key, token, armDetail, overview]);

  return {page: state.page, error: state.error, reload, loading: state.loading, progress: state.progress};
}

/** Refresh AI/decision on already-loaded rows after batch progress (avoids full catalog reload). */
export async function refreshLoadedResourceSignals(
  scanId: string,
  token: string,
  syncEpoch: number,
  options: UseResourcesOptions,
) {
  const key = resourceCacheKey(scanId, token, syncEpoch, options);
  const cached = resourceCache.get(key);
  if (!cached?.page?.items.length) return;
  const signals = await lookupResourceSignals(
    scanId,
    token,
    cached.page.items.map(row => ({provider: row.provider, resource_id: row.resource_id})),
  );
  const byIdentity = new Map(signals.map(row => [identityOf(row.provider, row.resource_id), row]));
  const items = cached.page.items.map(row => {
    const patch = byIdentity.get(identityOf(row.provider, row.resource_id));
    if (!patch) return row;
    return {...row, ai: patch.ai, decision: patch.decision};
  });
  publishResourceCache(key, {...cached, page: {...cached.page, items}});
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
