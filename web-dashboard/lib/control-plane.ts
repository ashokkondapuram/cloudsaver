export type SafetyDecisionStatus =
  | 'eligible_for_review'
  | 'blocked'
  | 'evidence_required'
  | 'unsupported'
  | 'expired';

export type GateCheckStatus = 'pass' | 'fail' | 'unknown' | 'not_applicable';

export interface ActionSafetyCheck {
  code:
    | 'AG-COST-01'
    | 'AG-ID-01'
    | 'AG-HA-01'
    | 'AG-DR-01'
    | 'AG-RET-01'
    | 'AG-REC-01'
    | 'AG-PERF-01'
    | 'AG-OPS-01'
    | string;
  status: GateCheckStatus;
  explanation?: string;
  evidence_fields?: string[];
}

export interface ActionAssessmentResponse {
  id: string;
  action_id: string;
  rule_version: string;
  findings: Record<string, GateCheckStatus>;
  decision: SafetyDecisionStatus;
  evidence_digest: string;
  policy_digest: string;
  evaluated_at?: string;
  created_at?: string;
  automatic_execution?: false;
  execution_enabled?: false;
}

export interface FinancialScenarioRequest {
  idempotency_key: string;
  currency: string;
  commitment_fee: string | null;
  uncommitted_baseline: string | null;
  uncommitted_if_absorbed: string | null;
  absorption_proven: boolean;
  new_recurring: string;
  one_time: string;
}

export interface FinancialScenarioResponse {
  id: string;
  status: string;
  currency?: string;
  baseline_payable?: string;
  post_payable?: string;
  net_recurring_benefit?: string;
  avoidable_payable_spend?: string;
  absorption_proven?: boolean;
  reason?: string;
}

export interface PlanRecord {
  id: string;
  objective: string;
  created_at: string;
  engineering_workload_id?: string | null;
  engineering_workload_name?: string | null;
}

export interface PlanVersionRecord {
  id: string;
  plan_id: string;
  version: number;
  state: string;
  targets: string[];
  parameters: Record<string, unknown>;
  identity_digest: string;
  policy_digest?: string;
  evidence_digest?: string;
  engineering_outbox_state?: 'pending' | 'published' | null;
  engineering_outbox_pending_count?: number;
  engineering_outbox_published_count?: number;
}

export interface EngineeringOutboxRow {
  event_id: string;
  kind: string;
  state: 'pending' | 'published';
  created_at: string;
}

export interface DeclaredWorkload {
  id: string;
  tenant_id: string;
  name: string;
  environment: string;
  provider: 'azure' | 'aws' | 'gcp' | 'kubernetes';
  scope_id: string;
  owner: string;
  team: string;
  requirements: Record<string, string | null | undefined>;
  version: number;
  created_at: string;
  updated_at: string;
}

const GATE_ORDER = [
  'AG-COST-01',
  'AG-ID-01',
  'AG-HA-01',
  'AG-DR-01',
  'AG-RET-01',
  'AG-REC-01',
  'AG-PERF-01',
  'AG-OPS-01',
] as const;

export function findingsToChecks(findings: Record<string, GateCheckStatus>): ActionSafetyCheck[] {
  const keys = [...GATE_ORDER, ...Object.keys(findings).filter(k => !GATE_ORDER.includes(k as typeof GATE_ORDER[number]))];
  const seen = new Set<string>();
  return keys.filter(k => findings[k] !== undefined && !seen.has(k) && seen.add(k)).map(code => ({
    code,
    status: findings[code],
  }));
}

export function actionEvidenceFromResource(detail: {
  assessment: {
    disposition: string;
    protected_reasons: string[];
    resource_id: string;
  };
  costs?: {
    opportunity_usd?: number | null;
    effective_cost_usd?: number | null;
    billed_cost_usd?: number | null;
  } | null;
  observation?: {evidence?: {
    metrics?: Record<string, {window_start?: string | null; window_end?: string | null}>;
    metric_summaries?: Record<string, {coverage_ratio?: number | null}>;
  }} | null;
}): Record<string, unknown> {
  const protectedReasons = detail.assessment.protected_reasons.map(r => r.toLowerCase());
  const standby = protectedReasons.some(r => r.includes('standby') || r.includes('replica') || r.includes('dr_'));
  const hold = protectedReasons.some(r => r.includes('hold') || r.includes('retention') || r.includes('legal'));
  const metrics = detail.observation?.evidence?.metrics || {};
  const summaries = detail.observation?.evidence?.metric_summaries || {};
  const memoryKey = Object.keys(metrics).find(k => k.toLowerCase().includes('memory'));
  const memoryWindow = memoryKey ? metrics[memoryKey] : undefined;
  const memoryDays = memoryWindow?.window_start && memoryWindow?.window_end
    ? Math.round((Date.parse(memoryWindow.window_end) - Date.parse(memoryWindow.window_start)) / 86_400_000)
    : null;
  const memoryRatio = memoryKey ? summaries[memoryKey]?.coverage_ratio ?? null : null;
  return {
    claims_positive_benefit: detail.costs?.opportunity_usd != null && detail.costs.opportunity_usd > 0,
    absorption_proven: null,
    fees_remain: detail.costs?.effective_cost_usd != null && detail.costs?.billed_cost_usd != null
      ? detail.costs.effective_cost_usd < detail.costs.billed_cost_usd
      : null,
    ip_dependency_confirmed: null,
    external_owner_known: null,
    removes_quorum_member: null,
    violates_capacity_floor: null,
    is_standby_or_replica: standby ? true : null,
    active_hold: hold ? true : null,
    destructive: null,
    restore_verified: null,
    capacity_reduction: detail.costs?.opportunity_usd != null ? detail.costs.opportunity_usd > 0 : null,
    memory_history_days: memoryDays,
    valid_sample_ratio: memoryRatio,
    insufficient_headroom: null,
    owner: null,
    responder_reachable: null,
    rollback_supported: null,
  };
}
