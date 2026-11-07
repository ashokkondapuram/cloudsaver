export type AgentTask = {state: string};
export type ObsSummaryItem = {id: string; status: string};
export type GitOpsReview = {id: string; repository: string; branch: string; status: string; attempts: number};

export function taskStateCounts(items: AgentTask[]) {
  const map = new Map<string, number>();
  for (const t of items) {
    const k = t.state || 'unknown';
    map.set(k, (map.get(k) ?? 0) + 1);
  }
  return [...map.entries()].sort((a, b) => b[1] - a[1]);
}

export function observabilityIssueCount(items: ObsSummaryItem[]) {
  return items.filter(i => i.status && i.status !== 'healthy' && i.status !== 'ok' && i.status !== 'synced').length;
}

export function gitopsOpenCount(rows: GitOpsReview[]) {
  return rows.filter(r => {
    const s = (r.status || '').toLowerCase();
    return s === 'open' || s === 'pending' || s === 'draft' || s === 'review';
  }).length;
}

export function agentInFlightCount(states: [string, number][]) {
  const inflight = new Set(['pending', 'queued', 'running', 'processing', 'in_progress']);
  return states.filter(([s]) => inflight.has((s || '').toLowerCase())).reduce((n, [, c]) => n + c, 0);
}
