import type {ChartSeries} from '../../lib/atlas-contracts';

export function AnalyticsChartTable({series, caption}: {series: ChartSeries; caption: string}) {
  return (
    <div className="analytics-chart-table">
      <table className="summary-table" aria-label={caption}>
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr>
            <th scope="col">Period</th>
            <th scope="col" className="cs-financial">Value ({series.unit})</th>
          </tr>
        </thead>
        <tbody>
          {series.points.map(point => (
            <tr key={point.timestamp}>
              <td>{point.timestamp}</td>
              <td className="cs-financial">{point.value == null ? '—' : point.value}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
