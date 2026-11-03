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
