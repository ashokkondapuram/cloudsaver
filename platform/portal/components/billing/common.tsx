'use client';

import {useSession} from '../SessionProvider';
import {Notice} from '../ui/shared';

export function customerBillingHref(customerId: string) {
  return `/customers/${encodeURIComponent(customerId)}?tab=billing`;
}

export function plural(count: number, one: string, many = `${one}s`) {
  return `${count.toLocaleString('en-US')} ${count === 1 ? one : many}`;
}

/** Shown on billing screens when PLATFORM_BILLING_ENABLED is off; plans and records stay viewable. */
export function BillingOffNotice() {
  const {session} = useSession();
  if (!session || session.billing_enabled) return null;
  return <Notice tone="info">Billing is turned off for this platform. You can view plans and billing details, but you can’t change them until billing is turned on.</Notice>;
}

export function ReadOnlyNotice() {
  const {session, canWrite} = useSession();
  if (!session || canWrite || !session.billing_enabled) return null;
  return <Notice tone="info">You have read-only access. Ask a platform operator to make billing changes.</Notice>;
}
