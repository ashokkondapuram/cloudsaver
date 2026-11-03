import type {PlanVersionRecord} from './control-plane';

export function planOutboxHasSurface(latest: PlanVersionRecord): boolean {
  const pending = latest.engineering_outbox_pending_count ?? 0;
  const published = latest.engineering_outbox_published_count ?? 0;
  return pending > 0 || published > 0 || !!latest.engineering_outbox_state;
}

export function planOutboxStatusCopy(latest: PlanVersionRecord): string {
  const pending = latest.engineering_outbox_pending_count ?? 0;
  const published = latest.engineering_outbox_published_count ?? 0;
  const total = pending + published;
  if (total > 0) {
    const latestState = latest.engineering_outbox_state ?? (pending > 0 ? 'pending' : 'published');
    return `Engineering event outbox: ${pending} pending, ${published} published (latest ${latestState}). Cloud execution remains disabled in this dashboard.`;
  }
  if (latest.engineering_outbox_state === 'pending') {
    return 'Engineering event outbox: pending dispatch. Cloud execution remains disabled in this dashboard.';
  }
  if (latest.engineering_outbox_state === 'published') {
    return 'Engineering event outbox: published. Control-plane execution tracking still does not invoke cloud APIs from this panel.';
  }
  return 'Worker outbox dispatch is not surfaced for this plan version. Status reflects control-plane transitions only; no automatic cloud mutations are triggered from this panel.';
}

/** Bullet lines for the expandable audit-only outbox readout on control-plane cards. */
export function planOutboxReadoutItems(latest: PlanVersionRecord): string[] {
  const pending = latest.engineering_outbox_pending_count ?? 0;
  const published = latest.engineering_outbox_published_count ?? 0;
  const lines: string[] = [];
  if (pending > 0) lines.push(`${pending} engineering event(s) pending worker dispatch.`);
  if (published > 0) lines.push(`${published} engineering event(s) published from the outbox.`);
  if (latest.engineering_outbox_state) {
    lines.push(`Latest outbox row state: ${latest.engineering_outbox_state}.`);
  }
  lines.push('Individual outbox rows are not listed here; aggregates bind to this plan version record.');
  lines.push('This dashboard does not dispatch or mutate worker outbox messages.');
  return lines;
}
