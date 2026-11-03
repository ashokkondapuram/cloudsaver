export const workloadTabs = ['assessments', 'declared', 'engineering'] as const;
export type WorkloadTab = (typeof workloadTabs)[number];

const queryToTab: Record<string, WorkloadTab> = {
  assessments: 'assessments',
  declared: 'declared',
  engineering: 'engineering',
};

export function workloadTabFromQuery(slug: string | null | undefined): WorkloadTab | null {
  if (!slug) return null;
  return queryToTab[slug] ?? null;
}

export function workloadQueryFromTab(tab: WorkloadTab): string {
  return tab;
}

/** Path + query for the Declared workloads tab with optional row focus. */
export function declaredWorkloadHref(workloadId: string): string {
  return `/workloads?tab=declared&workload=${encodeURIComponent(workloadId)}`;
}

export function declaredWorkloadShareUrl(workloadId: string, origin: string): string {
  return `${origin}${declaredWorkloadHref(workloadId)}`;
}
