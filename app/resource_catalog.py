"""v1.4 resource families; mirrored in the independently packaged control plane."""
VERSION = '1.4.0'
# provider, family, category, canonical resource types, rule IDs
FAMILIES = (
 ('azure','managed-disks','storage',('microsoft.compute/disks',),('AZURE_DISK_UNATTACHED_RETENTION','AZURE_DISK_PROVISIONED_PERFORMANCE')),
 ('azure','virtual-machines','compute',('microsoft.compute/virtualmachines',),('AZURE_VM_STOPPED_RESIDUAL_COST','AZURE_VM_RIGHTSIZING_UTILIZATION')),
 ('azure','ip-nat','network',('microsoft.network/publicipaddresses','microsoft.network/natgateways'),('AZURE_PUBLIC_IP_UNASSOCIATED','AZURE_PUBLIC_IP_ASSOCIATED_IDLE','AZURE_NAT_GATEWAY_SERVICE_ENDPOINT_BYPASS')),
 ('azure','gateways','network',('microsoft.network/applicationgateways','microsoft.network/loadbalancers'),('AZURE_APPGW_EMPTY_OR_HIGH_AUTOSCALE_FLOOR',)),
 ('azure','app-service','application',('microsoft.web/serverfarms',),('AZURE_ASP_EMPTY_PAID_PLAN','AZURE_ASP_UNDERUTILIZED_SKU')),
 ('azure','sql-postgres','database',('microsoft.dbforpostgresql/flexibleservers','microsoft.sql/servers/databases'),('AZURE_SQL_PG_IDLE_AND_NONPROD_HA_REVIEW',)),
 ('azure','cosmosdb','database',('microsoft.documentdb/databaseaccounts',),('AZURE_COSMOSDB_MANUAL_RU_TO_AUTOSCALE',)),
 ('azure','redis','database',('microsoft.cache/redis',),('AZURE_REDIS_UNDERUTILIZED_TIER_REVIEW',)),
 ('azure','blob-storage','storage',('microsoft.storage/storageaccounts',),('AZURE_STORAGE_LIFECYCLE_AND_ORPHANED_VHD',)),
 ('azure','ai-foundry','ai',('microsoft.cognitiveservices/accounts',),('AZURE_AI_FOUNDRY_PTU_VS_PAYG_ARBITRAGE',)),
 ('aws','ebs','storage',('aws:ec2:volume',),('AWS_UNATTACHED_EBS','AWS_EBS_GP2_TO_GP3_AND_IOPS_TUNING')),
 ('aws','ec2','compute',('aws:ec2:instance',),('AWS_EC2_STOPPED_EBS_RESIDUAL','AWS_EC2_GRAVITON_AND_SLO_RIGHTSIZING')),
 ('aws','eip-nat','network',('aws:ec2:elastic-ip','aws:ec2:natgateway'),('AWS_UNASSOCIATED_EIP','AWS_NAT_GW_ENDPOINT_BYPASS_AND_IDLE')),
 ('aws','load-balancers','network',('aws:elbv2:loadbalancer',),('AWS_ELB_ORPHANED_AND_INGRESS_CONSOLIDATION',)),
 ('aws','rds-aurora','database',('aws:rds:db','aws:rds:cluster'),('AWS_IDLE_RDS','AWS_RDS_AURORA_RIGHTSIZING_AND_GP3')),
 ('aws','dynamodb','database',('aws:dynamodb:table',),('AWS_DYNAMODB_BILLING_MODE_AND_UNUSED_GSI',)),
 ('aws','elasticache','database',('aws:elasticache:replication-group',),('AWS_ELASTICACHE_GRAVITON_AND_VALKEY_UPGRADE',)),
 ('aws','lambda-ecs','application',('aws:lambda:function','aws:ecs:service'),('AWS_LAMBDA_ARM64_AND_PROVISIONED_CONCURRENCY',)),
 ('aws','s3','storage',('aws:s3:bucket',),('AWS_S3_INTELLIGENT_TIERING_AND_MULTIPART_CLEANUP',)),
 ('aws','ai-inference','ai',('aws:sagemaker:endpoint','aws:bedrock:provisioned-throughput'),('AWS_BEDROCK_PT_AND_SAGEMAKER_IDLE_ENDPOINT',)),
 ('gcp','persistent-disks','storage',('compute.googleapis.com/Disk',),('GCP_UNATTACHED_DISK','GCP_DISK_HYPERDISK_IOPS_TUNING')),
 ('gcp','gce','compute',('compute.googleapis.com/Instance',),('GCP_GCE_STOPPED_DISK_TAX','GCP_GCE_AXION_AND_CUSTOM_RIGHTSIZING')),
 ('gcp','ip-nat','network',('compute.googleapis.com/Address','compute.googleapis.com/RouterNat'),('GCP_UNASSIGNED_ADDRESS','GCP_CLOUD_NAT_PRIVATE_GOOGLE_ACCESS')),
 ('gcp','load-balancers','network',('compute.googleapis.com/ForwardingRule',),('GCP_LB_EMPTY_BACKEND_FORWARDING_RULE',)),
 ('gcp','sql-alloydb','database',('sqladmin.googleapis.com/Instance','alloydb.googleapis.com/Cluster'),('GCP_IDLE_CLOUD_SQL','GCP_CLOUDSQL_ALLOYDB_RIGHTSIZING_AND_HA')),
 ('gcp','bigquery','database',('bigquery.googleapis.com/Reservation',),('GCP_BIGQUERY_SLOT_AUTOSCALE_AND_STORAGE',)),
 ('gcp','cloudrun-memorystore','application',('run.googleapis.com/Service','redis.googleapis.com/Instance'),('GCP_CLOUDRUN_MIN_INSTANCE_AND_MEMORYSTORE',)),
 ('gcp','vertex-ai','ai',('aiplatform.googleapis.com/Endpoint',),('GCP_VERTEX_AI_IDLE_ENDPOINT_AND_REPLICA_FLOOR',)),
 ('kubernetes','deployments','compute',('kubernetes.io/Container','kubernetes.io/Deployment','kubernetes.io/ReplicaSet'),('K8S_CONTAINER_CPU_OVERREQUEST','K8S_CONTAINER_MEMORY_OVERREQUEST')),
 ('kubernetes','statefulsets','compute',('kubernetes.io/StatefulSet',),('K8S_STATEFULSET_SIZING_AND_VOLUME_TEMPLATE',)),
 ('kubernetes','daemonsets','compute',('kubernetes.io/DaemonSet',),('K8S_DAEMONSET_CLUSTER_WIDE_OVERHEAD_TAX',)),
 ('kubernetes','jobs','application',('kubernetes.io/CronJob','kubernetes.io/Job'),('K8S_ABANDONED_WORKLOAD_OR_NAMESPACE',)),
 ('kubernetes','autoscaling','compute',('kubernetes.io/HorizontalPodAutoscaler','kubernetes.io/PodDisruptionBudget'),('K8S_HPA_PDB_CONFLICT_OR_IDLE_FLOOR',)),
 ('kubernetes','nodes','compute',('kubernetes.io/Node',),('K8S_NODE_POOL_FRAGMENTATION_WASTE',)),
 ('kubernetes','persistent-volumes','storage',('kubernetes.io/PersistentVolumeClaim',),('K8S_PVC_UNMOUNTED_OR_LOW_OCCUPANCY',)),
 ('kubernetes','services','network',('kubernetes.io/Service',),('K8S_ORPHANED_LOADBALANCER_SERVICE',)),
)

def family(resource):
    provider=resource.get('cloud_provider','azure');kind=resource.get('resource_type','').lower()
    return next((f for f in FAMILIES if f[0]==provider and kind in {k.lower() for k in f[3]}),None)

def catalog():
    return [dict(provider=p,family=f,service_category=c,resource_types=list(k),rule_ids=list(r)) for p,f,c,k,r in FAMILIES]

def definitions():
    # Legacy contracts keep their own established bounds. New contracts use these
    # conservative delegated thresholds; target compatibility is separate evidence.
    seen=set();rows=[]
    for provider,_,category,kinds,rules in FAMILIES:
        for rid in rules:
            if rid in seen:continue
            seen.add(rid)
            bounds={}
            if any(s in rid for s in ('UNATTACHED','STOPPED')):bounds={'minimum_days':(14,7,90)}
            if any(s in rid for s in ('UNASSIGNED','UNASSOCIATED','ELB_ORPHANED','APPGW_EMPTY','EMPTY_BACKEND')) or rid=='AWS_IDLE_RDS':bounds={'minimum_days':(7,7,90)}
            if 'RIGHTSIZING' in rid:bounds={'utilization_percent':(15 if category=='compute' else 20,1,35)}
            if rid in ('AWS_EBS_GP2_TO_GP3_AND_IOPS_TUNING','GCP_DISK_HYPERDISK_IOPS_TUNING'):bounds={'headroom_percent':(30,20,100)}
            for fragment,default in (('COSMOSDB',30),('REDIS_UNDERUTILIZED',25),('DYNAMODB',18),('ELASTICACHE',25),('LAMBDA',15),('BIGQUERY',25),('FOUNDRY_PTU',35)):
                if fragment in rid:bounds={'utilization_percent':(default,1,40)}
            if provider=='kubernetes':bounds={}
            pillar='reliability' if 'STATEFULSET' in rid else 'operations' if 'ABANDONED' in rid else 'cost'
            rows.append((rid,provider,category,kinds[0],rid.replace('_',' ').title(),pillar,bounds))
    return tuple(rows)
