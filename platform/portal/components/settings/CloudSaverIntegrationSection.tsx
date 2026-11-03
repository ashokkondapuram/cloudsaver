'use client';

import {useEffect, useState} from 'react';
import {Loader2, Save} from 'lucide-react';
import {errorMessage, portal} from '../../lib/api';
import {DEPLOYMENT_ONLY_SETTINGS, INTEGRATION_FIELDS} from '../../lib/cloudsaverConfigHints';
import type {CloudSaverIntegrationEffective, PlatformSettings} from '../../lib/types';
import {useSession} from '../SessionProvider';
import {FieldLabel, InfoButton} from '../ui/InfoButton';
import {Notice, SectionTitle, Switch} from '../ui/shared';

type Props = {settings: PlatformSettings; onSaved: (settings: PlatformSettings) => void};

function sourceLabel(source: string) {
  if (source === 'environment') return 'From CloudSaver .env';
  if (source === 'platform') return 'From platform settings';
  return 'Not set';
}

function displayValue(key: string, effective: CloudSaverIntegrationEffective | undefined, raw: unknown) {
  if (key === 'default_billing_currency') return String(raw || effective?.[key]?.value || 'USD');
  if (typeof raw === 'boolean') return raw ? 'On' : 'Off';
  if (typeof effective?.[key]?.value === 'boolean') return effective[key].value ? 'On' : 'Off';
  if (typeof raw === 'number') return raw === 0 ? 'No cap (0)' : String(raw);
  if (typeof effective?.[key]?.value === 'number') {
    const value = effective[key].value as number;
    return value === 0 ? 'No cap (0)' : String(value);
  }
  return effective?.[key]?.value ?? '—';
}

export function CloudSaverIntegrationSection({settings, onSaved}: Props) {
  const {canWrite} = useSession();
  const effective = settings.cloudsaver_integration_effective || {};
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<Record<string, string | boolean>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!editing) return;
    const next: Record<string, string | boolean> = {};
    for (const field of INTEGRATION_FIELDS) {
      const stored = settings.cloudsaver_integration?.[field.key as keyof typeof settings.cloudsaver_integration];
      const eff = effective[field.key]?.value;
      if (field.type === 'bool') next[field.key] = typeof stored === 'boolean' ? stored : Boolean(eff);
      else if (field.type === 'int') next[field.key] = String(stored ?? eff ?? 0);
      else next[field.key] = String(stored ?? eff ?? 'USD');
    }
    setDraft(next);
  }, [editing, settings, effective]);

  async function save() {
    setBusy(true); setError('');
    const patch: Record<string, boolean | number | string | null> = {};
    for (const field of INTEGRATION_FIELDS) {
      const current = settings.cloudsaver_integration?.[field.key as keyof typeof settings.cloudsaver_integration];
      if (field.type === 'bool') {
        const next = Boolean(draft[field.key]);
        if (next !== current) patch[field.key] = next;
      } else if (field.type === 'int') {
        const next = parseInt(String(draft[field.key] ?? '0'), 10);
        if (Number.isNaN(next) || next < 0 || next > 50000) {
          setError('Resource limits must be between 0 and 50000.');
          setBusy(false);
          return;
        }
        if (next !== current) patch[field.key] = next;
      } else {
        const next = String(draft[field.key] || '').trim().toUpperCase();
        if (next !== (current || effective[field.key]?.value || '')) patch[field.key] = next || null;
      }
    }
    try {
      onSaved(await portal<PlatformSettings>('platform-settings', {
        method: 'PUT',
        body: {version: settings.version, cloudsaver_integration: patch},
      }));
      setEditing(false);
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setBusy(false);
    }
  }

  return <>
    <section className="panel">
      <SectionTitle title="CloudSaver integration" action={canWrite ? <div className="section-actions">
        {!editing ? <button type="button" className="button secondary small" onClick={() => setEditing(true)}>Edit</button>
          : <>
            <button type="button" className="button secondary small" disabled={busy} onClick={() => setEditing(false)}>Cancel</button>
            <button type="button" className="button primary small" disabled={busy} onClick={() => void save()}>
              {busy ? <Loader2 className="spin" size={14}/> : <Save size={14}/>}Save
            </button>
          </>}
      </div> : undefined}>
        <p>Stack behavior for every workspace. Secrets and connection strings stay in CloudSaver <code>.env</code>.</p>
      </SectionTitle>
      {error && <Notice tone="error">{error}</Notice>}
      <dl className="detail-list integration-list">
        {INTEGRATION_FIELDS.map(field => <div key={field.key}>
          <dt>
            <FieldLabel label={field.label} hint={field.hint} info={<>
              <strong>{field.info.summary}</strong>
              <p>{field.info.detail}</p>
              {field.info.env && <p className="muted">Env: <code>{field.info.env}</code></p>}
            </>}/>
          </dt>
          <dd>
            {editing ? (field.type === 'bool'
              ? <Switch checked={Boolean(draft[field.key])} label={field.label}
                  onChange={value => setDraft({...draft, [field.key]: value})}/>
              : <input className="input" value={String(draft[field.key] ?? '')}
                  onChange={event => setDraft({...draft, [field.key]: event.target.value})}/>)
              : <code>{displayValue(field.key, effective, settings.cloudsaver_integration?.[field.key as keyof typeof settings.cloudsaver_integration])}</code>}
            <span className="cell-sub">{sourceLabel(effective[field.key]?.source || 'unset')}</span>
          </dd>
        </div>)}
      </dl>
    </section>
    <section className="panel">
      <SectionTitle title="Deployment-only settings">
        <p>Configure these in CloudSaver or platform <code>.env</code> files. They are documented here for operators.</p>
      </SectionTitle>
      <ul className="deployment-config-list">
        {DEPLOYMENT_ONLY_SETTINGS.map(item => <li key={item.env}>
          <div className="deployment-config-head">
            <code>{item.env}</code>
            <InfoButton label={item.summary}><strong>{item.summary}</strong><p>{item.detail}</p></InfoButton>
          </div>
        </li>)}
      </ul>
    </section>
  </>;
}
