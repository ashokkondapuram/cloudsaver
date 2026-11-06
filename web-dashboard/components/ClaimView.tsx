'use client';

import Link from 'next/link';
import {useState} from 'react';
import {ArrowRight, CircleNotch, LockKey, SealCheck} from '@phosphor-icons/react';
import {api} from '../lib/api';
import {useWorkspace} from './WorkspaceProvider';
import {SecretDialog} from './settings/AccessSettings';
import {Notice} from './ui/shared';

type Claimed = {customer_id: string; tenant_id: string; secret: string; user: {display_name: string}};

/** First-administrator onboarding: exchange the operator's single-use key for an owner account and personal key. */
export function ClaimView() {
  const {connect} = useWorkspace();
  const [key, setKey] = useState(''), [name, setName] = useState(''), [email, setEmail] = useState('');
  const [busy, setBusy] = useState(false), [error, setError] = useState('');
  const [claimed, setClaimed] = useState<Claimed | null>(null);
  const [secret, setSecret] = useState('');
  const valid = key.trim() && name.trim() && /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email.trim());

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!valid || busy) return;
    setBusy(true); setError('');
    try {
      // The onboarding route is public; the bootstrap key travels only in the request body.
      const result = await api<Claimed>('/onboarding/claim', '', {body: {key: key.trim(), display_name: name.trim(), email: email.trim()}});
      setKey(''); setClaimed(result); setSecret(result.secret);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'We could not complete onboarding. Try again or contact Support.');
    } finally {
      setBusy(false);
    }
  }

  return <div className="login-page claim-page" data-atlas-rollout="claim"><section className="login-connect">
    {claimed ? <div className="claim-form">
      <span className="pretitle">YOU’RE ALL SET</span>
      <h1>Welcome, {claimed.user.display_name}</h1>
      <p>You now own your organization’s CloudSaver account. Use your personal key to connect, then invite your team from Settings → Users & keys.</p>
      <button type="button" className="button primary connection-submit" disabled={!!secret} onClick={() => void connect(claimed.secret)}>Connect workspace<ArrowRight size={17} weight="regular"/></button>
    </div> : <form className="claim-form" onSubmit={submit}>
      <span className="pretitle">CLAIM YOUR ORGANIZATION</span>
      <h1>Set up your account</h1>
      <p>Enter the onboarding key from your platform operator. You’ll become the owner and can manage your own users and keys.</p>
      {error && <Notice tone="error">{error}</Notice>}
      <label>Onboarding key<div className="credential-input"><LockKey size={17} weight="regular"/><input type="password" autoComplete="off" value={key} onChange={e => setKey(e.target.value)} placeholder="Paste your onboarding key" required disabled={busy}/></div></label>
      <label>Your name<input type="text" value={name} onChange={e => setName(e.target.value)} maxLength={120} required disabled={busy}/></label>
      <label>Work email<input type="email" value={email} onChange={e => setEmail(e.target.value)} maxLength={320} required disabled={busy}/></label>
      <button className="button primary connection-submit" type="submit" disabled={busy || !valid}>{busy ? <><CircleNotch className="spin" size={17} weight="regular"/>Claiming account…</> : <>Claim account<ArrowRight size={17} weight="regular"/></>}</button>
      <div className="connection-security"><SealCheck size={16} weight="regular"/><span>The onboarding key works once and expires within 72 hours.</span></div>
      <p><Link className="text-link" href="/">Already have a key? Connect your workspace</Link></p>
    </form>}
    <SecretDialog secret={secret} onClose={() => setSecret('')}/>
  </section></div>;
}
