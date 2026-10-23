'use client';

import {useMemo, useState} from 'react';
import {BarChart3} from 'lucide-react';
import {Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis} from 'recharts';
import {portal} from '../../lib/api';
import {formatDateTime, formatNumber, formatShortDate} from '../../lib/format';
import type {UsageRow, Workspace} from '../../lib/types';
import {useLoad} from '../../lib/useLoad';
import {EmptyState, Loading, Notice, SectionTitle} from '../ui/shared';

const HOUR = 3_600_000;
const DAYS = 7;

type Point = {time: number; success: number; failure: number};

function ChartTooltip({active, payload, label}: {active?: boolean; payload?: ReadonlyArray<{dataKey?: unknown; value?: unknown}>; label?: unknown}) {
  if (!active || !payload?.length) return null;
  const value = (key: string) => Number(payload.find(item => item.dataKey === key)?.value || 0);
  return <div className="chart-tooltip">
    <strong>{formatDateTime(Number(label))}</strong>
    <span>Successful sign-ins: {formatNumber(value('success'))}</span>
    <span>Failed attempts: {formatNumber(value('failure'))}</span>
  </div>;
}

export function UsageTab({workspace}: {workspace: Workspace}) {
  const [range] = useState(() => {
    const to = new Date();
    return {from: new Date(to.getTime() - DAYS * 24 * HOUR).toISOString(), to: to.toISOString()};
  });
  const {data, error, loading} = useLoad(
    () => portal<{items: UsageRow[]}>(`workspaces/${encodeURIComponent(workspace.tenant_id)}/usage`, {query: range}),
    [workspace.tenant_id, range],
  );
  const rows = useMemo(() => data?.items || [], [data]);

  const points = useMemo<Point[]>(() => {
    const start = Math.floor(new Date(range.from).getTime() / HOUR) * HOUR;
    const end = Math.floor(new Date(range.to).getTime() / HOUR) * HOUR;
    const buckets = new Map<number, Point>();
    for (let time = start; time <= end; time += HOUR) buckets.set(time, {time, success: 0, failure: 0});
    for (const row of rows) {
      const time = Math.floor(new Date(row.hour).getTime() / HOUR) * HOUR;
      const bucket = buckets.get(time);
      if (bucket) {bucket.success += row.success_count; bucket.failure += row.failure_count;}
    }
    return [...buckets.values()];
  }, [rows, range]);

  const bySource = useMemo(() => {
    const map = new Map<string, {source_ip: string; success: number; failure: number; last_seen: string}>();
    for (const row of rows) {
      const entry = map.get(row.source_ip) || {source_ip: row.source_ip, success: 0, failure: 0, last_seen: row.last_seen_at};
      entry.success += row.success_count; entry.failure += row.failure_count;
      if (row.last_seen_at > entry.last_seen) entry.last_seen = row.last_seen_at;
      map.set(row.source_ip, entry);
    }
    return [...map.values()].sort((a, b) => b.last_seen.localeCompare(a.last_seen));
  }, [rows]);

  const lastSuccess = rows.filter(row => row.success_count > 0).sort((a, b) => b.last_seen_at.localeCompare(a.last_seen_at))[0];
  const lastUsedAt = workspace.last_used_at || lastSuccess?.last_seen_at || null;
  const lastUsedIp = lastSuccess?.source_ip;

  return <>
    <section className="panel">
      <SectionTitle title="Sign-in activity">Successful sign-ins and failed attempts per hour over the last {DAYS} days.</SectionTitle>
      <p className="usage-summary">{lastUsedAt ? <>Last used {formatDateTime(lastUsedAt)}{lastUsedIp ? ` from ${lastUsedIp}` : ''}</> : 'No keys for this workspace have been used yet.'}</p>
      {error && <Notice tone="error">{error}</Notice>}
      {loading && !data ? <Loading label="Loading usage…"/> : <>
        <div className="usage-chart" role="img" aria-label={`Hourly sign-ins over the last ${DAYS} days`}>
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={points} margin={{top: 8, right: 8, left: 0, bottom: 0}}>
              <CartesianGrid stroke="var(--chart-grid)" vertical={false}/>
              <XAxis dataKey="time" type="number" scale="time" domain={['dataMin', 'dataMax']} tickFormatter={value => formatShortDate(Number(value))} stroke="var(--chart-muted)" fontSize={11} tickLine={false} minTickGap={40}/>
              <YAxis allowDecimals={false} stroke="var(--chart-muted)" fontSize={11} tickLine={false} axisLine={false} width={44}/>
              <Tooltip content={props => <ChartTooltip active={props.active} payload={props.payload as ReadonlyArray<{dataKey?: unknown; value?: unknown}>} label={props.label}/>}/>
              <Area type="monotone" dataKey="success" name="Successful sign-ins" stroke="var(--chart-success)" fill="var(--chart-success)" fillOpacity={0.18} strokeWidth={1.5} isAnimationActive={false}/>
              <Area type="monotone" dataKey="failure" name="Failed attempts" stroke="var(--chart-failure)" fill="var(--chart-failure)" fillOpacity={0.18} strokeWidth={1.5} isAnimationActive={false}/>
            </AreaChart>
          </ResponsiveContainer>
        </div>
        <div className="chart-legend"><span><i style={{background: 'var(--chart-success)'}}/>Successful sign-ins</span><span><i style={{background: 'var(--chart-failure)'}}/>Failed attempts</span></div>
      </>}
    </section>
    <section className="panel">
      <SectionTitle title="Sources">Where sign-ins came from in the last {DAYS} days.</SectionTitle>
      {!loading && !bySource.length ? <EmptyState icon={BarChart3} title="No sign-ins yet">Sign-ins appear here after a customer uses a key.</EmptyState> :
        <div className="summary-table-scroll"><table className="summary-table">
          <thead><tr><th>Source IP</th><th className="number">Successful sign-ins</th><th className="number">Failed attempts</th><th>Last seen</th></tr></thead>
          <tbody>{bySource.map(source => <tr key={source.source_ip}>
            <td><code>{source.source_ip}</code></td>
            <td className="number">{formatNumber(source.success)}</td>
            <td className="number">{formatNumber(source.failure)}</td>
            <td>{formatDateTime(source.last_seen)}</td>
          </tr>)}</tbody>
        </table></div>}
    </section>
  </>;
}
