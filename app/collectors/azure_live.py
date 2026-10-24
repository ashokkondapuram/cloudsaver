"""Read-only Azure Monitor, Activity Log and operational guard evidence."""
from datetime import datetime,timedelta,timezone
from urllib.parse import urlsplit
from app.collectors.live_common import window,series,collect,enrich_metrics,transition
from app.telemetry_contract import moment

ARM='https://management.azure.com'
METRICS={
 'microsoft.compute/virtualmachines':{'cpu_percent':'Percentage CPU','memory_free_bytes':'Available Memory Bytes','disk_iops':'Disk Read Operations/Sec','network_bytes':'Network In Total','burst_credits':'CPU Credits Remaining'},
 'microsoft.compute/disks':{'iops':'Composite Disk Read Operations/sec','throughput':'Composite Disk Read Bytes/sec','burst_credits':'Disk Paid Burst IO Percentage'},
 'microsoft.network/publicipaddresses':{'ingress_bytes':'ByteCount'},
 'microsoft.network/natgateways':{'network_bytes':'ByteCount','connections':'SNATConnectionCount'},
 'microsoft.network/applicationgateways':{'requests':'TotalRequests','healthy_targets':'HealthyHostCount','capacity_units':'CapacityUnits','latency':'BackendLastByteResponseTime'},
 'microsoft.web/serverfarms':{'cpu_percent':'CpuPercentage','memory_percent':'MemoryPercentage','http_queue':'HttpQueueLength'},
 'microsoft.dbforpostgresql/flexibleservers':{'cpu_percent':'cpu_percent','memory_percent':'memory_percent','connections':'active_connections','iops':'iops'},
 'microsoft.sql/servers/databases':{'cpu_percent':'cpu_percent','connections':'connection_successful'},
 'microsoft.documentdb/databaseaccounts':{'normalized_ru_consumption':'NormalizedRUConsumption'},
 'microsoft.cache/redis':{'memory_percent':'usedmemorypercentage','cpu_percent':'serverLoad','connections':'connectedclients','evictions':'evictedkeys'},
 'microsoft.storage/storageaccounts':{'bytes':'UsedCapacity','requests':'Transactions'},
 'microsoft.cognitiveservices/accounts':{'ptu_utilization':'ProvisionedManagedUtilizationV2','invocations':'AzureOpenAIRequests'},
}

def pages(reader,url,params=None):
    seen=set();scope=urlsplit(url).path.split('/providers/')[0].lower()
    for _ in range(200):
        data=reader.get(url,params);values=data.get('value')
        if not isinstance(values,list):raise ValueError('Invalid Azure page')
        yield from values
        token=data.get('nextLink')
        if not token:return
        parsed=urlsplit(token)
        if token in seen or parsed.scheme!='https' or parsed.netloc!='management.azure.com' or not parsed.path.lower().startswith(scope+'/'):raise ValueError('Invalid Azure continuation')
        seen.add(token);url,params=token,None
    raise ValueError('Azure page bound exceeded')

def fetch_azure_monitor_series(reader,resource,now):
    start,end=window(now);rid=resource['resource_id'];result={}
    for key,name in METRICS.get(resource['resource_type'].lower(),{}).items():
        data=reader.get(ARM+rid+'/providers/microsoft.insights/metrics',dict(**{'api-version':'2023-10-01'},timespan=start.isoformat()+'/'+end.isoformat(),interval='PT5M',metricnames=name,aggregation='Maximum'))
        values=data.get('value')
        if not isinstance(values,list) or len(values)!=1:continue
        metric=values[0]
        if (metric.get('name') or {}).get('value')!=name or metric.get('errorCode') not in (None,'Success'):continue
        streams=metric.get('timeseries') or []
        # Unspecified dimensions cannot be collapsed by max and treated as a total.
        if len(streams)!=1 or streams[0].get('metadatavalues'):continue
        points=[(p.get('timeStamp'),p.get('maximum')) for p in streams[0].get('data',[]) if p.get('maximum') is not None]
        result[key]=series(points,now,bucket_start=True)
    return result

def fetch_azure_state_history(reader,resource,now):
    rid=resource['resource_id'];e=resource.get('evidence') or {};current=e.get('disk_state') or e.get('power_state')
    if e.get('association_verified') is False:current='Unassociated'
    if e.get('hosted_app_count')==0 and e.get('deployment_slot_count')==0:current='Empty'
    expected=current;events=[]
    url=ARM+'/subscriptions/'+resource['subscription_id']+'/providers/Microsoft.Insights/eventtypes/management/values'
    params={'api-version':'2015-04-01','$filter':"eventTimestamp ge '"+(now-timedelta(days=90)).isoformat()+"' and resourceUri eq '"+rid+"'"}
    states={'microsoft.compute/disks/detach/action':'Unattached','microsoft.compute/virtualmachines/deallocate/action':'PowerState/deallocated',
        'microsoft.compute/virtualmachines/stop/action':'PowerState/stopped'}
    for event in pages(reader,url,params):
        if str(event.get('resourceId','')).lower()!=rid.lower():raise ValueError('Activity event outside requested resource')
        if (event.get('status') or {}).get('value')!='Succeeded':continue
        operation=(event.get('operationName') or {}).get('value','').lower()
        if operation.endswith(('/write','/delete','/action')):events.append((moment(event.get('eventTimestamp')),states.get(operation,'Unknown')))
    return transition(events,current,expected,now) if expected else None

def fetch_azure_operational_guards(reader,resource,now):
    rid=resource['resource_id'];group='/'.join(rid.split('/')[:5]);result={}
    locks=[]
    for scope in (group,rid):
        locks.extend((r.get('properties') or {}).get('level') for r in pages(reader,ARM+scope+'/providers/Microsoft.Authorization/locks',{'api-version':'2016-09-01'}))
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

def enrich(reader,inventory,now=None):
    now=now or datetime.now(timezone.utc)
    import os
    limit=int(os.getenv('CLOUDSAVER_LIVE_EVIDENCE_MAX_RESOURCES','25'))
    if not 1<=limit<=100:raise ValueError('Live evidence bound must be 1–100 resources')
    candidates=[r for r in inventory if r['resource_type'].lower() in METRICS]
    recovery={}
    for r in candidates[limit:]:r.setdefault('evidence',{}).setdefault('live_sources',{})['telemetry']='resource_budget_exceeded'
    for r in candidates[:limit]:
        if r['resource_type'].lower() not in METRICS:continue
        e=r.setdefault('evidence',{})
        sub=r['subscription_id']
        if sub not in recovery:recovery[sub]=collect(e,'recovery_services',lambda:fetch_backup_replication(reader,sub))
        if recovery[sub] is not None:e.update(backup_enrolled=r['resource_id'].lower() in recovery[sub][0],replication_enrolled=r['resource_id'].lower() in recovery[sub][1])
        else:e.setdefault('live_sources',{})['recovery_services']='unavailable_or_incomplete'
        guards=collect(e,'operational_guards',lambda:fetch_azure_operational_guards(reader,r,now))
        if guards:e.update(guards)
        values=collect(e,'azure_monitor',lambda:fetch_azure_monitor_series(reader,r,now))
        if values:enrich_metrics(e,values,now)
        e['state_history']=collect(e,'activity_log',lambda:fetch_azure_state_history(reader,r,now))
        r['unsupported_rule_ids']=[]
    return inventory
