'use client';

import {useEffect, useState} from 'react';
import {Loader2, Save, ShieldCheck} from 'lucide-react';
import {errorMessage, portal} from '../../lib/api';
import type {PlatformSettings} from '../../lib/types';
import {useSession} from '../SessionProvider';
import {ConfirmDialog} from '../customers/CustomerDialogs';
import {Notice, SectionTitle} from '../ui/shared';

type Props = {settings: PlatformSettings; onSaved: (settings: PlatformSettings) => void};

const FIELDS = [
  {key: 'managed_identity_client_id', label: 'Managed identity client ID'},
  {key: 'azure_access', label: 'Azure access method'},
  {key: 'azure_app_client_id', label: 'Azure app client ID'},
  {key: 'azure_token_audience', label: 'Azure token audience'},
  {key: 'aws_hub_role_arn', label: 'AWS hub role ARN'},
  {key: 'aws_token_audience', label: 'AWS token audience'},
  {key: 'gcp_workload_provider', label: 'GCP workload identity provider'},
  {key: 'gcp_token_audience', label: 'GCP token audience'},
] as const;

function sourceLabel(source: string) {
  if (source === 'environment') return 'From environment';
  if (source === 'platform') return 'From platform settings';
  return 'Not set';
}

export function ResourceAccessSection({settings, onSaved}: Props) {
  const {canWrite} = useSession();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [confirmMi, setConfirmMi] = useState(false);
  const effective = settings.resource_access_effective || {};

  useEffect(() => {
    if (!editing) return;
    const values: Record<string, string> = {};
    for (const field of FIELDS) {
      values[field.key] = settings.resource_access?.[field.key] || '';
    }
    setDraft(values);
  }, [editing, settings]);

  async function save() {
    setBusy(true); setError('');
    const patch: Record<string, string | null> = {};
    for (const field of FIELDS) {
      const next = draft[field.key]?.trim() || '';
      const current = settings.resource_access?.[field.key] || '';
      if (next !== current) patch[field.key] = next || null;
    }
    if (patch.managed_identity_client_id && patch.managed_identity_client_id !== settings.resource_access?.managed_identity_client_id) {
      setConfirmMi(true);
      setBusy(false);
      return;
    }
    await persist(patch);
  }

  async function persist(patch: Record<string, string | null>) {
    setBusy(true); setError('');
    try {
      onSaved(await portal<PlatformSettings>('platform-settings', {method: 'PUT', body: {version: settings.version, resource_access: patch}}));
      setEditing(false);
      setConfirmMi(false);
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setBusy(false);
    }
  }

  async function testAccess() {
    setBusy(true); setError('');
    try {
      const created = await portal<{check_id: string}>('access-checks', {method: 'POST', body: {}});
      const result = await portal<{status: string; result?: {providers: {provider: string; status: string; message: string}[]}}>(
        `access-checks/${created.check_id}`);
      const row = result.result?.providers?.find(p => p.provider === 'managed_identity');
      if (row) setError(row.message);
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setBusy(false);
    }
  }

  return <section className="panel">
    <SectionTitle title="Resource access" action={canWrite ? <div className="section-actions">
      {!editing ? <>
        <button type="button" className="button secondary small" onClick={() => setEditing(true)}>Edit</button>
        <button type="button" className="button secondary small" disabled={busy} onClick={() => void testAccess()}><ShieldCheck size={14}/>Test access</button>
      </> : <>
        <button type="button" className="button secondary small" onClick={() => setEditing(false)} disabled={busy}>Cancel</button>
        <button type="button" className="button primary small" disabled={busy} onClick={() => void save()}>{busy ? <Loader2 className="spin" size={14}/> : <Save size={14}/>}Save</button>
      </>}
    </div> : undefined}/>
    {error && <Notice tone={error.includes('ready') ? 'success' : 'error'}>{error}</Notice>}
    <dl className="detail-list">
      {FIELDS.map(field => <div key={field.key}>
        <dt>{field.label}</dt>
        <dd>
          {editing ? <input className="input" value={draft[field.key] || ''} onChange={event => setDraft({...draft, [field.key]: event.target.value})}/>
            : <code>{settings.resource_access?.[field.key] || effective[field.key]?.value || <span className="muted">Not set</span>}</code>}
          <span className="cell-sub">{sourceLabel(effective[field.key]?.source || 'unset')}</span>
        </dd>
      </div>)}
    </dl>
    <ConfirmDialog open={confirmMi} title="Change managed identity?" confirmLabel="Confirm"
      body="Scans use this identity right away. Make sure it's attached to the scanner, worker and dispatcher containers."
      onClose={() => setConfirmMi(false)} onConfirm={async () => {
        const patch: Record<string, string | null> = {};
        for (const field of FIELDS) {
          const next = draft[field.key]?.trim() || '';
          const current = settings.resource_access?.[field.key] || '';
          if (next !== current) patch[field.key] = next || null;
        }
        await persist(patch);
      }}/>
  </section>;
}
