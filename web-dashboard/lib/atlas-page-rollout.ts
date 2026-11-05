/** §12 Atlas page rollout tracker — customer and console routes. */
export type AtlasRolloutPage = {
  route: string;
  label: string;
  status: 'pilot' | 'partial' | 'planned';
  notes: string;
};

export const ATLAS_PAGE_ROLLOUT: AtlasRolloutPage[] = [
  {route: '/', label: 'Overview', status: 'pilot', notes: 'Evidence health + expandable FinOps mini-chart (Atlas preset)'},
  {route: '/resources', label: 'Resources', status: 'pilot', notes: 'Live inventory, Arc-style dialog/tabs'},
  {route: '/resources/insight', label: 'Resource insight', status: 'pilot', notes: 'Specialist insight route'},
  {route: '/resources/report', label: 'Resource report', status: 'pilot', notes: 'Print/report surface'},
  {route: '/findings', label: 'Findings', status: 'pilot', notes: 'Legacy findings grid'},
  {route: '/workloads', label: 'Workload assessments', status: 'pilot', notes: 'Declared workloads + engineering tabs'},
  {route: '/allocation', label: 'Cost allocation', status: 'pilot', notes: 'BillingEvidencePanel + AnalyticsChart daily series'},
  {route: '/outcomes', label: 'Savings & investigations', status: 'pilot', notes: 'Finance investigations workspace'},
  {route: '/governance', label: 'Risk & compliance', status: 'pilot', notes: 'FindingWorkflowBoard + control-plane plans'},
  {route: '/automation', label: 'Automation & GitOps', status: 'pilot', notes: 'GitOps review + execution timeline'},
  {route: '/services', label: 'Services', status: 'pilot', notes: 'Service architecture analysis'},
  {route: '/kubernetes', label: 'Kubernetes', status: 'pilot', notes: 'Cluster workload evidence'},
  {route: '/optimization', label: 'Optimization evidence', status: 'pilot', notes: 'Topology / SLO evidence panels'},
  {route: '/agents', label: 'Agent worker', status: 'pilot', notes: 'Event log + Code Mode stub'},
  {route: '/activity', label: 'Activity & delivery', status: 'pilot', notes: 'Delivery + AI usage AnalyticsCharts'},
  {route: '/settings', label: 'Settings', status: 'pilot', notes: 'Workspace tabs + preferences'},
  {route: '/claim', label: 'Claim account', status: 'pilot', notes: 'Onboarding surface with Atlas route boundary'},
  {route: '/docs', label: 'Documentation', status: 'pilot', notes: 'Embedded docs reader'},
];

const SORTED_ROLLOUT = [...ATLAS_PAGE_ROLLOUT].sort((a, b) => b.route.length - a.route.length);

export function atlasRolloutForRoute(pathname: string): AtlasRolloutPage | undefined {
  const normalized = pathname.replace(/\/$/, '') || '/';
  return SORTED_ROLLOUT.find(page => {
    if (page.route === '/') return normalized === '/';
    return normalized === page.route || normalized.startsWith(`${page.route}/`);
  });
}

export function atlasRolloutComplete(): boolean {
  return ATLAS_PAGE_ROLLOUT.every(page => page.status === 'pilot');
}
