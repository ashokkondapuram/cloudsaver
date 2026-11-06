# CloudSaver — AWS extended billable resources & 5-pillar rule catalog

**Purpose:** Give the AWS subagent and **AnalysisService** an exhaustive, deterministic reference for **5-pillar** evaluation across **24 billable AWS resource types** (compute, containers/serverless, storage/backups, databases/analytics, networking/CDN, AI/ML, observability/security).

**Implementation note:** CloudSaver’s shipped **scanner waste catalog** uses stable ids such as `AWS_UNATTACHED_EBS`, `AWS_EC2_GRAVITON_AND_SLO_RIGHTSIZING` (`app/resource_catalog.py`). The rule ids below (e.g. `AWS-EC2-COST-01`) are **spec-level** labels — map them to catalog ids, **platform** `PLATFORM_*` hooks, or new first-party rules as you implement coverage.

**Related:** [well_architected_aws.md](./well_architected_aws.md) (concise agent brief), `app/analysis_service/*`, `app/scanner_aws.py`, `app/collectors/aws_live.py`.

---

## 1. Foundational AWS API contracts

| Concern | Primary APIs |
|--------|----------------|
| **Resource inventory & config** | Resource Explorer **Search**, **ListResources**, [Supported Resource Types](https://docs.aws.amazon.com/resource-explorer/latest/userguide/supported-resource-types.html); enrich with service **Describe\*** / **List\*** ([Permissions Reference](https://docs.aws.amazon.com/service-authorization/latest/reference/reference_policies_actions-resources-contextkeys.html)) |
| **Utilization & quota telemetry** | CloudWatch **GetMetricData** (boto3 `get_metric_data`); namespaces per service + **AWS/Usage** |
| **Actual vs retail cost** | Cost Explorer **GetCostAndUsageWithResources**, **GetCostAndUsage**; Price List **GetProducts** ([Using the Price List Query API](https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/using-pps.html)) |
| **Control-plane activity & drift** | CloudTrail **LookupEvents** ([CloudTrail topics](https://docs.aws.amazon.com/awscloudtrail/latest/userguide/cloudtrail-event-reference.html)); EventBridge Events Reference |
| **Native 5-pillar signals** | Well-Architected Framework; Trusted Advisor; Compute Optimizer; align with Stream E in `app/collectors/cloud_advisor.py` when enabled |

---

## 2. Compute, containers & serverless (resources 1–6)

### 2.1 Discovery, metrics, pricing & drift

| # | Billable resource | Resource Explorer type & discovery | CloudWatch (namespace, metrics, dimensions) | CE & Price List filters | CloudTrail drift `eventName` |
|---|-------------------|--------------------------------------|---------------------------------------------|-------------------------|------------------------------|
| 1 | **EC2 Instances** (On-Demand, Spot, Dedicated Hosts) | `ec2:instance`, `ec2:dedicated-host` — `describe_instances`, `describe_hosts`, `describe_instance_types` | **AWS/EC2**, **CWAgent**: CPUUtilization, CPUCreditBalance, CPUSurplusCreditCharged, NetworkIn, NetworkOut, EBSReadOps, EBSWriteOps, StatusCheckFailed, mem_used_percent, gpu_utilization — **InstanceId** | ServiceCode=`AmazonEC2`, productFamily in (Compute Instance, Dedicated Host), instanceType, tenancy, OS, capacitystatus=Used, usagetype BoxUsage:*, CPUCredits:* | RunInstances, ModifyInstanceAttribute, ModifyInstanceCreditSpecification, StartInstances, StopInstances, TerminateInstances, AllocateHosts |
| 2 | **EC2 Auto Scaling Groups** | `autoscaling:autoScalingGroup` — `describe_auto_scaling_groups`, `describe_launch_template_versions` | **AWS/AutoScaling**, **AWS/EC2**: GroupInServiceInstances, GroupPendingInstances, GroupStandbyInstances, GroupDesiredCapacity, GroupMaxSize, CPUUtilization — **AutoScalingGroupName** | Member instance ARNs + `aws:autoscaling:groupName` cost allocation tag | CreateAutoScalingGroup, UpdateAutoScalingGroup, PutScalingPolicy, DeletePolicy, SuspendProcesses, SetDesiredCapacity |
| 3 | **Lambda** | `lambda:function` — `list_functions`, `list_provisioned_concurrency_configs`, `get_function_url_config` | **AWS/Lambda**: Invocations, Duration, Errors, Throttles, ConcurrentExecutions, ProvisionedConcurrentExecutions, ProvisionedConcurrencyUtilization, ProvisionedConcurrencySpilloverInvocations, ClaimedAccountConcurrency — **FunctionName**, **Resource** | ServiceCode=AWSLambda, group in (AWS-Lambda-Duration, AWS-Lambda-Requests, …) | CreateFunction20150331, UpdateFunctionConfiguration20150331v2, PutFunctionConcurrency, PutProvisionedConcurrencyConfig, AddPermission20150331v2 |
| 4 | **ECS & Fargate** | `ecs:cluster`, `ecs:service`, `ecs:task` — `describe_clusters`, `describe_services`, `describe_task_definition` | **AWS/ECS**, **ECS/ContainerInsights**: CPUUtilization, MemoryUtilization, CpuReserved, MemoryReserved, EphemeralStorageUtilized — **ClusterName**, **ServiceName** | ServiceCode=AmazonECS, usagetype Fargate-vCPU-Hours, Fargate-GB-Hours, … | CreateService, UpdateService, RegisterTaskDefinition, PutClusterCapacityProviders, DeleteService |
| 5 | **EKS** | `eks:cluster`, `eks:nodegroup` — `describe_cluster`, `describe_nodegroup`, `list_fargate_profiles`, `list_addons` | **ContainerInsights**: node_cpu_utilization, node_memory_utilization, pod_cpu_utilization_over_pod_limit, pod_memory_utilization_over_pod_limit, cluster_failed_node_count — **ClusterName**, **Namespace**, **PodName** | ServiceCode=AmazonEKS + worker EC2/Fargate spend | CreateCluster, UpdateClusterConfig, UpdateClusterVersion, CreateNodegroup, UpdateNodegroupConfig |
| 6 | **ECR** | `ecr:repository` — `describe_repositories`, `get_lifecycle_policy`, `describe_images` | **AWS/ECR**, **AWS/Usage**: RepositoryPullCount; image metadata from API | ServiceCode=AmazonECR, TimedStorage-ByteHrs, data transfer | CreateRepository, PutLifecyclePolicy, DeleteLifecyclePolicy, PutImageScanningConfiguration, SetRepositoryPolicy |

### 2.2 Rules by resource type (compute, containers & serverless)

#### 1. EC2 Instances
- **Cost optimization:** `AWS-EC2-COST-01` … `AWS-EC2-COST-05`
- **Performance efficiency:** `AWS-EC2-PERF-01` … `AWS-EC2-PERF-04`
- **Reliability:** `AWS-EC2-REL-01` … `AWS-EC2-REL-03`
- **Security:** `AWS-EC2-SEC-01` … `AWS-EC2-SEC-03`
- **Operational excellence:** `AWS-EC2-OPS-01` … `AWS-EC2-OPS-04`

#### 2. EC2 Auto Scaling Groups
- **Cost optimization:** `AWS-ASG-COST-01`, `AWS-ASG-COST-02`
- **Performance efficiency:** `AWS-ASG-PERF-01`, `AWS-ASG-PERF-02`
- **Reliability:** `AWS-ASG-REL-01` … `AWS-ASG-REL-03`
- **Security:** `AWS-ASG-SEC-01`
- **Operational excellence:** `AWS-ASG-OPS-01`

#### 3. AWS Lambda
- **Cost optimization:** `AWS-LAM-COST-01` … `AWS-LAM-COST-04`
- **Performance efficiency:** `AWS-LAM-PERF-01`, `AWS-LAM-PERF-02`
- **Reliability:** `AWS-LAM-REL-01` … `AWS-LAM-REL-03`
- **Security:** `AWS-LAM-SEC-01`, `AWS-LAM-SEC-02`
- **Operational excellence:** `AWS-LAM-OPS-01`, `AWS-LAM-OPS-02`

#### 4. Amazon ECS & AWS Fargate
- **Cost optimization:** `AWS-ECS-COST-01` … `AWS-ECS-COST-03`
- **Performance efficiency:** `AWS-ECS-PERF-01`
- **Reliability:** `AWS-ECS-REL-01`, `AWS-ECS-REL-02`
- **Security:** `AWS-ECS-SEC-01`
- **Operational excellence:** `AWS-ECS-OPS-01`

#### 5. Amazon EKS
- **Cost optimization:** `AWS-EKS-COST-01` … `AWS-EKS-COST-03`
- **Performance efficiency:** `AWS-EKS-PERF-01`, `AWS-EKS-PERF-02`
- **Reliability:** `AWS-EKS-REL-01`, `AWS-EKS-REL-02`
- **Security:** `AWS-EKS-SEC-01`, `AWS-EKS-SEC-02`
- **Operational excellence:** `AWS-EKS-OPS-01`

#### 6. Amazon ECR
- **Cost optimization:** `AWS-ECR-COST-01`
- **Performance efficiency:** `AWS-ECR-PERF-01`
- **Reliability:** `AWS-ECR-REL-01`
- **Security:** `AWS-ECR-SEC-01`, `AWS-ECR-SEC-02`
- **Operational excellence:** `AWS-ECR-OPS-01`

*Per-rule formulas/thresholds: upstream FinOps spec; implementation binds to inventory + metrics + cost + activity evidence.*

---

## 3. Storage & backup (resources 7–11)

### 3.1 Discovery, metrics, pricing & drift

| # | Resource | Discovery | CloudWatch | CE / Price List | CloudTrail |
|---|----------|-----------|------------|-----------------|------------|
| 7 | **EBS volumes** | `ec2:volume` | **AWS/EBS**: VolumeReadOps, VolumeWriteOps, VolumeReadBytes, VolumeWriteBytes, VolumeIdleTime, BurstBalance, VolumeThroughputPercentage, VolumeQueueLength — **VolumeId** | AmazonEC2 Storage/System Operation, volumeApiName gp2/gp3/io1/io2/st1/sc1 | CreateVolume, ModifyVolume, AttachVolume, DetachVolume, DeleteVolume, EnableFastSnapshotRestores |
| 8 | **EBS snapshots & FSR** | `ec2:snapshot`, `ec2:ami` | Tier, StartTime, VolumeSize; FSR state | Storage Snapshot, EBS:SnapshotUsage/Archive, FastSnapshotRestore-Hours | CreateSnapshot, CopySnapshot, ModifySnapshotTier, ModifySnapshotAttribute, DisableFastSnapshotRestores |
| 9 | **S3** | `s3:bucket` | **AWS/S3**: BucketSizeBytes, NumberOfObjects, AllRequests, … — **BucketName**, **StorageType** | AmazonS3 Storage/API/Fee | CreateBucket, PutBucketLifecycle, PutBucketPolicy, PutBucketPublicAccessBlock, PutBucketVersioning, PutBucketEncryption |
| 10 | **EFS & FSx** | `elasticfilesystem:file-system`, `fsx:file-system` | **AWS/EFS**, **AWS/FSx**: PercentIOLimit, BurstCreditBalance, StorageBytes, … | AmazonEFS, AmazonFSx | CreateFileSystem, UpdateFileSystem, PutLifecycleConfiguration, PutBackupPolicy |
| 11 | **AWS Backup** | `backup:backup-vault`, `backup:backup-plan` | **AWS/Backup**: NumberOfRecoveryPoints, NumberOfBackupJobsFailed, … | AWSBackup warm/cold byte-hours | CreateBackupVault, DeleteRecoveryPoint, UpdateRecoveryPointLifecycle, PutBackupVaultAccessPolicy |

### 3.2 Rules by resource type (storage & backup)

#### 7. EBS Volumes
- **Cost optimization:** `AWS-EBS-COST-01` … `AWS-EBS-COST-03`
- **Performance efficiency:** `AWS-EBS-PERF-01`
- **Reliability:** `AWS-EBS-REL-01`, `AWS-EBS-REL-02`
- **Security:** `AWS-EBS-SEC-01`
- **Operational excellence:** `AWS-EBS-OPS-01`

#### 8. EBS Snapshots & Fast Snapshot Restore
- **Cost optimization:** `AWS-SNAP-COST-01` … `AWS-SNAP-COST-03`
- **Performance efficiency:** `AWS-SNAP-PERF-01`
- **Reliability:** `AWS-SNAP-REL-01`
- **Security:** `AWS-SNAP-SEC-01`, `AWS-SNAP-SEC-02`
- **Operational excellence:** `AWS-SNAP-OPS-01`

#### 9. Amazon S3
- **Cost optimization:** `AWS-S3-COST-01` … `AWS-S3-COST-04`
- **Performance efficiency:** `AWS-S3-PERF-01`
- **Reliability:** `AWS-S3-REL-01`
- **Security:** `AWS-S3-SEC-01`, `AWS-S3-SEC-02`
- **Operational excellence:** `AWS-S3-OPS-01`

#### 10. Amazon EFS & Amazon FSx
- **Cost optimization:** `AWS-EFS-COST-01` … `AWS-EFS-COST-03`
- **Performance efficiency:** `AWS-EFS-PERF-01`
- **Reliability:** `AWS-EFS-REL-01`
- **Security:** `AWS-EFS-SEC-01`
- **Operational excellence:** `AWS-EFS-OPS-01`

#### 11. AWS Backup
- **Cost optimization:** `AWS-BKP-COST-01`
- **Performance efficiency:** `AWS-BKP-PERF-01`
- **Reliability:** `AWS-BKP-REL-01`
- **Security:** `AWS-BKP-SEC-01`
- **Operational excellence:** `AWS-BKP-OPS-01`

---

## 4. Databases, cache & analytics (resources 12–16)

### 4.1 Discovery, metrics, pricing & drift

| # | Resource | Discovery | Key metrics namespaces | CE / Price List | CloudTrail |
|---|----------|-----------|------------------------|-----------------|------------|
| 12 | **RDS & Aurora** | `rds:db`, `rds:cluster` | **AWS/RDS**: CPUUtilization, FreeableMemory, DatabaseConnections, ReadIOPS, WriteIOPS, AuroraReplicaLag, EBSByteBalance%, EBSIOBalance% | AmazonRDS Database Instance/Storage/PIOPS/Aurora Serverless | CreateDBInstance, ModifyDBInstance, FailoverDBCluster, … |
| 13 | **DynamoDB** | `dynamodb:table` | **AWS/DynamoDB**: Consumed*Capacity*, Throttles, SuccessfulRequestLatency | DDB Read/Write units, TimedStorage | CreateTable, UpdateTable, UpdateContinuousBackups, PutResourcePolicy |
| 14 | **ElastiCache** | `elasticache:cluster`, `replicationgroup`, `serverlesscache` | **AWS/ElastiCache**: EngineCPUUtilization, Evictions, CurrConnections, … | Cache Instance, NodeUsage, ElastiCacheProcessingUnits | CreateReplicationGroup, ModifyReplicationGroup, … |
| 15 | **Redshift** | `redshift:cluster`, `redshift-serverless:workgroup` | **AWS/Redshift**, **AWS/Redshift-Serverless** | Node types, RMS Serverless RPU-hours | CreateCluster, PauseCluster, UpdateWorkgroup, … |
| 16 | **OpenSearch** | `es:domain`, `aoss:collection` | **AWS/ES**, **AWS/AOSS** | ESInstance, AOSS Search/Indexing OCU | CreateDomain, UpdateDomainConfig, CreateCollection, … |

### 4.2 Rules by resource type (databases, cache & analytics)

#### 12. Amazon RDS & Aurora
- **Cost optimization:** `AWS-RDS-COST-01` … `AWS-RDS-COST-04`
- **Performance efficiency:** `AWS-RDS-PERF-01`, `AWS-RDS-PERF-02`
- **Reliability:** `AWS-RDS-REL-01` … `AWS-RDS-REL-03`
- **Security:** `AWS-RDS-SEC-01`, `AWS-RDS-SEC-02`
- **Operational excellence:** `AWS-RDS-OPS-01`, `AWS-RDS-OPS-02`

#### 13. Amazon DynamoDB
- **Cost optimization:** `AWS-DDB-COST-01` … `AWS-DDB-COST-04`
- **Performance efficiency:** `AWS-DDB-PERF-01`
- **Reliability:** `AWS-DDB-REL-01`, `AWS-DDB-REL-02`
- **Security:** `AWS-DDB-SEC-01`
- **Operational excellence:** `AWS-DDB-OPS-01`

#### 14. Amazon ElastiCache
- **Cost optimization:** `AWS-ECACHE-COST-01`, `AWS-ECACHE-COST-02`
- **Performance efficiency:** `AWS-ECACHE-PERF-01`
- **Reliability:** `AWS-ECACHE-REL-01`, `AWS-ECACHE-REL-02`
- **Security:** `AWS-ECACHE-SEC-01`
- **Operational excellence:** `AWS-ECACHE-OPS-01`

#### 15. Amazon Redshift
- **Cost optimization:** `AWS-RS-COST-01`, `AWS-RS-COST-02`
- **Performance efficiency:** `AWS-RS-PERF-01`
- **Reliability:** `AWS-RS-REL-01`
- **Security:** `AWS-RS-SEC-01`
- **Operational excellence:** `AWS-RS-OPS-01`

#### 16. Amazon OpenSearch Service
- **Cost optimization:** `AWS-OS-COST-01`, `AWS-OS-COST-02`
- **Performance efficiency:** `AWS-OS-PERF-01`
- **Reliability:** `AWS-OS-REL-01`
- **Security:** `AWS-OS-SEC-01`
- **Operational excellence:** `AWS-OS-OPS-01`

---

## 5. Networking, AI/ML & observability (resources 17–24)

### 5.1 Discovery, metrics, pricing & drift

| # | Resource | Discovery | CloudWatch | CE / Price List | CloudTrail |
|---|----------|-----------|------------|-----------------|------------|
| 17 | **ELB** (ALB/NLB/GWLB/Classic) | `elasticloadbalancing:loadbalancer` | **AWS/ApplicationELB**, **AWS/NetworkELB**, **AWS/GatewayELB** | AWSELB LCU/usage | CreateLoadBalancer, RegisterTargets, … |
| 18 | **NAT Gateway** | `ec2:natgateway` | **AWS/NATGateway**: Bytes*, ActiveConnectionCount, ErrorPortAllocation, PacketsDropCount | NAT Gateway hours + bytes | CreateNatGateway, CreateRoute, ReplaceRoute |
| 19 | **EIPs & public IPv4** | `ec2:elastic-ip`, ENI | Association metadata | PublicIPv4 InUse/Idle, ElasticIP:IdleAddress | AllocateAddress, AssociateAddress, ReleaseAddress, ModifySubnetAttribute |
| 20 | **VPC endpoints & TGW** | `ec2:vpc-endpoint`, `ec2:transit-gateway*` | **AWS/PrivateLinkEndpoints**, **AWS/TransitGateway** | VpcEndpoint-Hours, TGW-Hours/Bytes | CreateVpcEndpoint, CreateTransitGatewayVpcAttachment |
| 21 | **CloudFront & Global Accelerator** | `cloudfront:distribution`, `globalaccelerator:accelerator` | **AWS/CloudFront** (global) | DataTransfer-Out, Requests | CreateDistribution, CreateInvalidation |
| 22 | **SageMaker & Bedrock** | `sagemaker:endpoint`, `bedrock:provisioned-model-throughput` | **AWS/SageMaker**, **AWS/Bedrock** | ml.* instances, provisioned throughput units | CreateEndpoint, CreateProvisionedModelThroughput, … |
| 23 | **CloudWatch** (logs, metrics, alarms) | `logs:log-group`, `cloudwatch:alarm` | **AWS/Logs**, **AWS/Usage** | DataProcessing, TimedStorage, custom metrics, alarms | PutRetentionPolicy, PutMetricAlarm, … |
| 24 | **KMS & Secrets Manager** | `kms:key`, `secretsmanager:secret` | **AWS/KMS**, **AWS/SecretsManager** + CloudTrail counts | Per-key, per-secret, API request charges | CreateKey, RotateSecret, … |

### 5.2 Rules by resource type (networking, AI/ML & observability)

#### 17. Elastic Load Balancing (ALB, NLB, GWLB, Classic)
- **Cost optimization:** `AWS-ELB-COST-01`, `AWS-ELB-COST-02`
- **Performance efficiency:** `AWS-ELB-PERF-01`
- **Reliability:** `AWS-ELB-REL-01`, `AWS-ELB-REL-02`
- **Security:** `AWS-ELB-SEC-01`, `AWS-ELB-SEC-02`
- **Operational excellence:** `AWS-ELB-OPS-01`

#### 18. VPC NAT Gateways
- **Cost optimization:** `AWS-NAT-COST-01` … `AWS-NAT-COST-03`
- **Performance efficiency:** `AWS-NAT-PERF-01`
- **Reliability:** `AWS-NAT-REL-01`, `AWS-NAT-REL-02`
- **Security:** `AWS-NAT-SEC-01`
- **Operational excellence:** `AWS-NAT-OPS-01`

#### 19. Elastic IPs & Public IPv4
- **Cost optimization:** `AWS-EIP-COST-01`, `AWS-EIP-COST-02`
- **Performance efficiency:** `AWS-EIP-PERF-01`
- **Reliability:** `AWS-EIP-REL-01`
- **Security:** `AWS-EIP-SEC-01`
- **Operational excellence:** `AWS-EIP-OPS-01`

#### 20. VPC Interface Endpoints & Transit Gateway
- **Cost optimization:** `AWS-VPCE-COST-01`, `AWS-VPCE-COST-02`
- **Performance efficiency:** `AWS-VPCE-PERF-01`
- **Reliability:** `AWS-VPCE-REL-01`
- **Security:** `AWS-VPCE-SEC-01`
- **Operational excellence:** `AWS-VPCE-OPS-01`

#### 21. Amazon CloudFront & AWS Global Accelerator
- **Cost optimization:** `AWS-CF-COST-01`, `AWS-CF-COST-02`
- **Performance efficiency:** `AWS-CF-PERF-01`
- **Reliability:** `AWS-CF-REL-01`
- **Security:** `AWS-CF-SEC-01`
- **Operational excellence:** `AWS-CF-OPS-01`

#### 22. Amazon SageMaker & Amazon Bedrock
- **Cost optimization:** `AWS-AIML-COST-01` … `AWS-AIML-COST-03`
- **Performance efficiency:** `AWS-AIML-PERF-01`
- **Reliability:** `AWS-AIML-REL-01`
- **Security:** `AWS-AIML-SEC-01`
- **Operational excellence:** `AWS-AIML-OPS-01`

#### 23. Amazon CloudWatch (logs, metrics, alarms)
- **Cost optimization:** `AWS-CW-COST-01` … `AWS-CW-COST-03`
- **Performance efficiency:** `AWS-CW-PERF-01`
- **Reliability:** `AWS-CW-REL-01`
- **Security:** `AWS-CW-SEC-01`
- **Operational excellence:** `AWS-CW-OPS-01`

#### 24. AWS KMS & AWS Secrets Manager
- **Cost optimization:** `AWS-SEC-COST-01` … `AWS-SEC-COST-03` *(KMS/Secrets family in upstream spec)*
- **Performance efficiency:** `AWS-SEC-PERF-01`
- **Reliability:** `AWS-SEC-REL-01`
- **Security:** `AWS-SEC-SEC-01`
- **Operational excellence:** `AWS-SEC-OPS-01`

---

## Implementation mapping (CloudSaver)

1. **Ingestion:** Extend `app/collectors/aws_live.py` / Resource Explorer paths so `inventory[].evidence` carries metrics series, CE joins, and `activity_events` required by each rule family.
2. **AnalysisService:** Add evaluators or **declarative JSON** (`CLOUDSAVER_ANALYSIS_DECLARATIVE_RULES`) + **platform hooks** for spec ids that are not yet first-class `AWS_*` catalog rules.
3. **Catalog:** When promoting a spec rule to product, add **`RULE_DISPLAY_NAMES`**, `FAMILIES`/`definitions()`, `ACTION_CLASS_BY_RULE`, `route_for_rule`, and regenerate **`docs/ANALYSIS_RULES_MASTER.md`** per repository process.

---

*This document is the extended AWS billable-resource & 5-pillar catalog for agents; threshold tuning belongs in implementation tickets per rule id.*
