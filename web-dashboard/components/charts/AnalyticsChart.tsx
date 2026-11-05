'use client';

import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type {ChartSeries} from '../../lib/atlas-contracts';
import {chartPointsForDisplay, validateChartSeries} from '../../lib/atlas-contracts';
import {AnalyticsChartTable} from './AnalyticsChartTable';

type Props = {
  title: string;
  interpretation?: string;
  periodLabel: string;
  series: ChartSeries;
  height?: number;
  className?: string;
};

/** Internal chart boundary — pages depend on this adapter, not on Recharts directly. */
export function AnalyticsChart({title, interpretation, periodLabel, series, height = 228, className = ''}: Props) {
  const error = validateChartSeries(series);
  const rows = chartPointsForDisplay(series);
  const unitLabel = series.currency ? `${series.currency} ${series.unit}` : series.unit;

  if (error || series.status === 'unavailable') {
    return (
      <section className={`panel analytics-chart ${className}`} aria-labelledby={`${series.id}-title`}>
        <div className="section-title">
          <div>
            <span className="eyebrow">{periodLabel}</span>
            <h2 id={`${series.id}-title`}>{title}</h2>
            {interpretation && <p>{interpretation}</p>}
          </div>
        </div>
        <p className="chart-error" role="status">
          {error || 'Chart data is unavailable for this scope.'}
        </p>
        <AnalyticsChartTable series={series} caption={`${title} — tabular view`} />
      </section>
    );
  }

  return (
    <section className={`panel analytics-chart ${className}`} aria-labelledby={`${series.id}-title`}>
      <div className="section-title">
        <div>
          <span className="eyebrow">{periodLabel}{series.status !== 'complete' ? ` · ${series.status}` : ''}</span>
          <h2 id={`${series.id}-title`}>{title}</h2>
          {interpretation && <p>{interpretation}</p>}
        </div>
      </div>
      <p className="sr-only">
        {title}. {interpretation || ''} Values in {unitLabel}.
        {rows.filter(r => r.y !== null).length} plotted points with null gaps preserved in the table below.
      </p>
      <div className="trend-chart" style={{height}} aria-hidden="true">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={rows} margin={{top: 8, right: 12, left: 0, bottom: 0}}>
            <CartesianGrid stroke="var(--chart-grid)" vertical={false} />
            <XAxis dataKey="x" tick={{fontSize: 11, fill: 'var(--chart-muted)'}} tickLine={false} axisLine={false} />
            <YAxis tick={{fontSize: 11, fill: 'var(--chart-muted)'}} tickLine={false} axisLine={false} width={48} />
            <Tooltip
              contentStyle={{background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 8}}
              formatter={(value) => {
                const numeric = typeof value === 'number' ? value : null;
                return [numeric == null ? '—' : numeric, unitLabel];
              }}
            />
            <Line
              type="linear"
              dataKey="y"
              stroke="var(--chart-line)"
              strokeWidth={2}
              dot={false}
              isAnimationActive={false}
              connectNulls={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <AnalyticsChartTable series={series} caption={`${title} — tabular view`} />
    </section>
  );
}
