export type ChartEngine = 'recharts' | 'nivo';

/**
 * Atlas uses Nivo only (Atlas `--cs-*` theme via `chart-theme.ts`).
 * Other presets default to Recharts unless `NEXT_PUBLIC_CHART_ENGINE=nivo`.
 */
export function resolveChartEngine(uiPreset: string | undefined | null, override?: ChartEngine): ChartEngine {
  if (override) return override;
  if (uiPreset === 'atlas') return 'nivo';
  return process.env.NEXT_PUBLIC_CHART_ENGINE === 'nivo' ? 'nivo' : 'recharts';
}
