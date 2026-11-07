"""Read-only evidence windows and bounded, non-sensitive failure provenance."""
from datetime import datetime,timedelta,timezone
import math,os
from app.telemetry_contract import moment,evaluate_series,TimeSeriesEvidenceContract

def enabled(settings=None):
    from app.cloudsaver_platform_settings import integration_flag
    return integration_flag(settings, 'live_evidence_enabled', 'CLOUDSAVER_LIVE_EVIDENCE_ENABLED')

def window(now):
    end=now.astimezone(timezone.utc).replace(second=0,microsecond=0)
    end-=timedelta(minutes=end.minute%5)
    return end-timedelta(days=30),end

def _snap_bucket(at, start, *, interval_seconds=300):
    offset = int((at - start).total_seconds())
    if offset <= 0:
        return None
    snapped = start + timedelta(seconds=round(offset / interval_seconds) * interval_seconds)
    if snapped <= start:
        return None
    return snapped

def series(points,now,*,bucket_start=False,scale=1,strict=True):
    start,end=window(now);seen={}
    interval=300
    for at,value in points:
        at=moment(at)
        if at and bucket_start:
            at+=timedelta(minutes=5)
        if not at:
            if strict:
                raise ValueError('Invalid metric sample timestamp')
            continue
        if not start<at<=end:
            if strict:
                raise ValueError('Invalid or duplicate metric sample')
            continue
        if type(value) not in (int,float) or not math.isfinite(value) or value<0:
            if strict:
                raise ValueError('Invalid or duplicate metric sample')
            continue
        bucket=_snap_bucket(at,start,interval_seconds=interval) or at
        if bucket <= start or bucket > end:
            if strict:
                raise ValueError('Invalid or duplicate metric sample')
            continue
        if bucket in seen:
            if strict:
                raise ValueError('Invalid or duplicate metric sample')
            continue
        seen[bucket]=value*scale
    if not seen:
        return dict(window_start=start.isoformat(),window_end=end.isoformat(),points=[])
    return dict(window_start=start.isoformat(),window_end=end.isoformat(),points=[dict(at=t.isoformat(),value=v) for t,v in sorted(seen.items())])

def monitor_series(points, now, *, scale=1):
    """Best-effort 5-minute buckets from Azure Monitor samples (never raises)."""
    return series(points, now, bucket_start=False, scale=scale, strict=False)

def summary(value,name,now):
    meta = {}
    if isinstance(value, dict):
        if value.get('source_aggregation'):
            meta['source_aggregation'] = value['source_aggregation']
        if value.get('azure_metric_name'):
            meta['azure_metric_name'] = value['azure_metric_name']
    results={stat:evaluate_series(value,TimeSeriesEvidenceContract(name,agg),now=now,require_resource_age=False)
        for stat,agg in (('p95','P95'),('p99','P99'),('maximum','MAX'))}
    r=results['p95']
    sufficient = r.is_sufficient
    return dict(sufficient=sufficient,coverage_ratio=r.coverage_ratio,
        window_start=r.window_start.isoformat() if r.window_start else None,window_end=r.window_end.isoformat() if r.window_end else None,
        samples=r.valid_samples,step_seconds=300,max_gap_seconds=r.max_observed_gap_minutes*60 if r.max_observed_gap_minutes is not None else None,
        gap_reason=r.gap_reason,**{k:v.observed_value for k,v in results.items()},**meta)

def collect(evidence,plane,fn):
    try:
        value=fn()
        evidence.setdefault('live_sources',{})[plane]='collected'
        return value
    except Exception as error:
        evidence.setdefault('live_sources',{})[plane]='unavailable_or_incomplete'
        if getattr(error,'retry_after',None):
            evidence.setdefault('collection_delays',{})[plane]={'reason':'provider_throttled','retry_after_seconds':error.retry_after}
        return None

def enrich_metrics(evidence,values,now):
    evidence.setdefault('metrics',{}).update(values)
    evidence['metric_summaries']={name:summary(value,name,now) for name,value in evidence['metrics'].items()}

def metrics_utilization_complete(evidence, metric_keys, *, now=None):
    """True when any named metric has a validated utilization window."""
    if not metric_keys:
        return False
    metrics = evidence.get('metrics') or {}
    summaries = evidence.get('metric_summaries') or {}
    now = now or datetime.now(timezone.utc)
    for key in metric_keys:
        summary = summaries.get(key)
        if isinstance(summary, dict) and summary.get('sufficient') is True:
            return True
        series = metrics.get(key)
        if not isinstance(series, dict):
            continue
        contract = TimeSeriesEvidenceContract(key)
        if evaluate_series(series, contract, now=now, require_resource_age=False).is_sufficient:
            return True
    return False

def transition(events,current,expected,now):
    """The latest authoritative state-changing event must agree with current state.

    No creation-time or no-event fallback; missing history is not an idle interval.
    """
    relevant=sorted((time,state) for time,state in events if time and time<=now)
    if not relevant or relevant[-1][1]!=expected or current!=expected:return None
    start=relevant[-1][0]
    return [dict(state=expected,start=start.isoformat(),end=now.isoformat(),complete=True)] if start<now else None
