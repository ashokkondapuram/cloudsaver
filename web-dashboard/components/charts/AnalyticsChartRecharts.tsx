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
import {chartPointsForDisplay} from '../../lib/atlas-contracts';

type Props = {series: ChartSeries; height: number; unitLabel: string};

export function AnalyticsChartRecharts({series, height, unitLabel}: Props) {
  const rows = chartPointsForDisplay(series);
  return (
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
  );
}
