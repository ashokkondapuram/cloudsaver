'use client';

import {useEffect, useState} from 'react';
import Link from 'next/link';
import {ArrowRight, Wallet} from 'lucide-react';
import {api} from '../lib/api';
import {AnalyticsChart} from './charts/AnalyticsChart';
import {billingDailyToChartSeries, finopsPeriodLabel} from '../lib/finops-chart';
import {useWorkspace} from './WorkspaceProvider';
import {Loading, Notice} from './ui/shared';

const monthRange = (): {start: string; end: string} => {
  const end = new Date().toISOString().slice(0, 10);
  const start = end.slice(0, 8) + '01';
  return {start, end};
};

function OverviewFinOpsChartBody() {
  const {token, canBill} = useWorkspace();
  const [selection] = useState(monthRange);
  const [series, setSeries] = useState<ReturnType<typeof billingDailyToChartSeries> | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    const request = new AbortController();
    setSeries(null);
    setError('');
    if (!canBill || !token) return () => request.abort();
    const query = new URLSearchParams({start: selection.start, end: selection.end, currency: 'USD'});
    api<{
      currency: string;
      daily: {date: string; billed_cost: string | null; complete: boolean}[];
    }>('/finops/summary?' + query, token, {signal: request.signal})
      .then(summary => {
        if (!request.signal.aborted) {
          setSeries(billingDailyToChartSeries(summary, {start: selection.start, end: selection.end}));
        }
      })
      .catch(cause => {
        if (!request.signal.aborted) setError((cause as Error).message);
      });
    return () => request.abort();
  }, [canBill, token, selection.end, selection.start]);

  if (!canBill) return null;
  if (error) return <Notice tone="error">{error}</Notice>;
  if (!series) return <Loading label="Loading billing snapshot…"/>;
  return (
    <AnalyticsChart
      className="analytics-chart-compact"
      height={176}
      title="Month-to-date billed cost"
      periodLabel={finopsPeriodLabel(selection.start, selection.end)}
      interpretation="Provider-reported sync for the current UTC month. Open cost allocation for commitments and imports."
      series={series}
    />
  );
}

/** Lazy FinOps headline — loads only after the user expands the panel (keeps overview free of billing API calls by default). */
export function OverviewFinOpsMiniChart() {
  const {canBill} = useWorkspace();
  const [open, setOpen] = useState(false);
  if (!canBill) return null;
  return (
    <details
      className="panel overview-finops-mini cs-panel"
      data-atlas-rollout="overview-finops"
      onToggle={event => setOpen((event.target as HTMLDetailsElement).open)}
    >
      <summary>
        <Wallet size={17} aria-hidden="true"/>
        <span>Billing snapshot (month to date)</span>
      </summary>
      <p className="overview-finops-actions">
        <Link className="text-link" href="/allocation">
          Open cost allocation
          <ArrowRight size={14}/>
        </Link>
      </p>
      {open ? <OverviewFinOpsChartBody/> : null}
    </details>
  );
}
