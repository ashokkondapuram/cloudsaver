import {governanceTabQuery, governanceTabs, type GovernanceTab} from './governance-tabs';
import type {PageTab} from '../components/ui/PageTabs';

export type WorkspaceTab = PageTab & {lead?: string};

const governanceLeads: Record<GovernanceTab, string> = {
  'Risk register': 'Track business risk, owners, and review dates.',
  Findings: 'Treatments for assessed resources—evidence, plans, and decisions.',
  Controls: 'Policy, appetite limits, and framework mappings.',
  Exceptions: 'Time-limited accepted risk with compensating controls.',
  Approvals: 'Human queue for proposed changes—not business risk acceptance.',
  'Control-Plane Plans': 'Approved change packages linked to findings and GitOps.',
  Evidence: 'Coverage, freshness, and what was assessed versus unknown.',
  'Audit exports': 'Hash-linked packages for findings, decisions, and exceptions.',
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
    lead: 'Delivery reliability and audit evidence for this workspace.',
  },
  {id: 'scans', label: 'Scan history', lead: 'Saved snapshots with paths back to inventory.'},
  {id: 'ai', label: 'AI assessments', lead: 'Assessment history under your data-use settings.'},
];

export const settingsWorkspaceTabs: WorkspaceTab[] = [
  {
    id: 'access',
    label: 'Access & API keys',
    lead: 'Roles, API keys, display preferences, and this browser session.',
  },
  {
    id: 'cloud',
    label: 'Cloud & plan',
    lead: 'Plan limits, scopes, identity access, and schedules.',
  },
  {id: 'rules', label: 'Analysis rules', lead: 'Customer rules that shape findings and priorities.'},
  {id: 'integrations', label: 'Integrations', lead: 'Observability and outbound connectors.'},
  {
    id: 'ai',
    label: 'AI & data governance',
    lead: 'Model routing, consent, and data-use boundaries.',
  },
];

export const automationWorkspaceTabs: WorkspaceTab[] = [
  {
    id: 'reviews',
    label: 'Review packages',
    lead: 'Terraform review artifacts from the selected snapshot.',
  },
  {id: 'policies', label: 'Plan guardrails', lead: 'Policies that constrain automation and publishing.'},
  {id: 'execution', label: 'Execution history', lead: 'Sync and execution events for operator review.'},
];

export const outcomesWorkspaceTabs: WorkspaceTab[] = [
  {
    id: 'savings',
    label: 'Verified savings',
    lead: 'Estimates, validated run rates, and reconciled benefit.',
  },
  {
    id: 'anomalies',
    label: 'Cost investigations',
    lead: 'Billing spikes with ownership routing.',
  },
  {
    id: 'ownership',
    label: 'Application ownership',
    lead: 'Application, team, and cost-center mappings.',
  },
];

export const findingDrawerTabs: WorkspaceTab[] = [
  {id: 'evidence', label: 'Evidence', lead: 'Collector metadata and supporting signals.'},
  {id: 'telemetry', label: 'Telemetry', lead: 'Utilization metrics when collectors provide them.'},
  {id: 'assessment', label: '360° assessment', lead: 'Architectural review and pillar coverage.'},
  {id: 'cost', label: 'Cost breakdown', lead: 'Retail estimates and billed amounts in this snapshot.'},
  {id: 'code', label: 'Review code', lead: 'Terraform for independent review only.'},
  {id: 'activity', label: 'Activity & ITSM', lead: 'Snapshot provenance and delivery history.'},
];

export const resourceDrawerLeads: Record<string, string> = {
  overview: 'Summary and pillar radar.',
  findings: 'Findings for this resource in the selected scan.',
  evidence: 'Collector evidence, telemetry, rules, and dependencies.',
  costs: 'Billed and retail breakdown when pricing exists.',
  safety: 'Checks before you approve remediation.',
  observability: 'Latency and utilization from configured collectors.',
  ai: 'Model assessment and follow-up questions.',
  decision: 'Recorded review decision and note.',
  history: 'Prior scans and decisions when available.',
  code: 'Generated Terraform—never auto-applied.',
};
