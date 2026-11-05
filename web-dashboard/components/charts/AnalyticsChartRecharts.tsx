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
import type {ChartVisualTokens} from '../../lib/chart-theme';
import {rechartsChartStyle} from '../../lib/chart-theme';
import type {ChartSeries} from '../../lib/atlas-contracts';
import {chartPointsForDisplay} from '../../lib/atlas-contracts';

type Props = {series: ChartSeries; height: number; unitLabel: string; tokens: ChartVisualTokens};

export function AnalyticsChartRecharts({series, height, unitLabel, tokens}: Props) {
  const rows = chartPointsForDisplay(series);
  const style = rechartsChartStyle(tokens);
  return (
    <div className="trend-chart" style={{height}} role="presentation">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={rows} margin={{top: 8, right: 12, left: 0, bottom: 0}}>
          <CartesianGrid stroke={style.gridStroke} vertical={false} />
          <XAxis dataKey="x" tick={{fontSize: 11, fill: style.tickFill}} tickLine={false} axisLine={false} />
          <YAxis tick={{fontSize: 11, fill: style.tickFill}} tickLine={false} axisLine={false} width={48} />
          <Tooltip
            contentStyle={{background: style.tooltipBackground, border: `1px solid ${style.tooltipBorder}`, borderRadius: 8}}
            formatter={(value) => {
              const numeric = typeof value === 'number' ? value : null;
              return [numeric == null ? '—' : numeric, unitLabel];
            }}
          />
          <Line
            type="linear"
            dataKey="y"
            stroke={style.lineStroke}
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
