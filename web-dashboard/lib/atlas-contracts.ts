/** Proposed Atlas analytics and notification contracts (frontend adapters). */

export type MetricPoint = {timestamp: string; value: number | null};

export type ChartSeriesStatus = 'complete' | 'partial' | 'stale' | 'unavailable';

export type ChartSeries = {
  id: string;
  label: string;
  unit: string;
  currency?: string;
  status: ChartSeriesStatus;
  observedAt: string | null;
  points: MetricPoint[];
};

export type NoticeSeverity = 'info' | 'success' | 'warning' | 'error';

export type AtlasNotice = {
  id: string;
  severity: NoticeSeverity;
  title: string;
  description?: string;
  action?: {label: string; href: string};
  persistent?: boolean;
};

export function validateChartSeries(series: ChartSeries): string | null {
  if (!series.id || !series.label || !series.unit) return 'Series requires id, label, and unit.';
  if (!['complete', 'partial', 'stale', 'unavailable'].includes(series.status)) {
    return 'Series status must be complete, partial, stale, or unavailable.';
  }
  for (const point of series.points) {
    if (point.value !== null && (!Number.isFinite(point.value) || Number.isNaN(point.value))) {
      return 'Series points must be finite numbers or null gaps.';
    }
  }
  return null;
}

export function chartPointsForDisplay(series: ChartSeries): {x: string; y: number | null}[] {
  return series.points.map(point => ({x: point.timestamp, y: point.value}));
}
