export type ChartEngine = 'recharts' | 'nivo';

/** Default Recharts; set `NEXT_PUBLIC_CHART_ENGINE=nivo` for the Nivo bundle pilot. */
export function resolveChartEngine(override?: ChartEngine): ChartEngine {
  if (override) return override;
  return process.env.NEXT_PUBLIC_CHART_ENGINE === 'nivo' ? 'nivo' : 'recharts';
}
