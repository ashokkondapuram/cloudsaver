import type {ChartSeries} from './atlas-contracts';

type BillingDailyRow = {date: string; billed_cost: string | null; complete: boolean};

type BillingSummarySlice = {
  currency: string;
  daily: BillingDailyRow[];
};

/** Map FinOps `/finops/summary` daily rows into an Atlas `ChartSeries`. */
export function billingDailyToChartSeries(
  summary: BillingSummarySlice,
  options: {start: string; end: string; observedAt?: string | null},
): ChartSeries {
  const {daily, currency} = summary;
  const completeDays = daily.filter(row => row.complete).length;
  let status: ChartSeries['status'] = 'unavailable';
  if (daily.length) {
    status = completeDays === daily.length ? 'complete' : completeDays > 0 ? 'partial' : 'stale';
  }
  const points = daily.map(row => ({
    timestamp: row.date,
    value:
      row.billed_cost == null || row.billed_cost === ''
        ? null
        : Number.isFinite(Number(row.billed_cost))
          ? Number(row.billed_cost)
          : null,
  }));
  return {
    id: 'finops-daily-billed-cost',
    label: 'Daily billed cost',
    unit: 'amount',
    currency,
    status,
    observedAt: options.observedAt ?? null,
    points,
  };
}

export function finopsPeriodLabel(start: string, end: string): string {
  return `UTC ${start} → ${end} (exclusive)`;
}
