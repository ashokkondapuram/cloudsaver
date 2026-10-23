'use client';

import {useState} from 'react';
import {Loader2, ShieldQuestion} from 'lucide-react';
import {errorMessage, portal} from '../../lib/api';
import type {AnalysisRule, Workspace, WorkspaceAnalysisRules} from '../../lib/types';
import {useLoad} from '../../lib/useLoad';
import {useSession} from '../SessionProvider';
import {EmptyState, Loading, Notice, SectionTitle, Switch} from '../ui/shared';

type Props = {workspace: Workspace};

export function RulesTab({workspace}: Props) {
  const {canWrite} = useSession();
  const path = `workspaces/${encodeURIComponent(workspace.tenant_id)}/analysis-rules`;
  const {data, setData, error, loading} = useLoad(() => portal<WorkspaceAnalysisRules>(path), [path]);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [message, setMessage] = useState('');

  async function toggle(rule: AnalysisRule) {
    if (!data) return;
    setBusyId(rule.id); setMessage('');
    try {
      const updated = await portal<WorkspaceAnalysisRules>(path, {
        method: 'PUT',
        body: {version: workspace.version, rules: [{rule_id: rule.id, enabled: !rule.enabled}]},
      });
      setData(updated);
    } catch (cause) {
      setMessage(errorMessage(cause));
    } finally {
      setBusyId(null);
    }
  }

  if (loading && !data) return <Loading label="Loading rules…"/>;
  const items = data?.items || [];

  return <>
    {error && <Notice tone="error">{error}</Notice>}
    {message && <Notice tone="error">{message}</Notice>}
    <section className="panel">
      <SectionTitle title="Published rules" eyebrow={`${items.length} in catalog`}/>
      {!items.length ? <EmptyState icon={ShieldQuestion} title="No published rules">The rule catalog is empty.</EmptyState> :
        <div className="summary-table-scroll"><table className="summary-table">
          <thead><tr><th>Rule</th><th>Provider</th><th>Service</th><th>Pillar</th><th>State</th><th/></tr></thead>
          <tbody>{items.map(rule => <tr key={rule.id}>
            <td>{rule.name}{rule.description && <div className="muted">{rule.description}</div>}</td>
            <td>{rule.provider}</td>
            <td>{rule.service_category}</td>
            <td>{rule.pillar}</td>
            <td>{rule.unavailable_reason ? <span className="state-badge deleted" title={rule.unavailable_reason}>Unavailable</span> :
                rule.enabled ? <span className="state-badge active">Enabled</span> : <span className="state-badge suspended">Disabled</span>}</td>
            <td>{canWrite && !rule.unavailable_reason && (busyId === rule.id ? <Loader2 className="spin" size={14}/> :
                <Switch checked={rule.enabled} onChange={() => void toggle(rule)} label={`Toggle ${rule.name}`}/>)}</td>
          </tr>)}</tbody>
        </table></div>}
    </section>
  </>;
}
