export const governanceTabs = [
  'Risk register',
  'Findings',
  'Controls',
  'Exceptions',
  'Approvals',
  'Control-Plane Plans',
  'Evidence',
  'Audit exports',
] as const;

export type GovernanceTab = (typeof governanceTabs)[number];

export const governanceTabQuery: Record<GovernanceTab, string> = {
  'Risk register': 'risk',
  Findings: 'findings',
  Controls: 'controls',
  Exceptions: 'exceptions',
  Approvals: 'approvals',
  'Control-Plane Plans': 'control-plane',
  Evidence: 'evidence',
  'Audit exports': 'audit',
};

const queryToTab = Object.fromEntries(
  Object.entries(governanceTabQuery).map(([tab, slug]) => [slug, tab]),
) as Record<string, GovernanceTab>;

export function governanceTabFromQuery(slug: string | null | undefined): GovernanceTab | null {
  if (!slug) return null;
  return queryToTab[slug] ?? null;
}

export function governanceQueryFromTab(tab: GovernanceTab): string {
  return governanceTabQuery[tab];
}
