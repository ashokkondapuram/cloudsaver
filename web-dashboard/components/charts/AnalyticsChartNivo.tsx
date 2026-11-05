'use client';

import {ResponsiveLine} from '@nivo/line';
import type {ChartVisualTokens} from '../../lib/chart-theme';
import {nivoChartTheme} from '../../lib/chart-theme';
import type {ChartSeries} from '../../lib/atlas-contracts';
import {chartPointsForDisplay} from '../../lib/atlas-contracts';

type Props = {series: ChartSeries; height: number; unitLabel: string; tokens: ChartVisualTokens};

export function AnalyticsChartNivo({series, height, unitLabel, tokens}: Props) {
  const rows = chartPointsForDisplay(series);
  return (
    <div className="trend-chart nivo-trend-chart" style={{height}} role="presentation">
      <ResponsiveLine
        animate={false}
        enableSlices={false}
        enablePoints={false}
        enableGridX={false}
        useMesh
        curve="linear"
        margin={{top: 8, right: 12, bottom: 28, left: 48}}
        xScale={{type: 'point'}}
        yScale={{type: 'linear', min: 'auto', max: 'auto', stacked: false}}
        axisBottom={{tickSize: 0, tickPadding: 8, tickRotation: 0}}
        axisLeft={{tickSize: 0, tickPadding: 8}}
        colors={[tokens.line]}
        theme={nivoChartTheme(tokens)}
        data={[
          {
            id: series.label,
            data: rows.map(row => ({x: row.x, y: row.y})),
          },
        ]}
        tooltip={({point}) => (
          <div>
            <strong>{String(point.data.x)}</strong>
            <div>
              {point.data.y == null ? '—' : point.data.y} {unitLabel}
            </div>
          </div>
        )}
      />
    </div>
  );
}
