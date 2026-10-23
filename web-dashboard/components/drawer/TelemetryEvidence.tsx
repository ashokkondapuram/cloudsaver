import {Activity,Clock3} from 'lucide-react';
import type {Finding} from '../../lib/types';
import {dateTime} from '../../lib/finops';
import {Notice} from '../ui/shared';

function numeric(value:unknown){return typeof value==='number'&&Number.isFinite(value)&&value>=0?value:null;}
export function TelemetryEvidence({finding}:{finding:Finding}){
  const evidence=finding.evidence||{};
  const p95=numeric(evidence.p95_usage),request=numeric(evidence.minimum_request);
  const dimension=evidence.dimension==='cpu'?'CPU':evidence.dimension==='memory'?'Memory':null;
  const unit=evidence.unit==='cores'?'cores':evidence.unit==='bytes'?'bytes':null;
  const complete=evidence.window_days===14&&p95!==null;
  return <div className="telemetry-evidence"><span className="eyebrow">SAVED WORKLOAD OBSERVATIONS</span><h3>Utilization & headroom</h3>
    <p className="muted">{dimension?`${dimension} request-sizing evidence`:'Metric coverage'} from this finding’s original snapshot.</p>
    <div className="telemetry-window"><Clock3 size={14}/><strong>{complete?'Complete 14-day sampled window':'Complete utilization window unavailable'}</strong></div>
    {dimension&&unit?<><div className="telemetry-metrics"><article><span>{dimension} P95 usage</span><strong>{p95===null?'Unknown':p95.toLocaleString(undefined,{maximumFractionDigits:4})}</strong><small>{unit} · hourly samples{dimension==='CPU'?' of five-minute rates':''}</small></article><article><span>Minimum observed request</span><strong>{request===null?'Unknown':request.toLocaleString(undefined,{maximumFractionDigits:4})}</strong><small>{unit} · request is not a cloud bill</small></article></div><dl className="detail-metadata">{typeof evidence.window_start==='string'&&<div><dt>Window start</dt><dd>{dateTime(evidence.window_start)}</dd></div>}{typeof evidence.window_end==='string'&&<div><dt>Window end</dt><dd>{dateTime(evidence.window_end)}</dd></div>}{numeric(evidence.samples)!==null&&<div><dt>Samples</dt><dd>{Number(evidence.samples).toLocaleString()}</dd></div>}{numeric(evidence.step_seconds)!==null&&<div><dt>Sample interval</dt><dd>{Number(evidence.step_seconds).toLocaleString()} seconds</dd></div>}</dl><Notice>Sampled P95 supports request review. Validate bursts, limits, controller configuration, and SLOs before resizing.</Notice></>:<div className="telemetry-empty"><Activity size={22}/><div><h4>No utilization series is attached</h4><p>Stopped or unattached state does not establish idle duration. CPU, memory, IOPS, and network usage remain unknown for this observation.</p></div></div>}
    <div className="drawer-section"><h3>Historical activity chart</h3><p className="muted">Raw time-series samples are not returned with this finding. A chart will need an authorized telemetry feed; no zero-activity line or synthetic history is inferred.</p></div>
  </div>;
}
