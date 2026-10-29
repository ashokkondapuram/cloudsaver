'use client';

import Link from 'next/link';
import {useState} from 'react';
import {Ban, KeyRound, Pencil, Plus, RotateCw, ShieldOff} from 'lucide-react';
import {portal} from '../../lib/api';
import {formatDate, formatDateTime} from '../../lib/format';
import {keyIdLabel, rolesText} from '../../lib/labels';
import type {ApiKey, Workspace} from '../../lib/types';
import {useLoad} from '../../lib/useLoad';
import {customerBillingHref} from '../billing/common';
import {useSession} from '../SessionProvider';
import {EmptyState, KeyStatusBadges, Loading, Notice, ProviderList, SectionTitle} from '../ui/shared';
import {EditKeyDialog, IssueKeyDialog, RevokeAllDialog, RevokeKeyDialog, RotateKeyDialog} from './KeyDialogs';

import {LicenseTokenDialog} from './LicenseTokenDialog';

const LIVE: ApiKey['status'][] = ['active', 'expiring_soon', 'rotating_out'];
const BLOCKED = 'This customer doesn’t have an active subscription.';

export function KeysTab({workspace, reloadWorkspace}: {workspace: Workspace; reloadWorkspace: () => Promise<void>}) {
  const {session, canWrite} = useSession();
  const [licensing,setLicensing]=useState(false);
  const [issuing, setIssuing] = useState(false);
  const [revokingAll, setRevokingAll] = useState(false);
  const [editing, setEditing] = useState<ApiKey | null>(null);
  const [rotating, setRotating] = useState<ApiKey | null>(null);
  const [revoking, setRevoking] = useState<ApiKey | null>(null);
  const [message, setMessage] = useState('');
  const {data, error, loading, reload} = useLoad(() => portal<{items: ApiKey[]}>(`workspaces/${encodeURIComponent(workspace.tenant_id)}/keys`), [workspace.tenant_id]);

  const keys = data?.items || [];
  const live = keys.filter(key => LIVE.includes(key.status));
  const editable = canWrite && workspace.status !== 'deleted';
  const blocked = !!workspace.issuance_blocked;
  const blockedTitle = blocked ? BLOCKED : undefined;
  const refreshAll = () => {void reload(); void reloadWorkspace();};

  return <section className="panel">
    <SectionTitle title="Keys" action={editable ? <div className="section-actions">
      <button type="button" className="button secondary small" disabled={blocked} onClick={()=>setLicensing(true)}>Issue license token</button>
      {live.length > 0 && <button type="button" className="button danger-outline small" onClick={() => setRevokingAll(true)}><ShieldOff size={14}/>Revoke all keys</button>}
      <button type="button" className="button primary small" disabled={blocked} title={blockedTitle} onClick={() => setIssuing(true)}><Plus size={14}/>Issue key</button>
    </div> : undefined}>Customers use workspace keys to sign in to the CloudSaver dashboard and API.</SectionTitle>
    {blocked && <Notice tone="warning">{BLOCKED} You can’t issue or rotate keys until you create a subscription or record a payment on the customer’s <Link className="text-link" href={customerBillingHref(workspace.customer_id)}>Billing tab</Link>. Existing keys keep working.</Notice>}
    {message && <Notice tone="success">{message}</Notice>}
    {error && <Notice tone="error">{error}</Notice>}
    {loading && !data ? <Loading label="Loading keys…"/> : !keys.length ? (!error && <EmptyState icon={KeyRound} title="No keys yet">Issue a key so this customer can sign in to CloudSaver.</EmptyState>) :
      <div className="summary-table-scroll"><table className="summary-table">
        <thead><tr><th>Name</th><th>Key ID</th><th>Roles</th><th>Providers</th><th>Created</th><th>Expires</th><th>Last used</th><th>Status</th>{editable && <th><span className="sr-only">Actions</span></th>}</tr></thead>
        <tbody>{keys.map(key => {
          const isLive = LIVE.includes(key.status);
          return <tr key={key.key_id}>
            <td><strong>{key.name}</strong>{key.rotated_from && <span className="cell-sub">Replaces {key.rotated_from}</span>}</td>
            <td><code>{keyIdLabel(key, session?.key_prefix)}</code></td>
            <td>{rolesText(key.roles)}</td>
            <td><ProviderList providers={key.effective_providers}/>{key.all_providers && <span className="cell-sub">Includes providers added later</span>}</td>
            <td>{formatDate(key.created_at)}<span className="cell-sub">by {key.created_by}</span></td>
            <td>{key.status === 'rotating_out' && key.rotates_out_at ? <>{formatDateTime(key.rotates_out_at)}<span className="cell-sub">Rotating out</span></> : key.expires_at ? formatDate(key.expires_at) : <span className="muted">No expiry</span>}</td>
            <td>{key.last_used_at ? <>{formatDateTime(key.last_used_at)}{key.last_used_ip && <span className="cell-sub">from {key.last_used_ip}</span>}</> : <span className="muted">Never</span>}</td>
            <td><KeyStatusBadges apiKey={key}/>{key.status === 'revoked' && key.revoked_at && <span className="cell-sub" title={key.revoke_reason || undefined}>{formatDate(key.revoked_at)}{key.revoked_by ? `, by ${key.revoked_by}` : ''}</span>}</td>
            {editable && <td><div className="row-actions">{isLive && <>
              <button type="button" className="button secondary small" onClick={() => setEditing(key)} aria-label={`Edit ${key.name}`}><Pencil size={13}/>Edit</button>
              {key.status !== 'rotating_out' && <button type="button" className="button secondary small" disabled={blocked} title={blockedTitle} onClick={() => setRotating(key)} aria-label={`Rotate ${key.name}`}><RotateCw size={13}/>Rotate</button>}
              <button type="button" className="button danger-outline small" onClick={() => setRevoking(key)} aria-label={`Revoke ${key.name}`}><Ban size={13}/>Revoke</button>
            </>}</div></td>}
          </tr>;
        })}</tbody>
      </table></div>}
    <LicenseTokenDialog open={licensing} workspace={workspace} onClose={()=>setLicensing(false)}/>
    <IssueKeyDialog open={issuing} workspace={workspace} onClose={() => setIssuing(false)} onIssued={() => {setMessage('Key issued.'); refreshAll();}}/>
    <EditKeyDialog apiKey={editing} workspace={workspace} onClose={() => setEditing(null)} onSaved={() => {setEditing(null); setMessage('Key updated.'); refreshAll();}}/>
    <RotateKeyDialog apiKey={rotating} workspace={workspace} onClose={() => setRotating(null)} onRotated={() => {setMessage('Key rotated.'); refreshAll();}}/>
    <RevokeKeyDialog apiKey={revoking} onClose={() => setRevoking(null)} onRevoked={() => {setRevoking(null); setMessage('Key revoked. Apps using it lose access within 30 seconds.'); refreshAll();}}/>
    <RevokeAllDialog open={revokingAll} workspace={workspace} activeCount={live.length} onClose={() => setRevokingAll(false)} onRevoked={count => {setRevokingAll(false); setMessage(`Revoked ${count} ${count === 1 ? 'key' : 'keys'}.`); refreshAll();}}/>
  </section>;
}
