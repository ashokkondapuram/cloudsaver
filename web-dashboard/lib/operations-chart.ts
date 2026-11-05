import type {ChartSeries} from './atlas-contracts';

type DeliveryCount = {kind: string; status: string; count: number};

const STATUS_ORDER = ['pending', 'leased', 'published', 'delivered', 'dead_letter'] as const;

/** Aggregate reliability `counts[]` into a categorical Atlas series for Activity charts. */
export function deliveryCountsToChartSeries(counts: DeliveryCount[], observedAt?: string | null): ChartSeries {
  const byStatus = new Map<string, number>();
  for (const row of counts) {
    byStatus.set(row.status, (byStatus.get(row.status) || 0) + row.count);
  }
  const points = STATUS_ORDER.map(status => ({
    timestamp: status.replaceAll('_', ' '),
    value: byStatus.get(status) ?? 0,
  }));
  const total = points.reduce((sum, p) => sum + (p.value ?? 0), 0);
  return {
    id: 'delivery-status-counts',
    label: 'Delivery backlog by state',
    unit: 'deliveries',
    status: total > 0 ? 'complete' : counts.length ? 'partial' : 'unavailable',
    observedAt: observedAt ?? null,
    points,
  };
}

type UsageGroup = {attempts: number; completed: number; incomplete_outcomes: number};

/** Summarize AI usage groups for a compact Activity chart. */
export function aiUsageToChartSeries(groups: UsageGroup[], observedAt?: string | null): ChartSeries {
  const totals = groups.reduce(
    (acc, g) => ({
      attempts: acc.attempts + g.attempts,
      completed: acc.completed + g.completed,
      incomplete: acc.incomplete + g.incomplete_outcomes,
    }),
    {attempts: 0, completed: 0, incomplete: 0},
  );
  const points = [
    {timestamp: 'Attempts', value: totals.attempts},
    {timestamp: 'Completed', value: totals.completed},
    {timestamp: 'Pending', value: totals.incomplete},
  ];
  return {
    id: 'ai-usage-summary',
    label: 'AI assessments (30 days)',
    unit: 'attempts',
    status: totals.attempts > 0 ? 'complete' : 'unavailable',
    observedAt: observedAt ?? null,
    points,
  };
}
