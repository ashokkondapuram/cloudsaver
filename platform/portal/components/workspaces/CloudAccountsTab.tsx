'use client';

import {useEffect, useState} from 'react';
import {Loader2, Plus, Save, Trash2} from 'lucide-react';
import {errorMessage, portal} from '../../lib/api';
import type {Provider, Workspace} from '../../lib/types';
import {useSession} from '../SessionProvider';
import {Notice, SectionTitle} from '../ui/shared';

type Row = Record<string, string>;
type Column = {key: string; label: string; placeholder: string; hint?: string};
type SectionConfig = {
  provider: Provider; title: string; description: string; noun: string; columns: Column[];
  fromWorkspace: (workspace: Workspace) => Row[];
  toItems: (rows: Row[]) => unknown[];
  validate: (row: Row) => string | null;
};

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

const SECTIONS: SectionConfig[] = [
  {
    provider: 'azure', title: 'Azure subscriptions', noun: 'subscription', description: 'Subscriptions CloudSaver can read in the customer’s Microsoft Entra tenant.',
    columns: [{key: 'subscription_id', label: 'Subscription ID', placeholder: '00000000-0000-0000-0000-000000000000'}],
    fromWorkspace: workspace => workspace.subscription_ids.map(subscription_id => ({subscription_id})),
    toItems: rows => rows.map(row => row.subscription_id.trim().toLowerCase()),
    validate: row => UUID.test(row.subscription_id.trim()) ? null : 'Enter each subscription ID in the format 00000000-0000-0000-0000-000000000000.',
  },
  {
    provider: 'aws', title: 'AWS accounts', noun: 'account', description: 'Accounts CloudSaver reads by assuming a role.',
    columns: [
      {key: 'account_id', label: 'Account ID', placeholder: '123456789012'},
      {key: 'region', label: 'Region', placeholder: 'us-east-1'},
      {key: 'role_arn', label: 'Role ARN', placeholder: 'arn:aws:iam::123456789012:role/CloudSaverReader'},
    ],
    fromWorkspace: workspace => workspace.aws_accounts.map(account => ({...account})),
    toItems: rows => rows.map(row => ({account_id: row.account_id.trim(), region: row.region.trim(), role_arn: row.role_arn.trim()})),
    validate: row => {
      if (!/^\d{12}$/.test(row.account_id.trim())) return 'Enter each AWS account ID as 12 digits.';
      if (!/^[a-z]{2}(-[a-z]+)+-\d$/.test(row.region.trim())) return 'Enter a region such as us-east-1.';
      if (!/^arn:aws[a-z-]*:iam::\d{12}:role\/.+$/.test(row.role_arn.trim())) return 'Enter a role ARN such as arn:aws:iam::123456789012:role/CloudSaverReader.';
      return null;
    },
  },
  {
    provider: 'gcp', title: 'Google Cloud projects', noun: 'project', description: 'Projects CloudSaver reads with the workspace service account.',
    columns: [
      {key: 'project_id', label: 'Project ID', placeholder: 'my-project-id'},
      {key: 'regions', label: 'Regions', placeholder: 'us-central1, europe-west1', hint: 'Comma-separated'},
    ],
    fromWorkspace: workspace => workspace.gcp_projects.map(project => ({project_id: project.project_id, regions: project.regions.join(', ')})),
    toItems: rows => rows.map(row => ({project_id: row.project_id.trim(), regions: row.regions.split(',').map(region => region.trim()).filter(Boolean)})),
    validate: row => /^[a-z][a-z0-9-]{4,28}[a-z0-9]$/.test(row.project_id.trim()) ? null : 'Enter a valid Google Cloud project ID, such as my-project-id.',
  },
  {
    provider: 'kubernetes', title: 'Kubernetes clusters', noun: 'cluster', description: 'Clusters CloudSaver reads through Prometheus.',
    columns: [
      {key: 'cluster_id', label: 'Cluster ID', placeholder: 'prod-eastus'},
      {key: 'prometheus_url', label: 'Prometheus URL', placeholder: 'https://prometheus.example.com'},
      {key: 'bearer_token_env', label: 'Token variable', placeholder: 'CLOUDSAVER_PROMETHEUS_TOKEN_PRIMARY', hint: 'An environment variable name, not the token'},
    ],
    fromWorkspace: workspace => workspace.kubernetes_clusters.map(cluster => ({...cluster})),
    toItems: rows => rows.map(row => ({cluster_id: row.cluster_id.trim(), prometheus_url: row.prometheus_url.trim(), bearer_token_env: row.bearer_token_env.trim()})),
    validate: row => {
      if (!row.cluster_id.trim()) return 'Enter a cluster ID for each cluster.';
      if (!/^https?:\/\/\S+$/.test(row.prometheus_url.trim())) return 'Enter a Prometheus URL that starts with https://.';
      if (!/^[A-Z_][A-Z0-9_]*$/.test(row.bearer_token_env.trim())) return 'Enter the token variable as an environment variable name, such as CLOUDSAVER_PROMETHEUS_TOKEN_PRIMARY.';
      return null;
    },
  },
];

type Props = {workspace: Workspace; onChange: (workspace: Workspace) => void; reload: () => Promise<void>};

export function CloudAccountsTab({workspace, onChange, reload}: Props) {
  return <>{SECTIONS.map(section => <ScopeSection key={section.provider} config={section} workspace={workspace} onChange={onChange} reload={reload}/>)}</>;
}

function ScopeSection({config, workspace, onChange, reload}: {config: SectionConfig} & Props) {
  const {canWrite} = useSession();
  const editable = canWrite && workspace.status !== 'deleted';
  const [rows, setRows] = useState<Row[]>(() => config.fromWorkspace(workspace));
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [saved, setSaved] = useState(false);

  useEffect(() => {if (!dirty) setRows(config.fromWorkspace(workspace));}, [workspace, dirty, config]);

  const update = (index: number, key: string, value: string) => {
    setRows(previous => previous.map((row, i) => i === index ? {...row, [key]: value} : row));
    setDirty(true); setSaved(false);
  };
  const add = () => {setRows(previous => [...previous, Object.fromEntries(config.columns.map(column => [column.key, '']))]); setDirty(true); setSaved(false);};
  const remove = (index: number) => {setRows(previous => previous.filter((_, i) => i !== index)); setDirty(true); setSaved(false);};
  const cancel = () => {setRows(config.fromWorkspace(workspace)); setDirty(false); setError('');};

  async function save() {
    const problem = rows.map(config.validate).find(Boolean);
    if (problem) {setError(problem); return;}
    setBusy(true); setError('');
    try {
      const updated = await portal<Workspace>(`workspaces/${encodeURIComponent(workspace.tenant_id)}/scopes/${config.provider}`, {
        method: 'PUT', body: {version: workspace.version, items: config.toItems(rows)},
      });
      setDirty(false); setSaved(true);
      onChange(updated);
      void reload();
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setBusy(false);
    }
  }

  return <section className="panel">
    <SectionTitle title={config.title} action={editable ? <button type="button" className="button secondary small" onClick={add}><Plus size={14}/>Add</button> : undefined}>{config.description}</SectionTitle>
    {error && <Notice tone="error">{error}</Notice>}
    {saved && !dirty && <Notice tone="success">{config.title} saved.</Notice>}
    {rows.length ? <div className="scope-rows">{rows.map((row, index) => <div key={index} className={`scope-row ${config.provider}`}>
      {config.columns.map(column => <label key={column.key} className="field">{column.label}{column.hint && <span className="field-hint">{column.hint}</span>}
        <input type="text" value={row[column.key] || ''} placeholder={column.placeholder} disabled={!editable} onChange={event => update(index, column.key, event.target.value)}/>
      </label>)}
      {editable && <button type="button" className="icon-button" aria-label={`Remove ${config.noun} ${index + 1}`} title="Remove" onClick={() => remove(index)}><Trash2 size={16}/></button>}
    </div>)}</div> : <p className="scope-empty">No {config.noun}s added.</p>}
    {editable ? <div className="scope-actions">
      <span className="muted">{dirty ? 'You have unsaved changes.' : ''}</span>
      <div className="section-actions">
        {dirty && <button type="button" className="button secondary small" onClick={cancel}>Cancel</button>}
        <button type="button" className="button primary small" disabled={busy || !dirty} onClick={() => void save()}>{busy ? <Loader2 className="spin" size={14}/> : <Save size={14}/>}Save changes</button>
      </div>
    </div> : <div style={{height: 22}}/>}
  </section>;
}
