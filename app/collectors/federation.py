"""Inventory survives independently failed secondary metric/cost sources."""
from datetime import datetime, timedelta, timezone
from app.collectors import kubernetes as collector
from app.collectors.provenance import entry, digest
from app.inventory import FindingBatch
from app.kubernetes_topology import project
from app.kubernetes_rules import evaluate_inventory, findings_from
from app.k8s_cost_reconciler import allocations


def scan(source, binding, *, api_reader=None, metric_reader=None, cost_reader=None, now=None):
    now=now or datetime.now(timezone.utc)
    owned=[]
    try:
        if api_reader is None:
            api_reader=collector.token_reader(binding['api_token_env']);owned.append(api_reader)
        objects,sources=collector.inventory(api_reader,binding['api_url'])
        try:
            if metric_reader is None:
                from app.collectors.prometheus_auth import reader
                metric_reader=reader(source,binding);owned.append(metric_reader)
            metrics,metric_sources=collector.telemetry(metric_reader,source['prometheus_url'],source['cluster_id'],now)
            sources.extend(metric_sources)
        except Exception:
            metrics={}
            sources.append(entry('prometheus','prometheus_range_api',status='unavailable',reason='identity_or_endpoint_unavailable'))
        rows=project(source['cluster_id'],objects,metrics,sources,now)
        if binding.get('opencost_url'):
            try:
                if cost_reader is None:
                    cost_reader=collector.token_reader(binding.get('opencost_token_env'));owned.append(cost_reader)
                end=now.replace(second=0,microsecond=0)-timedelta(minutes=now.minute%5);start=end-timedelta(days=30)
                containers={tuple(r['evidence'].get(k) for k in ('namespace','pod','container')) for r in rows if r['resource_type']=='kubernetes.io/Container'}
                payload=cost_reader.get(binding['opencost_url'].rstrip('/')+'/allocation',{'window':start.isoformat()+','+end.isoformat(),'aggregate':'cluster,namespace,pod,container','accumulate':'true'})
                cost=allocations(payload,source['cluster_id'],containers,start,end)
                for row in rows:
                    key=tuple(row['evidence'].get(k) for k in ('namespace','pod','container'))
                    if key in cost:row['evidence']['allocation']=cost[key]
                sources.append(entry('opencost','opencost_allocation',start=start.isoformat(),end=end.isoformat(),now=now,status='available' if cost else 'insufficient',digest=digest(cost_as_list(cost))))
            except Exception:
                sources.append(entry('opencost','opencost_allocation',status='unavailable',reason='allocation_unavailable_or_unreconciled'))
        else:
            sources.append(entry('opencost','opencost_allocation',status='not_configured',reason='operator_binding_required'))
        for row in rows:
            row['data_sources']=sources
        evaluations=evaluate_inventory(rows,observed_at=now.isoformat(),now=now)
        return FindingBatch(findings_from(evaluations,rows),rows,basis='kubernetes_api_discovery')
    finally:
        for value in owned:value.close()


def cost_as_list(cost):
    return [{'identity':list(key),**value} for key,value in sorted(cost.items())]
