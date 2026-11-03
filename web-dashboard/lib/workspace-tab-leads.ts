import {governanceTabQuery, governanceTabs, type GovernanceTab} from './governance-tabs';
import type {PageTab} from '../components/ui/PageTabs';

export type WorkspaceTab = PageTab & {lead?: string};

const governanceLeads: Record<GovernanceTab, string> = {
  'Risk register': 'Business risk stays separate from technical findings. Track inherent and residual scores, owners, and review dates.',
  Findings: 'Accountable treatments for assessed resources. Open a row to review evidence, plans, and decisions.',
  Controls: 'Reviewed control policy, appetite limits, and framework mappings before broad catalogs.',
  Exceptions: 'Time-limited accepted risk with compensating controls—distinct from a passing assessment.',
  Approvals: 'Human decision queue for proposed changes and verification steps—not business risk acceptance.',
  'Control-Plane Plans': 'Operator-approved change packages linked to findings and GitOps workflows.',
  Evidence: 'Coverage counts, freshness, and what was assessed versus unknown.',
  'Audit exports': 'Hash-linked packages for findings, decisions, and exceptions—retain your own trust anchor.',
};

export const governanceWorkspaceTabs: WorkspaceTab[] = governanceTabs.map(name => ({
  id: governanceTabQuery[name],
  label: name,
  lead: governanceLeads[name],
}));

export const activityWorkspaceTabs: WorkspaceTab[] = [
  {
    id: 'deliveries',
    label: 'Delivery & audit',
    lead: 'Notification delivery, reliability signals, and audit evidence for this workspace.',
  },
  {id: 'scans', label: 'Scan history', lead: 'Saved scan snapshots with quick paths back to inventory and findings.'},
  {id: 'ai', label: 'AI assessments', lead: 'Saved AI assessment history bound to your workspace data-use settings.'},
];

export const settingsWorkspaceTabs: WorkspaceTab[] = [
  {
    id: 'access',
    label: 'Access & API keys',
    lead: 'Roles, API keys, display preferences, and session details for this browser.',
  },
  {
    id: 'cloud',
    label: 'Cloud & plan',
    lead: 'Plan limits first, then scopes, identity access, and schedules. Billing imports live on Cost allocation; delivery history on Activity.',
  },
  {id: 'rules', label: 'Analysis rules', lead: 'Customer-owned rules that shape findings and review priorities.'},
  {id: 'integrations', label: 'Integrations', lead: 'Observability and outbound connectors configured for this workspace.'},
  {
    id: 'ai',
    label: 'AI & data governance',
    lead: 'Model routing, consent, and data-use boundaries before assessments run.',
  },
];

export const automationWorkspaceTabs: WorkspaceTab[] = [
  {
    id: 'reviews',
    label: 'Review packages',
    lead: 'Generate and inspect Terraform review artifacts from the selected snapshot.',
  },
  {id: 'policies', label: 'Plan guardrails', lead: 'Workspace policies that constrain automation and publishing.'},
  {id: 'execution', label: 'Execution history', lead: 'Timeline of sync and execution events for operator review.'},
];

export const outcomesWorkspaceTabs: WorkspaceTab[] = [
  {
    id: 'savings',
    label: 'Verified savings',
    lead: 'Separate estimates, validated run rates, and reconciled financial benefit.',
  },
  {
    id: 'anomalies',
    label: 'Cost investigations',
    lead: 'Imported billing spikes with ownership routing—not real-time cloud alerts.',
  },
  {
    id: 'ownership',
    label: 'Application ownership',
    lead: 'Versioned application, team, and cost-center mappings for accountability.',
  },
];

export const findingDrawerTabs: WorkspaceTab[] = [
  {id: 'evidence', label: 'Evidence', lead: 'Observation schema, collector metadata, and supporting signals.'},
  {id: 'telemetry', label: 'Telemetry', lead: 'Utilization and health metrics when collectors provide them.'},
  {id: 'assessment', label: '360° assessment', lead: 'Architectural review and pillar coverage for this resource.'},
  {id: 'cost', label: 'Cost breakdown', lead: 'Retail estimates and billed portions available in this snapshot.'},
  {id: 'code', label: 'Review code', lead: 'Terraform snippets generated for independent review only.'},
  {id: 'activity', label: 'Activity & ITSM', lead: 'Snapshot provenance and recent delivery history for this scan.'},
];

export const resourceDrawerLeads: Record<string, string> = {
  overview: 'Summary and pillar radar. Open Costs, Findings, or Evidence for detail.',
  findings: 'Findings linked to this resource in the selected scan.',
  evidence: 'Collector evidence, telemetry hooks, rules, and dependencies.',
  costs: 'Retail and billed cost breakdown when pricing evidence exists.',
  safety: 'Action safety checks before you approve remediation steps.',
  observability: 'Latency and utilization signals from configured collectors.',
  ai: 'AI assessment output and follow-up questions for this resource.',
  decision: 'Recorded review decision and rationale for this resource.',
  history: 'Prior observations and decision history when available.',
  code: 'Generated Terraform for independent review—never auto-applied.',
};
