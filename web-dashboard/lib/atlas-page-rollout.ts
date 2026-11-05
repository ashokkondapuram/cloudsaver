/** §12 Atlas page rollout tracker — incrementally wire presets, charts, and boards. */
export type AtlasRolloutPage = {
  route: string;
  label: string;
  status: 'pilot' | 'partial' | 'planned';
  notes: string;
};

export const ATLAS_PAGE_ROLLOUT: AtlasRolloutPage[] = [
  {route: '/allocation', label: 'Cost allocation', status: 'pilot', notes: 'BillingEvidencePanel + AnalyticsChart on live FinOps daily series'},
  {route: '/', label: 'Overview', status: 'partial', notes: 'Atlas tokens via preset; charts planned for finance headline'},
  {route: '/resources', label: 'Resources', status: 'partial', notes: 'Shared dialog / tabs (Arc UI mapping)'},
  {route: '/governance', label: 'Governance', status: 'pilot', notes: 'FindingWorkflowBoard on Findings tab'},
  {route: '/agents', label: 'Agent workspace', status: 'pilot', notes: 'Fleetflow-style event log + Code Mode stub panel'},
  {route: '/activity', label: 'Activity', status: 'planned', notes: 'Reliability + AI history tables'},
];

export function atlasRolloutForRoute(pathname: string): AtlasRolloutPage | undefined {
  const normalized = pathname === '' ? '/' : pathname.replace(/\/$/, '') || '/';
  return ATLAS_PAGE_ROLLOUT.find(page => page.route === normalized || (page.route !== '/' && normalized.startsWith(page.route)));
}
