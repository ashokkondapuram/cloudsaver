'use client';

import {useState} from 'react';
import {Copy, Loader2, ShieldCheck} from 'lucide-react';
import Link from 'next/link';
import {errorMessage, portal} from '../../lib/api';
import {formatDateTime} from '../../lib/format';
import type {PlatformSettings, Workspace} from '../../lib/types';
import {useSession} from '../SessionProvider';
import {Notice, SectionTitle} from '../ui/shared';

type Props = {workspace: Workspace; onChange: (workspace: Workspace) => void};

export function ResourceAccessTab({workspace, onChange}: Props) {
  const {canWrite} = useSession();
  const [appId, setAppId] = useState(workspace.identity.azure_app_client_id || '');
  const [serviceAccount, setServiceAccount] = useState(workspace.identity.gcp_service_account || '');
  const [platform, setPlatform] = useState<PlatformSettings | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [results, setResults] = useState<{provider: string; status: string; message: string; checked_at?: string}[]>([]);
  const path = `workspaces/${encodeURIComponent(workspace.tenant_id)}`;

  async function loadPlatform() {
    if (platform) return;
    try {
      setPlatform(await portal<PlatformSettings>('platform-settings'));
    } catch {
      setPlatform(null);
    }
  }

  async function save() {
    setBusy(true); setMessage('');
    try {
      const body = {version: workspace.version, identity: {
        azure_app_client_id: appId.trim() || null,
        gcp_service_account: serviceAccount.trim() || null,
      }};
      onChange(await portal<Workspace>(path, {method: 'PATCH', body}));
      setMessage('Resource access settings saved.');
    } catch (cause) {
      setMessage(errorMessage(cause));
    } finally {
      setBusy(false);
    }
  }

  async function testAccess() {
    await loadPlatform();
    setBusy(true); setMessage('');
    try {
      const created = await portal<{check_id: string}>('access-checks', {method: 'POST', body: {tenant_id: workspace.tenant_id}});
      let view = await portal<{status: string; result?: {providers: typeof results}}>(`access-checks/${created.check_id}`);
      for (let i = 0; i < 30 && view.status !== 'completed'; i += 1) {
        await new Promise(resolve => setTimeout(resolve, 1000));
        view = await portal(`access-checks/${created.check_id}`);
      }
      setResults(view.result?.providers || []);
    } catch (cause) {
      setMessage(errorMessage(cause));
    } finally {
      setBusy(false);
    }
  }

  const hub = platform?.resource_access_effective?.aws_hub_role_arn?.value;

  return <>
    {message && <Notice tone={message.includes('saved') ? 'success' : 'error'}>{message}</Notice>}
    <section className="panel">
      <SectionTitle title="Azure"/>
      <label className="field-label">Azure app client ID override</label>
      <input className="input" value={appId} onChange={event => setAppId(event.target.value)} disabled={!canWrite || busy}
        placeholder={platform?.resource_access_effective?.azure_app_client_id?.value || 'Platform default'}/>
      <p className="muted">Reader role ARNs are set on each account in <Link className="text-link" href="#" onClick={e => e.preventDefault()}>Cloud accounts</Link>.</p>
    </section>
    <section className="panel">
      <SectionTitle title="AWS"/>
      <dl className="detail-list">
        <div><dt>External ID</dt><dd><code>{workspace.tenant_id}</code> <button type="button" className="icon-button" onClick={() => navigator.clipboard.writeText(workspace.tenant_id)}><Copy size={14}/></button></dd></div>
        <div><dt>Trusted hub role</dt><dd>{hub ? <code>{hub}</code> : <span className="muted">Not set</span>}</dd></div>
      </dl>
      <p className="muted">Reader role ARNs are set on each account in Cloud accounts.</p>
    </section>
    <section className="panel">
      <SectionTitle title="Google Cloud"/>
      <label className="field-label">Reader service account</label>
      <input className="input" value={serviceAccount} onChange={event => setServiceAccount(event.target.value)} disabled={!canWrite || busy}/>
    </section>
    {canWrite && <div className="panel-footer">
      <button type="button" className="button primary small" disabled={busy} onClick={() => void save()}>{busy ? <Loader2 className="spin" size={14}/> : null}Save</button>
      <button type="button" className="button secondary small" disabled={busy} onClick={() => void testAccess()}><ShieldCheck size={14}/>Test access</button>
    </div>}
    {results.length > 0 && <section className="panel">
      <SectionTitle title="Test results"/>
      <ul className="simple-list">
        {results.map(row => <li key={row.provider}><strong>{row.provider}</strong> — {row.message}{row.checked_at ? ` · ${formatDateTime(row.checked_at)}` : ''}</li>)}
      </ul>
    </section>}
  </>;
}
