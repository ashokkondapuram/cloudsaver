'use client';

import {useEffect, useState} from 'react';
import {Loader2, Palette} from 'lucide-react';
import {ApiError, errorMessage, portal} from '../../lib/api';
import type {Workspace} from '../../lib/types';
import {UI_THEME_LABELS, UI_THEME_META, UI_THEME_PRESETS, type UiThemePreset} from '../../lib/ui-theme';
import {useSession} from '../SessionProvider';
import {Notice, SectionTitle} from '../ui/shared';

type Props = {workspace: Workspace; onChange: (workspace: Workspace) => void};

export function WorkspaceThemeSection({workspace, onChange}: Props) {
  const {canWrite} = useSession();
  const [preset, setPreset] = useState<UiThemePreset>(workspace.ui_theme_preset || 'console');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const editable = canWrite && workspace.status === 'active';

  useEffect(() => {
    setPreset(workspace.ui_theme_preset || 'console');
  }, [workspace.tenant_id, workspace.ui_theme_preset, workspace.version]);

  async function save(next: UiThemePreset) {
    setBusy(true); setError(''); setMessage('');
    try {
      const updated = await portal<Workspace>(`workspaces/${encodeURIComponent(workspace.tenant_id)}`, {
        method: 'PATCH',
        body: {version: workspace.version, ui_theme_preset: next},
      });
      onChange(updated);
      setPreset(updated.ui_theme_preset || 'console');
      setMessage('Dashboard theme saved. Users see it the next time they open the workspace console.');
    } catch (err) {
      setError(errorMessage(err as ApiError));
      setPreset(workspace.ui_theme_preset || 'console');
    } finally {
      setBusy(false);
    }
  }

  return <section className="panel">
    <SectionTitle title="Dashboard appearance" action={busy ? <Loader2 size={16} className="spin"/> : undefined}/>
    <p className="muted" style={{margin: '0 24px 16px'}}>
      Choose the CloudSaver console skin for this client workspace. Operators assign themes here; end users inherit the preset when they connect.
    </p>
    {message && <Notice tone="success">{message}</Notice>}
    {error && <Notice tone="error">{error}</Notice>}
    <div className="theme-preset-grid">
      {UI_THEME_PRESETS.map(id => {
        const active = preset === id;
        return <button key={id} type="button" className={`theme-preset-card${active ? ' active' : ''}`} disabled={!editable || busy}
          aria-pressed={active} onClick={() => {setPreset(id); void save(id);}}>
          <span className={`theme-swatch theme-swatch-${id.replace(/[^a-z0-9]+/g, '-')}`} aria-hidden><Palette size={18}/></span>
          <strong>{UI_THEME_LABELS[id]}</strong>
          <small>{UI_THEME_META[id].description}</small>
        </button>;
      })}
    </div>
  </section>;
}
