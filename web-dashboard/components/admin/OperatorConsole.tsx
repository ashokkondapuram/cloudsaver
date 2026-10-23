'use client';

import Link from 'next/link';
import {useState} from 'react';
import {ArrowRight, Building2, Check, Copy, Loader2, LockKeyhole, LogOut, Pencil, Plus, Save, ShieldCheck, Trash2} from 'lucide-react';
import {api} from '../../lib/api';
import type {IdentityOnboarding, KubernetesCluster, PlatformSettings, TenantSettings} from '../../lib/types';
import {Dialog} from '../ui/dialog';
import {Notice, SectionTitle} from '../ui/shared';

type Directory = {tenants: TenantSettings[]; platform: PlatformSettings; identity: IdentityOnboarding};
const tiers = ['STARTER', 'GROWTH', 'ENTERPRISE'] as const;
const tierLabel = (tier: string) => tier.charAt(0) + tier.slice(1).toLowerCase();

function OperatorSignIn({onConnect}: {onConnect: (key: string, directory: Directory) => void}) {
  const [key, setKey] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function submit(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setError('');
    try {onConnect(key.trim(), await api<Directory>('/admin/tenants', key.trim()));}
    catch (cause) {setError(cause instanceof Error ? cause.message : 'Operator access could not be verified.');}
    finally {setKey(''); setBusy(false);}
  }
  return <div className="operator-signin"><form onSubmit={submit} className="connection-form">
    <span className="pretitle">PLATFORM OPERATOR</span><h1>Open the operator console</h1>
    <p>Manage workspaces, plans, and platform-wide scan and alert settings.</p>
    {error && <Notice tone="error">{error}</Notice>}
    <label htmlFor="operator-key">Operator access key</label>
    <div className="credential-input"><LockKeyhole size={17}/><input id="operator-key" type="password" autoComplete="off" value={key} onChange={e => setKey(e.target.value)} placeholder="Paste your operator key" required disabled={busy}/></div>
    <button className="button primary connection-submit" type="submit" disabled={busy || !key.trim()}>{busy ? <><Loader2 className="spin" size={17}/>Verifying…</> : <>Open console<ArrowRight size={17}/></>}</button>
    <div className="connection-security"><ShieldCheck size={16}/><span>Your key stays in browser memory and clears when you sign out or reload.</span></div>
    <Link className="text-link" href="/">Go to workspace sign-in<ArrowRight size={14}/></Link>
  </form></div>;
}

function CreateTenant({token, onCreated}: {token: string; onCreated: () => Promise<void>}) {
  const [form, setForm] = useState({tenant_id: '', name: '', plan_tier: 'STARTER', subscriptions: ''});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [issued, setIssued] = useState<{name: string; key: string} | null>(null);
  const [copied, setCopied] = useState(false);
  async function submit(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setError(''); setIssued(null); setCopied(false);
    try {
      const result = await api<{tenant: TenantSettings; workspace_key: string}>('/admin/tenants', token, {body: {
        tenant_id: form.tenant_id.trim(), name: form.name.trim(), plan_tier: form.plan_tier,
        subscription_ids: form.subscriptions.split(/[\s,]+/).map(s => s.trim()).filter(Boolean),
      }});
      setIssued({name: result.tenant.name, key: result.workspace_key});
      setForm({tenant_id: '', name: '', plan_tier: 'STARTER', subscriptions: ''});
      await onCreated();
    } catch (cause) {setError(cause instanceof Error ? cause.message : 'The workspace could not be created.');}
    finally {setBusy(false);}
  }
  return <form className="panel settings-form" onSubmit={submit}>
    <SectionTitle title="Create workspace" action={<button className="button primary" type="submit" disabled={busy}><Plus size={15}/>{busy ? 'Creating…' : 'Create workspace'}</button>}>Register a customer Microsoft Entra tenant and issue its workspace key</SectionTitle>
    {error && <Notice tone="error">{error}</Notice>}
    {issued && <Notice tone="success"><strong>{issued.name} is ready.</strong> Copy this workspace key now. You won’t be able to see it again.<div className="issued-key"><code>{issued.key}</code><button type="button" className="button secondary" onClick={() => navigator.clipboard.writeText(issued.key).then(() => setCopied(true))}>{copied ? <><Check size={15}/>Copied</> : <><Copy size={15}/>Copy key</>}</button></div></Notice>}
    <fieldset className="settings-fieldset" disabled={busy}>
      <div className="settings-row">
        <label className="wide"><span className="field-label">Microsoft Entra tenant ID</span><input type="text" value={form.tenant_id} onChange={e => setForm({...form, tenant_id: e.target.value})} placeholder="00000000-0000-0000-0000-000000000000" required/></label>
        <label className="wide"><span className="field-label">Workspace name</span><input type="text" value={form.name} onChange={e => setForm({...form, name: e.target.value})} maxLength={120} required/></label>
        <label><span className="field-label">Plan</span><select value={form.plan_tier} onChange={e => setForm({...form, plan_tier: e.target.value})}>{tiers.map(t => <option key={t} value={t}>{tierLabel(t)}</option>)}</select></label>
      </div>
      <label className="field-label" htmlFor="new-subscriptions">Azure subscription IDs (optional), one per line</label>
      <textarea id="new-subscriptions" rows={2} value={form.subscriptions} onChange={e => setForm({...form, subscriptions: e.target.value})}/>
    </fieldset>
  </form>;
}

function EditTenant({token, tenant, onClose, onSaved}: {token: string; tenant: TenantSettings; onClose: () => void; onSaved: () => Promise<void>}) {
  const [name, setName] = useState(tenant.name);
  const [plan, setPlan] = useState(tenant.plan_tier);
  const [active, setActive] = useState(tenant.active);
  const [appId, setAppId] = useState(tenant.identity.azure_app_client_id || '');
  const [serviceAccount, setServiceAccount] = useState(tenant.identity.gcp_service_account || '');
  const [clusters, setClusters] = useState<KubernetesCluster[]>(tenant.kubernetes_clusters);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function submit(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setError('');
    try {
      await api(`/admin/tenants/${tenant.tenant_id}`, token, {method: 'PATCH', body: {
        version: tenant.version, name: name.trim(), plan_tier: plan, active,
        identity: {azure_app_client_id: appId.trim() || null, gcp_service_account: serviceAccount.trim() || null},
        kubernetes_clusters: clusters.map(c => ({cluster_id: c.cluster_id.trim(), prometheus_url: c.prometheus_url.trim(), bearer_token_env: c.bearer_token_env.trim()})),
      }});
      await onSaved(); onClose();
    } catch (cause) {setError(cause instanceof Error ? cause.message : 'The workspace could not be updated.');}
    finally {setBusy(false);}
  }
  return <Dialog open onClose={onClose} title={`Edit ${tenant.name}`}><form onSubmit={submit}><div className="dialog-content settings-form">
    {error && <Notice tone="error">{error}</Notice>}
    <fieldset className="settings-fieldset" disabled={busy}>
      <legend>Workspace</legend>
      <div className="settings-row">
        <label className="wide"><span className="field-label">Name</span><input type="text" value={name} onChange={e => setName(e.target.value)} maxLength={120} required/></label>
        <label><span className="field-label">Plan</span><select value={plan} onChange={e => setPlan(e.target.value)}>{tiers.map(t => <option key={t} value={t}>{tierLabel(t)}</option>)}</select></label>
      </div>
      <label className="checkbox-row"><input type="checkbox" checked={active} onChange={e => setActive(e.target.checked)}/>Active (workspace users can sign in and scans run)</label>
    </fieldset>
    <fieldset className="settings-fieldset" disabled={busy}>
      <legend>Identity bindings</legend>
      <label><span className="field-label">Azure app client ID override (optional)</span><input type="text" value={appId} onChange={e => setAppId(e.target.value)} placeholder="Uses the platform default when empty"/></label>
      <label><span className="field-label">GCP reader service account</span><input type="text" value={serviceAccount} onChange={e => setServiceAccount(e.target.value)} placeholder="tenant-reader@cloudsaver-project.iam.gserviceaccount.com"/></label>
    </fieldset>
    <fieldset className="settings-fieldset" disabled={busy}>
      <legend>Kubernetes clusters</legend>
      {clusters.map((cluster, index) => <div className="settings-row" key={index}>
        <label><span className="field-label">Cluster ID</span><input type="text" value={cluster.cluster_id} onChange={e => setClusters(clusters.map((c, i) => i === index ? {...c, cluster_id: e.target.value} : c))} required/></label>
        <label className="wide"><span className="field-label">Prometheus HTTPS URL</span><input type="text" value={cluster.prometheus_url} onChange={e => setClusters(clusters.map((c, i) => i === index ? {...c, prometheus_url: e.target.value} : c))} required/></label>
        <label><span className="field-label">Token variable</span><input type="text" value={cluster.bearer_token_env} onChange={e => setClusters(clusters.map((c, i) => i === index ? {...c, bearer_token_env: e.target.value} : c))} placeholder="CLOUDSAVER_PROMETHEUS_TOKEN_…" required/></label>
        <button type="button" className="icon-button" aria-label={`Remove cluster ${cluster.cluster_id || index + 1}`} onClick={() => setClusters(clusters.filter((_, i) => i !== index))}><Trash2 size={16}/></button>
      </div>)}
      <button type="button" className="button secondary" onClick={() => setClusters([...clusters, {cluster_id: '', prometheus_url: '', bearer_token_env: ''}])}><Plus size={15}/>Add cluster</button>
    </fieldset>
  </div><div className="dialog-actions"><button type="button" className="button secondary" onClick={onClose}>Cancel</button><button className="button primary" type="submit" disabled={busy}><Save size={15}/>{busy ? 'Saving…' : 'Save changes'}</button></div></form></Dialog>;
}

function PlatformPanel({token, directory, onSaved}: {token: string; directory: Directory; onSaved: () => Promise<void>}) {
  const [values, setValues] = useState(directory.platform);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{tone: 'success' | 'error'; text: string} | null>(null);
  async function submit(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setMessage(null);
    try {
      await api('/admin/settings', token, {method: 'PUT', body: values});
      await onSaved(); setMessage({tone: 'success', text: 'Platform settings saved.'});
    } catch (cause) {setMessage({tone: 'error', text: cause instanceof Error ? cause.message : 'Platform settings could not be saved.'});}
    finally {setBusy(false);}
  }
  const identity = directory.identity;
  return <form className="panel settings-form" onSubmit={submit}>
    <SectionTitle title="Platform settings" action={<button className="button primary" type="submit" disabled={busy}><Save size={15}/>{busy ? 'Saving…' : 'Save changes'}</button>}>Apply to every workspace. Changes take effect within a few seconds.</SectionTitle>
    {message && <Notice tone={message.tone}>{message.text}</Notice>}
    <fieldset className="settings-fieldset" disabled={busy}>
      <label className="checkbox-row"><input type="checkbox" checked={values.scheduled_scans_enabled} onChange={e => setValues({...values, scheduled_scans_enabled: e.target.checked})}/>Run scheduled scans</label>
      <label className="checkbox-row"><input type="checkbox" checked={values.automated_alerts_enabled} onChange={e => setValues({...values, automated_alerts_enabled: e.target.checked})}/>Send automated scan alerts</label>
    </fieldset>
    <dl className="settings-key-values">
      <div><dt>Cloud identity</dt><dd>{identity.identity_mode === 'developer' ? 'Developer sign-in (local only)' : 'Azure managed identity'}</dd></div>
      <div><dt>Managed identity client ID</dt><dd>{identity.managed_identity_client_id ? <code>{identity.managed_identity_client_id}</code> : 'System-assigned or not configured'}</dd></div>
      <div><dt>Azure app client ID</dt><dd>{identity.azure_app_client_id ? <code>{identity.azure_app_client_id}</code> : 'Not configured'}</dd></div>
      <div><dt>AWS hub role</dt><dd>{identity.aws_hub_role_arn ? <code>{identity.aws_hub_role_arn}</code> : 'Not configured'}</dd></div>
      <div><dt>GCP workload identity provider</dt><dd>{identity.gcp_workload_provider ? <code>{identity.gcp_workload_provider}</code> : 'Not configured'}</dd></div>
    </dl>
  </form>;
}

export function OperatorConsole() {
  const [token, setToken] = useState('');
  const [directory, setDirectory] = useState<Directory | null>(null);
  const [editing, setEditing] = useState<TenantSettings | null>(null);
  const [error, setError] = useState('');
  async function reload() {
    try {setDirectory(await api<Directory>('/admin/tenants', token)); setError('');}
    catch (cause) {setError(cause instanceof Error ? cause.message : 'Workspaces could not be loaded.');}
  }
  if (!directory) return <OperatorSignIn onConnect={(key, value) => {setToken(key); setDirectory(value);}}/>;
  return <div className="operator-console">
    <header className="operator-header"><div><span className="eyebrow">PLATFORM OPERATOR</span><h1>Workspaces & platform</h1><p>Create workspaces, change plans, and control platform-wide automation.</p></div><button className="button secondary" onClick={() => {setToken(''); setDirectory(null);}}><LogOut size={15}/>Sign out</button></header>
    {error && <Notice tone="error">{error}</Notice>}
    <section className="panel">
      <SectionTitle title="Workspaces">{directory.tenants.length} registered</SectionTitle>
      <div className="summary-table-scroll"><table className="summary-table"><thead><tr><th>Workspace</th><th>Tenant ID</th><th>Plan</th><th>Status</th><th>Scopes</th><th>Schedule</th><th><span className="sr-only">Actions</span></th></tr></thead><tbody>
        {directory.tenants.map(tenant => <tr key={tenant.tenant_id}>
          <td><Building2 size={15}/> {tenant.name}</td><td><code>{tenant.tenant_id}</code></td><td>{tierLabel(tenant.plan_tier)}</td>
          <td><span className={`state-badge ${tenant.active ? 'configured' : ''}`}>{tenant.active ? 'Active' : 'Inactive'}</span></td>
          <td>{tenant.subscription_ids.length + tenant.aws_accounts.length + tenant.gcp_projects.length + tenant.kubernetes_clusters.length}</td>
          <td>{tenant.schedule.frequency === 'manual' ? 'Manual' : tenant.schedule.frequency === 'daily' ? 'Daily' : 'Hourly'}</td>
          <td><button className="icon-button" aria-label={`Edit ${tenant.name}`} onClick={() => setEditing(tenant)}><Pencil size={15}/></button></td>
        </tr>)}
      </tbody></table></div>
    </section>
    <CreateTenant token={token} onCreated={reload}/>
    <PlatformPanel key={directory.platform.version} token={token} directory={directory} onSaved={reload}/>
    {editing && <EditTenant token={token} tenant={editing} onClose={() => setEditing(null)} onSaved={reload}/>}
  </div>;
}
