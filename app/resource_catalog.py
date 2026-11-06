"""v1.4 resource families; mirrored in the independently packaged control plane."""
VERSION = '1.4.1'
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
 ('aws','ec2','compute',('aws:ec2:instance',),('AWS_EC2_STOPPED_EBS_RESIDUAL','AWS_EC2_GRAVITON_AND_SLO_RIGHTSIZING','AWS_EC2_IMDSV2_NOT_REQUIRED')),
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
 ('kubernetes','deployments','compute',('kubernetes.io/Container','kubernetes.io/Deployment','kubernetes.io/ReplicaSet'),('K8S_CONTAINER_CPU_OVERREQUEST','K8S_CONTAINER_MEMORY_OVERREQUEST','K8S_CONTAINER_UNDERPROVISIONED_RISK')),
 ('kubernetes','statefulsets','compute',('kubernetes.io/StatefulSet',),('K8S_STATEFULSET_SIZING_AND_VOLUME_TEMPLATE',)),
 ('kubernetes','daemonsets','compute',('kubernetes.io/DaemonSet',),('K8S_DAEMONSET_CLUSTER_WIDE_OVERHEAD_TAX',)),
 ('kubernetes','jobs','application',('kubernetes.io/CronJob','kubernetes.io/Job'),('K8S_ABANDONED_WORKLOAD_OR_NAMESPACE',)),
 ('kubernetes','autoscaling','compute',('kubernetes.io/HorizontalPodAutoscaler','kubernetes.io/PodDisruptionBudget'),('K8S_HPA_PDB_CONFLICT_OR_IDLE_FLOOR',)),
 ('kubernetes','nodes','compute',('kubernetes.io/Node',),('K8S_NODE_POOL_FRAGMENTATION_WASTE',)),
 ('kubernetes','persistent-volumes','storage',('kubernetes.io/PersistentVolumeClaim',),('K8S_PVC_UNMOUNTED_OR_LOW_OCCUPANCY',)),
 ('kubernetes','services','network',('kubernetes.io/Service',),('K8S_ORPHANED_LOADBALANCER_SERVICE',)),
    (
        'platform',
        'policy',
        'operations',
        ('*',),
        ('PLATFORM_DEFAULT_TAGS', 'PLATFORM_PROD_ENCRYPTION_EXPECTATION', 'WIZ_SECURITY_POSTURE'),
    ),
)

# (rule_id, display title, legacy pillar key for catalog API: cost|performance|reliability|security|operations)
_PLATFORM_POLICY_RULES = (
    ('PLATFORM_DEFAULT_TAGS', 'Default FinOps tag set review (platform)', 'operations'),
    ('PLATFORM_PROD_ENCRYPTION_EXPECTATION', 'Production encryption expectation review (platform)', 'security'),
    ('WIZ_SECURITY_POSTURE', 'Wiz open security issues (CSPM)', 'security'),
)

# Human-readable rule titles (stable `rule_id` keys for policy, APIs, and storage).
RULE_DISPLAY_NAMES = {
    'AZURE_DISK_UNATTACHED_RETENTION': 'Retained unattached managed disk review',
    'AZURE_DISK_PROVISIONED_PERFORMANCE': 'Disk recovery and provisioned performance review',
    'AZURE_PUBLIC_IP_UNASSOCIATED': 'Unassociated public IP review',
    'AZURE_PUBLIC_IP_ASSOCIATED_IDLE': 'Associated public IP traffic review',
    'AZURE_VM_STOPPED_RESIDUAL_COST': 'Stopped VM residual charge review',
    'AZURE_VM_RIGHTSIZING_UTILIZATION': 'Evidence-based VM rightsizing review',
    'AZURE_ASP_EMPTY_PAID_PLAN': 'Empty paid App Service plan review',
    'AZURE_ASP_UNDERUTILIZED_SKU': 'App Service capacity review',
    'AZURE_NAT_GATEWAY_SERVICE_ENDPOINT_BYPASS': 'NAT gateway vs service endpoint routing review',
    'AZURE_APPGW_EMPTY_OR_HIGH_AUTOSCALE_FLOOR': 'Empty Application Gateway or high autoscale floor review',
    'AZURE_SQL_PG_IDLE_AND_NONPROD_HA_REVIEW': 'Azure SQL / PostgreSQL idle and non-production HA review',
    'AZURE_COSMOSDB_MANUAL_RU_TO_AUTOSCALE': 'Cosmos DB manual throughput vs autoscale review',
    'AZURE_REDIS_UNDERUTILIZED_TIER_REVIEW': 'Azure Cache for Redis tier utilization review',
    'AZURE_STORAGE_LIFECYCLE_AND_ORPHANED_VHD': 'Storage lifecycle and orphaned VHD page blob review',
    'AZURE_AI_FOUNDRY_PTU_VS_PAYG_ARBITRAGE': 'Azure AI Foundry PTU vs pay-as-you-go review',
    'AWS_UNATTACHED_EBS': 'Unattached EBS volume retention review',
    'AWS_EBS_GP2_TO_GP3_AND_IOPS_TUNING': 'EBS GP2 to GP3 and provisioned IOPS tuning review',
    'AWS_EC2_STOPPED_EBS_RESIDUAL': 'Stopped EC2 instance residual EBS charge review',
    'AWS_EC2_GRAVITON_AND_SLO_RIGHTSIZING': 'EC2 Graviton migration and SLO-bounded rightsizing review',
    'AWS_EC2_IMDSV2_NOT_REQUIRED': 'EC2 instance metadata IMDSv2 not required review',
    'AWS_UNASSOCIATED_EIP': 'Unassociated Elastic IP address review',
    'AWS_NAT_GW_ENDPOINT_BYPASS_AND_IDLE': 'NAT gateway idle and VPC endpoint bypass review',
    'AWS_ELB_ORPHANED_AND_INGRESS_CONSOLIDATION': 'Orphaned load balancer and ingress consolidation review',
    'AWS_IDLE_RDS': 'Idle or stopped RDS instance review',
    'AWS_RDS_AURORA_RIGHTSIZING_AND_GP3': 'RDS / Aurora rightsizing and GP3 storage review',
    'AWS_DYNAMODB_BILLING_MODE_AND_UNUSED_GSI': 'DynamoDB billing mode and unused GSI review',
    'AWS_ELASTICACHE_GRAVITON_AND_VALKEY_UPGRADE': 'ElastiCache Graviton and Valkey upgrade review',
    'AWS_LAMBDA_ARM64_AND_PROVISIONED_CONCURRENCY': 'Lambda ARM64 and provisioned concurrency review',
    'AWS_S3_INTELLIGENT_TIERING_AND_MULTIPART_CLEANUP': 'S3 Intelligent-Tiering and multipart cleanup review',
    'AWS_BEDROCK_PT_AND_SAGEMAKER_IDLE_ENDPOINT': 'Bedrock provisioned throughput and idle SageMaker endpoint review',
    'GCP_UNATTACHED_DISK': 'Unattached persistent disk retention review',
    'GCP_DISK_HYPERDISK_IOPS_TUNING': 'Persistent disk Hyperdisk IOPS tuning review',
    'GCP_GCE_STOPPED_DISK_TAX': 'Stopped GCE instance persistent disk charge review',
    'GCP_GCE_AXION_AND_CUSTOM_RIGHTSIZING': 'GCE Axion / custom machine rightsizing review',
    'GCP_UNASSIGNED_ADDRESS': 'Unassigned regional external IP review',
    'GCP_CLOUD_NAT_PRIVATE_GOOGLE_ACCESS': 'Cloud NAT vs Private Google Access routing review',
    'GCP_LB_EMPTY_BACKEND_FORWARDING_RULE': 'Empty backend forwarding rule review',
    'GCP_IDLE_CLOUD_SQL': 'Idle Cloud SQL instance review',
    'GCP_CLOUDSQL_ALLOYDB_RIGHTSIZING_AND_HA': 'Cloud SQL / AlloyDB rightsizing and HA review',
    'GCP_BIGQUERY_SLOT_AUTOSCALE_AND_STORAGE': 'BigQuery slot autoscale and storage review',
    'GCP_CLOUDRUN_MIN_INSTANCE_AND_MEMORYSTORE': 'Cloud Run min instances and Memorystore review',
    'GCP_VERTEX_AI_IDLE_ENDPOINT_AND_REPLICA_FLOOR': 'Vertex AI idle endpoint and replica floor review',
    'K8S_CONTAINER_CPU_OVERREQUEST': 'Container CPU request rightsizing review',
    'K8S_CONTAINER_MEMORY_OVERREQUEST': 'Container memory working-set rightsizing review',
    'K8S_CONTAINER_UNDERPROVISIONED_RISK': 'Container throttling, OOM, and QoS reliability review',
    'K8S_HPA_PDB_CONFLICT_OR_IDLE_FLOOR': 'Horizontal Pod Autoscaler floor and PDB conflict review',
    'K8S_NODE_POOL_FRAGMENTATION_WASTE': 'Node pool capacity reservation slack review',
    'K8S_ABANDONED_WORKLOAD_OR_NAMESPACE': 'Zero-traffic workload or namespace review',
    'K8S_PVC_UNMOUNTED_OR_LOW_OCCUPANCY': 'Unmounted or low-occupancy PVC review',
    'K8S_STATEFULSET_SIZING_AND_VOLUME_TEMPLATE': 'StatefulSet memory buffer and volume template review',
    'K8S_DAEMONSET_CLUSTER_WIDE_OVERHEAD_TAX': 'DaemonSet cluster-wide allocation overhead review',
    'K8S_ORPHANED_LOADBALANCER_SERVICE': 'LoadBalancer service with empty endpoints review',
    'WIZ_SECURITY_POSTURE': 'Wiz open security issues (CSPM)',
    'ORPHANED_DISK': 'Unattached managed disk',
    'ORPHANED_DISKS': 'Unattached managed disk',
    'UNASSOCIATED_PUBLIC_IP': 'Unassociated public IP',
    'UNASSOCIATED_PUBLIC_IPS': 'Unassociated public IP',
    'ORPHANED_NIC': 'Orphaned network interface',
    'ORPHANED_NSG': 'Unassociated network security group',
    'IDLE_APP_GATEWAY': 'Idle Application Gateway',
    'UNDERUTILIZED_VM': 'Underutilized virtual machine review',
    'STOPPED_VM': 'Stopped virtual machine',
    'STOPPED_VMS': 'Stopped virtual machine',
    'EMPTY_APP_SERVICE_PLAN': 'Empty App Service plan',
    'EMPTY_APP_SERVICE': 'Empty App Service plan',
    'UNDERUTILIZED_APP_SERVICE_PLAN': 'Underutilized App Service plan review',
}
for _rid, _title, _pillar in _PLATFORM_POLICY_RULES:
    RULE_DISPLAY_NAMES[_rid] = _title


def display_name(rule_id: str) -> str:
    from app.rule_id_canonical import canonical_rule_id

    rid = canonical_rule_id(rule_id)
    return RULE_DISPLAY_NAMES.get(rid, rule_id)


def family(resource):
    provider=resource.get('cloud_provider','azure');kind=resource.get('resource_type','').lower()
    return next((f for f in FAMILIES if f[0]==provider and kind in {k.lower() for k in f[3]}),None)

def catalog():
    return [dict(provider=p,family=f,service_category=c,resource_types=list(k),rule_ids=list(r)) for p,f,c,k,r in FAMILIES]

def definitions():
    # Legacy contracts keep their own established bounds. New contracts use these
    # conservative delegated thresholds; target compatibility is separate evidence.
    seen=set();rows=[]
    _platform_pillar_by_rule = {r: p for r, _t, p in _PLATFORM_POLICY_RULES}
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
            if provider == 'platform':
                pillar = _platform_pillar_by_rule[rid]
            elif rid == 'AWS_EC2_IMDSV2_NOT_REQUIRED':
                pillar = 'security'
            else:
                pillar='reliability' if 'STATEFULSET' in rid else 'operations' if 'ABANDONED' in rid else 'cost'
            if rid not in RULE_DISPLAY_NAMES:
                raise KeyError(f'Missing RULE_DISPLAY_NAMES entry for {rid}')
            rows.append((rid,provider,category,kinds[0],RULE_DISPLAY_NAMES[rid],pillar,bounds))
    from app.analysis_service.declarative_rules import extend_resource_catalog_definitions

    rows.extend(extend_resource_catalog_definitions())
    return tuple(rows)


def rules_catalog_items():
    """Published analysis rules with stable ids and operator-facing titles."""
    return [
        dict(id=row[0], name=row[4], provider=row[1], service_category=row[2], pillar=row[5])
        for row in definitions()
    ]
