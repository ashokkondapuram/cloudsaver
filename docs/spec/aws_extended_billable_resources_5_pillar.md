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

### 2.2 Extended 5-pillar rules (compute & containers)

**1. EC2:** AWS-EC2-COST-01 … 05, AWS-EC2-PERF-01 … 04, AWS-EC2-REL-01 … 03, AWS-EC2-SEC-01 … 03, AWS-EC2-OPS-01 … 04 (idle, rightsizing, surplus credits, stopped assets, dedicated host, saturation, burstable credits, Graviton upgrade, EBS bottleneck, standalone prod, status checks, termination protection, IMDSv1, public SSH/RDP, unencrypted volumes, missing CW Agent / SSM, non-prod 24×7, manual resize drift).

**2. ASG:** AWS-ASG-COST-01–02, AWS-ASG-PERF-01–02, AWS-ASG-REL-01–03, AWS-ASG-SEC-01, AWS-ASG-OPS-01 (min size vs utilization, mixed instances Spot, scaling ceiling, warm pool/predictive, single-AZ, ELB health check, suspended processes, launch configuration vs launch template, tag propagation).

**3. Lambda:** AWS-LAM-COST-01–04, AWS-LAM-PERF-01–02, AWS-LAM-REL-01–03, AWS-LAM-SEC-01–02, AWS-LAM-OPS-01–02 (provisioned concurrency idle, memory over-allocation, Graviton, ephemeral storage, spillover, timeout proximity, throttling/DLQ/subnets, public URL, wildcard IAM / secrets in env, deprecated runtime, log retention).

**4. ECS/Fargate:** AWS-ECS-COST-01–03, AWS-ECS-PERF-01, AWS-ECS-REL-01–02, AWS-ECS-SEC-01, AWS-ECS-OPS-01 (task overprovisioning, Spot candidate, ARM64, CPU/memory contention, single-task prod, deployment circuit breaker, privileged/public IP, Container Insights).

**5. EKS:** AWS-EKS-COST-01–03, AWS-EKS-PERF-01–02, AWS-EKS-REL-01–02, AWS-EKS-SEC-01–02, AWS-EKS-OPS-01 (extended support surcharge, overprovisioned node groups, idle dev cluster, pod throttling/OOM, VPC CNI IP exhaustion, failed nodes/single-AZ, PDB, public API, KMS secrets encryption, audit logs).

**6. ECR:** AWS-ECR-COST-01, AWS-ECR-PERF-01, AWS-ECR-REL-01, AWS-ECR-SEC-01–02, AWS-ECR-OPS-01 (image sprawl, cross-region pull, mutable tags, scan on push, wildcard policy, orphaned repos).

*(Full formula text for each rule id is identical to the specification you maintain for implementation thresholds.)*

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

### 3.2 Extended 5-pillar rules (storage)

**7–11:** EBS (unattached, gp2→gp3, overprovisioned IOPS, throttling, backup gaps, encryption, DeleteOnTermination); snapshots (orphan/stale, archive tier, FSR waste, DR hydration, cross-region, public sharing, unencrypted, ad-hoc tags); S3 (cold Standard without lifecycle/IT, version sprawl, multipart abort, small-object IA penalty, 503/prefix, versioning/CRR, PublicAccessBlock/TLS, lifecycle drift); EFS/FSx (provisioned throughput idle, IA/archive lifecycle, abandoned FS, I/O limit, one-zone prod, encryption/NFS, single-AZ mounts); AWS Backup (warm/cold transition, backup window overlap, failed jobs, vault lock, orphaned recovery points).

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

### 4.2 Extended rules (databases)

**12–16:** RDS (idle, rightsizing, Aurora I/O-optimized mode, gp2→gp3, saturation, replica lag, single-AZ prod, backups/deletion protection, auto-scaling storage, public/unencrypted, extended support, Performance Insights); DynamoDB (provisioned vs on-demand, unused GSI, IA table class, throttling, PITR, encryption, TTL); ElastiCache (idle, Valkey/Graviton, eviction/CPU, Multi-AZ/failover, snapshots, encryption, EOL engine); Redshift (idle/pause, dc2→ra3, WLM/disk spill, single-AZ, public/unencrypted, concurrency scaling cap); OpenSearch (idle/overprovisioned, OCU floor waste, JVM pressure, red/yellow/single-AZ, public/VPC/encryption/FGAC, ISM lifecycle).

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

### 5.2 Extended rules (networking & security ops)

**17–24:** ELB (orphan/idle, consolidation, latency/TLS, unhealthy targets, deletion protection, WAF, access logs); NAT (idle, S3/DynamoDB hairpinning, multi-AZ NAT in non-prod, packet drops, SNAT errors, single-AZ routing, flow logs, blackhole routes); EIP (unassociated, auto public IPv4 on private workloads, hairpin, hardcoded IP, perimeter bypass, untagged); VPCe/TGW (idle endpoint, unused attachment, drops, single-AZ endpoint, wildcard policies, private DNS); CloudFront (cache hit, price class, origin latency/HTTP3, origin failover, OAI/OAC/TLS, invalidations); SageMaker/Bedrock (idle notebook/endpoint, underused PT, GPU/latency, single-instance prod, notebook internet/root); CloudWatch (never-expire logs, IA log class, orphaned alarms, API throttling, alarm actions, encryption/PII, verbose debug); KMS/Secrets (unused CMK, S3 bucket keys, secret caching, KMS throttling, single-region keys, rotation, pending deletion references).

---

## Implementation mapping (CloudSaver)

1. **Ingestion:** Extend `app/collectors/aws_live.py` / Resource Explorer paths so `inventory[].evidence` carries metrics series, CE joins, and `activity_events` required by each rule family.
2. **AnalysisService:** Add evaluators or **declarative JSON** (`CLOUDSAVER_ANALYSIS_DECLARATIVE_RULES`) + **platform hooks** for spec ids that are not yet first-class `AWS_*` catalog rules.
3. **Catalog:** When promoting a spec rule to product, add **`RULE_DISPLAY_NAMES`**, `FAMILIES`/`definitions()`, `ACTION_CLASS_BY_RULE`, `route_for_rule`, and regenerate **`docs/ANALYSIS_RULES_MASTER.md`** per repository process.

---

*This document is the extended AWS billable-resource & 5-pillar catalog for agents; threshold tuning belongs in implementation tickets per rule id.*
