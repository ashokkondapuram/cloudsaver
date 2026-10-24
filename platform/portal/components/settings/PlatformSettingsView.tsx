'use client';

import {useEffect, useState} from 'react';
import {Loader2, Save} from 'lucide-react';
import {errorMessage, portal} from '../../lib/api';
import {formatAttribution} from '../../lib/format';
import type {PlatformSettings} from '../../lib/types';
import {useLoad} from '../../lib/useLoad';
import {useSession} from '../SessionProvider';
import {Loading, Notice, PageHeading, SectionTitle, Switch} from '../ui/shared';
import {BillingSettingsSection} from './BillingSettingsSection';
import {ResourceAccessSection} from './ResourceAccessSection';
import {AIPolicySection} from './AIPolicySection';

export function PlatformSettingsView() {
  const {canWrite} = useSession();
  const {data, setData, error, loading, reload} = useLoad(() => portal<PlatformSettings>('platform-settings'), []);
  const [scans, setScans] = useState(false);
  const [alerts, setAlerts] = useState(false);
  const [busy, setBusy] = useState(false);
  const [saveError, setSaveError] = useState('');
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (!data) return;
    setScans(data.scheduled_scans_enabled); setAlerts(data.automated_alerts_enabled);
  }, [data]);

  const dirty = !!data && (scans !== data.scheduled_scans_enabled || alerts !== data.automated_alerts_enabled);

  async function save() {
    if (!data) return;
    setBusy(true); setSaveError(''); setSaved(false);
    try {
      setData(await portal<PlatformSettings>('platform-settings', {method: 'PUT', body: {version: data.version, scheduled_scans_enabled: scans, automated_alerts_enabled: alerts}}));
      setSaved(true);
    } catch (cause) {
      setSaveError(errorMessage(cause));
    } finally {
      setBusy(false);
    }
  }

  return <>
    <PageHeading eyebrow="PLATFORM" title="Platform settings">Switches and billing rules that apply to every workspace.</PageHeading>
    {loading && !data ? <Loading label="Loading settings…"/> : !data ? <Notice tone="error">{error || 'Something went wrong. If the issue persists, contact Support.'}</Notice> : <section className="panel">
      <SectionTitle title="Automation"/>
      {saveError && <Notice tone="error">{saveError} {saveError.includes('Refresh') && <button type="button" className="text-button" onClick={() => void reload()}>Refresh</button>}</Notice>}
      {saved && !dirty && <Notice tone="success">Settings saved.</Notice>}
      <div className="switch-row">
        <div><h3 id="scans-label">Scheduled scans</h3><p>Run resource scans for every active workspace on its schedule.</p></div>
        <Switch checked={scans} onChange={value => {setScans(value); setSaved(false);}} label="Scheduled scans" disabled={!canWrite || busy}/>
      </div>
      <div className="switch-row">
        <div><h3 id="alerts-label">Automated alerts</h3><p>Send alerts to workspace integrations when scans find new savings.</p></div>
        <Switch checked={alerts} onChange={value => {setAlerts(value); setSaved(false);}} label="Automated alerts" disabled={!canWrite || busy}/>
      </div>
      <div className="panel-footer">
        <span>Last changed {formatAttribution(data.updated_at, data.updated_by)}</span>
        {canWrite && <button type="button" className="button primary small" disabled={!dirty || busy} onClick={() => void save()}>{busy ? <Loader2 className="spin" size={14}/> : <Save size={14}/>}Save changes</button>}
      </div>
    </section>}
    {data && <ResourceAccessSection settings={data} onSaved={setData}/>}
    <BillingSettingsSection/>
    <AIPolicySection/>
  </>;
}
