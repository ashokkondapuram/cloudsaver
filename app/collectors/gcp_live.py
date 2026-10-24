"""Cloud Asset, Monitoring and Audit readers with exact project/resource fences."""
from datetime import datetime,timedelta,timezone
import json,os
from app.cloud_http import pages
from app.collectors.live_common import window,series,collect,enrich_metrics,transition
from app.telemetry_contract import moment

ASSET_TYPES={
 'compute.googleapis.com/Instance':'compute.googleapis.com/Instance','compute.googleapis.com/ForwardingRule':'compute.googleapis.com/ForwardingRule',
 'alloydb.googleapis.com/Cluster':'alloydb.googleapis.com/Cluster','bigqueryreservation.googleapis.com/Reservation':'bigquery.googleapis.com/Reservation',
 'run.googleapis.com/Service':'run.googleapis.com/Service','redis.googleapis.com/Instance':'redis.googleapis.com/Instance',
 'aiplatform.googleapis.com/Endpoint':'aiplatform.googleapis.com/Endpoint','compute.googleapis.com/Router':'compute.googleapis.com/RouterNat',
}

def extra_inventory(reader,project,regions):
    rows=[]
    for page in pages(reader,'https://cloudasset.googleapis.com/v1/projects/'+project+'/assets',{'contentType':'RESOURCE','assetTypes':list(ASSET_TYPES),'pageSize':500}):
        for asset in page.get('assets',[]):
            kind=asset.get('assetType');rid=asset.get('name','');record=asset.get('resource') or {};data=record.get('data') or {};location=record.get('location')
            if kind not in ASSET_TYPES or '/projects/'+project+'/' not in rid:raise ValueError('Cloud Asset returned an unrelated resource')
            region=location.rsplit('-',1)[0] if location and location[-2:-1]=='-' else location
            if region not in regions:continue
            e=dict(source='Cloud Asset API',state=data.get('status',data.get('state')),power_state=data.get('status'),created_at=data.get('creationTimestamp'),
                labels=data.get('labels') or {},instance_id=str(data['id']) if data.get('id') is not None else None)
            # Deliberately omit environment variables, SQL users, arbitrary spec
            # text, networking addresses and credentials from config projection.
            if kind=='compute.googleapis.com/Instance':
                edges=[]
                for disk in data.get('disks',[]):
                    source=disk.get('source','')
                    if '/projects/'+project+'/' in source:
                        edges.append(dict(relationship='vm_to_disk',from_resource_id=rid,to_resource_id='//compute.googleapis.com'+source[source.index('/projects/'):],verification_state='verified',observed_at=datetime.now(timezone.utc).isoformat()))
            else:edges=[]
            if kind=='run.googleapis.com/Service':
                template=data.get('template') or {};e.update(minimum_instances=(template.get('scaling') or {}).get('minInstanceCount'),nonproduction=e['labels'].get('environment') in ('dev','test','staging','sandbox'))
            if kind=='redis.googleapis.com/Instance':e.update(memory_size_gb=data.get('memorySizeGb'),multi_az=data.get('tier')=='STANDARD_HA',tls_required=data.get('transitEncryptionMode')=='SERVER_AUTHENTICATION' if 'transitEncryptionMode' in data else None)
            if kind=='aiplatform.googleapis.com/Endpoint':e.update(encrypted=bool(data.get('encryptionSpec')) if 'encryptionSpec' in data else None,replica_count=sum(v.get('dedicatedResources',{}).get('minReplicaCount',0) for v in data.get('deployedModels',[])))
            entries=[(rid,e)]
            if kind=='compute.googleapis.com/Router':entries=[(rid+'/nats/'+n['name'],dict(e,nat_configured=True)) for n in data.get('nats',[])]
            for resource_id,evidence in entries:
                rows.append(dict(cloud_provider='gcp',scope_id=project,subscription_id=project,region=region,resource_id=resource_id,
                    resource_name=resource_id.rsplit('/',1)[-1],resource_group=project,resource_type=ASSET_TYPES[kind],evidence=evidence,
                    dependency_refs=edges,inventory_rule_id='MULTICLOUD_INVENTORY',collector_version='gcp-live-1.4.0'))
    return rows

def gcp_monitoring_series(reader,project,metric_type,resource_filter,now,window_days=30,step_seconds=300):
    if window_days!=30 or step_seconds!=300:raise ValueError('Unsupported metric contract')
    start,end=window(now);streams=[]
    params={'filter':'metric.type = '+json.dumps(metric_type)+' AND '+resource_filter,'interval.startTime':start.isoformat(),'interval.endTime':end.isoformat(),
        'aggregation.alignmentPeriod':'300s','aggregation.perSeriesAligner':'ALIGN_MAX','view':'FULL','pageSize':1000}
    for page in pages(reader,'https://monitoring.googleapis.com/v3/projects/'+project+'/timeSeries',params):
        if page.get('executionErrors'):raise ValueError('Incomplete Cloud Monitoring response')
        for value in page.get('timeSeries',[]):
            if value.get('metric',{}).get('type')!=metric_type or value.get('resource',{}).get('labels',{}).get('project_id')!=project:raise ValueError('Monitoring scope mismatch')
            streams.append(value)
            if len(streams)>100:raise ValueError('Ambiguous multi-dimensional telemetry')
    # Unverified dimensions must not be collapsed into a misleading zero/maximum.
    if len(streams)!=1:return series([],now)
    points=[]
    for p in streams[0].get('points',[]):
        raw=p.get('value') or {};v=raw.get('doubleValue',raw.get('int64Value'))
        if isinstance(v,str):v=float(v)
        if v is not None:points.append((p.get('interval',{}).get('endTime'),v))
    return series(points,now)

def audit_history(reader,project,resource,now):
    rid=resource['resource_id'];e=resource.get('evidence') or {};current='Stopped' if e.get('power_state')=='TERMINATED' else 'Unattached' if e.get('disk_state')=='READY' and e.get('association_verified') is False else None
    query={'resourceNames':['projects/'+project],'filter':'protoPayload.resourceName='+json.dumps(rid.removeprefix('//compute.googleapis.com/'))+' AND timestamp >= '+json.dumps((now-timedelta(days=90)).isoformat()),'pageSize':1000,'orderBy':'timestamp asc'}
    seen=set();events=[]
    for _ in range(200):
        page=reader.post_read('https://logging.googleapis.com/v2/entries:list',query)
        for entry in page.get('entries',[]):
            p=entry.get('protoPayload') or {};source=p.get('resourceName','')
            if source not in (rid,rid.split('.com/',1)[-1]):raise ValueError('Audit resource mismatch')
            if (p.get('status') or {}).get('code',0):continue
            method=p.get('methodName','')
            mapping={'v1.compute.instances.stop':'Stopped','v1.compute.instances.start':'Running','v1.compute.instances.detachDisk':'Unattached','v1.compute.instances.attachDisk':'Attached'}
            if method in mapping:events.append((moment(entry.get('timestamp')),mapping[method]))
        token=page.get('nextPageToken')
        if not token:return transition(events,current,current,now) if current else None
        if token in seen:raise ValueError('Repeated audit continuation')
        seen.add(token);query['pageToken']=token
    raise ValueError('Audit page bound exceeded')

def enrich(reader,project,inventory,now=None):
    now=now or datetime.now(timezone.utc);limit=int(os.getenv('CLOUDSAVER_LIVE_EVIDENCE_MAX_RESOURCES','25'))
    if not 1<=limit<=100:raise ValueError('Live evidence bound must be 1–100 resources')
    for r in inventory[:limit]:
        e=r.setdefault('evidence',{});kind=r['resource_type'];metrics={};spec=[]
        if kind=='compute.googleapis.com/Instance' and e.get('instance_id'):
            f='resource.type = "gce_instance" AND resource.labels.instance_id = '+json.dumps(e['instance_id'])
            spec=[('cpu_fraction','compute.googleapis.com/instance/cpu/utilization',f),('memory_percent','agent.googleapis.com/memory/percent_used',f)]
        elif kind=='sqladmin.googleapis.com/Instance':
            f='resource.type = "cloudsql_database" AND resource.labels.database_id = '+json.dumps(project+':'+r['resource_name'])
            spec=[('cpu_fraction','cloudsql.googleapis.com/database/cpu/utilization',f),('memory_fraction','cloudsql.googleapis.com/database/memory/utilization',f),('connections','cloudsql.googleapis.com/database/network/connections',f)]
        for key,name,f in spec:
            value=collect(e,'gcp_monitoring:'+key,lambda:gcp_monitoring_series(reader,project,name,f,now))
            if value is not None:
                if key.endswith('_fraction'):
                    value=dict(value,points=[dict(p,value=p['value']*100) for p in value['points']]);key=key.replace('_fraction','_percent')
                metrics[key]=value
        enrich_metrics(e,metrics,now)
        e['state_history']=collect(e,'cloud_audit',lambda:audit_history(reader,project,r,now))
        if kind=='compute.googleapis.com/Disk':
            def snapshots():
                ages=[]
                for page in pages(reader,'https://compute.googleapis.com/compute/v1/projects/'+project+'/global/snapshots',{'maxResults':500}):
                    for snap in page.get('items',[]):
                        source=snap.get('sourceDisk','');at=moment(snap.get('creationTimestamp'))
                        if source.endswith(r['resource_id'].split('.com',1)[-1]) and snap.get('status')=='READY' and at and at<=now:ages.append((now-at).total_seconds()/3600)
                return dict(recent_snapshot_verified=bool(ages and min(ages)<24),snapshot_age_hours=min(ages) if ages else None)
            value=collect(e,'snapshots',snapshots)
            if value:e.update(value)
    for r in inventory[limit:]:r.setdefault('evidence',{}).setdefault('live_sources',{})['telemetry']='resource_budget_exceeded'
    return inventory
