'use client';

import {useState} from 'react';
import {Loader2, LockKeyhole, LogIn} from 'lucide-react';
import {authRequest, errorMessage} from '../lib/api';
import {useSession} from './SessionProvider';
import {Notice} from './ui/shared';

/** Shown when the portal server asks for a recent sign-in before a destructive bulk action. */
export function StepUpPrompt({onSignedIn}: {onSignedIn: () => void}) {
  const {session, refresh} = useSession();
  const [key, setKey] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  if (session?.auth_mode !== 'operator_key') {
    const returnTo = typeof window === 'undefined' ? '/' : window.location.pathname;
    return <Notice tone="warning">
      <p>For your security, sign in again to continue. You need to have signed in within the last 15 minutes.</p>
      <p style={{marginTop: 10}}><a className="button secondary small" href={`/api/auth/login?prompt=login&max_age=0&return_to=${encodeURIComponent(returnTo)}`}><LogIn size={14}/>Sign in again</a></p>
    </Notice>;
  }
  async function submit() {
    setBusy(true); setError('');
    try {
      await authRequest('operator-key', {method: 'POST', body: {key: key.trim()}});
      await refresh();
      onSignedIn();
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setKey(''); setBusy(false);
    }
  }
  return <Notice tone="warning">
    <p>For your security, enter your operator access key again to continue.</p>
    {error && <p className="field-error">{error}</p>}
    <div style={{display: 'flex', gap: 8, marginTop: 10}}>
      <div className="credential-input" style={{flex: 1}}><LockKeyhole size={15}/><input type="password" aria-label="Operator access key" autoComplete="off" value={key} onChange={event => setKey(event.target.value)} onKeyDown={event => {if (event.key === 'Enter') {event.preventDefault(); if (key.trim()) void submit();}}}/></div>
      <button type="button" className="button secondary" disabled={busy || !key.trim()} onClick={() => void submit()}>{busy ? <Loader2 className="spin" size={15}/> : null}Sign in</button>
    </div>
  </Notice>;
}
