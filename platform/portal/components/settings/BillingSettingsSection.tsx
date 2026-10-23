'use client';

import {useEffect, useState} from 'react';
import {Check, Copy, Loader2, Save} from 'lucide-react';
import {errorMessage, portal} from '../../lib/api';
import {formatAttribution, httpsUrlError} from '../../lib/format';
import {billingProviderLabel, planName} from '../../lib/labels';
import type {BillingSettings, LapsedAction, Plan} from '../../lib/types';
import {useLoad} from '../../lib/useLoad';
import {useSession} from '../SessionProvider';
import {Loading, Notice, SectionTitle, Switch} from '../ui/shared';
import {BillingOffNotice} from '../billing/common';

type Draft = {default_plan_code: string; default_grace_days: string; lapsed_action: LapsedAction; lapsed_plan_code: string; default_manage_billing_url: string; require_subscription_for_keys: boolean};

function toDraft(settings: BillingSettings): Draft {
  return {
    default_plan_code: settings.default_plan_code, default_grace_days: String(settings.default_grace_days), lapsed_action: settings.lapsed_action,
    lapsed_plan_code: settings.lapsed_plan_code, default_manage_billing_url: settings.default_manage_billing_url || '',
    require_subscription_for_keys: settings.require_subscription_for_keys,
  };
}

export function BillingSettingsSection() {
  const {canManageBilling} = useSession();
  const {data, setData, error, loading, reload} = useLoad(async () => {
    const [settings, plans] = await Promise.all([portal<BillingSettings>('billing/settings'), portal<{items: Plan[]}>('plans')]);
    return {settings, plans: plans.items};
  }, []);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [busy, setBusy] = useState(false);
  const [saveError, setSaveError] = useState('');
  const [saved, setSaved] = useState(false);
  const [copied, setCopied] = useState(false);

  useEffect(() => {if (data) setDraft(toDraft(data.settings));}, [data]);

  if (loading && !data) return <section className="panel"><SectionTitle title="Billing"/><Loading label="Loading billing settings…"/></section>;
  if (!data || !draft) return <section className="panel"><SectionTitle title="Billing"/><Notice tone="error">{error || 'Something went wrong. If the issue persists, contact Support.'}</Notice></section>;

  const {settings, plans} = data;
  const original = toDraft(settings);
  const changed = (Object.keys(draft) as (keyof Draft)[]).filter(key => draft[key] !== original[key]);
  const graceDays = Number(draft.default_grace_days);
  const errors = {
    grace: !/^\d+$/.test(draft.default_grace_days.trim()) || graceDays > 60 ? 'Enter a whole number of days from 0 to 60.' : '',
    url: httpsUrlError(draft.default_manage_billing_url),
  };
  const invalid = Object.values(errors).some(Boolean);
  const editable = canManageBilling && !busy;
  const options = (current: string) => plans.filter(plan => plan.status === 'active' || plan.code === current);
  const update = (patch: Partial<Draft>) => {setDraft({...draft, ...patch}); setSaved(false);};
  const provider = settings.provider;

  async function save() {
    if (!draft || invalid) return;
    setBusy(true); setSaveError(''); setSaved(false);
    const body: Record<string, unknown> = {version: settings.version};
    for (const key of changed) {
      if (key === 'default_grace_days') body[key] = graceDays;
      else if (key === 'default_manage_billing_url') body[key] = draft[key].trim() || null;
      else body[key] = draft[key];
    }
    try {
      const updated = await portal<BillingSettings>('billing/settings', {method: 'PUT', body});
      setData({settings: updated, plans});
      setSaved(true);
    } catch (cause) {
      setSaveError(errorMessage(cause));
    } finally {
      setBusy(false);
    }
  }

  async function copyWebhook() {
    if (!provider.webhook_url) return;
    try {await navigator.clipboard.writeText(provider.webhook_url); setCopied(true);} catch {setCopied(false);}
  }

  return <section className="panel">
    <SectionTitle title="Billing">Plans, grace periods and what happens when a customer’s payment lapses.</SectionTitle>
    <BillingOffNotice/>
    {saveError && <Notice tone="error">{saveError} {saveError.includes('Refresh') && <button type="button" className="text-button" onClick={() => void reload()}>Refresh</button>}</Notice>}
    {saved && !changed.length && <Notice tone="success">Billing settings saved. Changes apply within 30 seconds.</Notice>}

    <div className="switch-row">
      <div>
        <h3>Payment provider: {billingProviderLabel[provider.name] || provider.name}</h3>
        <p>{provider.name === 'manual'
          ? 'Operators record payments on each customer’s Billing tab. To use Stripe, add the Stripe secret key and webhook secret to Key Vault, set the payment provider to Stripe and restart the identity service.'
          : provider.configured
            ? 'Stripe is configured. Add this webhook URL to the Stripe Dashboard so subscription and invoice events reach the platform.'
            : 'Stripe isn’t configured. To enable it, add the Stripe secret key and webhook secret to Key Vault and restart the identity service.'}</p>
        {provider.name === 'stripe' && provider.configured && provider.webhook_url && <div className="copy-field" style={{marginTop: 8}}>
          <code>{provider.webhook_url}</code>
          <button type="button" className="button secondary small" onClick={() => void copyWebhook()}>{copied ? <><Check size={13}/>Copied</> : <><Copy size={13}/>Copy URL</>}</button>
        </div>}
      </div>
      <span className={`state-badge ${provider.name === 'manual' || provider.configured ? 'billing-active' : 'billing-grace'}`}>{provider.name === 'manual' || provider.configured ? 'Configured' : 'Not configured'}</span>
    </div>

    <div className="switch-row">
      <div style={{flex: 1}}>
        <div className="form-grid">
          <label className="field">Default plan
            <select value={draft.default_plan_code} disabled={!editable} onChange={event => update({default_plan_code: event.target.value})}>
              {options(draft.default_plan_code).map(plan => <option key={plan.code} value={plan.code}>{plan.name}</option>)}
            </select>
            <span className="field-hint">Applies to customers without a subscription.</span>
          </label>
          <label className="field">Grace period (days)
            <input type="number" inputMode="numeric" min={0} max={60} step={1} value={draft.default_grace_days} disabled={!editable} onChange={event => update({default_grace_days: event.target.value})} aria-invalid={!!errors.grace}/>
            {errors.grace ? <span className="field-error">{errors.grace}</span> : <span className="field-hint">How long features stay available after a period ends without payment.</span>}
          </label>
          <fieldset className="choice-group full">
            <legend>After the grace period</legend>
            <div className="radio-row">
              <label className={draft.lapsed_action === 'downgrade' ? 'chosen' : ''}><input type="radio" name="lapsed-action" checked={draft.lapsed_action === 'downgrade'} disabled={!editable} onChange={() => update({lapsed_action: 'downgrade'})}/>Downgrade to {planName(draft.lapsed_plan_code, plans.find(plan => plan.code === draft.lapsed_plan_code)?.name)}</label>
              <label className={draft.lapsed_action === 'suspend' ? 'chosen' : ''}><input type="radio" name="lapsed-action" checked={draft.lapsed_action === 'suspend'} disabled={!editable} onChange={() => update({lapsed_action: 'suspend'})}/>Suspend workspaces</label>
            </div>
            <span className="field-hint">{draft.lapsed_action === 'downgrade' ? 'Keys keep working with the limits of the downgrade plan.' : 'Keys stop working until the customer pays. Workspaces reactivate automatically when you record a payment.'}</span>
          </fieldset>
          {draft.lapsed_action === 'downgrade' && <label className="field">Downgrade plan
            <select value={draft.lapsed_plan_code} disabled={!editable} onChange={event => update({lapsed_plan_code: event.target.value})}>
              {options(draft.lapsed_plan_code).map(plan => <option key={plan.code} value={plan.code}>{plan.name}</option>)}
            </select>
          </label>}
          <label className="field full">Default manage billing link
            <input type="url" value={draft.default_manage_billing_url} disabled={!editable} onChange={event => update({default_manage_billing_url: event.target.value})} placeholder="https://billing.example.com" aria-invalid={!!errors.url}/>
            {errors.url ? <span className="field-error">{errors.url}</span> : <span className="field-hint">Optional. CloudSaver shows a Manage billing button with this link when a customer doesn’t have its own. Otherwise, it shows “Contact your account manager.”</span>}
          </label>
        </div>
      </div>
    </div>

    <div className="switch-row">
      <div><h3>Require a subscription to issue keys</h3><p>Operators can issue and rotate keys only for customers with an active subscription or one in its grace period. Existing keys keep working.</p></div>
      <Switch checked={draft.require_subscription_for_keys} onChange={value => update({require_subscription_for_keys: value})} label="Require a subscription to issue keys" disabled={!editable}/>
    </div>

    <div className="panel-footer">
      <span>Last changed {formatAttribution(settings.updated_at, settings.updated_by)}</span>
      {canManageBilling && <button type="button" className="button primary small" disabled={!changed.length || invalid || busy} onClick={() => void save()}>{busy ? <Loader2 className="spin" size={14}/> : <Save size={14}/>}Save changes</button>}
    </div>
  </section>;
}
