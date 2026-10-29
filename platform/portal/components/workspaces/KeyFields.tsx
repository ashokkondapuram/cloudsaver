'use client';

import {useState} from 'react';
import {Check, Copy} from 'lucide-react';
import {addDays, formatDate, toDateInput} from '../../lib/format';
import {ROLES, providerLabel, roleLabel} from '../../lib/labels';
import type {Provider, Role, Session, Workspace} from '../../lib/types';
import {Notice} from '../ui/shared';

export const DEFAULT_EXPIRY_DAYS = 90;
export const MAX_EXPIRY_DAYS = 365;

export type Access = {roles: Role[]; allProviders: boolean; providers: Provider[]};

export function defaultAccess(workspace: Workspace): Access {
  return {roles: ['Viewer'], allProviders: false, providers: [...workspace.providers]};
}

/** Builds the provider fields for an API request, honoring the platform's provider-scoped-keys switch. */
export function accessBody(access: Access, session: Session | null) {
  if (!session?.provider_scoped_keys || access.allProviders) return {roles: access.roles, all_providers: true, allowed_providers: [] as Provider[]};
  return {roles: access.roles, all_providers: false, allowed_providers: access.providers};
}

export function accessError(access: Access, session: Session | null) {
  if (!access.roles.length) return 'Select at least one role.';
  if (session?.provider_scoped_keys && !access.allProviders && !access.providers.length) return 'Select at least one provider.';
  return '';
}

export function AccessFields({access, onChange, workspace, session, showErrors, freezeProviders = false}: {
  access: Access; onChange: (access: Access) => void; workspace: Workspace; session: Session | null; showErrors: boolean; freezeProviders?: boolean;
}) {
  const toggleRole = (role: Role) => onChange({...access, roles: access.roles.includes(role) ? access.roles.filter(r => r !== role) : [...access.roles, role]});
  const toggleProvider = (provider: Provider) => onChange({...access, providers: access.providers.includes(provider) ? access.providers.filter(p => p !== provider) : [...access.providers, provider]});
  return <>
    <fieldset className="choice-group">
      <legend>Roles</legend>
      <div className="choices">{ROLES.map(role => <label key={role} className="checkbox-row"><input type="checkbox" checked={access.roles.includes(role)} onChange={() => toggleRole(role)}/>{roleLabel[role]}</label>)}</div>
      {showErrors && !access.roles.length && <span className="field-error">Select at least one role.</span>}
    </fieldset>
    <fieldset className="choice-group">
      <legend>Providers</legend>
      {!session?.provider_scoped_keys ? <span className="muted">{freezeProviders ? 'All currently configured providers' : 'All providers, including providers added later'}</span> : <>
        {workspace.providers.length ? <div className="choices">{workspace.providers.map(provider => <label key={provider} className="checkbox-row">
          <input type="checkbox" checked={access.allProviders || access.providers.includes(provider)} disabled={access.allProviders} onChange={() => toggleProvider(provider)}/>{providerLabel[provider]}
        </label>)}</div> : <span className="muted">This workspace has no cloud accounts yet.</span>}
        <label className="checkbox-row"><input type="checkbox" checked={access.allProviders} onChange={event => onChange({...access, allProviders: event.target.checked})}/>{freezeProviders ? 'Include all currently configured providers' : 'Include providers added later'}</label>
        {showErrors && !access.allProviders && !access.providers.length && <span className="field-error">Select at least one provider.</span>}
      </>}
    </fieldset>
  </>;
}

export function expiryLimits() {
  const today = new Date();
  return {min: toDateInput(addDays(today, 1)), max: toDateInput(addDays(today, MAX_EXPIRY_DAYS)), fallback: toDateInput(addDays(today, DEFAULT_EXPIRY_DAYS))};
}

/** End of the chosen local day, capped just under the 365-day maximum. */
export function expiryIso(value: string) {
  const [year, month, day] = value.split('-').map(Number);
  const endOfDay = new Date(year, month - 1, day, 23, 59, 0);
  const cap = new Date(Date.now() + MAX_EXPIRY_DAYS * 86_400_000 - 60_000);
  return (endOfDay > cap ? cap : endOfDay).toISOString();
}

export function expiryError(value: string) {
  if (!value) return 'Choose an expiry date.';
  const {min, max} = expiryLimits();
  if (value < min) return 'Choose a date after today.';
  if (value > max) return `Choose a date on or before ${formatDate(addDays(new Date(), MAX_EXPIRY_DAYS))}.`;
  return '';
}

export function ExpiryField({value, onChange, showErrors}: {value: string; onChange: (value: string) => void; showErrors: boolean}) {
  const {min, max} = expiryLimits();
  const error = expiryError(value);
  return <label className="field">Expires on
    <input type="date" value={value} min={min} max={max} onChange={event => onChange(event.target.value)} required/>
    {showErrors && error ? <span className="field-error">{error}</span> : <span className="field-hint">{value && !error ? `The key stops working at the end of ${formatDate(new Date(`${value}T12:00:00`))}. ` : ''}Up to {MAX_EXPIRY_DAYS} days from today.</span>}
  </label>;
}

/** One-time display of a newly issued secret. The caller clears it from state on close. */
export function SecretReveal({secret, onClose, label = 'New workspace key'}: {secret: string; onClose: () => void; label?: string}) {
  const [copied, setCopied] = useState(false);
  const [stored, setStored] = useState(false);
  const [copyError, setCopyError] = useState(false);
  async function copy() {
    try {await navigator.clipboard.writeText(secret); setCopied(true); setCopyError(false);} catch {setCopyError(true);}
  }
  return <>
    <div className="dialog-content">
      <Notice tone="warning">Copy this key now. You won’t be able to see it again.</Notice>
      <code className="secret-box" aria-label={label}>{secret}</code>
      {copyError && <span className="field-error">We couldn’t copy the key. Select it and copy it manually.</span>}
      <div><button type="button" className="button secondary" onClick={() => void copy()}>{copied ? <><Check size={15}/>Copied</> : <><Copy size={15}/>Copy key</>}</button></div>
      <label className="checkbox-row"><input type="checkbox" checked={stored} onChange={event => setStored(event.target.checked)}/>I’ve stored this key securely</label>
    </div>
    <div className="dialog-actions"><button type="button" className="button primary" disabled={!stored} onClick={onClose}>Close</button></div>
  </>;
}
