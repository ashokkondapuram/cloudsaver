import type {Finding} from './types';

const labels: Record<string, string> = {
  ORPHANED_DISK: 'Unattached managed disk', ORPHANED_DISKS: 'Unattached managed disk',
  UNASSOCIATED_PUBLIC_IP: 'Unassociated public IP', UNASSOCIATED_PUBLIC_IPS: 'Unassociated public IP',
  STOPPED_VM: 'Stopped virtual machine', STOPPED_VMS: 'Stopped virtual machine',
  EMPTY_APP_SERVICE_PLAN: 'Empty App Service plan', EMPTY_APP_SERVICE: 'Empty App Service plan',
  UNDERUTILIZED_APP_SERVICE_PLAN: 'App Service plan review', ORPHANED_NIC: 'Orphaned network interface',
  ORPHANED_NSG: 'Unassociated security group', IDLE_APP_GATEWAY: 'Idle Application Gateway',
  AWS_UNATTACHED_EBS: 'Unattached EBS volume', AWS_UNASSOCIATED_EIP: 'Unassociated Elastic IP', AWS_IDLE_RDS: 'Stopped RDS instance',
  GCP_UNATTACHED_DISK: 'Unattached persistent disk', GCP_UNASSIGNED_ADDRESS: 'Unassigned external IPv4', GCP_IDLE_CLOUD_SQL: 'Idle Cloud SQL review',
  K8S_CPU_OVERSIZED: 'CPU request review', K8S_MEMORY_OVERSIZED: 'Memory request review',
};

export const providerNames: Record<string, string> = {azure: 'Azure', aws: 'AWS', gcp: 'Google Cloud', kubernetes: 'Kubernetes'};
export const providerColors: Record<string, string> = {azure: '#2563eb', aws: '#c2410c', gcp: '#15803d', kubernetes: '#7c3aed'};
export const terraformRules = new Set(['ORPHANED_DISK','UNASSOCIATED_PUBLIC_IP','ORPHANED_NIC','ORPHANED_NSG','IDLE_APP_GATEWAY','AWS_UNATTACHED_EBS','AWS_UNASSOCIATED_EIP','AWS_IDLE_RDS','GCP_UNATTACHED_DISK','GCP_UNASSIGNED_ADDRESS','GCP_IDLE_CLOUD_SQL']);
export const bashRules = new Set(['ORPHANED_DISK','UNASSOCIATED_PUBLIC_IP','ORPHANED_NIC','ORPHANED_NSG']);
export const ruleLabel = (rule: string) => labels[rule] || rule.replaceAll('_', ' ').toLowerCase();
export const providerOf = (finding: Finding) => finding.cloud_provider || 'azure';
export const scopeOf = (finding: Finding) => finding.scope_id || finding.subscription_id;
export const findingKey = (finding: Finding) => JSON.stringify([providerOf(finding), providerOf(finding) === 'azure' ? finding.resource_id.toLowerCase() : finding.resource_id, finding.rule_id]);
export const money = (value: number | null | undefined) => value == null || !Number.isFinite(value) ? 'Not estimated' : new Intl.NumberFormat('en-US', {style: 'currency', currency: 'USD', maximumFractionDigits: 2}).format(value);
export const dateTime = (value: string) => {const d = new Date(value); return Number.isNaN(d.valueOf()) ? 'Unknown time' : d.toLocaleString(undefined, {dateStyle: 'medium', timeStyle: 'short'});};
export const compact = (value: number) => new Intl.NumberFormat('en-US', {notation: value >= 10000 ? 'compact' : 'standard', maximumFractionDigits: 1}).format(value);

export function observedTags(finding: Finding): Record<string, string> {
  const raw = finding.evidence?.tags || finding.evidence?.labels;
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return {};
  return Object.fromEntries(Object.entries(raw).filter((entry): entry is [string,string] => typeof entry[1] === 'string'));
}

export function downloadFile(content: string, filename: string, type = 'text/plain') {
  const url = URL.createObjectURL(new Blob([content], {type}));
  const link = document.createElement('a');
  link.href = url; link.download = filename; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function exportFindings(findings: Finding[], kind: 'csv' | 'json', filename: string) {
  if (kind === 'json') return downloadFile(JSON.stringify(findings, null, 2), filename + '.json', 'application/json');
  const fields = ['cloud_provider','scope_id','rule_id','severity','resource_name','resource_type','resource_group','subscription_id','resource_id','estimated_monthly_waste_usd','details'] as const;
  const cell = (value: unknown) => {let text = String(value ?? ''); if (/^[\s]*[=+@\-]|^[\t\r\n]/.test(text)) text = "'" + text; return '"' + text.replaceAll('"','""') + '"';};
  const rows = findings.map(f => fields.map(field => cell(field === 'cloud_provider' ? providerOf(f) : field === 'scope_id' ? scopeOf(f) : f[field])).join(','));
  downloadFile('\ufeff' + [fields.join(','), ...rows].join('\r\n'), filename + '.csv', 'text/csv;charset=utf-8');
}
