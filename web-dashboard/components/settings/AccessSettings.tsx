'use client';

import {useCallback, useEffect, useState} from 'react';
import {Bot, Check, Copy, Download, KeyRound, RefreshCw, ShieldCheck, UserPlus, Users} from 'lucide-react';
import {api} from '../../lib/api';
import type {AccessEvent, AccessKey, CustomerRole, CustomerUser, ServiceAccount, WorkspaceMember} from '../../lib/types';
import {useWorkspace} from '../WorkspaceProvider';
import {Dialog} from '../ui/dialog';
import {EmptyState, Loading, Notice, SectionTitle} from '../ui/shared';

const WORKSPACE_ROLES = ['TenantAdmin', 'BillingAdmin', 'Viewer'];
const ROLE_LABELS: Record<string, string> = {
  CustomerOwner: 'Owner', CustomerAdmin: 'Administrator', CustomerAuditor: 'Auditor',
  TenantAdmin: 'Workspace admin', BillingAdmin: 'Billing admin', Viewer: 'Viewer',
};
const ACTION_LABELS: Record<string, string> = {
  customer_claimed: 'Account claimed', user_invited: 'User invited', user_suspended: 'User suspended',
  user_reactivated: 'User reactivated', ownership_transferred: 'Ownership transferred',
  workspace_membership_changed: 'Workspace access changed', workspace_membership_removed: 'Workspace access removed',
  service_account_created: 'Service account created', service_account_updated: 'Service account updated',
  issued: 'Key issued', revoked: 'Key revoked', rotated: 'Key rotated', bootstrap_issued: 'Onboarding key issued',
};

function when(value: string | null) {
  if (!value) return 'Never';
  const d = new Date(value);
  if (Number.isNaN(d.valueOf())) return 'Unknown';
  const date = d.toLocaleDateString('en-US', {month: 'short', day: 'numeric', year: 'numeric'});
  const time = d.toLocaleTimeString('en-US', {hour: 'numeric', minute: '2-digit'});
  return `${date} at ${time}`;
}

const roleList = (roles: string[]) => roles.map(r => ROLE_LABELS[r] || r).join(', ');
const defaultExpiry = () => new Date(Date.now() + 90 * 86400000).toISOString().slice(0, 10);

type Data = {users: CustomerUser[]; members: WorkspaceMember[]; accounts: ServiceAccount[]; keys: AccessKey[]; audit: AccessEvent[]};
type Pending =
  | {kind: 'invite'} | {kind: 'member'; user?: WorkspaceMember} | {kind: 'account'} | {kind: 'key'}
  | {kind: 'confirm'; title: string; body: string; label: string; run: () => Promise<unknown>}
  | null;

export function AccessSettings() {
  const {token, workspace, notify} = useWorkspace();
  const keyAdmin = workspace?.subject_type === 'operator' && !!workspace.roles?.includes('TenantAdmin');
  const roles: CustomerRole[] = keyAdmin ? ['CustomerAdmin'] : workspace?.customer_roles || [];
  const isAdmin = roles.includes('CustomerOwner') || roles.includes('CustomerAdmin');
  const isOwner = roles.includes('CustomerOwner');
  const [data, setData] = useState<Data | null>(null);
  const [error, setError] = useState('');
  const [pending, setPending] = useState<Pending>(null);
  const [secret, setSecret] = useState('');

  const load = useCallback(async (signal?: AbortSignal) => {
    try {
      const [users, members, accounts, keys, audit] = await Promise.all([
        api<{items: CustomerUser[]}>('/customer/users', token, {signal}),
        api<{items: WorkspaceMember[]}>('/customer/members', token, {signal}),
        api<{items: ServiceAccount[]}>('/customer/service-accounts', token, {signal}),
        api<{items: AccessKey[]}>('/customer/keys', token, {signal}),
        api<{items: AccessEvent[]}>('/customer/audit', token, {signal}),
      ]);
      setData({users: users.items, members: members.items, accounts: accounts.items, keys: keys.items, audit: audit.items});
      setError('');
    } catch (cause) {
      if (!signal?.aborted) setError(cause instanceof Error ? cause.message : 'Access settings could not be loaded.');
    }
  }, [token]);

  useEffect(() => {
    if (!roles.length) return;
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load, roles.length]);

  async function act(run: () => Promise<unknown>, message: string) {
    try {
      await run();
      notify(message);
      setPending(null);
      await load();
    } catch (cause) {
      notify(cause instanceof Error ? cause.message : 'This change could not be saved.', 'error');
    }
  }

  async function exportCsv() {
    try {
      const response = await fetch('/api/v1/customer/access-export', {headers: {Authorization: 'Bearer ' + token}, cache: 'no-store'});
      if (!response.ok) throw new Error('The access review could not be exported.');
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement('a');
      link.href = url; link.download = 'access-review.csv'; link.click();
      URL.revokeObjectURL(url);
    } catch (cause) {
      notify(cause instanceof Error ? cause.message : 'The access review could not be exported.', 'error');
    }
  }

  if (!roles.length) {
    return <section className="panel"><SectionTitle title="Users and keys">Manage who can use this workspace</SectionTitle>
      <EmptyState icon={Users} title="Organization access isn't available with this key">Connect with your personal key to manage users and keys. If your organization hasn't been claimed yet, ask your platform operator for an onboarding key and open the claim page.</EmptyState>
    </section>;
  }
  if (error && !data) return <Notice tone="error">{error}</Notice>;
  if (!data) return <Loading label="Loading users and keys…"/>;

  const names = new Map<string, string>([...data.users.map(u => [u.user_id, u.display_name] as [string, string]),
    ...data.accounts.map(a => [a.service_account_id, a.name] as [string, string])]);
  const subject = (key: AccessKey) => key.subject_id ? names.get(key.subject_id) || 'Unknown' : 'Platform operator';

  return <>
    {!isAdmin && <Notice tone="info">You have auditor access. You can review users, keys, and activity, but you can't make changes.</Notice>}
    {workspace?.scope_restrictions && <Notice tone="info">Your key is limited to some cloud scopes.</Notice>}
    {keyAdmin && <Notice tone="info">You’re signed in with a workspace admin key. You can add people to this workspace and issue their keys. Your organization owner manages user status.</Notice>}

    <section className="panel">
      <SectionTitle title="Organization users" action={<div className="section-actions">
        <button type="button" className="button secondary" onClick={() => void load()}><RefreshCw size={15}/>Refresh</button>
        <button type="button" className="button secondary" onClick={() => void exportCsv()}><Download size={15}/>Export access review</button>
        {isAdmin && <button type="button" className="button primary" onClick={() => setPending({kind: 'invite'})}><UserPlus size={15}/>Invite user</button>}
      </div>}>People who can manage your organization’s access</SectionTitle>
      <div className="summary-table-scroll"><table className="summary-table">
        <thead><tr><th>Name</th><th>Email</th><th>Role</th><th>Status</th>{isAdmin && <th><span className="sr-only">Actions</span></th>}</tr></thead>
        <tbody>{data.users.map(user => <tr key={user.user_id}>
          <td>{user.display_name}</td><td>{user.email || '—'}</td><td>{ROLE_LABELS[user.customer_role]}</td>
          <td>{user.membership_status === 'active' ? 'Active' : 'Suspended'}</td>
          {isAdmin && <td className="row-actions">{!keyAdmin && user.customer_role !== 'CustomerOwner' && user.user_id !== workspace?.subject_id && <>
            {user.membership_status === 'active'
              ? <button type="button" className="button secondary small" onClick={() => setPending({kind: 'confirm', title: `Suspend ${user.display_name}?`, label: 'Suspend user',
                  body: `${user.display_name} loses access right away and every key issued to them is revoked. You can reactivate them later, but you'll need to issue new keys.`,
                  run: () => api(`/customer/users/${user.user_id}/suspend`, token, {body: {}})})}>Suspend</button>
              : <button type="button" className="button secondary small" onClick={() => void act(() => api(`/customer/users/${user.user_id}/reactivate`, token, {body: {}}), `${user.display_name} reactivated.`)}>Reactivate</button>}
            {isOwner && user.membership_status === 'active' && <button type="button" className="button secondary small" onClick={() => setPending({kind: 'confirm', title: `Make ${user.display_name} the owner?`, label: 'Transfer ownership',
              body: `${user.display_name} becomes the owner of your organization. You'll stay an administrator.`,
              run: () => api('/customer/ownership/transfer', token, {body: {user_id: user.user_id}})})}>Make owner</button>}
          </>}</td>}
        </tr>)}</tbody>
      </table></div>
    </section>

    <section className="panel">
      <SectionTitle title="Workspace members" action={isAdmin ? <button type="button" className="button secondary" onClick={() => setPending({kind: 'member'})}><Users size={15}/>Add member</button> : undefined}>Roles each person has in {workspace?.name}</SectionTitle>
      {data.members.length ? <div className="summary-table-scroll"><table className="summary-table">
        <thead><tr><th>Name</th><th>Workspace roles</th>{isAdmin && <th><span className="sr-only">Actions</span></th>}</tr></thead>
        <tbody>{data.members.map(member => <tr key={member.user_id}>
          <td>{member.display_name}</td><td>{roleList(member.roles)}</td>
          {isAdmin && <td className="row-actions">
            <button type="button" className="button secondary small" onClick={() => setPending({kind: 'member', user: member})}>Edit roles</button>
            <button type="button" className="button secondary small" onClick={() => setPending({kind: 'confirm', title: `Remove ${member.display_name}?`, label: 'Remove access',
              body: `${member.display_name} loses access to ${workspace?.name} and their keys for this workspace are revoked.`,
              run: () => api(`/customer/members/${member.user_id}/remove`, token, {body: {version: member.version}})})}>Remove</button>
          </td>}
        </tr>)}</tbody>
      </table></div> : <p className="inline-help">No members yet.</p>}
    </section>

    <section className="panel">
      <SectionTitle title="Service accounts" action={isAdmin ? <button type="button" className="button secondary" onClick={() => setPending({kind: 'account'})}><Bot size={15}/>Create service account</button> : undefined}>Non-human identities for automation and CI</SectionTitle>
      {data.accounts.filter(a => a.status !== 'deleted').length ? <div className="summary-table-scroll"><table className="summary-table">
        <thead><tr><th>Name</th><th>Description</th><th>Status</th>{isAdmin && <th><span className="sr-only">Actions</span></th>}</tr></thead>
        <tbody>{data.accounts.filter(a => a.status !== 'deleted').map(account => <tr key={account.service_account_id}>
          <td>{account.name}</td><td>{account.description || '—'}</td><td>{account.status === 'active' ? 'Active' : 'Suspended'}</td>
          {isAdmin && <td className="row-actions">
            {account.status === 'active'
              ? <button type="button" className="button secondary small" onClick={() => setPending({kind: 'confirm', title: `Suspend ${account.name}?`, label: 'Suspend service account',
                  body: `Every key issued to ${account.name} is revoked right away.`,
                  run: () => api(`/customer/service-accounts/${account.service_account_id}`, token, {method: 'PATCH', body: {version: account.version, status: 'suspended'}})})}>Suspend</button>
              : <button type="button" className="button secondary small" onClick={() => void act(() => api(`/customer/service-accounts/${account.service_account_id}`, token, {method: 'PATCH', body: {version: account.version, status: 'active'}}), `${account.name} reactivated.`)}>Reactivate</button>}
          </td>}
        </tr>)}</tbody>
      </table></div> : <p className="inline-help">No service accounts yet.</p>}
    </section>

    <section className="panel">
      <SectionTitle title="Access keys" action={isAdmin ? <button type="button" className="button primary" onClick={() => setPending({kind: 'key'})}><KeyRound size={15}/>Issue key</button> : undefined}>Keys for {workspace?.name}. Secrets are shown once, when you issue a key.</SectionTitle>
      {data.keys.length ? <div className="summary-table-scroll"><table className="summary-table">
        <thead><tr><th>Name</th><th>Issued to</th><th>Roles</th><th>Status</th><th>Expires</th><th>Last used</th>{isAdmin && <th><span className="sr-only">Actions</span></th>}</tr></thead>
        <tbody>{data.keys.map(key => <tr key={key.key_id}>
          <td>{key.name}<br/><code>{key.key_id}</code></td><td>{subject(key)}</td><td>{roleList(key.roles)}{key.scope_restrictions && <><br/><small>Limited scopes</small></>}</td>
          <td className="capitalize">{key.status.replace('_', ' ')}</td><td>{when(key.expires_at)}</td><td>{when(key.last_used_at)}</td>
          {isAdmin && <td className="row-actions">{key.subject_type !== 'operator' && !['revoked', 'expired'].includes(key.status) && key.key_id !== workspace?.key_id && <>
            <button type="button" className="button secondary small" onClick={() => void act(async () => {const rotated = await api<{secret: string}>(`/customer/keys/${key.key_id}/rotate`, token, {body: {overlap_hours: 24}}); setSecret(rotated.secret);}, 'Key rotated. The old key keeps working for 24 hours.')}>Rotate</button>
            <button type="button" className="button secondary small" onClick={() => setPending({kind: 'confirm', title: `Revoke ${key.name}?`, label: 'Revoke key',
              body: 'Anything using this key stops working right away. You can’t undo this.',
              run: () => api(`/customer/keys/${key.key_id}/revoke`, token, {body: {}})})}>Revoke</button>
          </>}</td>}
        </tr>)}</tbody>
      </table></div> : <p className="inline-help">No keys yet.</p>}
    </section>

    <section className="panel">
      <SectionTitle title="Activity">Recent access changes in your organization</SectionTitle>
      {data.audit.length ? <div className="summary-table-scroll"><table className="summary-table">
        <thead><tr><th>When</th><th>Change</th><th>By</th></tr></thead>
        <tbody>{data.audit.slice(0, 50).map(event => <tr key={event.id}>
          <td>{when(event.occurred_at)}</td><td>{ACTION_LABELS[event.action] || event.action.replaceAll('_', ' ')}</td>
          <td>{event.actor_type === 'customer' ? names.get(event.actor) || 'Your organization' : event.actor_type === 'operator' ? 'Platform operator' : 'System'}</td>
        </tr>)}</tbody>
      </table></div> : <p className="inline-help">No activity yet.</p>}
    </section>

    <InviteDialog open={pending?.kind === 'invite'} onClose={() => setPending(null)} onSubmit={body => act(() => api('/customer/users/invite', token, {body}), `Invitation sent to ${body.email}.`)}/>
    <MemberDialog pending={pending?.kind === 'member' ? pending : null} users={data.users} members={data.members} onClose={() => setPending(null)}
      onSubmit={(userId, roles, version) => act(() => api(`/customer/members/${userId}`, token, {method: 'PUT', body: {roles, version}}), 'Workspace access saved.')}/>
    <AccountDialog open={pending?.kind === 'account'} onClose={() => setPending(null)} onSubmit={body => act(() => api('/customer/service-accounts', token, {body}), `${body.name} created.`)}/>
    <KeyDialog open={pending?.kind === 'key'} members={data.members} accounts={data.accounts.filter(a => a.status === 'active')} onClose={() => setPending(null)}
      onSubmit={body => act(async () => {const issued = await api<{secret: string}>('/customer/keys', token, {body}); setSecret(issued.secret);}, 'Key issued.')}/>
    <Dialog open={pending?.kind === 'confirm'} onClose={() => setPending(null)} title={pending?.kind === 'confirm' ? pending.title : ''}>
      {pending?.kind === 'confirm' && <><div className="dialog-content"><p>{pending.body}</p></div>
        <div className="dialog-actions"><button type="button" className="button secondary" onClick={() => setPending(null)}>Cancel</button>
          <button type="button" className="button danger" onClick={() => void act(pending.run, 'Change saved.')}>{pending.label}</button></div></>}
    </Dialog>
    <SecretDialog secret={secret} onClose={() => setSecret('')}/>
  </>;
}

function InviteDialog({open, onClose, onSubmit}: {open: boolean; onClose: () => void; onSubmit: (body: {display_name: string; email: string; role: string}) => Promise<void>}) {
  const [name, setName] = useState(''), [email, setEmail] = useState(''), [role, setRole] = useState('CustomerAdmin');
  useEffect(() => {if (open) {setName(''); setEmail(''); setRole('CustomerAdmin');}}, [open]);
  const valid = name.trim() && /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email.trim());
  return <Dialog open={open} onClose={onClose} title="Invite user">
    <form onSubmit={event => {event.preventDefault(); if (valid) void onSubmit({display_name: name.trim(), email: email.trim(), role});}}>
      <div className="dialog-content">
        <label><span className="field-label">Name</span><input type="text" value={name} onChange={e => setName(e.target.value)} maxLength={120} required autoFocus/></label>
        <label><span className="field-label">Work email</span><input type="email" value={email} onChange={e => setEmail(e.target.value)} maxLength={320} required/></label>
        <label><span className="field-label">Role</span><select value={role} onChange={e => setRole(e.target.value)}>
          <option value="CustomerAdmin">Administrator: manages users and keys</option>
          <option value="CustomerAuditor">Auditor: reviews users, keys, and activity</option>
        </select></label>
        <p className="inline-help">After you invite them, add them to a workspace and issue them a key.</p>
      </div>
      <div className="dialog-actions"><button type="button" className="button secondary" onClick={onClose}>Cancel</button><button type="submit" className="button primary" disabled={!valid}>Invite user</button></div>
    </form>
  </Dialog>;
}

function MemberDialog({pending, users, members, onClose, onSubmit}: {
  pending: {kind: 'member'; user?: WorkspaceMember} | null; users: CustomerUser[]; members: WorkspaceMember[]; onClose: () => void;
  onSubmit: (userId: string, roles: string[], version: number) => Promise<void>;
}) {
  const candidates = users.filter(u => u.membership_status === 'active' && !members.some(m => m.user_id === u.user_id));
  const [userId, setUserId] = useState(''), [roles, setRoles] = useState<string[]>(['Viewer']);
  useEffect(() => {
    if (!pending) return;
    setUserId(pending.user?.user_id || candidates[0]?.user_id || '');
    setRoles(pending.user ? [...pending.user.roles] : ['Viewer']);
  }, [pending]);
  const editing = pending?.user;
  return <Dialog open={!!pending} onClose={onClose} title={editing ? `Edit roles for ${editing.display_name}` : 'Add member'}>
    <form onSubmit={event => {event.preventDefault(); if (userId && roles.length) void onSubmit(userId, roles, editing?.version ?? 0);}}>
      <div className="dialog-content">
        {!editing && (candidates.length
          ? <label><span className="field-label">User</span><select value={userId} onChange={e => setUserId(e.target.value)}>{candidates.map(u => <option key={u.user_id} value={u.user_id}>{u.display_name}</option>)}</select></label>
          : <Notice tone="info">Everyone in your organization already has access. Invite a user first.</Notice>)}
        <fieldset className="settings-fieldset"><legend>Workspace roles</legend>
          {WORKSPACE_ROLES.map(role => <label key={role} className="checkbox-row"><input type="checkbox" checked={roles.includes(role)} onChange={() => setRoles(roles.includes(role) ? roles.filter(r => r !== role) : [...roles, role])}/>{ROLE_LABELS[role]}</label>)}
        </fieldset>
        <p className="inline-help">You can only assign roles you have yourself.</p>
      </div>
      <div className="dialog-actions"><button type="button" className="button secondary" onClick={onClose}>Cancel</button><button type="submit" className="button primary" disabled={!userId || !roles.length}>Save</button></div>
    </form>
  </Dialog>;
}

function AccountDialog({open, onClose, onSubmit}: {open: boolean; onClose: () => void; onSubmit: (body: {name: string; description?: string}) => Promise<void>}) {
  const [name, setName] = useState(''), [description, setDescription] = useState('');
  useEffect(() => {if (open) {setName(''); setDescription('');}}, [open]);
  return <Dialog open={open} onClose={onClose} title="Create service account">
    <form onSubmit={event => {event.preventDefault(); if (name.trim()) void onSubmit({name: name.trim(), ...(description.trim() ? {description: description.trim()} : {})});}}>
      <div className="dialog-content">
        <label><span className="field-label">Name</span><input type="text" value={name} onChange={e => setName(e.target.value)} maxLength={80} placeholder="Nightly CI" required autoFocus/></label>
        <label><span className="field-label">Description (optional)</span><input type="text" value={description} onChange={e => setDescription(e.target.value)} maxLength={500}/></label>
      </div>
      <div className="dialog-actions"><button type="button" className="button secondary" onClick={onClose}>Cancel</button><button type="submit" className="button primary" disabled={!name.trim()}>Create service account</button></div>
    </form>
  </Dialog>;
}

function KeyDialog({open, members, accounts, onClose, onSubmit}: {
  open: boolean; members: WorkspaceMember[]; accounts: ServiceAccount[]; onClose: () => void; onSubmit: (body: Record<string, unknown>) => Promise<void>;
}) {
  const [name, setName] = useState(''), [subject, setSubject] = useState(''), [roles, setRoles] = useState<string[]>(['Viewer']), [expiry, setExpiry] = useState(defaultExpiry());
  useEffect(() => {if (open) {setName(''); setSubject(members[0] ? `user:${members[0].user_id}` : accounts[0] ? `sa:${accounts[0].service_account_id}` : ''); setRoles(['Viewer']); setExpiry(defaultExpiry());}}, [open]);
  const [kind, id] = subject.split(':');
  return <Dialog open={open} onClose={onClose} title="Issue key">
    <form onSubmit={event => {event.preventDefault(); if (!name.trim() || !subject || !roles.length) return;
      void onSubmit({name: name.trim(), roles, all_providers: true, expires_at: new Date(`${expiry}T23:59:00`).toISOString(),
        ...(kind === 'user' ? {subject_user_id: id} : {service_account_id: id})});}}>
      <div className="dialog-content">
        <label><span className="field-label">Name</span><input type="text" value={name} onChange={e => setName(e.target.value)} maxLength={80} placeholder="Cost reporting" required autoFocus/></label>
        <label><span className="field-label">Issued to</span><select value={subject} onChange={e => setSubject(e.target.value)}>
          {members.map(m => <option key={m.user_id} value={`user:${m.user_id}`}>{m.display_name}</option>)}
          {accounts.map(a => <option key={a.service_account_id} value={`sa:${a.service_account_id}`}>{a.name} (service account)</option>)}
        </select></label>
        <fieldset className="settings-fieldset"><legend>Roles</legend>
          {WORKSPACE_ROLES.map(role => <label key={role} className="checkbox-row"><input type="checkbox" checked={roles.includes(role)} onChange={() => setRoles(roles.includes(role) ? roles.filter(r => r !== role) : [...roles, role])}/>{ROLE_LABELS[role]}</label>)}
        </fieldset>
        <label><span className="field-label">Expires on</span><input type="date" value={expiry} min={new Date().toISOString().slice(0, 10)} onChange={e => setExpiry(e.target.value)} required/></label>
        <p className="inline-help">A user’s key can’t have more roles than their workspace membership.</p>
      </div>
      <div className="dialog-actions"><button type="button" className="button secondary" onClick={onClose}>Cancel</button><button type="submit" className="button primary" disabled={!name.trim() || !subject || !roles.length}>Issue key</button></div>
    </form>
  </Dialog>;
}

export function SecretDialog({secret, onClose}: {secret: string; onClose: () => void}) {
  const [copied, setCopied] = useState(false), [stored, setStored] = useState(false);
  useEffect(() => {setCopied(false); setStored(false);}, [secret]);
  return <Dialog open={!!secret} onClose={() => {if (stored) onClose();}} title="Your new key">
    <div className="dialog-content">
      <Notice tone="warning">Copy this key now. You won’t be able to see it again.</Notice>
      <code className="secret-box" aria-label="New access key">{secret}</code>
      <div><button type="button" className="button secondary" onClick={() => void navigator.clipboard.writeText(secret).then(() => setCopied(true))}>{copied ? <><Check size={15}/>Copied</> : <><Copy size={15}/>Copy key</>}</button></div>
      <label className="checkbox-row"><input type="checkbox" checked={stored} onChange={e => setStored(e.target.checked)}/>I’ve stored this key securely</label>
    </div>
    <div className="dialog-actions"><button type="button" className="button primary" disabled={!stored} onClick={onClose}><ShieldCheck size={15}/>Close</button></div>
  </Dialog>;
}
