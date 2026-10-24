'use client';

import {useCallback, useEffect, useState} from 'react';
import {Bell, CalendarClock, Fingerprint, Plus, Save, Trash2} from 'lucide-react';
import {api} from '../../lib/api';
import {NOT_INCLUDED} from '../../lib/plan';
import type {AwsAccount, Frequency, SettingsResponse, TenantSettings} from '../../lib/types';
import {useWorkspace} from '../WorkspaceProvider';
import {Loading, Notice, ProviderBadge, SectionTitle} from '../ui/shared';

type GcpDraft = {project_id: string; regions: string};
type Alerts = {enabled: boolean; channel: 'slack' | 'teams' | null; webhook_url?: string; remove_webhook?: boolean};

const frequencyLabels: Record<Frequency, string> = {manual: 'Manual only', daily: 'Daily', hourly: 'Hourly'};

function useSettings() {
  const {token} = useWorkspace();
  const [data, setData] = useState<SettingsResponse | null>(null);
  const [error, setError] = useState('');
  const load = useCallback(async (signal?: AbortSignal) => {
    try {setData(await api<SettingsResponse>('/settings', token, {signal})); setError('');}
    catch (cause) {if (!signal?.aborted) setError(cause instanceof Error ? cause.message : 'Settings could not be loaded.');}
  }, [token]);
  useEffect(() => {const controller = new AbortController(); load(controller.signal); return () => controller.abort();}, [load]);
  return {data, error, reload: () => load()};
}

type IdentityDraft = {azure_app_client_id?: string; gcp_service_account?: string};

function useSave(data: SettingsResponse | null, onSaved: () => Promise<void>) {
  const {token, notify, reloadProfile} = useWorkspace();
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  async function save(changes: Partial<Pick<TenantSettings, 'subscription_ids' | 'aws_accounts' | 'gcp_projects' | 'schedule'>> & {alerts?: Alerts; identity?: IdentityDraft}, message: string) {
    if (!data) return false;
    const current = data.settings;
    setSaving(true); setError('');
    try {
      await api('/settings', token, {method: 'PUT', body: {
        version: current.version,
        subscription_ids: changes.subscription_ids ?? current.subscription_ids,
        aws_accounts: changes.aws_accounts ?? current.aws_accounts,
        gcp_projects: changes.gcp_projects ?? current.gcp_projects,
        schedule: changes.schedule ?? current.schedule,
        alerts: changes.alerts ?? {enabled: current.alerts.enabled, channel: current.alerts.channel},
        ...(changes.identity ? {identity: changes.identity} : {}),
      }});
      await onSaved();
      await reloadProfile().catch(() => {});
      notify(message);
      return true;
    } catch (cause) {setError(cause instanceof Error ? cause.message : 'Settings could not be saved.'); return false;}
    finally {setSaving(false);}
  }
  return {save, saving, error};
}

function ReadOnlyNotice({data}: {data: SettingsResponse}) {
  if (data.editable) return null;
  return <Notice>{data.platform ? 'Only workspace administrators can change these settings.' : 'Settings are managed in the server configuration for this deployment.'}</Notice>;
}

export function CloudScopesEditor() {
  const {data, error, reload} = useSettings();
  const {workspace, planProviders} = useWorkspace();
  const {save, saving, error: saveError} = useSave(data, reload);
  const [subscriptions, setSubscriptions] = useState('');
  const [aws, setAws] = useState<AwsAccount[]>([]);
  const [gcp, setGcp] = useState<GcpDraft[]>([]);
  useEffect(() => {
    if (!data) return;
    setSubscriptions(data.settings.subscription_ids.join('\n'));
    setAws(data.settings.aws_accounts);
    setGcp(data.settings.gcp_projects.map(p => ({project_id: p.project_id, regions: p.regions.join(', ')})));
  }, [data]);
  if (error) return <Notice tone="error">{error}</Notice>;
  if (!data) return <Loading label="Loading cloud accounts…"/>;
  const editable = data.scopes_editable ?? data.editable;
  const allowed = planProviders(workspace?.allowed_providers ?? ['azure', 'aws', 'gcp', 'kubernetes']);
  const subscriptionList = subscriptions.split(/[\s,]+/).map(s => s.trim()).filter(Boolean);
  function submit(event: React.FormEvent) {
    event.preventDefault();
    save({
      subscription_ids: subscriptionList,
      aws_accounts: aws.map(a => ({account_id: a.account_id.trim(), region: a.region.trim(), role_arn: a.role_arn.trim()})),
      gcp_projects: gcp.map(p => ({project_id: p.project_id.trim(), regions: p.regions.split(',').map(r => r.trim()).filter(Boolean)})),
    }, 'Cloud accounts saved. Changes apply to your next scan.');
  }
  return <form className="panel settings-form" onSubmit={submit}>
    <SectionTitle title="Authorized cloud scopes" action={editable && <button className="button primary" type="submit" disabled={saving}><Save size={15}/>{saving ? 'Saving…' : 'Save changes'}</button>}>Choose which cloud accounts, projects, and clusters CloudSaver scans</SectionTitle>
    {data.directory_mode === 'cutover' ? <Notice>Your CloudSaver administrator manages cloud accounts in the platform portal. Contact them to add or remove accounts.</Notice> : <ReadOnlyNotice data={data}/>}
    {saveError && <Notice tone="error">{saveError}</Notice>}
    {!allowed.length && <Notice tone="warning">This workspace key doesn&apos;t include any cloud providers. Ask your administrator for a new key.</Notice>}
    {allowed.includes('azure') && <fieldset className="settings-fieldset" disabled={!editable || saving}>
      <legend><ProviderBadge provider="azure"/>Azure subscriptions</legend>
      <label className="field-label" htmlFor="azure-subscriptions">Subscription IDs, one per line</label>
      <textarea id="azure-subscriptions" rows={4} value={subscriptions} onChange={e => setSubscriptions(e.target.value)} placeholder="00000000-0000-0000-0000-000000000000"/>
      <p className="inline-help">{subscriptionList.length} of {data.limits.max_subscriptions} subscriptions allowed on your plan.</p>
    </fieldset>}
    {allowed.includes('aws') && <fieldset className="settings-fieldset" disabled={!editable || saving}>
      <legend><ProviderBadge provider="aws"/>AWS accounts</legend>
      {aws.map((account, index) => <div className="settings-row" key={index}>
        <label><span className="field-label">Account ID</span><input type="text" inputMode="numeric" value={account.account_id} onChange={e => setAws(aws.map((a, i) => i === index ? {...a, account_id: e.target.value} : a))} placeholder="123456789012" required/></label>
        <label><span className="field-label">Region</span><input type="text" value={account.region} onChange={e => setAws(aws.map((a, i) => i === index ? {...a, region: e.target.value} : a))} placeholder="us-east-1" required/></label>
        <label className="wide"><span className="field-label">Reader role ARN</span><input type="text" value={account.role_arn} onChange={e => setAws(aws.map((a, i) => i === index ? {...a, role_arn: e.target.value} : a))} placeholder="arn:aws:iam::123456789012:role/CloudSaverReader" required/></label>
        <button type="button" className="icon-button" aria-label={`Remove AWS account ${account.account_id || index + 1}`} onClick={() => setAws(aws.filter((_, i) => i !== index))}><Trash2 size={16}/></button>
      </div>)}
      {editable && <button type="button" className="button secondary" onClick={() => setAws([...aws, {account_id: '', region: '', role_arn: ''}])}><Plus size={15}/>Add account</button>}
    </fieldset>}
    {allowed.includes('gcp') && <fieldset className="settings-fieldset" disabled={!editable || saving}>
      <legend><ProviderBadge provider="gcp"/>Google Cloud projects</legend>
      {gcp.map((project, index) => <div className="settings-row" key={index}>
        <label><span className="field-label">Project ID</span><input type="text" value={project.project_id} onChange={e => setGcp(gcp.map((p, i) => i === index ? {...p, project_id: e.target.value} : p))} placeholder="customer-project" required/></label>
        <label className="wide"><span className="field-label">Regions, comma-separated</span><input type="text" value={project.regions} onChange={e => setGcp(gcp.map((p, i) => i === index ? {...p, regions: e.target.value} : p))} placeholder="us-central1, europe-west1" required/></label>
        <button type="button" className="icon-button" aria-label={`Remove project ${project.project_id || index + 1}`} onClick={() => setGcp(gcp.filter((_, i) => i !== index))}><Trash2 size={16}/></button>
      </div>)}
      {editable && <button type="button" className="button secondary" onClick={() => setGcp([...gcp, {project_id: '', regions: ''}])}><Plus size={15}/>Add project</button>}
    </fieldset>}
    {allowed.includes('kubernetes') && <fieldset className="settings-fieldset" disabled>
      <legend><ProviderBadge provider="kubernetes"/>Kubernetes clusters</legend>
      {data.settings.kubernetes_clusters.length ? <div className="subscription-list">{data.settings.kubernetes_clusters.map(c => <div key={c.cluster_id}><code>{c.cluster_id}</code><span className="inline-help">{c.prometheus_url}</span></div>)}</div> : <p className="inline-help">No clusters are connected.</p>}
      <p className="inline-help">Your platform operator manages cluster endpoints because they use operator-held tokens.</p>
    </fieldset>}
  </form>;
}

function Value({label, value}: {label: string; value: string | null | undefined}) {
  return <div><dt>{label}</dt><dd>{value ? <code>{value}</code> : 'Not configured'}</dd></div>;
}

export function IdentityOnboardingPanel() {
  const {data} = useSettings();
  if (!data) return null;
  const identity = data.identity;
  const localSignIn = identity.identity_mode === 'developer';
  return <section className="panel">
    <SectionTitle title="Resource access" action={<span className="state-badge configured"><Fingerprint size={14}/>{localSignIn ? 'Local sign-in (Azure CLI)' : 'Managed identity'}</span>}>CloudSaver never asks for client secrets or access keys. Copy the commands below to grant read-only access.</SectionTitle>
    {localSignIn && <Notice tone="info">Scans use your local Azure CLI, AWS, and gcloud credentials. Hosted deployments use a managed identity instead.</Notice>}
    <p className="inline-help"><a className="text-link" href={`/${identity.setup_guide_path || 'docs/MANAGED_IDENTITY_ROLES.md'}`} target="_blank" rel="noreferrer">View setup guide</a></p>
    <div className="identity-grid">
      <article><ProviderBadge provider="azure"/><p>Consent the CloudSaver app in your Microsoft Entra tenant, then assign Reader on each subscription.</p><dl className="settings-key-values"><Value label="App (client) ID" value={identity.azure_app_client_id}/>{identity.azure_access === 'direct' && <Value label="Managed identity client ID" value={identity.managed_identity_client_id}/>}<Value label="Access method" value={identity.azure_access === 'direct' ? 'Managed identity (same tenant)' : 'Federated app credential'}/></dl>{identity.commands?.azure?.map((line: string) => <code key={line} className="command-block">{line}</code>)}</article>
      <article><ProviderBadge provider="aws"/><p>Create a read-only role that trusts the CloudSaver hub role and requires your external ID.</p><dl className="settings-key-values"><Value label="Trusted hub role" value={identity.aws_hub_role_arn}/><Value label="External ID" value={identity.aws_external_id}/></dl>{identity.commands?.aws?.map((line: string) => <code key={line} className="command-block">{line}</code>)}</article>
      <article><ProviderBadge provider="gcp"/><p>Grant the Viewer role in each project to your CloudSaver service account.</p><dl className="settings-key-values"><Value label="Service account" value={identity.gcp_service_account}/><Value label="Workload identity provider" value={identity.gcp_workload_provider}/></dl>{identity.commands?.gcp?.map((line: string) => <code key={line} className="command-block">{line}</code>)}</article>
    </div>
  </section>;
}

export function ResourceAccessIdentityEditor() {
  const {data, reload} = useSettings();
  const {save, saving, error} = useSave(data, reload);
  const [azureAppClientId, setAzureAppClientId] = useState('');
  const [gcpServiceAccount, setGcpServiceAccount] = useState('');
  useEffect(() => {
    if (!data) return;
    setAzureAppClientId(data.settings.identity?.azure_app_client_id || '');
    setGcpServiceAccount(data.settings.identity?.gcp_service_account || '');
  }, [data]);
  if (!data) return null;
  if (data.directory_mode === 'cutover') {
    return <section className="panel">
      <SectionTitle title="Identity overrides"/>
      <Notice>Identity bindings are managed in the platform portal while this workspace is on the platform directory.</Notice>
    </section>;
  }
  async function submit() {
    await save({identity: {
      azure_app_client_id: azureAppClientId.trim() || undefined,
      gcp_service_account: gcpServiceAccount.trim() || undefined,
    }}, 'Resource access identity saved.');
  }
  return <section className="panel">
    <SectionTitle title="Identity overrides">Point CloudSaver at your own Azure app registration or GCP service account instead of the platform default.</SectionTitle>
    {error && <Notice tone="error">{error}</Notice>}
    <label className="field-label">Azure app client ID</label>
    <input className="input" value={azureAppClientId} onChange={event => setAzureAppClientId(event.target.value)} disabled={!data.editable || saving} placeholder="Platform default"/>
    <label className="field-label">GCP service account</label>
    <input className="input" value={gcpServiceAccount} onChange={event => setGcpServiceAccount(event.target.value)} disabled={!data.editable || saving} placeholder="Platform default"/>
    {data.editable && <div className="panel-bottom-action"><button type="button" className="button secondary" disabled={saving} onClick={() => void submit()}><Save size={15}/>Save</button></div>}
  </section>;
}

export function ScheduleAlertsEditor() {
  const {data, error, reload} = useSettings();
  const {save, saving, error: saveError} = useSave(data, reload);
  const [frequency, setFrequency] = useState<Frequency>('manual');
  const [alerts, setAlerts] = useState<Alerts>({enabled: false, channel: null});
  const [webhook, setWebhook] = useState('');
  useEffect(() => {
    if (!data) return;
    setFrequency(data.settings.schedule.frequency);
    setAlerts({enabled: data.settings.alerts.enabled, channel: data.settings.alerts.channel});
    setWebhook('');
  }, [data]);
  if (error) return <Notice tone="error">{error}</Notice>;
  if (!data) return <Loading label="Loading schedule and alerts…"/>;
  const {limits, platform, settings} = data;
  const editable = data.editable;
  const excluded = (['daily', 'hourly'] as Frequency[]).filter(value => !limits.allowed_scan_frequencies.includes(value));
  function submit(event: React.FormEvent) {
    event.preventDefault();
    save({schedule: {frequency}, alerts: {enabled: alerts.enabled, channel: alerts.channel, ...(webhook.trim() ? {webhook_url: webhook.trim()} : {})}}, 'Schedule and alerts saved.');
  }
  function removeWebhook() {
    save({alerts: {enabled: false, channel: alerts.channel, remove_webhook: true}}, 'Webhook removed. Alerts are off.');
  }
  return <form className="panel settings-form" onSubmit={submit}>
    <SectionTitle title="Schedule & alerts" action={editable && <button className="button primary" type="submit" disabled={saving}><Save size={15}/>{saving ? 'Saving…' : 'Save changes'}</button>}>Choose how often CloudSaver scans and where it sends results</SectionTitle>
    <ReadOnlyNotice data={data}/>
    {saveError && <Notice tone="error">{saveError}</Notice>}
    <fieldset className="settings-fieldset" disabled={!editable || saving}>
      <legend><CalendarClock size={16}/>Scheduled scans</legend>
      <label className="field-label" htmlFor="scan-frequency">Scan frequency</label>
      <select id="scan-frequency" value={frequency} onChange={e => setFrequency(e.target.value as Frequency)}>
        {(['manual', 'daily', 'hourly'] as Frequency[]).map(value => <option key={value} value={value} disabled={!limits.allowed_scan_frequencies.includes(value)}>{frequencyLabels[value]}{limits.allowed_scan_frequencies.includes(value) ? '' : ` · ${NOT_INCLUDED}`}</option>)}
      </select>
      {excluded.length > 0 && <p className="inline-help">{excluded.join(' and ').replace(/^./, c => c.toUpperCase())} scans: {NOT_INCLUDED}</p>}
      {platform && !platform.scheduled_scans_enabled && <p className="inline-help">Scheduled scans are paused for all workspaces by your platform operator. Your choice is saved and applies when they resume.</p>}
    </fieldset>
    <fieldset className="settings-fieldset" disabled={!editable || saving || !limits.can_dispatch_automated_alerts}>
      <legend><Bell size={16}/>Scan alerts</legend>
      {!limits.can_dispatch_automated_alerts && <p className="inline-help">{NOT_INCLUDED}</p>}
      <label className="checkbox-row"><input type="checkbox" checked={alerts.enabled} onChange={e => setAlerts({...alerts, enabled: e.target.checked})}/>Send a summary when a scheduled scan completes</label>
      <div className="settings-row">
        <label><span className="field-label">Channel</span><select value={alerts.channel || ''} onChange={e => setAlerts({...alerts, channel: (e.target.value || null) as Alerts['channel']})}><option value="">Choose a channel</option><option value="slack">Slack</option><option value="teams">Microsoft Teams</option></select></label>
        <label className="wide"><span className="field-label">Webhook URL</span><input type="password" autoComplete="off" value={webhook} onChange={e => setWebhook(e.target.value)} placeholder={settings.alerts.webhook_configured ? 'Webhook saved. Enter a new URL to replace it.' : 'https://hooks.slack.com/services/…'}/></label>
      </div>
      <p className="inline-help">The webhook URL is stored securely and never shown again after you save it.</p>
      {settings.alerts.webhook_configured && <button type="button" className="button secondary" onClick={removeWebhook}><Trash2 size={15}/>Remove webhook</button>}
      {platform && !platform.automated_alerts_enabled && <p className="inline-help">Automated alerts are paused for all workspaces by your platform operator.</p>}
    </fieldset>
  </form>;
}
