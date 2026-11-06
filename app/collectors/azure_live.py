"""Read-only Azure Monitor, Activity Log and operational guard evidence."""
from datetime import datetime,timedelta,timezone
from app.collectors.azure_endpoint import ARM_ROOT, validate_arm_https_url, arm_url
from app.azure_rest_catalog import (
    ACTIVITY_LOG_EVENTS_API_VERSION,
    AUTHORIZATION_LOCKS_API_VERSION,
    activity_log_events_url,
    resource_metrics_params,
    resource_metrics_url,
)
from app.collectors.live_common import window,series,collect,enrich_metrics,transition
from app.telemetry_contract import moment

ARM=ARM_ROOT
from app.azure_resource_registry import azure_monitor_metrics_catalog

METRICS = azure_monitor_metrics_catalog()

def pages(reader,url,params=None):
    from app.collectors._pagination import iter_arm_next_link_values

    yield from iter_arm_next_link_values(
        reader,
        url,
        params,
        validate_link=validate_arm_https_url,
    )

_AZURE_AGG_VALUE = {
    'Maximum': 'maximum',
    'Minimum': 'minimum',
    'Average': 'average',
    'Total': 'total',
}


def _series_from_platform_metric(metric,*,name,aggregation,now):
    agg_key = _AZURE_AGG_VALUE.get(aggregation, aggregation.lower())
    if (metric.get('name') or {}).get('value') != name or metric.get('errorCode') not in (None, 'Success'):
        return None
    streams = metric.get('timeseries') or []
    # Unspecified dimensions cannot be collapsed by max and treated as a total.
    if len(streams) != 1 or streams[0].get('metadatavalues'):
        return None
    points = [
        (p.get('timeStamp'), p.get(agg_key))
        for p in streams[0].get('data', [])
        if p.get(agg_key) is not None
    ]
    return dict(
        **series(points, now, bucket_start=True),
        source_aggregation=aggregation,
        azure_metric_name=name,
    )


def fetch_azure_monitor_series(reader,resource,now):
    start,end=window(now);rid=resource['resource_id'];result={}
    for key,spec in METRICS.get(resource['resource_type'].lower(),{}).items():
        name, aggregation = spec if isinstance(spec, tuple) else (spec, 'Maximum')
        data=reader.get(
            resource_metrics_url(rid),
            resource_metrics_params(
                timespan=start.isoformat()+'/'+end.isoformat(),
                metricnames=name,
                aggregation=aggregation,
            ),
        )
        values=data.get('value')
        if not isinstance(values, list) or len(values) != 1:
            continue
        parsed = _series_from_platform_metric(values[0], name=name, aggregation=aggregation, now=now)
        if parsed is not None:
            result[key] = parsed
    return result

def _azure_activity_log_events(reader, resource, now):
    rid = resource['resource_id']
    url = activity_log_events_url(resource['subscription_id'])
    params = {
        'api-version': ACTIVITY_LOG_EVENTS_API_VERSION,
        '$filter': "eventTimestamp ge '" + (now - timedelta(days=90)).isoformat() + "' and resourceUri eq '" + rid + "'",
    }
    raw = []
    for event in pages(reader, url, params):
        if str(event.get('resourceId', '')).lower() != rid.lower():
            raise ValueError('Activity event outside requested resource')
        if (event.get('status') or {}).get('value') != 'Succeeded':
            continue
        raw.append(event)
    return raw


def collect_azure_activity_log_evidence(reader, resource, now):
    from app.collectors.activity_events import append_activity_events, normalize_activity_event

    e = resource.get('evidence') or {}
    current = e.get('disk_state') or e.get('power_state')
    if e.get('association_verified') is False:
        current = 'Unassociated'
    if e.get('hosted_app_count') == 0 and e.get('deployment_slot_count') == 0:
        current = 'Empty'
    expected = current
    transition_events = []
    normalized = []
    states = {
        'microsoft.compute/disks/detach/action': 'Unattached',
        'microsoft.compute/virtualmachines/deallocate/action': 'PowerState/deallocated',
        'microsoft.compute/virtualmachines/stop/action': 'PowerState/stopped',
    }
    for event in _azure_activity_log_events(reader, resource, now):
        operation = (event.get('operationName') or {}).get('value', '').lower()
        if operation.endswith(('/write', '/delete', '/action')):
            transition_events.append((moment(event.get('eventTimestamp')), states.get(operation, 'Unknown')))
        item = normalize_activity_event(provider='azure', payload=event)
        if item:
            normalized.append(item)
    normalized.sort(key=lambda item: item.get('event_time') or '', reverse=True)
    append_activity_events(resource.setdefault('evidence', {}), normalized)
    return transition(transition_events, current, expected, now) if expected else None


def fetch_azure_state_history(reader, resource, now):
    return collect_azure_activity_log_evidence(reader, resource, now)


def fetch_azure_activity_events(reader, resource, now):
    collect_azure_activity_log_evidence(reader, resource, now)
    return (resource.get('evidence') or {}).get('activity_events')

def fetch_flow_logs_enabled(reader, subscription_id, region):
    """True when any NSG flow log is enabled in the resource region (subscription watchers)."""
    if not isinstance(region, str) or not region.strip():
        return None
    region_key = region.replace(' ', '').lower()
    saw_disabled = False
    url = ARM + '/subscriptions/' + subscription_id + '/providers/Microsoft.Network/networkWatchers'
    for watcher in pages(reader, url, {'api-version': '2023-05-01'}):
        if (watcher.get('location') or '').replace(' ', '').lower() != region_key:
            continue
        wid = watcher.get('id') or ''
        for fl in pages(reader, ARM + wid + '/flowLogs', {'api-version': '2023-05-01'}):
            props = fl.get('properties') or {}
            if props.get('enabled') is True:
                return True
            if props.get('enabled') is False:
                saw_disabled = True
    return False if saw_disabled else None

def fetch_azure_operational_guards(reader,resource,now):
    rid=resource['resource_id'];group='/'.join(rid.split('/')[:5]);result={}
    locks=[]
    for scope in (group,rid):
        locks.extend((r.get('properties') or {}).get('level') for r in pages(reader,arm_url(scope+'/providers/Microsoft.Authorization/locks'),{'api-version':AUTHORIZATION_LOCKS_API_VERSION}))
    result['management_locks']=locks
    if resource['resource_type'].lower()=='microsoft.compute/disks':
        ages=[]
        for snap in pages(reader,ARM+group+'/providers/Microsoft.Compute/snapshots',{'api-version':'2023-04-02'}):
            p=snap.get('properties') or {};source=(p.get('creationData') or {}).get('sourceResourceId','')
            at=moment(p.get('timeCreated'))
            if source.lower()==rid.lower() and p.get('provisioningState')=='Succeeded' and at and at<=now:ages.append((now-at).total_seconds()/3600)
        result.update(recent_snapshot_verified=bool(ages and min(ages)<24),snapshot_age_hours=min(ages) if ages else None)
    if resource['resource_type'].lower()=='microsoft.web/serverfarms':
        sites=list(pages(reader,ARM+rid+'/sites',{'api-version':'2023-12-01'}));slots=0
        for site in sites:
            if (site.get('properties') or {}).get('serverFarmId','').lower()!=rid.lower():raise ValueError('Unrelated App Service site')
            slots+=len(list(pages(reader,ARM+site['id']+'/slots',{'api-version':'2023-12-01'})))
        result.update(deployment_slot_count=slots,hosted_app_count=len(sites))
        paths=[((s.get('properties') or {}).get('siteConfig') or {}).get('healthCheckPath') for s in sites]
        paths=[p for p in paths if isinstance(p,str) and p]
        if paths:
            result['health_probes_enabled']=True
            result['health_check_paths']=paths[:20]
        elif sites:
            result['health_probes_enabled']=False
    if resource['resource_type'].lower().startswith('microsoft.network/'):
        flow = fetch_flow_logs_enabled(reader, resource['subscription_id'], resource.get('region'))
        if type(flow) is bool:
            result['flow_logs_enabled'] = flow
    return result

def fetch_backup_replication(reader,subscription):
    """Read every vault before asserting absence; one denied plane stays unknown."""
    protected=set();replicated=set();prefix='/subscriptions/'+subscription+'/'
    for vault in pages(reader,ARM+'/subscriptions/'+subscription+'/providers/Microsoft.RecoveryServices/vaults',{'api-version':'2023-06-01'}):
        vid=vault.get('id','')
        if not vid.lower().startswith(prefix.lower()) or '/providers/microsoft.recoveryservices/vaults/' not in vid.lower():raise ValueError('Recovery vault outside requested subscription')
        for item in pages(reader,ARM+vid+'/backupProtectedItems',{'api-version':'2023-02-01'}):
            p=item.get('properties') or {};rid=p.get('sourceResourceId') or p.get('virtualMachineId')
            if isinstance(rid,str) and rid.lower().startswith(prefix.lower()):protected.add(rid.lower())
        for fabric in pages(reader,ARM+vid+'/replicationFabrics',{'api-version':'2023-02-01'}):
            fid=fabric.get('id','')
            if not fid.lower().startswith(vid.lower()+'/replicationfabrics/'):raise ValueError('Invalid ASR fabric')
            for container in pages(reader,ARM+fid+'/replicationProtectionContainers',{'api-version':'2023-02-01'}):
                cid=container.get('id','')
                if not cid.lower().startswith(fid.lower()+'/replicationprotectioncontainers/'):raise ValueError('Invalid ASR container')
                for item in pages(reader,ARM+cid+'/replicationProtectedItems',{'api-version':'2023-02-01'}):
                    p=item.get('properties') or {};rid=p.get('protectedItemId') or (p.get('providerSpecificDetails') or {}).get('fabricObjectId')
                    if isinstance(rid,str) and rid.lower().startswith(prefix.lower()):replicated.add(rid.lower())
    return protected,replicated

def _live_resource_limit(settings=None):
    from app.cloudsaver_platform_settings import integration_int
    value = integration_int(settings, 'live_evidence_max_resources', 'CLOUDSAVER_LIVE_EVIDENCE_MAX_RESOURCES', default=0)
    if value == 0:
        return None
    if not 1 <= value <= 50000:
        raise ValueError('Live evidence bound must be 0 (all metric types) or 1–50000')
    return value


def enrich_live_row(reader, resource, *, now=None, recovery=None, batch_metrics=None):
    now = now or datetime.now(timezone.utc)
    recovery = recovery if recovery is not None else {}
    if resource['resource_type'].lower() not in METRICS:
        return resource
    e = resource.setdefault('evidence', {})
    sub = resource['subscription_id']
    if sub not in recovery:
        recovery[sub] = collect(e, 'recovery_services', lambda: fetch_backup_replication(reader, sub))
    if recovery[sub] is not None:
        e.update(
            backup_enrolled=resource['resource_id'].lower() in recovery[sub][0],
            replication_enrolled=resource['resource_id'].lower() in recovery[sub][1],
        )
    else:
        e.setdefault('live_sources', {})['recovery_services'] = 'unavailable_or_incomplete'
    guards = collect(e, 'operational_guards', lambda: fetch_azure_operational_guards(reader, resource, now))
    if guards:
        e.update(guards)
    def load_monitor():
        if batch_metrics is not None:
            cached = batch_metrics.get((resource.get('resource_id') or '').lower())
            if cached is not None:
                return cached
        return fetch_azure_monitor_series(reader, resource, now)

    values = collect(e, 'azure_monitor', load_monitor)
    if values:
        enrich_metrics(e, values, now)
    e['state_history'] = collect(e, 'activity_log', lambda: fetch_azure_state_history(reader, resource, now))
    from app.collectors.azure_configuration_evidence import enrich_configuration_evidence
    enrich_configuration_evidence(resource)
    from app.resource_timestamps import touch_azure_status_fetched

    touch_azure_status_fetched(e, now=now)
    return resource


def enrich(reader,inventory,now=None,*,settings=None):
    now=now or datetime.now(timezone.utc)
    limit = _live_resource_limit(settings)
    candidates=[r for r in inventory if r['resource_type'].lower() in METRICS]
    from app.collectors.azure_configuration_evidence import enrich_configuration_evidence, live_collection_priority
    candidates.sort(key=live_collection_priority)
    recovery={}
    if limit is not None:
        for r in candidates[limit:]:
            r.setdefault('evidence', {}).setdefault('live_sources', {})['telemetry'] = 'resource_budget_exceeded'
            enrich_configuration_evidence(r)
    selected = candidates if limit is None else candidates[:limit]
    from app.collectors.azure_monitor_batch import prefetch_batch_metrics
    batch_metrics = prefetch_batch_metrics(reader, selected, now)
    for r in selected:
        enrich_live_row(reader, r, now=now, recovery=recovery, batch_metrics=batch_metrics)
    return inventory
