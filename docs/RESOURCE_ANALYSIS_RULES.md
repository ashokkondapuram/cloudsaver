# Analysis rules by resource type

This document is generated from the v1.4 resource catalog (`app/resource_catalog.py`). 
For each canonical **resource type**, it lists every **rule_id** the scan engine evaluates on a completed observation, plus the operator-facing **display name**.

Regenerate after catalog changes:

```bash
PYTHONPATH=. python3 scripts/generate_resource_rules_doc.py
```

Stable policy keys remain the `rule_id` values; UI and evaluations use the **display name** from `RULE_DISPLAY_NAMES`.

**Evaluation wiring:**
- **Azure** legacy rules match the ARM type suffix (e.g. `.../disks` → disk rules).
- **Kubernetes** rules match workload **kind** (e.g. `Container`, `Deployment`).
- **AWS / GCP / Azure (catalog)** rules come from the resource **family** row below (excluding legacy Azure duplicates already covered by suffix rules).

Related: [FINOPS_ANALYSIS_VERIFICATION.md](FINOPS_ANALYSIS_VERIFICATION.md), `GET /api/v1/rules/catalog`.

---

## azure · Managed Disks (`storage`)

| Resource type | Rules evaluated |
| --- | --- |
| `microsoft.compute/disks` | **Disk recovery and provisioned performance review** (`AZURE_DISK_PROVISIONED_PERFORMANCE`)<br>**Retained unattached managed disk review** (`AZURE_DISK_UNATTACHED_RETENTION`) |

**Family rule set** (2 ids): `AZURE_DISK_UNATTACHED_RETENTION`, `AZURE_DISK_PROVISIONED_PERFORMANCE`

## azure · Virtual Machines (`compute`)

| Resource type | Rules evaluated |
| --- | --- |
| `microsoft.compute/virtualmachines` | **Evidence-based VM rightsizing review** (`AZURE_VM_RIGHTSIZING_UTILIZATION`)<br>**Stopped VM residual charge review** (`AZURE_VM_STOPPED_RESIDUAL_COST`) |

**Family rule set** (2 ids): `AZURE_VM_STOPPED_RESIDUAL_COST`, `AZURE_VM_RIGHTSIZING_UTILIZATION`

## azure · Ip Nat (`network`)

| Resource type | Rules evaluated |
| --- | --- |
| `microsoft.network/publicipaddresses` | **NAT gateway vs service endpoint routing review** (`AZURE_NAT_GATEWAY_SERVICE_ENDPOINT_BYPASS`)<br>**Associated public IP traffic review** (`AZURE_PUBLIC_IP_ASSOCIATED_IDLE`)<br>**Unassociated public IP review** (`AZURE_PUBLIC_IP_UNASSOCIATED`) |
| `microsoft.network/natgateways` | **NAT gateway vs service endpoint routing review** (`AZURE_NAT_GATEWAY_SERVICE_ENDPOINT_BYPASS`) |

**Family rule set** (3 ids): `AZURE_PUBLIC_IP_UNASSOCIATED`, `AZURE_PUBLIC_IP_ASSOCIATED_IDLE`, `AZURE_NAT_GATEWAY_SERVICE_ENDPOINT_BYPASS`

## azure · Gateways (`network`)

| Resource type | Rules evaluated |
| --- | --- |
| `microsoft.network/applicationgateways` | **Empty Application Gateway or high autoscale floor review** (`AZURE_APPGW_EMPTY_OR_HIGH_AUTOSCALE_FLOOR`) |
| `microsoft.network/loadbalancers` | **Empty Application Gateway or high autoscale floor review** (`AZURE_APPGW_EMPTY_OR_HIGH_AUTOSCALE_FLOOR`) |

**Family rule set** (1 ids): `AZURE_APPGW_EMPTY_OR_HIGH_AUTOSCALE_FLOOR`

## azure · App Service (`application`)

| Resource type | Rules evaluated |
| --- | --- |
| `microsoft.web/serverfarms` | **Empty paid App Service plan review** (`AZURE_ASP_EMPTY_PAID_PLAN`)<br>**App Service capacity review** (`AZURE_ASP_UNDERUTILIZED_SKU`) |

**Family rule set** (2 ids): `AZURE_ASP_EMPTY_PAID_PLAN`, `AZURE_ASP_UNDERUTILIZED_SKU`

## azure · Sql Postgres (`database`)

| Resource type | Rules evaluated |
| --- | --- |
| `microsoft.dbforpostgresql/flexibleservers` | **Azure SQL / PostgreSQL idle and non-production HA review** (`AZURE_SQL_PG_IDLE_AND_NONPROD_HA_REVIEW`) |
| `microsoft.sql/servers/databases` | **Azure SQL / PostgreSQL idle and non-production HA review** (`AZURE_SQL_PG_IDLE_AND_NONPROD_HA_REVIEW`) |

**Family rule set** (1 ids): `AZURE_SQL_PG_IDLE_AND_NONPROD_HA_REVIEW`

## azure · Cosmosdb (`database`)

| Resource type | Rules evaluated |
| --- | --- |
| `microsoft.documentdb/databaseaccounts` | **Cosmos DB manual throughput vs autoscale review** (`AZURE_COSMOSDB_MANUAL_RU_TO_AUTOSCALE`) |

**Family rule set** (1 ids): `AZURE_COSMOSDB_MANUAL_RU_TO_AUTOSCALE`

## azure · Redis (`database`)

| Resource type | Rules evaluated |
| --- | --- |
| `microsoft.cache/redis` | **Azure Cache for Redis tier utilization review** (`AZURE_REDIS_UNDERUTILIZED_TIER_REVIEW`) |

**Family rule set** (1 ids): `AZURE_REDIS_UNDERUTILIZED_TIER_REVIEW`

## azure · Blob Storage (`storage`)

| Resource type | Rules evaluated |
| --- | --- |
| `microsoft.storage/storageaccounts` | **Storage lifecycle and orphaned VHD page blob review** (`AZURE_STORAGE_LIFECYCLE_AND_ORPHANED_VHD`) |

**Family rule set** (1 ids): `AZURE_STORAGE_LIFECYCLE_AND_ORPHANED_VHD`

## azure · Ai Foundry (`ai`)

| Resource type | Rules evaluated |
| --- | --- |
| `microsoft.cognitiveservices/accounts` | **Azure AI Foundry PTU vs pay-as-you-go review** (`AZURE_AI_FOUNDRY_PTU_VS_PAYG_ARBITRAGE`) |

**Family rule set** (1 ids): `AZURE_AI_FOUNDRY_PTU_VS_PAYG_ARBITRAGE`

## aws · Ebs (`storage`)

| Resource type | Rules evaluated |
| --- | --- |
| `aws:ec2:volume` | **EBS GP2 to GP3 and provisioned IOPS tuning review** (`AWS_EBS_GP2_TO_GP3_AND_IOPS_TUNING`)<br>**Unattached EBS volume retention review** (`AWS_UNATTACHED_EBS`) |

**Family rule set** (2 ids): `AWS_UNATTACHED_EBS`, `AWS_EBS_GP2_TO_GP3_AND_IOPS_TUNING`

## aws · Ec2 (`compute`)

| Resource type | Rules evaluated |
| --- | --- |
| `aws:ec2:instance` | **EC2 Graviton migration and SLO-bounded rightsizing review** (`AWS_EC2_GRAVITON_AND_SLO_RIGHTSIZING`)<br>**Stopped EC2 instance residual EBS charge review** (`AWS_EC2_STOPPED_EBS_RESIDUAL`) |

**Family rule set** (2 ids): `AWS_EC2_STOPPED_EBS_RESIDUAL`, `AWS_EC2_GRAVITON_AND_SLO_RIGHTSIZING`

## aws · Eip Nat (`network`)

| Resource type | Rules evaluated |
| --- | --- |
| `aws:ec2:elastic-ip` | **NAT gateway idle and VPC endpoint bypass review** (`AWS_NAT_GW_ENDPOINT_BYPASS_AND_IDLE`)<br>**Unassociated Elastic IP address review** (`AWS_UNASSOCIATED_EIP`) |
| `aws:ec2:natgateway` | **NAT gateway idle and VPC endpoint bypass review** (`AWS_NAT_GW_ENDPOINT_BYPASS_AND_IDLE`)<br>**Unassociated Elastic IP address review** (`AWS_UNASSOCIATED_EIP`) |

**Family rule set** (2 ids): `AWS_UNASSOCIATED_EIP`, `AWS_NAT_GW_ENDPOINT_BYPASS_AND_IDLE`

## aws · Load Balancers (`network`)

| Resource type | Rules evaluated |
| --- | --- |
| `aws:elbv2:loadbalancer` | **Orphaned load balancer and ingress consolidation review** (`AWS_ELB_ORPHANED_AND_INGRESS_CONSOLIDATION`) |

**Family rule set** (1 ids): `AWS_ELB_ORPHANED_AND_INGRESS_CONSOLIDATION`

## aws · Rds Aurora (`database`)

| Resource type | Rules evaluated |
| --- | --- |
| `aws:rds:db` | **Idle or stopped RDS instance review** (`AWS_IDLE_RDS`)<br>**RDS / Aurora rightsizing and GP3 storage review** (`AWS_RDS_AURORA_RIGHTSIZING_AND_GP3`) |
| `aws:rds:cluster` | **Idle or stopped RDS instance review** (`AWS_IDLE_RDS`)<br>**RDS / Aurora rightsizing and GP3 storage review** (`AWS_RDS_AURORA_RIGHTSIZING_AND_GP3`) |

**Family rule set** (2 ids): `AWS_IDLE_RDS`, `AWS_RDS_AURORA_RIGHTSIZING_AND_GP3`

## aws · Dynamodb (`database`)

| Resource type | Rules evaluated |
| --- | --- |
| `aws:dynamodb:table` | **DynamoDB billing mode and unused GSI review** (`AWS_DYNAMODB_BILLING_MODE_AND_UNUSED_GSI`) |

**Family rule set** (1 ids): `AWS_DYNAMODB_BILLING_MODE_AND_UNUSED_GSI`

## aws · Elasticache (`database`)

| Resource type | Rules evaluated |
| --- | --- |
| `aws:elasticache:replication-group` | **ElastiCache Graviton and Valkey upgrade review** (`AWS_ELASTICACHE_GRAVITON_AND_VALKEY_UPGRADE`) |

**Family rule set** (1 ids): `AWS_ELASTICACHE_GRAVITON_AND_VALKEY_UPGRADE`

## aws · Lambda Ecs (`application`)

| Resource type | Rules evaluated |
| --- | --- |
| `aws:lambda:function` | **Lambda ARM64 and provisioned concurrency review** (`AWS_LAMBDA_ARM64_AND_PROVISIONED_CONCURRENCY`) |
| `aws:ecs:service` | **Lambda ARM64 and provisioned concurrency review** (`AWS_LAMBDA_ARM64_AND_PROVISIONED_CONCURRENCY`) |

**Family rule set** (1 ids): `AWS_LAMBDA_ARM64_AND_PROVISIONED_CONCURRENCY`

## aws · S3 (`storage`)

| Resource type | Rules evaluated |
| --- | --- |
| `aws:s3:bucket` | **S3 Intelligent-Tiering and multipart cleanup review** (`AWS_S3_INTELLIGENT_TIERING_AND_MULTIPART_CLEANUP`) |

**Family rule set** (1 ids): `AWS_S3_INTELLIGENT_TIERING_AND_MULTIPART_CLEANUP`

## aws · Ai Inference (`ai`)

| Resource type | Rules evaluated |
| --- | --- |
| `aws:sagemaker:endpoint` | **Bedrock provisioned throughput and idle SageMaker endpoint review** (`AWS_BEDROCK_PT_AND_SAGEMAKER_IDLE_ENDPOINT`) |
| `aws:bedrock:provisioned-throughput` | **Bedrock provisioned throughput and idle SageMaker endpoint review** (`AWS_BEDROCK_PT_AND_SAGEMAKER_IDLE_ENDPOINT`) |

**Family rule set** (1 ids): `AWS_BEDROCK_PT_AND_SAGEMAKER_IDLE_ENDPOINT`

## gcp · Persistent Disks (`storage`)

| Resource type | Rules evaluated |
| --- | --- |
| `compute.googleapis.com/Disk` | **Persistent disk Hyperdisk IOPS tuning review** (`GCP_DISK_HYPERDISK_IOPS_TUNING`)<br>**Unattached persistent disk retention review** (`GCP_UNATTACHED_DISK`) |

**Family rule set** (2 ids): `GCP_UNATTACHED_DISK`, `GCP_DISK_HYPERDISK_IOPS_TUNING`

## gcp · Gce (`compute`)

| Resource type | Rules evaluated |
| --- | --- |
| `compute.googleapis.com/Instance` | **GCE Axion / custom machine rightsizing review** (`GCP_GCE_AXION_AND_CUSTOM_RIGHTSIZING`)<br>**Stopped GCE instance persistent disk charge review** (`GCP_GCE_STOPPED_DISK_TAX`) |

**Family rule set** (2 ids): `GCP_GCE_STOPPED_DISK_TAX`, `GCP_GCE_AXION_AND_CUSTOM_RIGHTSIZING`

## gcp · Ip Nat (`network`)

| Resource type | Rules evaluated |
| --- | --- |
| `compute.googleapis.com/Address` | **Cloud NAT vs Private Google Access routing review** (`GCP_CLOUD_NAT_PRIVATE_GOOGLE_ACCESS`)<br>**Unassigned regional external IP review** (`GCP_UNASSIGNED_ADDRESS`) |
| `compute.googleapis.com/RouterNat` | **Cloud NAT vs Private Google Access routing review** (`GCP_CLOUD_NAT_PRIVATE_GOOGLE_ACCESS`)<br>**Unassigned regional external IP review** (`GCP_UNASSIGNED_ADDRESS`) |

**Family rule set** (2 ids): `GCP_UNASSIGNED_ADDRESS`, `GCP_CLOUD_NAT_PRIVATE_GOOGLE_ACCESS`

## gcp · Load Balancers (`network`)

| Resource type | Rules evaluated |
| --- | --- |
| `compute.googleapis.com/ForwardingRule` | **Empty backend forwarding rule review** (`GCP_LB_EMPTY_BACKEND_FORWARDING_RULE`) |

**Family rule set** (1 ids): `GCP_LB_EMPTY_BACKEND_FORWARDING_RULE`

## gcp · Sql Alloydb (`database`)

| Resource type | Rules evaluated |
| --- | --- |
| `sqladmin.googleapis.com/Instance` | **Cloud SQL / AlloyDB rightsizing and HA review** (`GCP_CLOUDSQL_ALLOYDB_RIGHTSIZING_AND_HA`)<br>**Idle Cloud SQL instance review** (`GCP_IDLE_CLOUD_SQL`) |
| `alloydb.googleapis.com/Cluster` | **Cloud SQL / AlloyDB rightsizing and HA review** (`GCP_CLOUDSQL_ALLOYDB_RIGHTSIZING_AND_HA`)<br>**Idle Cloud SQL instance review** (`GCP_IDLE_CLOUD_SQL`) |

**Family rule set** (2 ids): `GCP_IDLE_CLOUD_SQL`, `GCP_CLOUDSQL_ALLOYDB_RIGHTSIZING_AND_HA`

## gcp · Bigquery (`database`)

| Resource type | Rules evaluated |
| --- | --- |
| `bigquery.googleapis.com/Reservation` | **BigQuery slot autoscale and storage review** (`GCP_BIGQUERY_SLOT_AUTOSCALE_AND_STORAGE`) |

**Family rule set** (1 ids): `GCP_BIGQUERY_SLOT_AUTOSCALE_AND_STORAGE`

## gcp · Cloudrun Memorystore (`application`)

| Resource type | Rules evaluated |
| --- | --- |
| `run.googleapis.com/Service` | **Cloud Run min instances and Memorystore review** (`GCP_CLOUDRUN_MIN_INSTANCE_AND_MEMORYSTORE`) |
| `redis.googleapis.com/Instance` | **Cloud Run min instances and Memorystore review** (`GCP_CLOUDRUN_MIN_INSTANCE_AND_MEMORYSTORE`) |

**Family rule set** (1 ids): `GCP_CLOUDRUN_MIN_INSTANCE_AND_MEMORYSTORE`

## gcp · Vertex Ai (`ai`)

| Resource type | Rules evaluated |
| --- | --- |
| `aiplatform.googleapis.com/Endpoint` | **Vertex AI idle endpoint and replica floor review** (`GCP_VERTEX_AI_IDLE_ENDPOINT_AND_REPLICA_FLOOR`) |

**Family rule set** (1 ids): `GCP_VERTEX_AI_IDLE_ENDPOINT_AND_REPLICA_FLOOR`

## kubernetes · Deployments (`compute`)

| Resource type | Rules evaluated |
| --- | --- |
| `kubernetes.io/Container` | **Zero-traffic workload or namespace review** (`K8S_ABANDONED_WORKLOAD_OR_NAMESPACE`)<br>**Container CPU request rightsizing review** (`K8S_CONTAINER_CPU_OVERREQUEST`)<br>**Container memory working-set rightsizing review** (`K8S_CONTAINER_MEMORY_OVERREQUEST`)<br>**Container throttling, OOM, and QoS reliability review** (`K8S_CONTAINER_UNDERPROVISIONED_RISK`) |
| `kubernetes.io/Deployment` | *(none — verify catalog)* |
| `kubernetes.io/ReplicaSet` | *(none — verify catalog)* |

**Family rule set** (3 ids): `K8S_CONTAINER_CPU_OVERREQUEST`, `K8S_CONTAINER_MEMORY_OVERREQUEST`, `K8S_CONTAINER_UNDERPROVISIONED_RISK`

## kubernetes · Statefulsets (`compute`)

| Resource type | Rules evaluated |
| --- | --- |
| `kubernetes.io/StatefulSet` | **StatefulSet memory buffer and volume template review** (`K8S_STATEFULSET_SIZING_AND_VOLUME_TEMPLATE`) |

**Family rule set** (1 ids): `K8S_STATEFULSET_SIZING_AND_VOLUME_TEMPLATE`

## kubernetes · Daemonsets (`compute`)

| Resource type | Rules evaluated |
| --- | --- |
| `kubernetes.io/DaemonSet` | **DaemonSet cluster-wide allocation overhead review** (`K8S_DAEMONSET_CLUSTER_WIDE_OVERHEAD_TAX`) |

**Family rule set** (1 ids): `K8S_DAEMONSET_CLUSTER_WIDE_OVERHEAD_TAX`

## kubernetes · Jobs (`application`)

| Resource type | Rules evaluated |
| --- | --- |
| `kubernetes.io/CronJob` | **Zero-traffic workload or namespace review** (`K8S_ABANDONED_WORKLOAD_OR_NAMESPACE`) |
| `kubernetes.io/Job` | **Zero-traffic workload or namespace review** (`K8S_ABANDONED_WORKLOAD_OR_NAMESPACE`) |

**Family rule set** (1 ids): `K8S_ABANDONED_WORKLOAD_OR_NAMESPACE`

## kubernetes · Autoscaling (`compute`)

| Resource type | Rules evaluated |
| --- | --- |
| `kubernetes.io/HorizontalPodAutoscaler` | **Horizontal Pod Autoscaler floor and PDB conflict review** (`K8S_HPA_PDB_CONFLICT_OR_IDLE_FLOOR`) |
| `kubernetes.io/PodDisruptionBudget` | **Horizontal Pod Autoscaler floor and PDB conflict review** (`K8S_HPA_PDB_CONFLICT_OR_IDLE_FLOOR`) |

**Family rule set** (1 ids): `K8S_HPA_PDB_CONFLICT_OR_IDLE_FLOOR`

## kubernetes · Nodes (`compute`)

| Resource type | Rules evaluated |
| --- | --- |
| `kubernetes.io/Node` | **Node pool capacity reservation slack review** (`K8S_NODE_POOL_FRAGMENTATION_WASTE`) |

**Family rule set** (1 ids): `K8S_NODE_POOL_FRAGMENTATION_WASTE`

## kubernetes · Persistent Volumes (`storage`)

| Resource type | Rules evaluated |
| --- | --- |
| `kubernetes.io/PersistentVolumeClaim` | **Unmounted or low-occupancy PVC review** (`K8S_PVC_UNMOUNTED_OR_LOW_OCCUPANCY`) |

**Family rule set** (1 ids): `K8S_PVC_UNMOUNTED_OR_LOW_OCCUPANCY`

## kubernetes · Services (`network`)

| Resource type | Rules evaluated |
| --- | --- |
| `kubernetes.io/Service` | **LoadBalancer service with empty endpoints review** (`K8S_ORPHANED_LOADBALANCER_SERVICE`) |

**Family rule set** (1 ids): `K8S_ORPHANED_LOADBALANCER_SERVICE`

---

## Full rule index (display name → id)

| Display name | rule_id | Providers |
| --- | --- | --- |
| Bedrock provisioned throughput and idle SageMaker endpoint review | `AWS_BEDROCK_PT_AND_SAGEMAKER_IDLE_ENDPOINT` | aws |
| DynamoDB billing mode and unused GSI review | `AWS_DYNAMODB_BILLING_MODE_AND_UNUSED_GSI` | aws |
| EBS GP2 to GP3 and provisioned IOPS tuning review | `AWS_EBS_GP2_TO_GP3_AND_IOPS_TUNING` | aws |
| EC2 Graviton migration and SLO-bounded rightsizing review | `AWS_EC2_GRAVITON_AND_SLO_RIGHTSIZING` | aws |
| Stopped EC2 instance residual EBS charge review | `AWS_EC2_STOPPED_EBS_RESIDUAL` | aws |
| ElastiCache Graviton and Valkey upgrade review | `AWS_ELASTICACHE_GRAVITON_AND_VALKEY_UPGRADE` | aws |
| Orphaned load balancer and ingress consolidation review | `AWS_ELB_ORPHANED_AND_INGRESS_CONSOLIDATION` | aws |
| Idle or stopped RDS instance review | `AWS_IDLE_RDS` | aws |
| Lambda ARM64 and provisioned concurrency review | `AWS_LAMBDA_ARM64_AND_PROVISIONED_CONCURRENCY` | aws |
| NAT gateway idle and VPC endpoint bypass review | `AWS_NAT_GW_ENDPOINT_BYPASS_AND_IDLE` | aws |
| RDS / Aurora rightsizing and GP3 storage review | `AWS_RDS_AURORA_RIGHTSIZING_AND_GP3` | aws |
| S3 Intelligent-Tiering and multipart cleanup review | `AWS_S3_INTELLIGENT_TIERING_AND_MULTIPART_CLEANUP` | aws |
| Unassociated Elastic IP address review | `AWS_UNASSOCIATED_EIP` | aws |
| Unattached EBS volume retention review | `AWS_UNATTACHED_EBS` | aws |
| Azure AI Foundry PTU vs pay-as-you-go review | `AZURE_AI_FOUNDRY_PTU_VS_PAYG_ARBITRAGE` | azure |
| Empty Application Gateway or high autoscale floor review | `AZURE_APPGW_EMPTY_OR_HIGH_AUTOSCALE_FLOOR` | azure |
| Empty paid App Service plan review | `AZURE_ASP_EMPTY_PAID_PLAN` | azure |
| App Service capacity review | `AZURE_ASP_UNDERUTILIZED_SKU` | azure |
| Cosmos DB manual throughput vs autoscale review | `AZURE_COSMOSDB_MANUAL_RU_TO_AUTOSCALE` | azure |
| Disk recovery and provisioned performance review | `AZURE_DISK_PROVISIONED_PERFORMANCE` | azure |
| Retained unattached managed disk review | `AZURE_DISK_UNATTACHED_RETENTION` | azure |
| NAT gateway vs service endpoint routing review | `AZURE_NAT_GATEWAY_SERVICE_ENDPOINT_BYPASS` | azure |
| Associated public IP traffic review | `AZURE_PUBLIC_IP_ASSOCIATED_IDLE` | azure |
| Unassociated public IP review | `AZURE_PUBLIC_IP_UNASSOCIATED` | azure |
| Azure Cache for Redis tier utilization review | `AZURE_REDIS_UNDERUTILIZED_TIER_REVIEW` | azure |
| Azure SQL / PostgreSQL idle and non-production HA review | `AZURE_SQL_PG_IDLE_AND_NONPROD_HA_REVIEW` | azure |
| Storage lifecycle and orphaned VHD page blob review | `AZURE_STORAGE_LIFECYCLE_AND_ORPHANED_VHD` | azure |
| Evidence-based VM rightsizing review | `AZURE_VM_RIGHTSIZING_UTILIZATION` | azure |
| Stopped VM residual charge review | `AZURE_VM_STOPPED_RESIDUAL_COST` | azure |
| BigQuery slot autoscale and storage review | `GCP_BIGQUERY_SLOT_AUTOSCALE_AND_STORAGE` | gcp |
| Cloud Run min instances and Memorystore review | `GCP_CLOUDRUN_MIN_INSTANCE_AND_MEMORYSTORE` | gcp |
| Cloud SQL / AlloyDB rightsizing and HA review | `GCP_CLOUDSQL_ALLOYDB_RIGHTSIZING_AND_HA` | gcp |
| Cloud NAT vs Private Google Access routing review | `GCP_CLOUD_NAT_PRIVATE_GOOGLE_ACCESS` | gcp |
| Persistent disk Hyperdisk IOPS tuning review | `GCP_DISK_HYPERDISK_IOPS_TUNING` | gcp |
| GCE Axion / custom machine rightsizing review | `GCP_GCE_AXION_AND_CUSTOM_RIGHTSIZING` | gcp |
| Stopped GCE instance persistent disk charge review | `GCP_GCE_STOPPED_DISK_TAX` | gcp |
| Idle Cloud SQL instance review | `GCP_IDLE_CLOUD_SQL` | gcp |
| Empty backend forwarding rule review | `GCP_LB_EMPTY_BACKEND_FORWARDING_RULE` | gcp |
| Unassigned regional external IP review | `GCP_UNASSIGNED_ADDRESS` | gcp |
| Unattached persistent disk retention review | `GCP_UNATTACHED_DISK` | gcp |
| Vertex AI idle endpoint and replica floor review | `GCP_VERTEX_AI_IDLE_ENDPOINT_AND_REPLICA_FLOOR` | gcp |
| Zero-traffic workload or namespace review | `K8S_ABANDONED_WORKLOAD_OR_NAMESPACE` | kubernetes |
| Container CPU request rightsizing review | `K8S_CONTAINER_CPU_OVERREQUEST` | kubernetes |
| Container memory working-set rightsizing review | `K8S_CONTAINER_MEMORY_OVERREQUEST` | kubernetes |
| Container throttling, OOM, and QoS reliability review | `K8S_CONTAINER_UNDERPROVISIONED_RISK` | kubernetes |
| DaemonSet cluster-wide allocation overhead review | `K8S_DAEMONSET_CLUSTER_WIDE_OVERHEAD_TAX` | kubernetes |
| Horizontal Pod Autoscaler floor and PDB conflict review | `K8S_HPA_PDB_CONFLICT_OR_IDLE_FLOOR` | kubernetes |
| Node pool capacity reservation slack review | `K8S_NODE_POOL_FRAGMENTATION_WASTE` | kubernetes |
| LoadBalancer service with empty endpoints review | `K8S_ORPHANED_LOADBALANCER_SERVICE` | kubernetes |
| Unmounted or low-occupancy PVC review | `K8S_PVC_UNMOUNTED_OR_LOW_OCCUPANCY` | kubernetes |
| StatefulSet memory buffer and volume template review | `K8S_STATEFULSET_SIZING_AND_VOLUME_TEMPLATE` | kubernetes |
