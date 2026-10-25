"""Keyless AWS inventory expansion and resource-bound CloudWatch/CloudTrail reads."""
from datetime import datetime,timezone
import json
from app.collectors.live_common import window,series,collect,enrich_metrics,transition
from app.telemetry_contract import moment

METRICS={
 'aws:ec2:volume':('AWS/EBS','VolumeId',{'iops_read':'VolumeReadOps','iops_write':'VolumeWriteOps','disk_queue':'VolumeQueueLength','burst_credits':'BurstBalance'}),
 'aws:ec2:instance':('AWS/EC2','InstanceId',{'cpu_percent':'CPUUtilization','burst_credits':'CPUCreditBalance','surplus_credits':'CPUSurplusCreditsCharged'}),
 'aws:ec2:natgateway':('AWS/NATGateway','NatGatewayId',{'connections':'ActiveConnectionCount','network_bytes':'BytesOutToDestination'}),
 'aws:rds:db':('AWS/RDS','DBInstanceIdentifier',{'cpu_percent':'CPUUtilization','memory_free_bytes':'FreeableMemory','connections':'DatabaseConnections','iops_read':'ReadIOPS','iops_write':'WriteIOPS','replication_lag':'ReplicaLag'}),
 'aws:lambda:function':('AWS/Lambda','FunctionName',{'invocations':'Invocations','latency':'Duration','provisioned_concurrency_utilization':'ProvisionedConcurrencyUtilization'}),
 'aws:sagemaker:endpoint':('AWS/SageMaker','EndpointName',{'invocations':'Invocations','latency':'ModelLatency'}),
 'aws:dynamodb:table':('AWS/DynamoDB','TableName',{'read_capacity':'ConsumedReadCapacityUnits','write_capacity':'ConsumedWriteCapacityUnits','throttle_events':'ReadThrottleEvents'}),
}

def fetch_cloudwatch_series(cloudwatch,namespace,metric_name,dimensions,now,window_days=30,period=300):
    if window_days!=30 or period!=300:raise ValueError('Only the 30-day five-minute contract is supported')
    start,end=window(now);token=None;seen=set();points=[]
    query=dict(Id='metric',MetricStat=dict(Metric=dict(Namespace=namespace,MetricName=metric_name,Dimensions=dimensions),Period=300,Stat='Maximum'),ReturnData=True)
    for _ in range(200):
        response=cloudwatch.get_metric_data(MetricDataQueries=[query],StartTime=start,EndTime=end,ScanBy='TimestampAscending',MaxDatapoints=100800,**({'NextToken':token} if token else {}))
        rows=response.get('MetricDataResults')
        if response.get('Messages') or not isinstance(rows,list) or len(rows)!=1:raise ValueError('Incomplete CloudWatch response')
        row=rows[0]
        if row.get('Id')!='metric' or row.get('StatusCode')!='Complete' or row.get('Messages'):raise ValueError('Incomplete CloudWatch metric')
        times,values=row.get('Timestamps',[]),row.get('Values',[])
        if len(times)!=len(values) or len(points)+len(times)>8640:raise ValueError('Invalid CloudWatch points')
        points.extend(zip(times,values));token=response.get('NextToken')
        if not token:return series(points,now,bucket_start=True)
        if not isinstance(token,str) or token in seen:raise ValueError('Invalid CloudWatch continuation')
        seen.add(token)
    raise ValueError('CloudWatch page bound exceeded')

def fetch_cloudtrail_transition_age(cloudtrail,resource_name,event_names,now,*,current=None):
    from datetime import timedelta
    token=None;seen=set();events=[]
    for _ in range(200):
        response=cloudtrail.lookup_events(LookupAttributes=[{'AttributeKey':'ResourceName','AttributeValue':resource_name}],StartTime=now-timedelta(days=90),EndTime=now,MaxResults=50,**({'NextToken':token} if token else {}))
        if not isinstance(response.get('Events'),list):raise ValueError('Invalid CloudTrail response')
        for event in response['Events']:
            body=json.loads(event.get('CloudTrailEvent','{}'))
            if body.get('errorCode'):continue
            if not any(r.get('ResourceName')==resource_name for r in event.get('Resources',[])):raise ValueError('Unrelated CloudTrail event')
            name=event.get('EventName')
            if name in event_names:events.append((moment(event.get('EventTime')),event_names[name]))
        token=response.get('NextToken')
        if not token:return transition(events,current,current,now)
        if token in seen:raise ValueError('Repeated CloudTrail continuation')
        seen.add(token)
    raise ValueError('CloudTrail page bound exceeded')

def pages(api,operation,field,*,token_key='NextToken',request_key='NextToken',**kwargs):
    token=None;seen=set();count=0
    for _ in range(200):
        response=getattr(api,operation)(**dict(kwargs,**({request_key:token} if token else {})))
        values=response.get(field)
        if not isinstance(values,list):raise ValueError('Malformed AWS inventory')
        count+=len(values)
        if count>20000:raise ValueError('AWS inventory bound exceeded')
        yield from values
        token=response.get(token_key)
        if not token:return
        if token in seen:raise ValueError('Repeated AWS inventory continuation')
        seen.add(token)
    raise ValueError('AWS inventory page bound exceeded')

def extra_inventory(client,account,region):
    """Every enabled inventory API is mandatory. Metric/guard gaps are separate."""
    rows=[];now=datetime.now(timezone.utc)
    def add(kind,rid,name,e,edges=()):
        if kind!='aws:s3:bucket' and (not rid.startswith('arn:aws:') or rid.split(':')[4]!=account or rid.split(':')[3]!=region):raise ValueError('AWS resource outside configured account/region')
        rows.append(dict(cloud_provider='aws',scope_id=account,subscription_id=account,region=region,resource_id=rid,resource_name=name,
            resource_group=region,resource_type=kind,inventory_rule_id='MULTICLOUD_INVENTORY',evidence=dict(source='AWS live reader APIs',**e),dependency_refs=list(edges),collector_version='aws-live-1.4.0',observed_at=now.isoformat()))
    ec2=client('ec2')
    for reservation in pages(ec2,'describe_instances','Reservations',MaxResults=500):
        for r in reservation.get('Instances',[]):
            iid=r['InstanceId'];rid=f'arn:aws:ec2:{region}:{account}:instance/{iid}'
            edges=[dict(relationship='vm_to_disk',from_resource_id=rid,to_resource_id=f"arn:aws:ec2:{region}:{account}:volume/{d['Ebs']['VolumeId']}",verification_state='verified',observed_at=now.isoformat()) for d in r.get('BlockDeviceMappings',[]) if d.get('Ebs',{}).get('VolumeId')]
            add('aws:ec2:instance',rid,iid,dict(instance_type=r.get('InstanceType'),power_state=r.get('State',{}).get('Name'),created_at=str(r.get('LaunchTime')),
                imds_v2_required=r.get('MetadataOptions',{}).get('HttpTokens')=='required',tags={t['Key']:t['Value'] for t in r.get('Tags',[])}),edges)
    for r in pages(ec2,'describe_nat_gateways','NatGateways',MaxResults=100):add('aws:ec2:natgateway',f"arn:aws:ec2:{region}:{account}:natgateway/{r['NatGatewayId']}",r['NatGatewayId'],dict(state=r.get('State')))
    elb=client('elbv2')
    for r in pages(elb,'describe_load_balancers','LoadBalancers',token_key='NextMarker',request_key='Marker',PageSize=100):
        groups=list(pages(elb,'describe_target_groups','TargetGroups',token_key='NextMarker',request_key='Marker',LoadBalancerArn=r['LoadBalancerArn']))
        targets=[v for group in groups for v in elb.describe_target_health(TargetGroupArn=group['TargetGroupArn']).get('TargetHealthDescriptions',[])]
        add('aws:elbv2:loadbalancer',r['LoadBalancerArn'],r['LoadBalancerName'],dict(backend_count=len(targets),dependencies_verified=True,publicly_accessible=r.get('Scheme')=='internet-facing'))
    rds=client('rds')
    for r in pages(rds,'describe_db_clusters','DBClusters',token_key='Marker',request_key='Marker',MaxRecords=100):add('aws:rds:cluster',r['DBClusterArn'],r['DBClusterIdentifier'],dict(encrypted=r.get('StorageEncrypted'),backup_retention_days=r.get('BackupRetentionPeriod'),deletion_protection=r.get('DeletionProtection')))
    ddb=client('dynamodb')
    for name in pages(ddb,'list_tables','TableNames',token_key='LastEvaluatedTableName',request_key='ExclusiveStartTableName',Limit=100):
        r=ddb.describe_table(TableName=name)['Table'];add('aws:dynamodb:table',r['TableArn'],name,dict(billing_mode=r.get('BillingModeSummary',{}).get('BillingMode'),encrypted=r.get('SSEDescription',{}).get('Status')=='ENABLED' if r.get('SSEDescription') else None))
    cache=client('elasticache')
    for r in pages(cache,'describe_replication_groups','ReplicationGroups',token_key='Marker',request_key='Marker',MaxRecords=100):add('aws:elasticache:replication-group',r['ARN'],r['ReplicationGroupId'],dict(encrypted=r.get('AtRestEncryptionEnabled'),tls_required=r.get('TransitEncryptionEnabled')))
    function=client('lambda')
    for r in pages(function,'list_functions','Functions',token_key='NextMarker',request_key='Marker',MaxItems=50):add('aws:lambda:function',r['FunctionArn'],r['FunctionName'],dict(architectures=r.get('Architectures'),memory_mb=r.get('MemorySize')))
    ecs=client('ecs')
    for cluster in pages(ecs,'list_clusters','clusterArns',token_key='nextToken',request_key='nextToken',maxResults=100):
        arns=list(pages(ecs,'list_services','serviceArns',token_key='nextToken',request_key='nextToken',cluster=cluster,maxResults=100))
        for i in range(0,len(arns),10):
            data=ecs.describe_services(cluster=cluster,services=arns[i:i+10])
            if data.get('failures'):raise ValueError('Incomplete ECS inventory')
            for r in data.get('services',[]):add('aws:ecs:service',r['serviceArn'],r['serviceName'],dict(desired_count=r.get('desiredCount'),running_count=r.get('runningCount')))
    s3=client('s3')
    for r in pages(s3,'list_buckets','Buckets',token_key='ContinuationToken',request_key='ContinuationToken',MaxBuckets=1000):
        name=r['Name'];location=s3.get_bucket_location(Bucket=name,ExpectedBucketOwner=account).get('LocationConstraint') or 'us-east-1'
        if location=='EU':location='eu-west-1'
        if location!=region:continue
        e={}
        rules=collect(e,'s3_lifecycle',lambda:s3.get_bucket_lifecycle_configuration(Bucket=name,ExpectedBucketOwner=account).get('Rules'))
        if isinstance(rules,list):e.update(lifecycle_policy_verified=True,multipart_abort_rule_present=any(v.get('Status')=='Enabled' and v.get('AbortIncompleteMultipartUpload',{}).get('DaysAfterInitiation',999)<=7 for v in rules))
        add('aws:s3:bucket','arn:aws:s3:::'+name,name,e)
    sm=client('sagemaker')
    for r in pages(sm,'list_endpoints','Endpoints',MaxResults=100):
        full=sm.describe_endpoint(EndpointName=r['EndpointName']);add('aws:sagemaker:endpoint',full['EndpointArn'],full['EndpointName'],dict(state=full.get('EndpointStatus')))
    bedrock=client('bedrock')
    for r in pages(bedrock,'list_provisioned_model_throughputs','provisionedModelSummaries',token_key='nextToken',request_key='nextToken',maxResults=100):add('aws:bedrock:provisioned-throughput',r['provisionedModelArn'],r['provisionedModelName'],dict(state=r.get('status'),commitment_lock_conflict=r.get('commitmentDuration') is not None))
    return rows

def enrich(client,inventory,now=None):
    import os
    now=now or datetime.now(timezone.utc);limit=int(os.getenv('CLOUDSAVER_LIVE_EVIDENCE_MAX_RESOURCES','25'))
    if not 1<=limit<=100:raise ValueError('Live evidence bound must be 1–100 resources')
    cw,trail=client('cloudwatch'),client('cloudtrail')
    for r in inventory[:limit]:
        e=r.setdefault('evidence',{});kind=r['resource_type'];spec=METRICS.get(kind);values={}
        if spec:
            namespace,dimension,names=spec
            for key,name in names.items():
                value=collect(e,'cloudwatch:'+name,lambda:fetch_cloudwatch_series(cw,namespace,name,[{'Name':dimension,'Value':r['resource_name']}],now))
                if value is not None:values[key]=value
            enrich_metrics(e,values,now)
        states={'DetachVolume':'Unattached','AttachVolume':'Attached'} if kind=='aws:ec2:volume' else {'StopInstances':'Stopped','StartInstances':'Running','StopDBInstance':'Stopped','StartDBInstance':'Running'}
        current='Unattached' if e.get('disk_state')=='available' else 'Stopped' if e.get('power_state')=='stopped' else None
        e['state_history']=collect(e,'cloudtrail',lambda:fetch_cloudtrail_transition_age(trail,r['resource_name'],states,now,current=current))
        if kind in ('aws:ec2:volume','aws:rds:db'):
            def snapshots():
                if kind=='aws:ec2:volume':return list(pages(client('ec2'),'describe_snapshots','Snapshots',OwnerIds=[r['scope_id']],Filters=[{'Name':'volume-id','Values':[r['resource_name']]}],MaxResults=100))
                return list(pages(client('rds'),'describe_db_snapshots','DBSnapshots',token_key='Marker',request_key='Marker',DBInstanceIdentifier=r['resource_name'],MaxRecords=100))
            snaps=collect(e,'snapshots',snapshots)
            if snaps is not None:
                ages=[]
                for s in snaps:
                    stamp=moment(s.get('StartTime') or s.get('SnapshotCreateTime'))
                    if s.get('State',s.get('Status')) in ('completed','available') and stamp and stamp<=now:ages.append((now-stamp).total_seconds()/3600)
                e.update(recent_snapshot_verified=bool(ages and min(ages)<24),snapshot_age_hours=min(ages) if ages else None)
    for r in inventory[limit:]:r.setdefault('evidence',{}).setdefault('live_sources',{})['telemetry']='resource_budget_exceeded'
    return inventory
