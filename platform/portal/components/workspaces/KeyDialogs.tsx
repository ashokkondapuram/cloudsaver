'use client';

import {useEffect, useState} from 'react';
import {Loader2} from 'lucide-react';
import {ApiError, errorMessage, portal} from '../../lib/api';
import {formatDate, formatTime, formatNumber, toDateInput} from '../../lib/format';
import {keyIdLabel} from '../../lib/labels';
import type {ApiKey, IssuedKey, Workspace} from '../../lib/types';
import {useSession} from '../SessionProvider';
import {StepUpPrompt} from '../StepUpPrompt';
import {Dialog} from '../ui/Dialog';
import {Notice} from '../ui/shared';
import {AccessFields, accessBody, accessError, defaultAccess, expiryError, ExpiryField, expiryIso, expiryLimits, SecretReveal, type Access} from './KeyFields';

export function IssueKeyDialog({open, workspace, onClose, onIssued}: {open: boolean; workspace: Workspace; onClose: () => void; onIssued: () => void}) {
  const {session} = useSession();
  const [name, setName] = useState('');
  const [access, setAccess] = useState<Access>(() => defaultAccess(workspace));
  const [expiry, setExpiry] = useState('');
  const [submitted, setSubmitted] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [secret, setSecret] = useState('');

  useEffect(() => {
    if (!open) return;
    setName(''); setAccess(defaultAccess(workspace)); setExpiry(expiryLimits().fallback); setSubmitted(false); setError(''); setSecret('');
    // The workspace reloads after issuing; resetting on that would discard the one-time secret.
  }, [open]);

  function close() {setSecret(''); onClose();}

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setSubmitted(true);
    if (!name.trim() || accessError(access, session) || expiryError(expiry)) return;
    setBusy(true); setError('');
    try {
      const issued = await portal<IssuedKey>(`workspaces/${encodeURIComponent(workspace.tenant_id)}/keys`, {
        method: 'POST', body: {name: name.trim(), ...accessBody(access, session), expires_at: expiryIso(expiry)},
      });
      setSecret(issued.secret);
      onIssued();
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setBusy(false);
    }
  }

  return <Dialog open={open} onClose={close} title={secret ? 'Your new key' : 'Issue key'} dismissible={!secret}>
    {secret ? <SecretReveal secret={secret} onClose={close}/> : <form className="dialog-form" onSubmit={submit} noValidate>
      <div className="dialog-content">
        {error && <Notice tone="error">{error}</Notice>}
        <label className="field">Name<input type="text" value={name} onChange={event => setName(event.target.value)} maxLength={120} placeholder="AWS cost automation" autoFocus/>
          {submitted && !name.trim() ? <span className="field-error">Enter a name for this key.</span> : <span className="field-hint">Helps you recognize where the key is used.</span>}
        </label>
        <AccessFields access={access} onChange={setAccess} workspace={workspace} session={session} showErrors={submitted}/>
        <ExpiryField value={expiry} onChange={setExpiry} showErrors={submitted}/>
      </div>
      <div className="dialog-actions">
        <button type="button" className="button secondary" onClick={close}>Cancel</button>
        <button type="submit" className="button primary" disabled={busy}>{busy && <Loader2 className="spin" size={15}/>}Issue key</button>
      </div>
    </form>}
  </Dialog>;
}

function accessFromKey(apiKey: ApiKey, workspace: Workspace): Access {
  return {roles: [...apiKey.roles], allProviders: apiKey.all_providers, providers: apiKey.all_providers ? [...workspace.providers] : apiKey.allowed_providers.filter(p => workspace.providers.includes(p))};
}

export function EditKeyDialog({apiKey, workspace, onClose, onSaved}: {apiKey: ApiKey | null; workspace: Workspace; onClose: () => void; onSaved: () => void}) {
  const {session} = useSession();
  const [name, setName] = useState('');
  const [access, setAccess] = useState<Access>(() => defaultAccess(workspace));
  const [expiry, setExpiry] = useState('');
  const [submitted, setSubmitted] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!apiKey) return;
    setName(apiKey.name); setAccess(accessFromKey(apiKey, workspace));
    setExpiry(apiKey.expires_at ? toDateInput(new Date(apiKey.expires_at)) : ''); setSubmitted(false); setError('');
  }, [apiKey]);

  if (!apiKey) return null;
  const originalExpiry = apiKey.expires_at ? toDateInput(new Date(apiKey.expires_at)) : '';
  const expiryChanged = expiry !== originalExpiry;

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!apiKey) return;
    setSubmitted(true);
    if (!name.trim() || accessError(access, session) || (expiryChanged && expiryError(expiry))) return;
    setBusy(true); setError('');
    try {
      await portal<ApiKey>(`keys/${encodeURIComponent(apiKey.key_id)}`, {method: 'PATCH', body: {
        version: apiKey.version, name: name.trim(), ...accessBody(access, session), ...(expiryChanged ? {expires_at: expiryIso(expiry)} : {}),
      }});
      onSaved();
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setBusy(false);
    }
  }

  return <Dialog open onClose={onClose} title="Edit key">
    <form className="dialog-form" onSubmit={submit} noValidate>
      <div className="dialog-content">
        {error && <Notice tone="error">{error}</Notice>}
        <p>{keyIdLabel(apiKey, session?.key_prefix)}</p>
        <label className="field">Name<input type="text" value={name} onChange={event => setName(event.target.value)} maxLength={120}/>{submitted && !name.trim() && <span className="field-error">Enter a name for this key.</span>}</label>
        <AccessFields access={access} onChange={setAccess} workspace={workspace} session={session} showErrors={submitted}/>
        <ExpiryField value={expiry} onChange={setExpiry} showErrors={submitted && expiryChanged}/>
      </div>
      <div className="dialog-actions">
        <button type="button" className="button secondary" onClick={onClose}>Cancel</button>
        <button type="submit" className="button primary" disabled={busy}>{busy && <Loader2 className="spin" size={15}/>}Save changes</button>
      </div>
    </form>
  </Dialog>;
}

const OVERLAPS = [{hours: 0, label: 'No overlap'}, {hours: 1, label: '1 hour'}, {hours: 24, label: '24 hours'}, {hours: 168, label: '7 days'}] as const;

export function RotateKeyDialog({apiKey, workspace, onClose, onRotated}: {apiKey: ApiKey | null; workspace: Workspace; onClose: () => void; onRotated: () => void}) {
  const {session} = useSession();
  const [access, setAccess] = useState<Access>(() => defaultAccess(workspace));
  const [overlap, setOverlap] = useState<number>(24);
  const [submitted, setSubmitted] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [secret, setSecret] = useState('');

  useEffect(() => {
    if (!apiKey) return;
    setAccess(accessFromKey(apiKey, workspace)); setOverlap(24); setSubmitted(false); setError(''); setSecret('');
  }, [apiKey]);

  if (!apiKey) return null;
  function close() {setSecret(''); onClose();}
  const until = new Date(Date.now() + overlap * 3_600_000);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!apiKey) return;
    setSubmitted(true);
    if (accessError(access, session)) return;
    setBusy(true); setError('');
    try {
      const rotated = await portal<IssuedKey>(`keys/${encodeURIComponent(apiKey.key_id)}/rotate`, {method: 'POST', body: {overlap_hours: overlap, ...accessBody(access, session)}});
      setSecret(rotated.secret);
      onRotated();
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setBusy(false);
    }
  }

  return <Dialog open onClose={close} title={secret ? 'Your new key' : `Rotate ${apiKey.name}`} dismissible={!secret}>
    {secret ? <SecretReveal secret={secret} onClose={close}/> : <form className="dialog-form" onSubmit={submit} noValidate>
      <div className="dialog-content">
        {error && <Notice tone="error">{error}</Notice>}
        <p>Rotating issues a new key with the same name. Update your apps with the new key before the current key stops working.</p>
        <AccessFields access={access} onChange={setAccess} workspace={workspace} session={session} showErrors={submitted}/>
        <fieldset className="choice-group">
          <legend>Overlap window</legend>
          <div className="radio-row">{OVERLAPS.map(option => <label key={option.hours} className={overlap === option.hours ? 'chosen' : ''}>
            <input type="radio" name="overlap" checked={overlap === option.hours} onChange={() => setOverlap(option.hours)}/>{option.label}
          </label>)}</div>
          <span className="field-hint">{overlap === 0 ? 'The current key stops working as soon as you rotate it.' : `The current key keeps working until ${formatDate(until)} at ${formatTime(until)}.`}</span>
        </fieldset>
      </div>
      <div className="dialog-actions">
        <button type="button" className="button secondary" onClick={close}>Cancel</button>
        <button type="submit" className="button primary" disabled={busy}>{busy && <Loader2 className="spin" size={15}/>}Rotate key</button>
      </div>
    </form>}
  </Dialog>;
}

export function RevokeKeyDialog({apiKey, onClose, onRevoked}: {apiKey: ApiKey | null; onClose: () => void; onRevoked: () => void}) {
  const {session} = useSession();
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => {if (apiKey) {setReason(''); setError('');}}, [apiKey]);
  if (!apiKey) return null;

  async function revoke() {
    if (!apiKey) return;
    setBusy(true); setError('');
    try {
      await portal<ApiKey>(`keys/${encodeURIComponent(apiKey.key_id)}/revoke`, {method: 'POST', body: {reason: reason.trim()}});
      onRevoked();
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setBusy(false);
    }
  }

  return <Dialog open onClose={onClose} title="Revoke this key?">
    <div className="dialog-content">
      {error && <Notice tone="error">{error}</Notice>}
      <p><strong>{apiKey.name}</strong> · <code>{keyIdLabel(apiKey, session?.key_prefix)}</code></p>
      <p>Apps using this key lose access within 30 seconds. You can’t undo this.</p>
      <label className="field">Reason<textarea rows={3} value={reason} onChange={event => setReason(event.target.value)} maxLength={500} placeholder="For example, the key was shared in a support ticket" required/><span className="field-hint">Recorded in the activity log.</span></label>
    </div>
    <div className="dialog-actions">
      <button type="button" className="button secondary" onClick={onClose}>Cancel</button>
      <button type="button" className="button danger" disabled={busy || !reason.trim()} onClick={() => void revoke()}>{busy && <Loader2 className="spin" size={15}/>}Revoke key</button>
    </div>
  </Dialog>;
}

export function RevokeAllDialog({open, workspace, activeCount, onClose, onRevoked}: {open: boolean; workspace: Workspace; activeCount: number; onClose: () => void; onRevoked: (count: number) => void}) {
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [stepUp, setStepUp] = useState(false);
  useEffect(() => {if (open) {setReason(''); setError(''); setStepUp(false);}}, [open]);

  async function revoke() {
    setBusy(true); setError('');
    try {
      const result = await portal<{revoked: number}>(`workspaces/${encodeURIComponent(workspace.tenant_id)}/keys/revoke-all`, {method: 'POST', body: {reason: reason.trim()}});
      onRevoked(result.revoked);
    } catch (cause) {
      if (cause instanceof ApiError && cause.stepUp) setStepUp(true);
      else setError(errorMessage(cause));
    } finally {
      setBusy(false);
    }
  }

  return <Dialog open={open} onClose={onClose} title="Revoke all keys?">
    <div className="dialog-content">
      {error && <Notice tone="error">{error}</Notice>}
      {stepUp && <StepUpPrompt onSignedIn={() => {setStepUp(false); void revoke();}}/>}
      <p>This revokes {formatNumber(activeCount)} {activeCount === 1 ? 'key' : 'keys'} for {workspace.name}, including keys that are rotating out. Apps lose access within 30 seconds. You can’t undo this.</p>
      <label className="field">Reason<textarea rows={3} value={reason} onChange={event => setReason(event.target.value)} maxLength={500} placeholder="For example, suspected key exposure" required/><span className="field-hint">Recorded in the activity log.</span></label>
    </div>
    <div className="dialog-actions">
      <button type="button" className="button secondary" onClick={onClose}>Cancel</button>
      <button type="button" className="button danger" disabled={busy || !reason.trim()} onClick={() => void revoke()}>{busy && <Loader2 className="spin" size={15}/>}Revoke all keys</button>
    </div>
  </Dialog>;
}
