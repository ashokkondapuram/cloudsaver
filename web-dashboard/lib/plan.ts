import type {BillingState, Entitlements} from './types';

export const NOT_INCLUDED = 'Not included in your plan.';
export const CONTACT_ACCOUNT_MANAGER = 'To change your plan, contact your account manager.';
export const billingStateLabels: Record<BillingState, string> = {active: 'Active', grace: 'Grace period', lapsed: 'Lapsed', none: 'No subscription'};
export const frequencyNames: Record<string, string> = {manual: 'Manual', daily: 'Daily', hourly: 'Hourly'};

// Billing period boundaries are UTC midnights; formatting them in local time would show the previous day west of UTC.
export const planDate = (value: string | null) => {if (!value) return null; const d = new Date(value); return Number.isNaN(d.valueOf()) ? null : d.toLocaleDateString('en-US', {month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC'});};

export function manageBillingUrl(value: string | null) {
  if (!value) return null;
  try {const url = new URL(value); return url.protocol === 'https:' ? url.href : null;} catch {return null;}
}

export function billingBanner(plan: Entitlements | null) {
  if (!plan) return null;
  if (plan.billing_state === 'grace') {
    const until = planDate(plan.grace_ends_at);
    return `Your payment is past due. ${plan.plan_name} features stay available ${until ? `until ${until}` : 'for a limited time'}. Contact your account manager.`;
  }
  if (plan.billing_state === 'lapsed') {
    const ended = planDate(plan.grace_ends_at ?? plan.current_period_end);
    const subscribed = plan.subscription_plan_name && plan.subscription_plan_name !== plan.plan_name ? `${plan.subscription_plan_name} plan` : 'plan';
    return `Your ${subscribed} ended${ended ? ` on ${ended}` : ''}. ${plan.plan_name} limits now apply.`;
  }
  return null;
}
