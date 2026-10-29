"""Read-only evidence windows and bounded, non-sensitive failure provenance."""
from datetime import datetime,timedelta,timezone
import math,os
from app.telemetry_contract import moment,evaluate_series,TimeSeriesEvidenceContract

def enabled():return os.getenv('CLOUDSAVER_LIVE_EVIDENCE_ENABLED','false').lower()=='true'

def window(now):
    end=now.astimezone(timezone.utc).replace(second=0,microsecond=0)
    end-=timedelta(minutes=end.minute%5)
    return end-timedelta(days=30),end

def series(points,now,*,bucket_start=False,scale=1):
    start,end=window(now);seen={}
    for at,value in points:
        at=moment(at)
        if at and bucket_start:at+=timedelta(minutes=5)
        if not at or not start<at<=end:continue
        if type(value) not in (int,float) or not math.isfinite(value) or value<0 or at in seen:raise ValueError('Invalid or duplicate metric sample')
        seen[at]=value*scale
    return dict(window_start=start.isoformat(),window_end=end.isoformat(),points=[dict(at=t.isoformat(),value=v) for t,v in sorted(seen.items())])

def summary(value,name,now):
    results={stat:evaluate_series(value,TimeSeriesEvidenceContract(name,agg),now=now,require_resource_age=False)
        for stat,agg in (('p95','P95'),('p99','P99'),('maximum','MAX'))}
    r=results['p95']
    return dict(sufficient=all(v.is_sufficient for v in results.values()),coverage_ratio=r.coverage_ratio,
        window_start=r.window_start.isoformat() if r.window_start else None,window_end=r.window_end.isoformat() if r.window_end else None,
        samples=r.valid_samples,step_seconds=300,max_gap_seconds=r.max_observed_gap_minutes*60 if r.max_observed_gap_minutes is not None else None,
        gap_reason=r.gap_reason,**{k:v.observed_value for k,v in results.items()})

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

def transition(events,current,expected,now):
    """The latest authoritative state-changing event must agree with current state.

    No creation-time or no-event fallback; missing history is not an idle interval.
    """
    relevant=sorted((time,state) for time,state in events if time and time<=now)
    if not relevant or relevant[-1][1]!=expected or current!=expected:return None
    start=relevant[-1][0]
    return [dict(state=expected,start=start.isoformat(),end=now.isoformat(),complete=True)] if start<now else None
