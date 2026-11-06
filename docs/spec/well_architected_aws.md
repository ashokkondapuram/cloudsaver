# AWS — Well-Architected agent specification

**Audience:** AWS FinOps & Well-Architected backend subagents (Python 3.12+ / FastAPI / Pydantic / boto3).

**CloudSaver paths:** `app/scanner_aws.py`, `app/collectors/aws_live.py`, `app/collectors/aws_resource_explorer.py`; target split: `app/adapters/aws/` + `app/rules/aws_rules.py`. **Pillar analysis:** `app/analysis_service/*` (deterministic, no live HTTP).

**Reliability:** Use documented APIs, pagination, and `provider_retry`; map inventory rows to `canonical_resource_id('aws', arn)`.

---

## 1. Subagent prompt (AWS)

**Role:** AWS FinOps & Well-Architected Backend Subagent (Python 3.12+ / FastAPI / Pydantic / boto3)

**Objective:** Implement and maintain `app/adapters/aws/` and `app/rules/aws_rules.py` using boto3: **resource-explorer-2**, **ec2**, **rds**, **elbv2**, **s3**, **lambda**, **eks**, **cloudwatch**, **ce**, **pricing**, **cloudtrail**, **compute-optimizer**, **trustedadvisor** (Support API).

### Data ingestion contracts

| Stream | Contract |
|--------|----------|
| **Discovery** | Resource Explorer (Search / ListResources) + Describe* enrichment |
| **Metrics** | CloudWatch **GetMetricData** — up to **500** `MetricDataQuery` items per call |
| **Cost** | **GetCostAndUsageWithResources** (14d resource-level) + **GetCostAndUsage** (30d service/tag) + **Price List GetProducts** (retail/on-demand) |
| **Activity** | CloudTrail **LookupEvents** — 90d management mutations (`ReadOnly="false"`) |
| **Signals** | Trusted Advisor (Support API) + Compute Optimizer recommendations (align with Stream E in `app/collectors/cloud_advisor.py` when enabled) |

---

## 2. Discovery, metrics, cost/retail & drift mapping

### 2.1 Resource catalog table

| Resource category & type | Resource Explorer type & discovery | CloudWatch namespace / metrics / dimensions | CE & Price List filters | CloudTrail drift `eventName` (examples) |
|--------------------------|--------------------------------------|-----------------------------------------------|-------------------------|----------------------------------------|
| **EC2 instances & ASG** | `ec2:instance`, `autoscaling:autoScalingGroup` — `DescribeInstances`, `DescribeAutoScalingGroups` | **AWS/EC2**, **CWAgent**: CPUUtilization, NetworkIn, NetworkOut, CPUCreditBalance, EBSReadOps, EBSWriteOps, mem_used_percent — dimensions **InstanceId**, **AutoScalingGroupName** | ServiceCode=`AmazonEC2`, productFamily=`Compute Instance`, instanceType, tenancy, operatingSystem, capacitystatus=`Used` | RunInstances, ModifyInstanceAttribute, StopInstances, TerminateInstances, UpdateAutoScalingGroup, PutScalingPolicy |
| **Lambda & ECS / EKS** | `lambda:function`, `ecs:service`, `eks:cluster` — ListFunctions, DescribeServices, DescribeCluster, DescribeNodegroup | **AWS/Lambda**, **AWS/ECS**, **ContainerInsights**: Invocations, Duration, Errors, Throttles, ProvisionedConcurrentExecutions, CPUUtilization, MemoryUtilization | ServiceCode in (AWSLambda, AmazonECS, AmazonEKS); usage types for Fargate vCPU/GB-hours | UpdateFunctionConfiguration, PutFunctionConcurrency, UpdateService, UpdateClusterConfig, UpdateNodegroupConfig |
| **EBS volumes & snapshots** | `ec2:volume`, `ec2:snapshot` — DescribeVolumes, DescribeSnapshots | **AWS/EBS**: VolumeReadOps, VolumeWriteOps, VolumeReadBytes, VolumeWriteBytes, VolumeIdleTime, BurstBalance, VolumeThroughputPercentage — **VolumeId** | ServiceCode=`AmazonEC2`, productFamily in (Storage, Storage Snapshot), volumeApiName (gp2, gp3, io1, io2, st1, sc1) | CreateVolume, ModifyVolume, AttachVolume, DetachVolume, DeleteVolume, CreateSnapshot, ModifySnapshotAttribute |
| **S3 & EFS** | `s3:bucket`, `elasticfilesystem:file-system` — ListBuckets, GetBucket*, DescribeFileSystems | **AWS/S3**, **AWS/EFS**: BucketSizeBytes, NumberOfObjects, AllRequests, 4xxErrors, 5xxErrors, PercentIOLimit, BurstCreditBalance — **BucketName**, **StorageType**, **FileSystemId** | ServiceCode in (AmazonS3, AmazonEFS), volumeType / storage class dimensions | PutBucketPolicy, PutBucketPublicAccessBlock, PutBucketLifecycle, PutBucketEncryption, UpdateFileSystem |
| **RDS, Aurora, DynamoDB, ElastiCache** | `rds:db`, `rds:cluster`, `dynamodb:table`, `elasticache:cluster` — DescribeDBInstances, DescribeDBClusters, DescribeTable, DescribeReplicationGroups | **AWS/RDS**, **AWS/DynamoDB**, **AWS/ElastiCache**: CPUUtilization, FreeableMemory, FreeStorageSpace, DatabaseConnections, ReadIOPS, WriteIOPS, ConsumedReadCapacityUnits, EngineCPUUtilization, Evictions | ServiceCode in (AmazonRDS, AmazonDynamoDB, AmazonElastiCache), instanceType, deploymentOption, databaseEngine | ModifyDBInstance, ModifyDBCluster, RebootDBInstance, FailoverDBCluster, UpdateTable, ModifyReplicationGroup |
| **ELB, NAT, Elastic IP** | `elasticloadbalancing:loadbalancer`, `ec2:natgateway`, `ec2:elastic-ip` — DescribeLoadBalancers, DescribeTargetHealth, DescribeNatGateways, DescribeAddresses | **AWS/ApplicationELB**, **AWS/NetworkELB**, **AWS/NATGateway**: RequestCount, ActiveFlowCount, ConsumedLCUs, HealthyHostCount, HTTPCode_ELB_5XX_Count, BytesOutToDestination, ErrorPortAllocation | ServiceCode AWSELB or AmazonEC2; productFamily load balancer / NAT / IP | CreateLoadBalancer, ModifyLoadBalancerAttributes, DeleteLoadBalancer, CreateNatGateway, AllocateAddress, ReleaseAddress, AuthorizeSecurityGroupIngress |

*Use AWS “Supported Resource Types” and permissions docs for the authoritative list; extend rows as coverage grows.*

### 2.2 AWS 5-pillar deterministic rules (summary)

| Resource group | Cost optimization | Performance efficiency | Reliability | Security | Operational excellence |
|----------------|-------------------|------------------------|-------------|----------|------------------------|
| **EC2, ASG, Lambda, EKS** | Idle EC2 (14d max CPU &lt; 5%, network &lt; 100 MB); unused Lambda provisioned concurrency &lt; 20%; Graviton / ARM modernization | Credit throttling (t3/t4g CPUCreditBalance); saturation p95 CPU &gt; 85%; rightsizing p95 CPU/mem thresholds | Single-AZ ASG / missing health checks; termination protection off on prod | IMDSv1 (HttpTokens ≠ required); SG 0.0.0.0/0:22/3389; non-IaC AuthorizeSecurityGroupIngress | Missing CW Agent mem metrics; missing FinOps tags; Compute Optimizer alignment |
| **EBS, S3, EFS** | Unattached EBS ≥ 7d; gp2→gp3; stale snapshots &gt; 90d; S3 Standard &gt; 1 TB without lifecycle/Intelligent-Tiering | EBS throughput saturation; EFS PercentIOLimit | Missing backups / DLM / versioning / CRR where required | Unencrypted storage; S3 PublicAccessBlock not fully true; root volume DeleteOnTermination false | AbortIncompleteMultipartUpload rule missing |
| **RDS, DynamoDB, ElastiCache, networking** | Idle DB (14d max connections 0); idle LB/NAT (14d zero flows); unassociated EIP; NAT hairpin without VPC endpoint | RDS/Cache CPU/memory thresholds; Evictions | Single-AZ prod DB; backup &lt; 7d; NAT errors | Public RDS; weak transit/auth on cache | Manual resize drift (console user); unpatched engines |

Map each rule to a **stable `rule_id`** (see `app/resource_catalog.py` and waste/analysis catalogs). For **custom** logic the core engine does not ship with, use **platform evaluators** (`docs/ANALYSIS_SERVICE.md` — “Platform-extensible analysis rules”).

---

## 3. Relation to CloudSaver analysis

- Ingestion fills `inventory[].evidence` (metrics, cost, `activity_events`, optional `advisor_signals`).
- `app/analysis_service/loader.py` builds `UnifiedResourceContext`.
- `AnalysisService` + optional **`evaluate_platform`** hooks produce `PillarFinding` rows and pillar scores.

See also: `docs/spec/well_architected_overview.md` (cross-provider), `docs/ANALYSIS_SERVICE.md`.
