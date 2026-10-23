'use client';

import {useEffect, useState} from 'react';
import {ArrowRight, Loader2, LockKeyhole, ShieldCheck} from 'lucide-react';
import {authRequest, errorMessage} from '../lib/api';
import {Brand} from './AppShell';
import {useSession} from './SessionProvider';
import {ThemeToggle} from './ThemeProvider';
import {Notice} from './ui/shared';

const ERRORS: Record<string, string> = {
  access_denied: 'Sign-in was canceled. Try again when you’re ready.',
  sign_in_failed: 'We couldn’t sign you in. Try again. If the issue persists, contact Support.',
  sign_in_expired: 'Your sign-in took too long or was started in another browser. Try again.',
  not_authorized: 'Your account doesn’t have access to the platform portal. Ask your administrator to assign the Platform operator or Platform auditor role.',
  not_configured: 'Microsoft sign-in isn’t configured for this portal. Contact Support.',
  identity_unavailable: 'The identity service is unavailable. Try again in a few minutes.',
  session_ended: 'Your session has ended. Sign in again.',
};

function safeReturn(value: string) {
  return value.startsWith('/') && !value.startsWith('//') && !value.startsWith('/api/') && !value.startsWith('/sign-in') ? value : '/customers';
}

export function SignIn({authMode, error, signedOut, returnTo}: {authMode: 'entra' | 'operator_key'; error: string; signedOut: boolean; returnTo: string}) {
  const {session, refresh} = useSession();
  const [key, setKey] = useState('');
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState(error ? ERRORS[error] || ERRORS.sign_in_failed : '');
  const target = safeReturn(returnTo);

  useEffect(() => {if (session) window.location.replace(target);}, [session, target]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true); setFailure('');
    try {
      await authRequest('operator-key', {method: 'POST', body: {key: key.trim()}});
      await refresh();
    } catch (cause) {
      setFailure(errorMessage(cause));
    } finally {
      setKey(''); setBusy(false);
    }
  }

  return <main className="signin-page">
    <div className="signin-theme"><ThemeToggle/></div>
    <div className="signin-card">
      <Brand/>
      <span className="pretitle">PLATFORM OPERATORS</span>
      <h1>Sign in to the platform portal</h1>
      <p>Manage customers, workspaces and workspace keys.</p>
      {signedOut && !failure && <Notice tone="success">You’ve signed out.</Notice>}
      {failure && <Notice tone="error">{failure}</Notice>}
      {authMode === 'entra' ? <>
        <a className="button primary signin-submit" href={`/api/auth/login?return_to=${encodeURIComponent(target)}`}>Sign in with Microsoft<ArrowRight size={17}/></a>
        <div className="connection-security"><ShieldCheck size={16}/><span>You sign in with your Microsoft Entra work account. Your access is checked on every request.</span></div>
      </> : <form onSubmit={submit} style={{display: 'flex', flexDirection: 'column', gap: 12}}>
        <Notice tone="warning">Local development sign-in. Production uses Microsoft sign-in.</Notice>
        <label className="field" htmlFor="operator-key">Operator access key
          <span className="credential-input"><LockKeyhole size={17}/><input id="operator-key" type="password" autoComplete="off" value={key} onChange={event => setKey(event.target.value)} required disabled={busy}/></span>
        </label>
        <button className="button primary signin-submit" type="submit" disabled={busy || !key.trim()}>{busy ? <><Loader2 className="spin" size={17}/>Signing in…</> : <>Sign in<ArrowRight size={17}/></>}</button>
        <div className="connection-security"><ShieldCheck size={16}/><span>Your key is checked on the portal server and never stored in your browser.</span></div>
      </form>}
    </div>
  </main>;
}
