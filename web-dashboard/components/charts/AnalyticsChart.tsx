'use client';

import type {ChartEngine} from '../../lib/chart-engine';
import {resolveChartEngine} from '../../lib/chart-engine';
import {chartTokensForUiPreset} from '../../lib/chart-theme';
import type {ChartSeries} from '../../lib/atlas-contracts';
import {chartPointsForDisplay, validateChartSeries} from '../../lib/atlas-contracts';
import {activeUiThemePreset} from '../../lib/ui-theme';
import {useWorkspace} from '../WorkspaceProvider';
import {AnalyticsChartTable} from './AnalyticsChartTable';
import {AnalyticsChartNivo} from './AnalyticsChartNivo';
import {AnalyticsChartRecharts} from './AnalyticsChartRecharts';

type Props = {
  title: string;
  interpretation?: string;
  periodLabel: string;
  series: ChartSeries;
  height?: number;
  className?: string;
  engine?: ChartEngine;
};

/** Internal chart boundary — pages depend on this adapter, not on Recharts/Nivo directly. */
export function AnalyticsChart({
  title,
  interpretation,
  periodLabel,
  series,
  height = 228,
  className = '',
  engine,
}: Props) {
  const {workspace} = useWorkspace();
  const uiPreset = activeUiThemePreset(workspace?.ui_theme_preset);
  const tokens = chartTokensForUiPreset(uiPreset);
  const error = validateChartSeries(series);
  const rows = chartPointsForDisplay(series);
  const unitLabel = series.currency ? `${series.currency} ${series.unit}` : series.unit;
  const chartEngine = resolveChartEngine(uiPreset, engine);

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

  const ChartBody =
    chartEngine === 'nivo' ? (
      <AnalyticsChartNivo series={series} height={height} unitLabel={unitLabel} tokens={tokens} labelledBy={`${series.id}-title`} />
    ) : (
      <AnalyticsChartRecharts series={series} height={height} unitLabel={unitLabel} tokens={tokens} />
    );

  return (
    <section
      className={`panel analytics-chart ${className}`}
      aria-labelledby={`${series.id}-title`}
      data-chart-engine={chartEngine}
      data-chart-theme={uiPreset === 'atlas' ? 'atlas-cs' : 'semantic'}
    >
      <div className="section-title">
        <div>
          <span className="eyebrow">
            {periodLabel}
            {series.status !== 'complete' ? ` · ${series.status}` : ''}
          </span>
          <h2 id={`${series.id}-title`}>{title}</h2>
          {interpretation && <p>{interpretation}</p>}
        </div>
      </div>
      <p className="sr-only">
        {title}. {interpretation || ''} Values in {unitLabel}.
        {rows.filter(r => r.y !== null).length} plotted points with null gaps preserved in the table below.
      </p>
      {ChartBody}
      <AnalyticsChartTable series={series} caption={`${title} — tabular view`} />
    </section>
  );
}
